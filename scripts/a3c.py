"""
월하사신을 A3C(Asynchronous Advantage Actor-Critic)로 학습

환경(GuardianEnv), 신경망(ActorCritic), 평가, 그래프는 scripts/ppo.py의 것을 그대로 가져다 쓴다.
그래서 PPO와 A3C의 차이는 "신경망을 어떻게 고치는가" 하나뿐이고, 결과를 그대로 비교할 수 있다.

PPO와 다른 점
1. 동기 대신 비동기: PPO는 환경 전부가 경험을 모을 때까지 기다렸다가 한 번에 학습한다.
   A3C는 워커(프로세스)마다 N_STEPS개만 모으면 바로 그래디언트를 계산해서 공용 신경망에 반영한다. 서로 기다리지 않는다.
2. 경험은 한 번만 쓴다: 모은 경험으로 한 번 고치고 버린다(PPO처럼 여러 번 다시 학습하지 않으므로 clip도 없다).
3. 공용 신경망과 공용 Adam: 신경망 가중치와 Adam의 상태(평균, 분산)를 공유 메모리에 두고 모든 워커가 같이 고친다.

실행: python scripts/a3c.py   (--config가 없으면 scripts/a3c_configs/a3c.json을 읽는다)
다른 파일로: python scripts/a3c.py --config 파일.json --set a3c.lr=3e-4 --set run.output_dir=\"results/jeabin_a3c_실험1\"
학습 중 지표와 그래프(7장)는 results/jeabin_a3c/ 에 저장. 쓴 수치는 출력 폴더의 config.json에 저장
"""

import argparse
import copy
import json
import multiprocessing as mp
import os
import queue
import sys
import time
import traceback
from pathlib import Path

# ----- 설정 파일 -----
# ppo.py와 같은 방식이다. 파일에는 바꿀 값만 적으면 되고, "_"로 시작하는 키는 메모라서 무시한다.
# 우선순위: 아래 기본값 < 설정 파일 < 명령줄 --set 구역.키=값
# reward 구역은 ppo.py와 같은 키를 쓴다(clear, life, over, goal, boss, scale도 더 적을 수 있다).
DEFAULT_CONFIG = {
    "run": {
        "total_timesteps": 300_000,  # 목표 총 Step(모든 워커가 고른 결정 수의 합). 이어서 할 때도 "누적 목표"
        "resume": True,              # checkpoint.pt가 있으면 거기서 이어서. 처음부터 다시 하려면 false
        "seed": 2026,
        "output_dir": None,          # 비우면 results/jeabin_a3c
        "train_stages": 30,
    },
    "a3c": {
        "num_workers": None,     # 동시에 학습하는 워커(프로세스) 수. 비우면 CPU 코어 수 - 1 (최대 16)
        "n_steps": 20,           # 워커가 몇 결정마다 공용 신경망을 고칠지(n-step). 원 논문은 5~20
        "gamma": 0.995,
        # 1.0이면 원 논문처럼 n-step Return(실제 보상 n개 + 마지막 가치), 1보다 작으면 GAE로 섞는다.
        "gae_lambda": 1.0,
        "lr": 1e-4,              # 워커들이 따로따로 자주 고치므로 PPO(3e-4)보다 작게 둔다
        "value_coef": 0.5,
        "entropy_coef": 0.01,
        "max_grad_norm": 0.5,
        "hidden": 128,
        "log_every_steps": 2048,  # 이만큼 Step마다 로그 한 줄 + updates.csv 한 줄 + 체크포인트 저장
    },
    "eval": {
        "every_steps": 10240,
        "games": 40,
        "greedy": False,
        "compare_random": True,
    },
    "reward": {  # tune_v2.json(PPO 30소동 클리어율 85%)과 같은 값
        "profile": "design_scaled",
        "sell_loss": 0.05,
        "action_cost": 0.0,
        "cost_start": 0.0,
        "cost_buy": 0.1,
        "cost_upgrade": 0.1,
        "cost_sell": 0.3,
        "boss_life": 0.0,
    },
}
REWARD_OVERRIDE_KEYS = ("clear", "life", "over", "goal", "boss", "scale")
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "a3c_configs" / "a3c.json"


def load_config():
    # 워커 프로세스(spawn)는 이 파일을 다시 읽으므로, 부모가 정한 설정을 환경 변수로 물려받는다.
    packed = os.environ.get("A3C_CONFIG_JSON")
    if packed:
        return json.loads(packed)
    config = copy.deepcopy(DEFAULT_CONFIG)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    parser.add_argument("--set", action="append", default=[])
    args, _ = parser.parse_known_args()
    config_file = args.config or (DEFAULT_CONFIG_FILE if DEFAULT_CONFIG_FILE.exists() else None)

    def put(section, key, value):
        allowed = key in config.get(section, {}) or (section == "reward" and key in REWARD_OVERRIDE_KEYS)
        if not allowed:
            raise SystemExit(f"설정에 없는 항목입니다: {section}.{key}")
        config[section][key] = value

    if config_file:
        with open(config_file, encoding="utf-8") as file:
            for section, values in json.load(file).items():
                if section.startswith("_"):
                    continue
                if section not in config or not isinstance(values, dict):
                    raise SystemExit(f"설정 파일의 구역이 올바르지 않습니다: {section}")
                for key, value in values.items():
                    if not key.startswith("_"):
                        put(section, key, value)
    for item in args.set:
        path, _, raw = item.partition("=")
        section, _, key = path.partition(".")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        put(section, key, value)
    # 비워 둔 값은 여기서 정해 둔다(워커와 부모가 같은 값을 쓰도록).
    config["a3c"]["num_workers"] = config["a3c"]["num_workers"] or max(1, min(16, (os.cpu_count() or 2) - 1))
    config["run"]["output_dir"] = str(config["run"]["output_dir"]
                                      or Path(__file__).resolve().parents[1] / "results" / "jeabin_a3c")
    config["_config_file"] = str(config_file or "")
    os.environ["A3C_CONFIG_JSON"] = json.dumps(config)
    return config


CONFIG = load_config()
A3C = CONFIG["a3c"]
NUM_WORKERS = A3C["num_workers"]
N_STEPS = A3C["n_steps"]
LR = A3C["lr"]
VALUE_COEF = A3C["value_coef"]
ENTROPY_COEF = A3C["entropy_coef"]
MAX_GRAD_NORM = A3C["max_grad_norm"]
LOG_EVERY_STEPS = A3C["log_every_steps"]

# ppo.py는 import될 때 설정(PPO_CONFIG_JSON)을 읽어 환경·보상·평가 값을 정한다. 그래서 import 전에 A3C 설정을 그 모양으로 넘긴다.
# rollout_steps = n_steps x 워커 수로 두면 ppo.collect_segment가 워커마다 정확히 n_steps개를 모은다.
# epochs, minibatch_size, clip_eps는 A3C에서 쓰지 않지만 ppo.py가 읽으므로 자리만 채운다.
os.environ["PPO_CONFIG_JSON"] = json.dumps({
    "run": CONFIG["run"],
    "ppo": {
        "rollout_steps": N_STEPS * NUM_WORKERS, "num_envs": NUM_WORKERS, "epochs": 1, "minibatch_size": N_STEPS,
        "gamma": A3C["gamma"], "gae_lambda": A3C["gae_lambda"], "clip_eps": 0.2, "lr": LR,
        "value_coef": VALUE_COEF, "entropy_coef": ENTROPY_COEF, "max_grad_norm": MAX_GRAD_NORM, "hidden": A3C["hidden"],
    },
    "eval": CONFIG["eval"],
    "reward": CONFIG["reward"],
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ppo  # noqa: E402  (matplotlib을 그림 파일 전용(Agg)으로 정하므로 pyplot보다 먼저)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from torch import nn  # noqa: E402

OUTPUT_DIR = ppo.OUTPUT_DIR
MODEL_PATH = OUTPUT_DIR / "a3c_policy.pt"
ppo.BEST_MODEL_PATH = OUTPUT_DIR / "a3c_best.pt"  # ppo.save_if_best가 저장하는 곳(정기 평가에서 가장 좋았던 신경망)
CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.pt"  # 공용 신경망 + 공용 Adam 상태 + 기록. LOG_EVERY_STEPS마다 덮어쓴다
POLICY_NAME = "A3C 정책"


class SharedAdam(torch.optim.Adam):
    """
    모든 워커가 같이 쓰는 Adam. 상태(step, 1차·2차 모멘트)를 공유 메모리에 두고, 워커마다 그 텐서를 그대로 끼워 넣는다.
    torch의 Adam은 상태를 제자리에서 고치므로(+=), 한 워커가 고친 값이 다른 워커에게 바로 보인다.
    """

    def __init__(self, params, lr, shared_state):
        super().__init__(params, lr=lr)
        params = [p for group in self.param_groups for p in group["params"]]
        for param, state in zip(params, shared_state):
            self.state[param] = state

    @staticmethod
    def new_state(model):
        state = [{"step": torch.zeros(()), "exp_avg": torch.zeros_like(p), "exp_avg_sq": torch.zeros_like(p)}
                 for p in model.parameters()]
        for item in state:
            for tensor in item.values():
                tensor.share_memory_()
        return state


def a3c_loss(model, batch, advantages, returns):
    """
    A3C 손실. 정책은 log pi(a|s) x A를 키우고, Critic은 Return을 맞히고, 엔트로피로 탐험을 유지한다.
        loss = -log pi(a|s) * A + c1 * (R - V)^2 - c2 * 엔트로피
    방금 이 신경망으로 모은 경험이라 PPO의 ratio(새/옛 정책 비율)가 항상 1이다. 그래서 clip이 필요 없다.
    """
    obs = torch.as_tensor(batch["obs"])
    masks = torch.as_tensor(batch["masks"])
    actions = torch.as_tensor(batch["actions"])
    logits, values = model(obs)
    dist = ppo.masked_dist(logits, masks)
    actor_loss = -(dist.log_prob(actions) * torch.as_tensor(advantages)).mean()
    critic_loss = (torch.as_tensor(returns) - values).square().mean()
    entropy = dist.entropy().mean()
    loss = actor_loss + VALUE_COEF * critic_loss - ENTROPY_COEF * entropy
    return loss, {"actor_loss": float(actor_loss.item()), "critic_loss": float(critic_loss.item()),
                  "entropy": float(entropy.item())}


def _a3c_worker(worker_id, global_model, shared_state, steps, lock, go, eval_jobs, out, seed_offset):
    """
    워커 하나. 공용 신경망을 복사해 n_steps개를 모으고, 자기 사본에서 그래디언트를 계산해 공용 신경망에 반영한다.
    go가 꺼져 있으면(정기 평가 중) 학습을 멈추고 평가 판을 나눠 둔다.
    """
    try:
        torch.set_num_threads(1)  # 프로세스 여러 개가 CPU 코어를 서로 빼앗지 않게
        worker = ppo.EnvWorker(worker_id)  # 환경 하나 + 신경망 사본 하나 + 판 시드 관리
        worker.start(seed_offset)
        optimizer = SharedAdam(global_model.parameters(), LR, shared_state)
        while True:
            if not go.is_set():
                try:
                    job = eval_jobs.get(timeout=0.2)
                except queue.Empty:
                    continue
                out.put(("eval", job[1], ppo._eval_worker(job)))
                continue
            if steps.value >= ppo.TOTAL_TIMESTEPS:
                break

            segment = worker.collect(global_model.state_dict())  # 공용 신경망을 사본에 복사한 뒤 n_steps개 모음
            batch = segment["batch"]
            advantages, returns = ppo.compute_gae(batch["rewards"], batch["values"], batch["dones"],
                                                  segment["last_value"])
            loss, stats = a3c_loss(worker.model, batch, advantages, returns)
            worker.model.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(worker.model.parameters(), MAX_GRAD_NORM)
            # 사본의 그래디언트를 공용 신경망에 넘기고 공용 Adam으로 한 걸음. 한 번에 한 워커만 고치도록 잠근다.
            with lock:
                for global_param, local_param in zip(global_model.parameters(), worker.model.parameters()):
                    global_param.grad = local_param.grad
                optimizer.step()
            with steps.get_lock():
                steps.value += len(batch["actions"])
            stats["explained_variance"] = ppo.explained_variance(batch["values"], returns)
            out.put(("update", stats))
            for episode in segment["episodes"]:
                out.put(("episode", episode))
        out.put(("done", worker_id))
    except Exception:
        out.put(("error", traceback.format_exc()))


class Trainer:
    """부모 프로세스. 워커를 띄우고, 워커가 보내는 기록을 모으고, 정기 평가와 체크포인트를 맡는다."""

    def __init__(self):
        ppo.set_seed(ppo.RANDOM_SEED)
        self.model = ppo.ActorCritic()
        self.shared_state = SharedAdam.new_state(self.model)
        self.run = self.load_checkpoint() if ppo.RESUME else None
        self.model.share_memory()
        context = mp.get_context("spawn")
        self.context = context
        self.steps = context.Value("q", 0)
        self.lock = context.Lock()
        self.go = context.Event()  # 처음에는 꺼 둔다: 0 Step 평가부터 하고 학습을 시작
        self.eval_jobs = context.Queue()
        self.out = context.Queue()
        self.workers = []
        self.finished = 0  # 학습을 마친 워커 수
        self.window = []  # 아직 로그로 묶지 않은 업데이트 통계
        self.window_start = 0

    # ----- 체크포인트 -----

    def save_checkpoint(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with self.lock:
            model = {k: v.clone() for k, v in self.model.state_dict().items()}
            optimizer = [{k: v.clone() for k, v in item.items()} for item in self.shared_state]
        torch.save({"model": model, "optimizer": optimizer, "run": self.run}, CHECKPOINT_PATH)

    def load_checkpoint(self):
        if not CHECKPOINT_PATH.exists():
            return None
        checkpoint = torch.load(CHECKPOINT_PATH, weights_only=False)
        if not isinstance(checkpoint.get("optimizer"), list):
            raise SystemExit(f"A3C 체크포인트가 아닙니다(PPO 결과 폴더일 수 있음): {CHECKPOINT_PATH}")
        self.model.load_state_dict(checkpoint["model"])
        for item, saved in zip(self.shared_state, checkpoint["optimizer"]):
            for key, tensor in item.items():
                tensor.copy_(saved[key])
        return checkpoint["run"]

    # ----- 워커가 보내는 기록 -----

    def receive(self):
        """워커가 보낸 기록 하나를 받는다. 1초 안에 없으면 None(워커가 모두 죽었으면 오류)."""
        try:
            return self.out.get(timeout=1.0)
        except queue.Empty:
            if not any(worker.is_alive() for worker in self.workers):
                raise RuntimeError("워커 프로세스가 모두 멈췄습니다.") from None
            return None

    def handle(self, message):
        kind = message[0]
        if kind == "error":
            raise RuntimeError(f"워커 프로세스에서 오류가 났습니다:\n{message[1]}")
        if kind == "done":
            self.finished += 1
        elif kind == "update":
            self.window.append(message[1])
        elif kind == "episode":
            run = self.run
            run["episodes"].append({"episode": len(run["episodes"]) + 1, "timesteps": self.steps.value, **message[1]})
        return kind

    def flush_log(self, force=False):
        """LOG_EVERY_STEPS마다 업데이트 통계를 평균 내서 한 줄로 남기고 체크포인트를 저장한다."""
        steps = self.steps.value
        if not self.window or (steps - self.window_start < LOG_EVERY_STEPS and not force):
            return
        run = self.run
        row = {"update": len(run["updates"]) + 1, "timesteps": steps, "worker_updates": len(self.window)}
        for key in ("actor_loss", "critic_loss", "entropy", "explained_variance"):
            values = [s[key] for s in self.window if not np.isnan(s[key])]
            row[key] = float(np.mean(values)) if values else float("nan")
        run["updates"].append(row)
        run["timesteps"] = steps
        self.window, self.window_start = [], steps
        self.save_checkpoint()

        recent = run["episodes"][-10:]
        if recent:
            episode_text = (f"최근 {len(recent)}판 보상 {np.mean([e['reward'] for e in recent]):6.2f} | "
                            f"도달 소동 {np.mean([e['reached'] for e in recent]):4.1f}")
        else:
            episode_text = "아직 끝난 판 없음"
        speed = (steps - self.started_steps) / max(time.perf_counter() - self.started, 1e-9)
        print(f"{steps:7d} Step | 끝난 판 {len(run['episodes']):4d} | {episode_text} | "
              f"엔트로피 {row['entropy']:.3f} | EV {row['explained_variance']:5.2f} | {speed:5.1f} Step/초")

    # ----- 정기 평가 -----

    def evaluate(self):
        """워커를 잠시 멈추고, 그 워커들에게 평가 판을 나눠 준다. 공용 신경망의 지금 가중치로 고정 시드 판을 둔다."""
        self.go.clear()
        with self.lock:
            weights = {k: v.clone() for k, v in self.model.state_dict().items()}
        for i in range(ppo.EVAL_GAMES):
            self.eval_jobs.put((weights, ppo.EVAL_SEED_BASE + i))
        results = {}
        while len(results) < ppo.EVAL_GAMES:
            # 평가를 시작하는 순간 목표 Step에 닿아 워커가 모두 끝나 버렸으면 평가를 맡을 워커가 없다(최종 평가로 대신).
            if self.finished == NUM_WORKERS:
                self.go.set()
                return None
            message = self.receive()
            if message is not None and self.handle(message) == "eval":
                results[message[1]] = message[2]
        self.go.set()
        return [results[seed] for seed in sorted(results)]

    def periodic_eval(self):
        run = self.run
        steps = self.steps.value
        results = self.evaluate()
        if results is None:
            return
        summary = ppo.summarize(results)
        run["timesteps"] = steps
        run["evals"].append({"timesteps": steps, **summary})
        ppo.print_eval("정기", steps, summary)
        run["next_eval"] = steps - steps % ppo.EVAL_EVERY_STEPS + ppo.EVAL_EVERY_STEPS
        ppo.save_if_best(self.model, run, summary)

    # ----- 학습 -----

    def train(self):
        print_intro()
        if self.run is None:
            self.run = ppo.new_run()
        else:
            print(f"체크포인트에서 이어서 학습합니다: {self.run['timesteps']} Step, 끝난 판 {len(self.run['episodes'])}판 "
                  f"-> 목표 {ppo.TOTAL_TIMESTEPS} Step")
            print()
        run = self.run
        self.steps.value = run["timesteps"]
        self.started_steps = self.window_start = run["timesteps"]
        self.started = time.perf_counter()
        if run["timesteps"] >= ppo.TOTAL_TIMESTEPS:
            print(f"이미 목표 {ppo.TOTAL_TIMESTEPS} Step에 도달해 학습은 건너뜁니다. 더 하려면 total_timesteps를 늘리세요.")
            return

        # 판 시드는 워커마다 다르고, 이어서 할 때는 끝난 판 수만큼 밀어서 이미 쓴 시드와 겹치는 것을 줄인다.
        self.workers = [self.context.Process(
            target=_a3c_worker,
            args=(i, self.model, self.shared_state, self.steps, self.lock, self.go, self.eval_jobs, self.out,
                  len(run["episodes"])),
            daemon=True) for i in range(NUM_WORKERS)]
        for worker in self.workers:
            worker.start()
        try:
            while self.finished < NUM_WORKERS:
                steps = self.steps.value
                # 워커가 하나라도 끝났으면 목표 Step에 닿은 것이라 정기 평가는 하지 않는다(최종 평가는 따로 한다).
                if self.finished == 0 and steps < ppo.TOTAL_TIMESTEPS and steps >= run["next_eval"]:
                    self.periodic_eval()
                    continue
                self.go.set()
                message = self.receive()
                if message is not None:
                    self.handle(message)
                self.flush_log()
        finally:
            for worker in self.workers:
                worker.join(timeout=5)
                if worker.is_alive():
                    worker.terminate()
        self.flush_log(force=True)
        self.run["timesteps"] = self.steps.value
        self.save_checkpoint()

        elapsed = time.perf_counter() - self.started
        print()
        print(f"이번 실행 학습 {run['timesteps'] - self.started_steps} Step({elapsed / 60:.1f}분), "
              f"누적 {run['timesteps']} Step, 끝난 판 {len(run['episodes'])}판")


# ----- 결과 저장 -----

def plot_a3c_stability(run, filename):
    """6번: A3C에는 ratio·clip이 없으므로 엔트로피, Critic 손실, explained_variance를 본다."""
    steps = [u["timesteps"] for u in run["updates"]]
    panels = (
        ("entropy", "엔트로피", "정책이 얼마나 고르게 고르는지. 너무 빨리 0에 가까워지면 탐험을 멈춘 것"),
        ("critic_loss", "critic_loss", "Critic이 Return을 얼마나 틀리는지"),
        ("explained_variance", "explained_variance", "1에 가까울수록 Critic이 Return을 잘 예측"),
    )
    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    for ax, (key, ylabel, note) in zip(axes, panels):
        ax.plot(steps, [u[key] for u in run["updates"]], color=ppo.COLOR_MAIN, linewidth=2)
        ax.set_ylabel(ylabel)
        ax.set_title(note, loc="left", fontsize=10, fontweight="normal", color=ppo.COLOR_TEXT_MUTED)
    axes[-1].set_xlabel("Total Timesteps")
    fig.suptitle("6. A3C 학습 안정성", x=0.02, ha="left", fontsize=14, fontweight="bold", color=ppo.COLOR_TEXT)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename)
    plt.close(fig)


def report(trainer):
    """학습이 끝난 공용 신경망을 최종 평가하고, CSV 4개와 그래프 7장을 저장한다(ppo.py와 같은 파일 이름)."""
    model, run = trainer.model, trainer.run
    model.eval()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    print(f"학습한 신경망을 저장했습니다: {MODEL_PATH}")
    print()
    how = "확률이 가장 큰 행동" if ppo.EVAL_GREEDY else "확률대로 뽑기"
    print(f"최종 평가: 고정 시드 {ppo.EVAL_GAMES}판을 30소동까지 둡니다. {POLICY_NAME}은 {how}.")
    final = {}
    with ppo.WorkerPool(NUM_WORKERS) as pool:
        if ppo.COMPARE_RANDOM:
            final["무작위 정책"] = ppo.evaluate(None, pool)
        final[POLICY_NAME] = ppo.evaluate(model, pool)

    trained = ppo.summarize(final[POLICY_NAME])
    run["evals"] = [e for e in run["evals"] if e["timesteps"] != run["timesteps"]]
    run["evals"].append({"timesteps": run["timesteps"], **trained})
    run["next_eval"] = run["timesteps"] + ppo.EVAL_EVERY_STEPS
    trainer.save_checkpoint()
    for name, results in final.items():
        ppo.print_eval(name, run["timesteps"], ppo.summarize(results))
    print()
    print(f"{POLICY_NAME}: 소동별 클리어율이 가장 낮은 곳(주로 막히는 소동)")
    rates = ppo.stage_clear_rates(final[POLICY_NAME])
    for rate, stage in sorted((rate, stage) for stage, rate in enumerate(rates, 1) if not np.isnan(rate))[:3]:
        print(f"  {stage}소동: {rate:.0f}%")
    print(f"{POLICY_NAME} 한 판 평균 행동: 소환 {trained['avg_buy']:.1f}번, 강화 {trained['avg_upgrade']:.1f}번, "
          f"판매 {trained['avg_sell']:.1f}번")

    ppo.write_csv(OUTPUT_DIR / "episodes.csv", run["episodes"],
                  ["episode", "timesteps", "reward", "reached", "cleared", "won", "life", "gold",
                   "length", "buy", "upgrade", "sell"])
    ppo.write_csv(OUTPUT_DIR / "evaluations.csv", run["evals"],
                  ["timesteps", "clear_rate", "avg_reached", "avg_life", "avg_gold", "avg_reward",
                   "avg_length", "avg_buy", "avg_upgrade", "avg_sell"])
    ppo.write_csv(OUTPUT_DIR / "updates.csv", run["updates"],
                  ["update", "timesteps", "worker_updates", "actor_loss", "critic_loss", "entropy",
                   "explained_variance"])
    rows = [{"policy": name, **result} for name, results in final.items() for result in results]
    ppo.write_csv(OUTPUT_DIR / "final_eval.csv", rows,
                  ["policy", "seed", "won", "reached", "cleared", "life", "gold", "reward",
                   "length", "buy", "upgrade", "sell"])

    ppo.setup_plot_style()
    ppo.plot_episode_trend(run, "reward", "1. Episode별 누적 Reward", "누적 Reward", "1_episode_reward.png")
    ppo.plot_episode_trend(run, "reached", "2. Episode별 도달 소동", "도달 소동", "2_episode_stage.png",
                           ylim=(0, ppo.MAX_STAGES + 1))
    ppo.plot_eval_trend(run, "clear_rate", f"3. 30소동 클리어율 (고정 시드 {ppo.EVAL_GAMES}판)", "클리어율 (%)",
                        "3_clear_rate.png", ylim=(-5, 105), fmt="{:.0f}%")
    ppo.plot_eval_trend(run, "avg_life", "4. 평균 잔여 결계", "평균 잔여 결계", "4_remaining_life.png",
                        ylim=(-0.5, ppo.INITIAL_LIFE + 0.5))
    ppo.plot_eval_trend(run, "avg_gold", "5. 평균 잔여 골드", "평균 잔여 골드", "5_remaining_gold.png", fmt="{:.0f}")
    plot_a3c_stability(run, "6_a3c_stability.png")
    ppo.plot_final_summary(final, "7_final_summary.png")
    print()
    print(f"지표 CSV 4개와 그래프 7장을 저장했습니다: {OUTPUT_DIR}")


def print_intro():
    print("A3C로 월하사신 준비 단계를 학습합니다.")
    print("loss = -log pi(a|s) * A + c1 * (R - V)^2 - c2 * 엔트로피  (워커마다 따로 계산해서 공용 신경망에 바로 반영)")
    target = "n-step Return" if A3C["gae_lambda"] >= 1.0 else f"GAE(lambda={A3C['gae_lambda']})"
    print(f"총 {ppo.TOTAL_TIMESTEPS} Step, 워커 {NUM_WORKERS}개가 각자 {N_STEPS} Step마다 공용 신경망을 고침, "
          f"어드밴티지는 {target}, gamma={A3C['gamma']}, lr={LR}")
    print(f"설정 파일: {CONFIG['_config_file'] or '없음(코드 기본값)'}, 저장 위치: {OUTPUT_DIR}")
    reward = ppo.REWARD
    print(
        f"보상({ppo.REWARD_PROFILE}): 소동 버티면 +{reward['clear']}, 결계 1당 -{reward['life']}, "
        f"게임 오버 {reward['over']}, {ppo.TRAIN_STAGES}소동 도달 +{reward['goal']}, 보스 처치 {reward['boss'] or '없음'}, "
        f"판매로 잃는 골드 1당 -{reward['sell_loss']}, 행동 1번당 -{reward['action_cost']}"
        f"(추가: 시작 {reward['cost_start']}, 소환 {reward['cost_buy']}, 강화 {reward['cost_upgrade']}, "
        f"판매 {reward['cost_sell']}), 학습용 보상 배율 x{reward['scale']}"
    )
    print(f"정기 평가: {ppo.EVAL_EVERY_STEPS} Step마다 고정 시드 {ppo.EVAL_GAMES}판 (그동안 워커는 학습을 멈추고 평가 판을 나눠 둔다)")
    print()


def save_config():
    """이번 실행에 쓴 수치를 남긴다. 이어서 학습할 때는 처음 설정을 지우지 않게 config_<Step>.json으로 따로 남긴다."""
    used = {key: value for key, value in CONFIG.items() if not key.startswith("_")}
    used["reward"] = {"profile": ppo.REWARD_PROFILE, **ppo.REWARD}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "config.json"
    if path.exists() and ppo.RESUME and CHECKPOINT_PATH.exists():
        path = OUTPUT_DIR / f"config_{torch.load(CHECKPOINT_PATH, weights_only=False)['run']['timesteps']}.json"
    with open(path, "w", encoding="utf-8") as file:
        json.dump(used, file, ensure_ascii=False, indent=2)


def main():
    save_config()
    trainer = Trainer()
    trainer.train()
    report(trainer)


if __name__ == "__main__":
    main()
