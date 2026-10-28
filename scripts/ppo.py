"""
월하사신을 PPO로 학습

scripts/balance.py처럼 화면 없이 게임 엔진(game/engine.py)을 직접 돌림
5_A2C_A3C_PPO.ipynb의 A2C와 같은 액터-크리틱 신경망을 쓰고, PPO에서 바뀌는 것은 세 가지!!
1. 한 번 모은 경험을 버리지 않고 여러 번(PPO_EPOCHS) 나눠서 다시 학습
2. 새 정책 / 옛 정책 확률 비율을 1 ± CLIP_EPS 안으로 잘라서, 한 번에 정책이 너무 크게 바뀌지 않게 함
3. 어드밴티지를 GAE(여러 스텝의 TD 오차를 lambda로 섞은 값)로 계산

에이전트는 준비 단계에서 "어느 칸에 소환 / 어느 사신 강화 / 어느 사신 판매 / 소동 시작"만 고름
소동이 시작되면 전투는 게임 엔진이 끝까지 자동으로 진행하고, 그 결과로 보상을 받음

학습 중 지표와 그래프(7장)는 results/ppo/ 에 저장
실행: python scripts/ppo.py   (torch, numpy, matplotlib 필요)
"""

import csv
import multiprocessing as mp
import os
import random
import sys
import time
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 창을 띄우지 않고 그림 파일로만 저장
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from torch import nn  # noqa: E402
from torch.distributions import Categorical  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (  # noqa: E402
    INITIAL_LIFE,
    MAX_ACTIONS_PER_WAVE,
    MAX_STAGES,
    MAX_TOWER_LEVEL,
    SLOT_COUNT,
    SUMMON_TOTAL_SECONDS,
)
from game.actions import Action, ActionType  # noqa: E402
from game.engine import Game  # noqa: E402
from game.state import GamePhase  # noqa: E402
from game.tower import Tower  # noqa: E402
from game.wave import WaveManager  # noqa: E402

# ----- 학습 설정 -----
# 시간은 거의 전부 전투 계산에 쓰인다(신경망·GPU와는 상관없음). 그래서 환경을 NUM_ENVS개 프로세스로 나눠 동시에 돌린다.
TOTAL_TIMESTEPS = 30_000  # 목표 총 Step(환경에서 고르는 결정 수의 합). 이어서 할 때도 "누적 목표"
RESUME = True             # checkpoint.pt가 있으면 거기서 이어서, 없으면 처음부터. 처음부터 다시 하려면 False
ROLLOUT_STEPS = 256       # 한 번 학습할 때 모으는 결정 수(환경들이 나눠서 모은다)
NUM_ENVS = max(1, min(16, (os.cpu_count() or 2) - 1))  # 동시에 돌릴 환경(프로세스) 수. 정기 평가도 이 프로세스들이 나눠서 한다.
ENV_STEPS = -(-ROLLOUT_STEPS // NUM_ENVS)  # 환경 하나가 한 번에 모으는 결정 수(올림 나눗셈)
BATCH_STEPS = ENV_STEPS * NUM_ENVS         # 실제로 한 번 학습할 때 쓰는 결정 수
PPO_EPOCHS = 4           # 같은 경험으로 몇 번 다시 학습할지
MINIBATCH_SIZE = 64
GAMMA = 0.99
GAE_LAMBDA = 0.95
CLIP_EPS = 0.2
LR = 1e-4  # 1차(10,240 Step)는 3e-4. 길게 이어 가며 clip 비율이 커져서 낮춤
VALUE_COEF = 0.5
ENTROPY_COEF = 0.01
MAX_GRAD_NORM = 0.5
HIDDEN = 128
LOG_EVERY = 2             # 업데이트 몇 번마다 로그를 찍을지
EXPLAIN_UPDATE = 1
RANDOM_SEED = int(os.environ.get("PPO_SEED", 2026))  # 환경 변수 PPO_SEED로 바꿀 수 있다(여러 시드 비교용)

# ----- 환경 설정 -----
TRAIN_STAGES = MAX_STAGES  # 학습할 때 한 판을 몇 소동까지 할지(30이면 끝까지)
WAVE_TICK = 0.1            # 소동 중 엔진을 한 번에 진행시키는 시간(초). 엔진 안에서는 1/120초씩 계산
MAX_WAVE_TICKS = 6000      # 600초 넘게 안 끝나면 오류

# ----- 평가 설정 -----
EVAL_EVERY_STEPS = 2048    # 학습 몇 Step마다 정기 평가할지(처음 0 Step에도 한 번)
EVAL_GAMES = 20            # 정기 평가 판 수. 클리어율 측정 단위는 100 / EVAL_GAMES = 5%p
EVAL_SEED_BASE = RANDOM_SEED + 100_000  # 학습 판과 겹치지 않는 고정 시드
# 평가 때 행동 고르는 법. False(기본)면 확률대로 뽑고, True면 확률이 가장 큰 행동 하나만 고른다.
# 소환은 24칸에 확률이 나뉘어 있어서, 하나만 고르면 소환 쪽 확률이 더 커도 "소동 시작"이 1등이 되기 쉽다.
# 뽑는 난수는 판의 시드로 고정하므로, 같은 모델·같은 시드면 평가 결과가 매번 같다.
EVAL_GREEDY = False
COMPARE_RANDOM = True      # 최종 평가에서 무작위 정책도 같은 시드로 돌려 비교
MOVING_AVERAGE = 20        # 1~2번 그래프의 이동평균 판 수

# 환경 변수 PPO_OUTPUT_DIR로 저장 위치를 바꿀 수 있다(보상 비교처럼 여러 번 돌릴 때 결과가 섞이지 않게)
OUTPUT_DIR = Path(os.environ.get("PPO_OUTPUT_DIR") or Path(__file__).resolve().parents[1] / "results" / "ppo")
MODEL_PATH = OUTPUT_DIR / "ppo_policy.pt"
BEST_MODEL_PATH = OUTPUT_DIR / "ppo_best.pt"  # 정기 평가에서 가장 좋았던 신경망
# 이어서 학습하기용: 신경망 + 옵티마이저 + 지금까지의 기록 + 난수 상태. 업데이트마다 덮어쓴다.
CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.pt"

# ----- 보상 -----
# 환경 변수 PPO_REWARD로 고른다. 기본은 "old".
#   old           : 처음 쓰던 보상
#   design        : 「강화학습 보상·패널티 1차 설계안 v1.0」(2026.10.27)의 값 그대로
#   design_scaled : design에 scale 0.01을 곱함. 값이 커서 Critic 손실이 정책 학습을 누르는 것을 막아 본 것
# clear: 소동을 버티면, life: 결계 1 잃을 때마다 감점, over: 게임 오버, goal: TRAIN_STAGES까지 버티면(30이면 게임 클리어),
# boss: {소동: 보스 처치 보상}. 보스를 처치한 소동에서만 준다. scale: 학습에 쓰는 보상에 곱하는 값
DESIGN_REWARD = {"clear": 2.0, "life": 10.0, "over": -50.0, "goal": 100.0,
                 "boss": {5: 3.0, 10: 4.0, 15: 5.0, 20: 6.0, 25: 7.0, 30: 8.0}}
REWARD_PROFILES = {
    "old": {"clear": 1.0, "life": 0.2, "over": -5.0, "goal": 10.0, "boss": {}, "scale": 1.0},
    "design": {**DESIGN_REWARD, "scale": 1.0},
    "design_scaled": {**DESIGN_REWARD, "scale": 0.01},
}
REWARD_PROFILE = os.environ.get("PPO_REWARD", "old")
REWARD = dict(REWARD_PROFILES[REWARD_PROFILE])
# 판매로 잃는 골드 1당 감점(scale 곱하기 전 값). 환경 변수 PPO_SELL_LOSS로 정한다. 0이면 판매에 보상이 없다.
# 소환한 사신을 되팔면 투자의 40%를 잃는데, 그 손실이 보상에 드러나지 않으면 되팔기(리롤)를 줄이지 못한다.
REWARD["sell_loss"] = float(os.environ.get("PPO_SELL_LOSS", 0.0))

# ----- 행동 번호 -----
# 0: 소동 시작, 1~24: 그 칸에 랜덤 사신 소환, 25~48: 그 칸의 사신 강화, 49~72: 그 칸의 사신 판매
START_WAVE = 0
BUY_OFFSET = 1
UPGRADE_OFFSET = BUY_OFFSET + SLOT_COUNT
SELL_OFFSET = UPGRADE_OFFSET + SLOT_COUNT
NUM_ACTIONS = SELL_OFFSET + SLOT_COUNT

TOWER_TYPES = Tower.all_types()
GUARDIAN_NAMES = {kind: Tower.display_name(kind) for kind in TOWER_TYPES}

# 상태: [소동, 결계, 골드, 이번 소동 행동 수] + 칸마다 [사신 종류 원-핫 4개, 레벨, 빈 칸] + [적 수, 적 체력, 보스 여부, 보스 체력]
OBS_DIM = 4 + SLOT_COUNT * (len(TOWER_TYPES) + 2) + 4
GOLD_SCALE = 2000.0
COUNT_SCALE = float(max(WaveManager.STAGE_COUNTS.values()))
HP_SCALE = float(max(WaveManager.STAGE_HP.values()))
BOSS_HP_SCALE = float(max(boss["hp"] for boss in WaveManager.BOSSES.values()))

DEVICE = torch.device("cpu")

# ----- 그래프 색 (dataviz 기본 팔레트: 1번 파랑, 2번 주황, 글자·격자는 회색 계열) -----
COLOR_MAIN = "#2a78d6"
COLOR_MAIN_LIGHT = "#86b6ef"
COLOR_SECOND = "#eb6834"
COLOR_TEXT = "#0b0b0b"
COLOR_TEXT_MUTED = "#52514e"
COLOR_GRID = "#e4e3df"
COLOR_SURFACE = "#fcfcfb"


def action_kind(action):
    if action == START_WAVE:
        return "start"
    if action < UPGRADE_OFFSET:
        return "buy"
    if action < SELL_OFFSET:
        return "upgrade"
    return "sell"


def action_name(action):
    kind = action_kind(action)
    if kind == "start":
        return "소동 시작"
    if kind == "buy":
        return f"{action - BUY_OFFSET}번 칸 소환"
    if kind == "upgrade":
        return f"{action - UPGRADE_OFFSET}번 칸 강화"
    return f"{action - SELL_OFFSET}번 칸 판매"


class GuardianEnv:
    """게임 엔진을 강화학습용 reset/step으로 감싼다. maze_env.MazeEnv와 같은 모양."""

    def __init__(self, stages=TRAIN_STAGES):
        self.stages = stages
        self.game = Game()
        self.state = None
        self.won = False

    def reset(self, seed=None):
        # seed는 랜덤 소환 순서를 정한다. 판마다 다른 seed를 주면 다른 사신 조합을 겪는다.
        self.state = self.game.reset(seed=seed, start_at_title=False)
        self.won = False
        return self.observe()

    def valid_action_mask(self):
        """지금 할 수 있는 행동이면 True. 판단은 게임 규칙(Economy)을 그대로 쓴다."""
        economy, state = self.game.economy, self.state
        mask = [False] * NUM_ACTIONS
        mask[START_WAVE] = economy.can_start_wave(state)
        can_act = economy.can_take_preparation_action(state)
        for slot in range(SLOT_COUNT):
            mask[BUY_OFFSET + slot] = economy.can_buy(state, slot)
            mask[UPGRADE_OFFSET + slot] = economy.can_upgrade(state, slot)
            # 게임의 판매는 "칸 선택 -> 판매 -> 확인" 3단계라 선택 여부는 step()에서 맞춘다.
            mask[SELL_OFFSET + slot] = can_act and state.has_tower(slot)
        return mask

    def observe(self):
        state = self.state
        stage = min(state.current_stage, MAX_STAGES)
        features = [
            stage / MAX_STAGES,
            max(state.life, 0) / INITIAL_LIFE,
            min(state.gold / GOLD_SCALE, 1.0),
            state.actions_taken_this_wave / MAX_ACTIONS_PER_WAVE,
        ]
        for slot in range(SLOT_COUNT):
            tower = state.towers.get(slot)
            kind = [0.0] * len(TOWER_TYPES)
            if tower is None:
                features += kind + [0.0, 1.0]
            else:
                kind[TOWER_TYPES.index(tower["type"])] = 1.0
                features += kind + [tower["level"] / MAX_TOWER_LEVEL, 0.0]
        boss = WaveManager.BOSSES.get(stage)
        features += [
            WaveManager.STAGE_COUNTS[stage] / COUNT_SCALE,
            WaveManager.STAGE_HP[stage] / HP_SCALE,
            1.0 if boss else 0.0,
            (boss["hp"] if boss else 0) / BOSS_HP_SCALE,
        ]
        return np.asarray(features, dtype=np.float32)

    def step(self, action):
        if not self.valid_action_mask()[action]:
            raise ValueError(f"지금 할 수 없는 행동입니다: {action_name(action)}")

        kind = action_kind(action)
        if kind == "start":
            return self._play_wave()
        if kind == "buy":
            self.game.step(Action(ActionType.BUY, slot_id=action - BUY_OFFSET))
        elif kind == "upgrade":
            self.game.step(Action(ActionType.UPGRADE, slot_id=action - UPGRADE_OFFSET))
        else:
            slot = action - SELL_OFFSET
            economy = self.game.economy
            # 판매로 잃는 골드 = 투자한 골드 - 돌려받는 골드(환급률 60%라서 투자의 40%)
            lost_gold = economy.get_total_investment(self.state, slot) - economy.get_sell_refund(self.state, slot)
            self.game.step(Action(ActionType.SELECT_SLOT, slot_id=slot))
            self.game.step(Action(ActionType.SELL, slot_id=slot))
            self.game.step(Action(ActionType.CONFIRM_SELL, slot_id=slot))
            if self.state.phase != GamePhase.PREPARATION or self.state.has_tower(slot):
                raise RuntimeError(f"{slot}번 칸 판매가 끝나지 않았습니다.")
            return self.observe(), -REWARD["sell_loss"] * lost_gold * REWARD["scale"], False
        # 소환·강화 자체에는 보상이 없다. 그 결과로 소동을 버텼는지가 보상이 된다(판매는 잃는 골드만큼 감점).
        return self.observe(), 0.0, False

    def _play_wave(self):
        state = self.state
        stage, life_before, bosses_before = state.current_stage, state.life, state.bosses_killed
        # 사람이 플레이할 때처럼 소환 연출이 끝난 뒤 시작한다(준비 단계에서는 전투 시간이 흐르지 않음).
        self.game.update(SUMMON_TOTAL_SECONDS)
        self.game.step(Action(ActionType.START_WAVE))
        for _ in range(MAX_WAVE_TICKS):
            self.game.update(WAVE_TICK)
            if state.phase != GamePhase.WAVE_ACTIVE:
                break
        else:
            raise RuntimeError(f"{stage}번째 소동이 {MAX_WAVE_TICKS * WAVE_TICK:.0f}초 안에 끝나지 않았습니다.")

        lost = life_before - max(state.life, 0)
        reward = -REWARD["life"] * lost
        if state.bosses_killed > bosses_before:
            reward += REWARD["boss"].get(stage, 0.0)
        scale = REWARD["scale"]
        if state.phase == GamePhase.GAME_OVER:
            return self.observe(), (reward + REWARD["over"]) * scale, True

        reward += REWARD["clear"]
        if stage >= self.stages:
            self.won = True
            return self.observe(), (reward + REWARD["goal"]) * scale, True
        self.game.step(Action(ActionType.CONTINUE))
        return self.observe(), reward * scale, False

    def episode_result(self):
        """판이 끝났을 때의 지표. 도달 소동은 마지막으로 진입한 소동."""
        state = self.state
        return {
            "won": self.won,
            "reached": state.current_stage,
            "cleared": state.current_stage if self.won else state.current_stage - 1,
            "life": max(state.life, 0),
            "gold": state.gold,
        }


class ActorCritic(nn.Module):
    """노트북의 DiscreteActorCritic과 같은 구조. 몸통을 공유하고 머리만 둘(정책, 가치)."""

    def __init__(self, obs_dim=OBS_DIM, n_actions=NUM_ACTIONS, hidden=HIDDEN):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
        )
        self.actor = nn.Linear(hidden, n_actions)
        self.critic = nn.Linear(hidden, 1)

    def forward(self, states):
        features = self.body(states)
        logits = self.actor(features)
        values = self.critic(features).squeeze(-1)
        return logits, values


def masked_dist(logits, masks):
    """할 수 없는 행동은 logit을 아주 작게 만들어 확률이 0이 되게 한다(-inf는 엔트로피가 NaN이 됨)."""
    return Categorical(logits=logits.masked_fill(~masks, -1e9))


def set_seed(seed=RANDOM_SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def new_episode_counter():
    return {"reward": 0.0, "length": 0, "buy": 0, "upgrade": 0, "sell": 0}


def total_updates():
    return -(-TOTAL_TIMESTEPS // BATCH_STEPS)  # 올림 나눗셈


def print_intro():
    updates = total_updates()
    print("PPO로 월하사신 준비 단계를 학습합니다.")
    print("ratio = pi_new(a|s) / pi_old(a|s)")
    print("loss = -min(ratio * A, clip(ratio, 1-eps, 1+eps) * A) + c1 * (R - V)^2 - c2 * 엔트로피")
    print(
        f"총 {TOTAL_TIMESTEPS} Step = 업데이트 {updates}번 x 경험 {BATCH_STEPS}개"
        f"(환경 {NUM_ENVS}개 x {ENV_STEPS}개), "
        f"같은 경험으로 {PPO_EPOCHS}번 학습, gamma={GAMMA}, lambda={GAE_LAMBDA}, eps={CLIP_EPS}"
    )
    print(
        f"행동 {NUM_ACTIONS}개(소동 시작 1 + 소환 {SLOT_COUNT} + 강화 {SLOT_COUNT} + 판매 {SLOT_COUNT}), "
        f"상태 {OBS_DIM}차원"
    )
    print(
        f"보상({REWARD_PROFILE}): 소동 버티면 +{REWARD['clear']}, 결계 1당 -{REWARD['life']}, "
        f"게임 오버 {REWARD['over']}, {TRAIN_STAGES}소동 도달 +{REWARD['goal']}, "
        f"보스 처치 {REWARD['boss'] or '없음'}, 판매로 잃는 골드 1당 -{REWARD['sell_loss']}, "
        f"학습용 보상 배율 x{REWARD['scale']}"
    )
    how = "확률이 가장 큰 행동" if EVAL_GREEDY else "확률대로 뽑기(판마다 시드 고정)"
    print(f"정기 평가: {EVAL_EVERY_STEPS} Step마다 고정 시드 {EVAL_GAMES}판, {how} (프로세스 {NUM_ENVS}개로 동시에)")
    print(f"무작위 시드={RANDOM_SEED}")
    print()


# ----- 병렬 환경 -----
# 프로세스마다 환경 하나를 계속 들고 있다가, 업데이트마다 받은 신경망 가중치로 ENV_STEPS개의 결정을 혼자 모은다.
# 한 Step마다 서로 맞추지 않으므로, 소동이 오래 걸리는 환경 때문에 다른 환경이 기다리지 않는다.
# 이 프로세스들은 정기 평가도 나눠서 한다(평가 전용 프로세스를 따로 만들지 않아 메모리를 아낀다).

def collect_segment(env, model, obs, counter, next_seed):
    """현재 정책(옛 정책)으로 ENV_STEPS개의 결정을 모은다. 판이 끝나면 바로 다음 판을 시작."""
    batch = {key: [] for key in ("obs", "masks", "actions", "logps", "values", "rewards", "dones")}
    episodes = []
    for _ in range(ENV_STEPS):
        mask = env.valid_action_mask()
        x = torch.as_tensor(obs, device=DEVICE).unsqueeze(0)
        m = torch.as_tensor(mask, device=DEVICE).unsqueeze(0)
        with torch.no_grad():
            logits, value = model(x)
            dist = masked_dist(logits, m)
            action = dist.sample()

        action_id = int(action.item())
        next_obs, reward, done = env.step(action_id)
        batch["obs"].append(obs)
        batch["masks"].append(mask)
        batch["actions"].append(action_id)
        batch["logps"].append(float(dist.log_prob(action).item()))
        batch["values"].append(float(value.item()))
        batch["rewards"].append(reward)
        batch["dones"].append(done)

        counter["reward"] += reward
        counter["length"] += 1
        kind = action_kind(action_id)
        if kind != "start":
            counter[kind] += 1
        if done:
            episodes.append({**env.episode_result(), **counter})
            counter.update(new_episode_counter())
            next_obs = env.reset(seed=next_seed())
        obs = next_obs

    # 마지막 결정 뒤의 미래는 아직 모르므로 Critic이 예측한 가치로 대신한다(Bootstrap).
    with torch.no_grad():
        _, last_value = model(torch.as_tensor(obs, device=DEVICE).unsqueeze(0))
    batch = {
        "obs": np.asarray(batch["obs"], dtype=np.float32),
        "masks": np.asarray(batch["masks"], dtype=bool),
        "actions": np.asarray(batch["actions"], dtype=np.int64),
        "logps": np.asarray(batch["logps"], dtype=np.float32),
        "values": np.asarray(batch["values"], dtype=np.float32),
        "rewards": np.asarray(batch["rewards"], dtype=np.float32),
        "dones": np.asarray(batch["dones"], dtype=bool),
    }
    return batch, episodes, obs, float(last_value.item())


class EnvWorker:
    """프로세스 안에서 환경 하나와 신경망 사본 하나를 들고 있는 쪽."""

    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.model = ActorCritic().to(DEVICE)
        self.env = GuardianEnv(stages=TRAIN_STAGES)
        self.counter = new_episode_counter()
        self.seed_offset = 0
        self.episode_count = 0
        self.obs = None

    def next_seed(self):
        # 환경마다, 판마다 다른 시드. 이어서 학습할 때는 offset(끝난 판 수)으로 이미 쓴 시드와 겹치는 것을 줄인다.
        seed = RANDOM_SEED + self.seed_offset + self.worker_id + NUM_ENVS * self.episode_count
        self.episode_count += 1
        return seed

    def start(self, seed_offset):
        self.seed_offset, self.episode_count = seed_offset, 0
        self.counter = new_episode_counter()
        torch.manual_seed(RANDOM_SEED + seed_offset + 1000 * self.worker_id)
        self.obs = self.env.reset(seed=self.next_seed())

    def collect(self, weights):
        self.model.load_state_dict(weights)
        batch, episodes, self.obs, last_value = collect_segment(
            self.env, self.model, self.obs, self.counter, self.next_seed)
        return {"batch": batch, "episodes": episodes, "last_value": last_value}

    @staticmethod
    def call(function, jobs):
        return [function(job) for job in jobs]


def _worker_main(conn, worker_id):
    torch.set_num_threads(1)  # 프로세스 여러 개가 CPU 코어를 서로 빼앗지 않게
    worker = EnvWorker(worker_id)
    while True:
        message = conn.recv()
        if message is None:
            return
        command, payload = message
        try:
            conn.send(("ok", getattr(worker, command)(*payload)))
        except Exception:
            conn.send(("error", traceback.format_exc()))


class WorkerPool:
    """환경 프로세스 NUM_ENVS개를 띄워 두고 같은 명령을 한꺼번에 시킨다."""

    def __init__(self, count):
        context = mp.get_context("spawn")
        self.connections, self.processes = [], []
        for worker_id in range(count):
            parent, child = context.Pipe()
            process = context.Process(target=_worker_main, args=(child, worker_id), daemon=True)
            process.start()
            child.close()
            self.connections.append(parent)
            self.processes.append(process)

    def _ask(self, messages):
        for connection, message in zip(self.connections, messages):
            connection.send(message)
        replies = []
        for connection in self.connections:
            status, payload = connection.recv()
            if status == "error":
                raise RuntimeError(f"환경 프로세스에서 오류가 났습니다:\n{payload}")
            replies.append(payload)
        return replies

    def start(self, seed_offset):
        self._ask([("start", (seed_offset,))] * len(self.connections))

    def collect(self, model):
        weights = {k: v.detach().cpu() for k, v in model.state_dict().items()}
        return self._ask([("collect", (weights,))] * len(self.connections))

    def map(self, function, jobs):
        """jobs를 프로세스들에 돌려가며 나눠 주고, 결과는 jobs 순서대로 돌려준다."""
        count = len(self.connections)
        replies = self._ask([("call", (function, jobs[i::count])) for i in range(count)])
        results = [None] * len(jobs)
        for i, chunk in enumerate(replies):
            results[i::count] = chunk
        return results

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for connection in self.connections:
            try:
                connection.send(None)
            except (OSError, BrokenPipeError):
                pass
        for process in self.processes:
            process.join(timeout=5)
        return False


def compute_gae(rewards, values, dones, last_value):
    """
    GAE: 한 스텝 TD 오차(delta)를 뒤에서부터 gamma * lambda로 섞어서 어드밴티지를 만든다.
        delta_t = r_t + gamma * V(s_{t+1}) - V(s_t)
        A_t     = delta_t + gamma * lambda * A_{t+1}
    lambda=0이면 한 스텝 TD(A2C와 비슷), lambda=1이면 끝까지 실제 보상을 더한 몬테카를로에 가까움
    판이 끝난 스텝(done)에서는 다음 판의 값이 섞이면 안 되므로 미래를 0으로 끊는다.
    """
    advantages = np.zeros(len(rewards), dtype=np.float32)
    running = 0.0
    for t in reversed(range(len(rewards))):
        next_value = last_value if t == len(rewards) - 1 else values[t + 1]
        not_done = 0.0 if dones[t] else 1.0
        delta = rewards[t] + GAMMA * next_value * not_done - values[t]
        running = delta + GAMMA * GAE_LAMBDA * not_done * running
        advantages[t] = running
    returns = advantages + np.asarray(values, dtype=np.float32)
    return advantages, returns


def explained_variance(values, returns):
    """
    Critic이 Return의 흔들림을 얼마나 설명하는지. 1이면 완벽, 0이면 평균만 맞히는 수준, 음수면 그보다 못함
        EV = 1 - Var(Return - V) / Var(Return)
    """
    values, returns = np.asarray(values, dtype=np.float64), np.asarray(returns, dtype=np.float64)
    var_returns = returns.var()
    if var_returns < 1e-12:
        return float("nan")
    return float(1.0 - (returns - values).var() / var_returns)


def ppo_update(model, optimizer, batch, advantages, returns, explain=False):
    obs = torch.as_tensor(np.asarray(batch["obs"]), device=DEVICE)
    masks = torch.as_tensor(batch["masks"], device=DEVICE)
    actions = torch.as_tensor(batch["actions"], device=DEVICE)
    old_logps = torch.as_tensor(batch["logps"], device=DEVICE)
    returns_t = torch.as_tensor(returns, device=DEVICE)
    adv_t = torch.as_tensor(advantages, device=DEVICE)
    # 어드밴티지 정규화: 보상 크기가 판마다 달라도 학습 속도가 일정해진다.
    adv_t = (adv_t - adv_t.mean()) / (adv_t.std() + 1e-8)

    size = len(actions)
    stats = {"actor_loss": [], "critic_loss": [], "entropy": [], "approx_kl": [], "clip_fraction": []}
    for _ in range(PPO_EPOCHS):
        order = torch.randperm(size, device=DEVICE)
        for start in range(0, size, MINIBATCH_SIZE):
            idx = order[start:start + MINIBATCH_SIZE]
            logits, values = model(obs[idx])
            dist = masked_dist(logits, masks[idx])
            new_logps = dist.log_prob(actions[idx])

            log_ratio = new_logps - old_logps[idx]
            ratio = torch.exp(log_ratio)
            surr1 = ratio * adv_t[idx]
            surr2 = torch.clamp(ratio, 1 - CLIP_EPS, 1 + CLIP_EPS) * adv_t[idx]
            actor_loss = -torch.min(surr1, surr2).mean()
            critic_loss = (returns_t[idx] - values).square().mean()
            entropy = dist.entropy().mean()
            loss = actor_loss + VALUE_COEF * critic_loss - ENTROPY_COEF * entropy

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), MAX_GRAD_NORM)
            optimizer.step()

            with torch.no_grad():
                stats["actor_loss"].append(float(actor_loss.item()))
                stats["critic_loss"].append(float(critic_loss.item()))
                stats["entropy"].append(float(entropy.item()))
                # approx_kl: 옛 정책과 새 정책이 얼마나 달라졌는지. (ratio - 1) - log(ratio)는 항상 0 이상
                stats["approx_kl"].append(float(((ratio - 1) - log_ratio).mean().item()))
                # clip_fraction: ratio가 1 ± eps 밖으로 나가 잘린 결정의 비율
                stats["clip_fraction"].append(float(((ratio - 1).abs() > CLIP_EPS).float().mean().item()))

    if explain:
        with torch.no_grad():
            logits, _ = model(obs)
            new_logps = masked_dist(logits, masks).log_prob(actions)
        print_ratio_example(batch, old_logps, new_logps, adv_t)
    return {key: float(np.mean(values)) for key, values in stats.items()}


def print_ratio_example(batch, old_logps, new_logps, adv_t):
    """학습 직후, 확률이 가장 많이 바뀐 결정 하나로 PPO 식을 숫자로 풀어 본다."""
    ratios = torch.exp(new_logps - old_logps)
    index = int((ratios - 1).abs().argmax().item())
    ratio = float(ratios[index].item())
    adv = float(adv_t[index].item())
    clipped = min(max(ratio, 1 - CLIP_EPS), 1 + CLIP_EPS)
    surr1, surr2 = ratio * adv, clipped * adv
    print()
    print(f"----- 업데이트 {EXPLAIN_UPDATE}: 확률이 가장 많이 바뀐 결정 하나 -----")
    print(f"행동 a = {action_name(batch['actions'][index])}")
    print(f"옛 정책 확률 = {np.exp(float(old_logps[index].item())):.4f}")
    print(f"새 정책 확률 = {np.exp(float(new_logps[index].item())):.4f}")
    print(f"ratio = 새 / 옛 = {ratio:.4f}")
    print(f"어드밴티지 A(정규화) = {adv:.4f}  ({'평균보다 좋은 행동' if adv > 0 else '평균보다 나쁜 행동'})")
    print(f"clip(ratio, {1 - CLIP_EPS}, {1 + CLIP_EPS}) = {clipped:.4f}")
    print(f"ratio * A = {surr1:.4f}, clip * A = {surr2:.4f}, 둘 중 작은 값 = {min(surr1, surr2):.4f}")
    if surr2 < surr1:
        print("잘린 쪽이 작습니다. 이 결정은 이미 충분히 바뀌어서 더는 이 방향으로 밀지 않습니다.")
    else:
        print("자르지 않은 쪽이 작습니다. 아직 clip 범위 안이라 평소처럼 학습합니다.")
    print("--------------------------------------------------------------")
    print()


def print_log(update, updates, run, stats):
    recent = run["episodes"][-10:]
    if recent:
        episode_text = (
            f"최근 {len(recent)}판 보상 {np.mean([e['reward'] for e in recent]):6.2f} | "
            f"도달 소동 {np.mean([e['reached'] for e in recent]):4.1f}"
        )
    else:
        episode_text = "아직 끝난 판 없음"
    print(
        f"업데이트 {update:3d}/{updates} | {run['timesteps']:6d} Step | 끝난 판 {len(run['episodes']):3d} | "
        f"{episode_text} | KL {stats['approx_kl']:.4f} | clip {stats['clip_fraction'] * 100:4.1f}% | "
        f"EV {stats['explained_variance']:5.2f}"
    )


# ----- 평가 -----

def play_one(model, seed, stages=MAX_STAGES):
    """
    한 판을 끝까지 둔다. model이 없으면 할 수 있는 행동 중 무작위.
    model이 있으면 EVAL_GREEDY에 따라 확률대로 뽑거나, 확률이 가장 큰 행동을 고른다.
    seed 하나로 게임(소환 순서)과 행동 뽑기 난수를 모두 고정해서, 같은 seed면 결과가 같다.
    """
    env = GuardianEnv(stages=stages)
    obs = env.reset(seed=seed)
    picker = random.Random(seed)
    generator = torch.Generator().manual_seed(seed)
    counter = new_episode_counter()
    done = False
    while not done:
        mask = env.valid_action_mask()
        if model is None:
            action = picker.choice([a for a, ok in enumerate(mask) if ok])
        else:
            with torch.no_grad():
                logits, _ = model(torch.as_tensor(obs, device=DEVICE).unsqueeze(0))
                probs = masked_dist(logits, torch.as_tensor(mask, device=DEVICE).unsqueeze(0)).probs[0]
            if EVAL_GREEDY:
                action = int(probs.argmax().item())
            else:
                action = int(torch.multinomial(probs, 1, generator=generator).item())
        obs, reward, done = env.step(action)
        counter["reward"] += reward
        counter["length"] += 1
        kind = action_kind(action)
        if kind != "start":
            counter[kind] += 1
    return {"seed": seed, **env.episode_result(), **counter, "towers": dict(env.state.towers)}


def _eval_worker(job):
    """평가 프로세스 하나가 한 판을 둔다. 신경망은 가중치(state_dict)만 받아서 다시 만든다."""
    weights, seed = job
    torch.set_num_threads(1)  # 프로세스 여러 개가 CPU 코어를 서로 빼앗지 않게
    model = None
    if weights is not None:
        model = ActorCritic()
        model.load_state_dict(weights)
        model.eval()
    return play_one(model, seed)


def evaluate(model, pool):
    """고정 시드 EVAL_GAMES판을 30소동까지 둔다. model=None이면 무작위 정책."""
    weights = None if model is None else {k: v.detach().cpu() for k, v in model.state_dict().items()}
    jobs = [(weights, EVAL_SEED_BASE + i) for i in range(EVAL_GAMES)]
    return pool.map(_eval_worker, jobs)


def summarize(results):
    """필수 지표를 이미지의 계산 기준 그대로 계산한다."""
    count = len(results)
    return {
        "clear_rate": sum(r["won"] for r in results) / count * 100,      # 30소동 승리 횟수 / 평가 횟수 x 100
        "avg_reached": sum(r["reached"] for r in results) / count,       # 마지막 진입 소동 합 / 판 수
        "avg_life": sum(r["life"] for r in results) / count,             # 종료 시 결계 합 / 판 수
        "avg_gold": sum(r["gold"] for r in results) / count,             # 종료 시 골드 합 / 판 수
        "avg_reward": sum(r["reward"] for r in results) / count,         # 판별 보상 합의 평균
        "avg_length": sum(r["length"] for r in results) / count,         # 환경 Step 수 합 / 판 수
        "avg_buy": sum(r["buy"] for r in results) / count,
        "avg_upgrade": sum(r["upgrade"] for r in results) / count,
        "avg_sell": sum(r["sell"] for r in results) / count,
    }


def stage_clear_rates(results):
    """소동별 클리어율 = 그 소동을 넘긴 판 / 그 소동에 진입한 판. 아무도 진입 못 한 소동은 nan."""
    rates = []
    for stage in range(1, MAX_STAGES + 1):
        entered = [r for r in results if r["reached"] >= stage]
        if not entered:
            rates.append(float("nan"))
            continue
        rates.append(sum(r["cleared"] >= stage for r in entered) / len(entered) * 100)
    return rates


def print_eval(label, timesteps, summary):
    print(
        f"[평가 {label} | {timesteps:6d} Step] 클리어율 {summary['clear_rate']:5.1f}% | "
        f"도달 소동 {summary['avg_reached']:4.1f} | 잔여 결계 {summary['avg_life']:4.1f} | "
        f"잔여 골드 {summary['avg_gold']:6.0f} | 보상 {summary['avg_reward']:6.2f} | 길이 {summary['avg_length']:5.1f}"
    )


# ----- 학습 -----

def new_run():
    # next_eval: 다음 정기 평가를 할 Step. 처음에는 학습 전(0 Step)에 한 번 평가한다.
    return {"timesteps": 0, "episodes": [], "updates": [], "evals": [], "next_eval": 0}


def save_checkpoint(model, optimizer, run):
    """
    이어서 학습할 수 있게 지금 상태를 통째로 저장한다.
    진행 중이던 판은 게임 상태까지 저장할 수 없어서, 이어 갈 때 환경마다 새 판부터 시작한다.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "run": run,
        "rng": {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state()},
    }, CHECKPOINT_PATH)


def load_checkpoint(model, optimizer):
    """체크포인트가 있으면 불러와서 run을 돌려준다. 없으면 None."""
    if not CHECKPOINT_PATH.exists():
        return None
    # 우리가 저장한 파일이라 신경망 가중치 말고도 기록(dict, list)과 난수 상태를 함께 읽는다.
    checkpoint = torch.load(CHECKPOINT_PATH, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    optimizer.load_state_dict(checkpoint["optimizer"])
    for group in optimizer.param_groups:
        group["lr"] = LR  # 학습률을 바꿔서 이어 가면 새 값을 쓴다
    random.setstate(checkpoint["rng"]["python"])
    np.random.set_state(checkpoint["rng"]["numpy"])
    torch.set_rng_state(checkpoint["rng"]["torch"])
    run = checkpoint["run"]
    run.pop("current", None)  # 병렬화 전 체크포인트에 있던 값
    return run


def save_if_best(model, run, summary):
    """
    정기 평가 성적(클리어율, 같으면 평균 도달 소동)이 지금까지 가장 좋으면 그 신경망을 따로 저장한다.
    오래 학습하면 중간에 최고점을 찍고 나빠질 수 있어서, 마지막 신경망(ppo_policy.pt)과 별도로 남긴다.
    평가가 고정 시드라 이 성적은 약간 높게 나오는 편이므로, 최종 성능은 다른 시드로 다시 재야 한다.
    """
    score = (summary["clear_rate"], summary["avg_reached"])
    best = run.get("best")
    if best is not None and score <= (best["clear_rate"], best["avg_reached"]):
        return
    run["best"] = {"timesteps": run["timesteps"], "clear_rate": summary["clear_rate"],
                   "avg_reached": summary["avg_reached"]}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), BEST_MODEL_PATH)
    print(f"  -> 최고 성적 갱신({run['timesteps']} Step): 클리어율 {summary['clear_rate']:.1f}%, "
          f"도달 소동 {summary['avg_reached']:.1f}. {BEST_MODEL_PATH.name}에 저장")


def train(pool):
    set_seed(RANDOM_SEED)  # 신경망을 만들기 전에 고정해야 초기 가중치도 같다(이어서 학습할 때는 체크포인트의 난수 상태로 바뀜)
    model = ActorCritic().to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    run = load_checkpoint(model, optimizer) if RESUME else None
    print_intro()
    if run is None:
        run = new_run()
    else:
        print(
            f"체크포인트에서 이어서 학습합니다: {run['timesteps']} Step, 끝난 판 {len(run['episodes'])}판, "
            f"업데이트 {len(run['updates'])}번 -> 목표 {TOTAL_TIMESTEPS} Step"
        )
        print()

    # 학습 판의 시드는 끝난 판 수를 기준으로 정한다. 이어 갈 때 이미 끝난 판과 겹치는 것을 줄인다.
    pool.start(len(run["episodes"]))
    started_steps = run["timesteps"]
    started = time.perf_counter()
    updates = total_updates()

    while run["timesteps"] < TOTAL_TIMESTEPS:
        if run["timesteps"] >= run["next_eval"]:
            summary = summarize(evaluate(model, pool))
            run["evals"].append({"timesteps": run["timesteps"], **summary})
            print_eval("정기", run["timesteps"], summary)
            run["next_eval"] += EVAL_EVERY_STEPS
            save_if_best(model, run, summary)

        update = len(run["updates"]) + 1
        segments = pool.collect(model)
        run["timesteps"] += BATCH_STEPS
        for segment in segments:
            for episode in segment["episodes"]:
                run["episodes"].append({"episode": len(run["episodes"]) + 1, "timesteps": run["timesteps"], **episode})
        # GAE는 환경마다 따로 계산한다(구간 끝의 미래는 그 환경의 last_value로 대신한다).
        parts = [compute_gae(s["batch"]["rewards"], s["batch"]["values"], s["batch"]["dones"], s["last_value"])
                 for s in segments]
        advantages = np.concatenate([part[0] for part in parts])
        returns = np.concatenate([part[1] for part in parts])
        batch = {key: np.concatenate([s["batch"][key] for s in segments]) for key in segments[0]["batch"]}
        stats = ppo_update(model, optimizer, batch, advantages, returns, explain=update == EXPLAIN_UPDATE)
        stats["explained_variance"] = explained_variance(batch["values"], returns)
        run["updates"].append({"update": update, "timesteps": run["timesteps"], **stats})
        save_checkpoint(model, optimizer, run)  # 중간에 꺼져도 여기서부터 이어 갈 수 있다
        if update % LOG_EVERY == 0 or update == 1:
            print_log(update, updates, run, stats)

    elapsed = time.perf_counter() - started
    print()
    if run["timesteps"] == started_steps:
        print(f"이미 목표 {TOTAL_TIMESTEPS} Step에 도달해 학습은 건너뜁니다. 더 하려면 TOTAL_TIMESTEPS를 늘리세요.")
    print(
        f"이번 실행 학습 {run['timesteps'] - started_steps} Step({elapsed / 60:.1f}분), "
        f"누적 {run['timesteps']} Step, 끝난 판 {len(run['episodes'])}판"
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    print(f"학습한 신경망을 저장했습니다: {MODEL_PATH}")
    return model, optimizer, run


# ----- 결과 저장 -----

def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_tables(run, final):
    write_csv(OUTPUT_DIR / "episodes.csv", run["episodes"],
              ["episode", "timesteps", "reward", "reached", "cleared", "won", "life", "gold",
               "length", "buy", "upgrade", "sell"])
    write_csv(OUTPUT_DIR / "evaluations.csv", run["evals"],
              ["timesteps", "clear_rate", "avg_reached", "avg_life", "avg_gold", "avg_reward",
               "avg_length", "avg_buy", "avg_upgrade", "avg_sell"])
    write_csv(OUTPUT_DIR / "updates.csv", run["updates"],
              ["update", "timesteps", "approx_kl", "clip_fraction", "explained_variance",
               "actor_loss", "critic_loss", "entropy"])
    rows = [{"policy": name, **result} for name, results in final.items() for result in results]
    write_csv(OUTPUT_DIR / "final_eval.csv", rows,
              ["policy", "seed", "won", "reached", "cleared", "life", "gold", "reward",
               "length", "buy", "upgrade", "sell"])


# ----- 그래프 -----

def setup_plot_style():
    # 설치된 한글 글꼴만 고른다(없는 글꼴을 넣으면 글자마다 경고가 찍힘). Windows / macOS / 리눅스 순
    installed = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    korean = [name for name in ("Malgun Gothic", "AppleGothic", "NanumGothic") if name in installed]
    plt.rcParams.update({
        "font.family": korean[:1] + ["DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.facecolor": COLOR_SURFACE,
        "axes.facecolor": COLOR_SURFACE,
        "axes.edgecolor": COLOR_GRID,
        "axes.labelcolor": COLOR_TEXT_MUTED,
        "axes.titlecolor": COLOR_TEXT,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": COLOR_GRID,
        "grid.linewidth": 0.8,
        "xtick.color": COLOR_TEXT_MUTED,
        "ytick.color": COLOR_TEXT_MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "savefig.dpi": 150,
    })


def moving_average(values, window):
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1):i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def plot_episode_trend(run, key, title, ylabel, filename, ylim=None):
    """1~2번: 판별 원본은 연한 선, 최근 MOVING_AVERAGE판 이동평균은 진한 선."""
    episodes = [e["episode"] for e in run["episodes"]]
    values = [e[key] for e in run["episodes"]]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(episodes, values, color=COLOR_MAIN_LIGHT, linewidth=1, label="판별 값")
    ax.plot(episodes, moving_average(values, MOVING_AVERAGE), color=COLOR_MAIN, linewidth=2.2,
            label=f"최근 {MOVING_AVERAGE}판 이동평균")
    ax.set_title(title, loc="left")
    ax.set_xlabel("Episode")
    ax.set_ylabel(ylabel)
    if ylim:
        ax.set_ylim(*ylim)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename)
    plt.close(fig)


def plot_eval_trend(run, key, title, ylabel, filename, ylim=None, fmt="{:.1f}"):
    """3~5번: 정기 평가 값을 Total Timesteps에 따라 점+선으로. 마지막 값만 직접 표시."""
    steps = [e["timesteps"] for e in run["evals"]]
    values = [e[key] for e in run["evals"]]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(steps, values, color=COLOR_MAIN, linewidth=2, marker="o", markersize=6)
    if values:
        ax.annotate(fmt.format(values[-1]), (steps[-1], values[-1]), textcoords="offset points",
                    xytext=(0, 9), ha="center", color=COLOR_TEXT, fontsize=10)
    ax.set_title(title, loc="left")
    ax.set_xlabel("Total Timesteps")
    ax.set_ylabel(ylabel)
    if ylim:
        ax.set_ylim(*ylim)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename)
    plt.close(fig)


def plot_ppo_stability(run, filename):
    """6번: approx_kl, clip_fraction, explained_variance는 의미와 크기가 달라 축을 따로 쓴다."""
    steps = [u["timesteps"] for u in run["updates"]]
    panels = (
        ("approx_kl", "approx_kl", "옛/새 정책 차이. 갑자기 커지면 정책이 한 번에 너무 많이 바뀐 것"),
        ("clip_fraction", "clip_fraction (%)", "ratio가 잘린 결정의 비율"),
        ("explained_variance", "explained_variance", "1에 가까울수록 Critic이 Return을 잘 예측"),
    )
    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    for ax, (key, ylabel, note) in zip(axes, panels):
        values = [u[key] * (100 if key == "clip_fraction" else 1) for u in run["updates"]]
        ax.plot(steps, values, color=COLOR_MAIN, linewidth=2)
        if key == "clip_fraction":
            ax.set_ylim(bottom=0)
        ax.set_ylabel(ylabel)
        ax.set_title(note, loc="left", fontsize=10, fontweight="normal", color=COLOR_TEXT_MUTED)
    axes[-1].set_xlabel("Total Timesteps")
    fig.suptitle("6. PPO 학습 안정성", x=0.02, ha="left", fontsize=14, fontweight="bold", color=COLOR_TEXT)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename)
    plt.close(fig)


def plot_final_summary(final, filename):
    """7번 최종 평가 요약: 필수 지표 표 + 소동별 클리어율 + 행동 횟수."""
    names = list(final)
    summaries = {name: summarize(final[name]) for name in names}
    colors = {name: color for name, color in zip(names, (COLOR_SECOND, COLOR_MAIN))} if len(names) == 2 \
        else {names[0]: COLOR_MAIN}

    fig = plt.figure(figsize=(12, 9))
    grid = fig.add_gridspec(2, 2, height_ratios=(0.9, 1.4))
    table_ax = fig.add_subplot(grid[0, :])
    stage_ax = fig.add_subplot(grid[1, 0])
    action_ax = fig.add_subplot(grid[1, 1])

    rows = (
        ("30소동 클리어율", "clear_rate", "{:.0f}%"),
        ("평균 도달 소동", "avg_reached", "{:.1f}"),
        ("평균 잔여 결계", "avg_life", "{:.1f}"),
        ("평균 잔여 골드", "avg_gold", "{:.0f}"),
        ("평균 누적 Reward", "avg_reward", "{:.2f}"),
        ("평균 Episode 길이", "avg_length", "{:.1f}"),
    )
    table_ax.axis("off")
    cells = [[label] + [fmt.format(summaries[name][key]) for name in names] for label, key, fmt in rows]
    table = table_ax.table(cellText=cells, colLabels=["지표"] + names, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 1.6)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor(COLOR_GRID)
        cell.set_text_props(color=COLOR_TEXT if row else COLOR_TEXT_MUTED, weight="bold" if row == 0 else "normal")
    games = len(final[names[0]])
    table_ax.set_title(f"7. 최종 평가 요약 (고정 시드 {games}판, 30소동까지)", loc="left")

    stages = list(range(1, MAX_STAGES + 1))
    for name in names:
        stage_ax.plot(stages, stage_clear_rates(final[name]), color=colors[name], linewidth=2,
                      marker="o", markersize=4, label=name)
    stage_ax.set_title("소동별 클리어율 (어디서 막히는가)", loc="left")
    stage_ax.set_xlabel("소동")
    stage_ax.set_ylabel("클리어율 (%)")
    stage_ax.set_ylim(-5, 105)
    stage_ax.set_xticks([1, 5, 10, 15, 20, 25, 30])
    # 두 그래프가 같은 색을 쓰므로 범례는 오른쪽 그래프에 한 번만 둔다(선과 겹치지 않게).

    kinds = (("소환", "avg_buy"), ("강화", "avg_upgrade"), ("판매", "avg_sell"))
    width = 0.8 / len(names)
    x = np.arange(len(kinds))
    for i, name in enumerate(names):
        heights = [summaries[name][key] for _label, key in kinds]
        bars = action_ax.bar(x + (i - (len(names) - 1) / 2) * width, heights, width * 0.92,
                             color=colors[name], label=name)
        action_ax.bar_label(bars, fmt="%.1f", padding=2, color=COLOR_TEXT, fontsize=9)
    action_ax.set_xticks(x, [label for label, _key in kinds])
    action_ax.set_title("한 판 평균 행동 횟수 (어떤 전략인가)", loc="left")
    action_ax.set_ylabel("횟수")
    action_ax.grid(axis="x", visible=False)
    if len(names) > 1:
        action_ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename)
    plt.close(fig)


def save_plots(run, final):
    setup_plot_style()
    plot_episode_trend(run, "reward", "1. Episode별 누적 Reward", "누적 Reward", "1_episode_reward.png")
    plot_episode_trend(run, "reached", "2. Episode별 도달 소동", "도달 소동", "2_episode_stage.png",
                       ylim=(0, MAX_STAGES + 1))
    plot_eval_trend(run, "clear_rate", f"3. 30소동 클리어율 (고정 시드 {EVAL_GAMES}판)", "클리어율 (%)",
                    "3_clear_rate.png", ylim=(-5, 105), fmt="{:.0f}%")
    plot_eval_trend(run, "avg_life", "4. 평균 잔여 결계", "평균 잔여 결계", "4_remaining_life.png",
                    ylim=(-0.5, INITIAL_LIFE + 0.5))
    plot_eval_trend(run, "avg_gold", "5. 평균 잔여 골드", "평균 잔여 골드", "5_remaining_gold.png", fmt="{:.0f}")
    plot_ppo_stability(run, "6_ppo_stability.png")
    plot_final_summary(final, "7_final_summary.png")


def report(model, optimizer, run, pool):
    """학습이 끝난 정책을 최종 평가하고, 지표 표·CSV·그래프를 저장한다."""
    model.eval()
    print()
    how = "확률이 가장 큰 행동" if EVAL_GREEDY else "확률대로 뽑기"
    print(f"최종 평가: 고정 시드 {EVAL_GAMES}판을 30소동까지 둡니다. PPO 정책은 {how}.")
    final = {}
    if COMPARE_RANDOM:
        final["무작위 정책"] = evaluate(None, pool)
    final["PPO 정책"] = evaluate(model, pool)

    trained = summarize(final["PPO 정책"])
    # 3~5번 그래프의 마지막 점. 같은 Step에서 다시 평가했다면(학습 없이 다시 실행) 예전 값을 바꾼다.
    run["evals"] = [e for e in run["evals"] if e["timesteps"] != run["timesteps"]]
    run["evals"].append({"timesteps": run["timesteps"], **trained})
    # 방금 평가했으니 이어 갈 때 같은 Step에서 또 평가하지 않게 한다.
    run["next_eval"] = run["timesteps"] + EVAL_EVERY_STEPS
    save_checkpoint(model, optimizer, run)
    for name, results in final.items():
        print_eval(name, run["timesteps"], summarize(results))

    print()
    print("PPO 정책: 소동별 클리어율이 가장 낮은 곳(주로 막히는 소동)")
    rates = stage_clear_rates(final["PPO 정책"])
    hardest = sorted((rate, stage) for stage, rate in enumerate(rates, 1) if not np.isnan(rate))[:3]
    for rate, stage in hardest:
        print(f"  {stage}소동: {rate:.0f}%")
    print(
        f"PPO 정책 한 판 평균 행동: 소환 {trained['avg_buy']:.1f}번, 강화 {trained['avg_upgrade']:.1f}번, "
        f"판매 {trained['avg_sell']:.1f}번"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_tables(run, final)
    save_plots(run, final)
    print()
    print(f"지표 CSV 4개와 그래프 7장을 저장했습니다: {OUTPUT_DIR}")
    return final


def main():
    # 경험 모으기와 평가 판은 서로 독립이라 여러 프로세스로 동시에 돌린다. 신경망 업데이트만 이 프로세스.
    with WorkerPool(NUM_ENVS) as pool:
        model, optimizer, run = train(pool)
        report(model, optimizer, run, pool)


if __name__ == "__main__":
    main()
