"""
AI 자동 플레이 진행기. Pygame에 의존하지 않아 화면 없이도 같은 흐름을 검증할 수 있다(ai_demo/verify.py).

흐름은 scripts/ppo.py의 GuardianEnv / play_one과 같다.
  준비 단계: 정책이 행동 하나를 고른다 -> (시연용으로 잠깐 보여 준 뒤) 실행
    - 소환·강화·판매: GuardianEnv.step()을 그대로 호출
    - 소동 시작: 소환 연출이 끝나면 START_WAVE. 전투는 게임 엔진이 프레임마다 진행(AI는 관여하지 않음)
  정산: 잠깐 보여 준 뒤 CONTINUE. 30소동을 버티면 승리
  게임 오버/승리: 결과 기록
게임 시간은 엔진의 고정 시간 간격(1/120초)으로만 계산되므로, 프레임 길이나 배속이 달라도 결과는 같다.
"""

from enum import Enum
from typing import List, Optional, Tuple

from config import COMBAT_SPEEDS, MAX_STAGES
from game.actions import Action, ActionType
from game.state import GamePhase
from game.tower import Tower

from ai_demo.ppo_bridge import Decision, PolicyAgent
from ai_demo.stats import ActionRecord, DemoStats, SessionLogger

# main.py와 같은 값: 한 프레임에 반영할 최대 시간(초)
MAX_FRAME_SECONDS = 0.1


class Status(Enum):
    NO_MODEL = "no_model"
    DECIDING = "deciding"          # 준비 단계: 고른 행동을 보여 주는 중
    WAITING_SUMMON = "waiting"     # 소동 시작을 골랐고 소환 연출이 끝나기를 기다림
    WAVE = "wave"                  # 전투(게임 엔진 자동 진행)
    SETTLEMENT = "settlement"
    FINISHED = "finished"


class DemoController:
    def __init__(self, ppo, agent: Optional[PolicyAgent], stats: DemoStats,
                 logger: Optional[SessionLogger] = None, think_seconds: float = 0.6,
                 settle_seconds: float = 1.8, stages: int = MAX_STAGES, model_name: str = ""):
        self.ppo = ppo
        self.agent = agent
        self.stats = stats
        self.logger = logger or SessionLogger(None)
        self.think_seconds = think_seconds
        self.settle_seconds = settle_seconds
        self.stages = stages
        self.model_name = model_name
        # 평가와 같은 환경(30소동). 엔진·관측·마스크·소환/강화/판매 처리를 그대로 쓴다.
        self.env = ppo.GuardianEnv(stages=stages)
        self.wave_time_limit = ppo.MAX_WAVE_TICKS * ppo.WAVE_TICK
        self.combat_speed = 1.0
        self.games_played = 0
        self.seed = 0
        self.events: List[Tuple[str, object]] = []  # 화면 연출용(소환·강화·판매·소동 시작/종료)
        self.pending: Optional[Decision] = None
        self.last_decision: Optional[Decision] = None
        self.last_record: Optional[ActionRecord] = None
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.paused = False
        self._timer = 0.0
        self._settle_timer: Optional[float] = None

    # ----- 상태 -----

    @property
    def game(self):
        return self.env.game

    @property
    def state(self):
        return self.env.game.state

    @property
    def status(self) -> Status:
        phase = self.state.phase
        if self.result is not None or phase in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
            return Status.FINISHED
        if self.agent is None:
            return Status.NO_MODEL
        if phase == GamePhase.WAVE_ACTIVE:
            return Status.WAVE
        if phase == GamePhase.SETTLEMENT:
            return Status.SETTLEMENT
        if self.pending is not None and self.ppo.action_kind(self.pending.action) == "start" and self.state.summons:
            return Status.WAITING_SUMMON
        return Status.DECIDING

    def action_kind(self, action: int) -> str:
        return self.ppo.action_kind(action)

    def action_slot(self, action: int) -> Optional[int]:
        kind = self.ppo.action_kind(action)
        offsets = {"buy": self.ppo.BUY_OFFSET, "upgrade": self.ppo.UPGRADE_OFFSET, "sell": self.ppo.SELL_OFFSET}
        return action - offsets[kind] if kind in offsets else None

    def describe_action(self, action: int) -> str:
        kind = self.ppo.action_kind(action)
        if kind == "start":
            return f"{self.state.current_stage}번째 소동 시작"
        slot = self.action_slot(action)
        label = {"buy": "소환", "upgrade": "강화", "sell": "판매"}[kind]
        tower = self.state.towers.get(slot)
        if tower is not None and kind != "buy":
            return f"슬롯 {slot + 1} {Tower.display_name(tower['type'])} {label}"
        return f"슬롯 {slot + 1} {label}"

    # ----- 진행 -----

    def new_game(self, seed: int) -> None:
        self.seed = seed
        self.games_played += 1
        self.env.reset(seed=seed)
        self.state.combat_speed = self.combat_speed
        if self.agent is not None:
            self.agent.reset(seed)
        self.counter = {"length": 0, "start": 0, "buy": 0, "upgrade": 0, "sell": 0}
        self.pending = self.last_decision = self.last_record = None
        self.result = self.error = None
        self._timer = 0.0
        self._settle_timer = None
        self.stats.new_game()
        self.events.append(("new_game", seed))

    def set_speed(self, speed: float) -> None:
        self.combat_speed = speed
        self.state.combat_speed = speed

    def cycle_speed(self) -> float:
        """게임의 배속 버튼과 같은 순서(1 -> 1.5 -> 2 -> 5). 전투 중에는 엔진의 CYCLE_SPEED를 그대로 쓴다."""
        if self.state.phase == GamePhase.WAVE_ACTIVE:
            self.game.step(Action(ActionType.CYCLE_SPEED))
            self.combat_speed = self.state.combat_speed
        else:
            index = COMBAT_SPEEDS.index(self.combat_speed) if self.combat_speed in COMBAT_SPEEDS else 0
            self.set_speed(COMBAT_SPEEDS[(index + 1) % len(COMBAT_SPEEDS)])
        return self.combat_speed

    def update(self, dt: float) -> None:
        if self.paused:
            return
        dt = min(max(dt, 0.0), MAX_FRAME_SECONDS)
        self.game.update(dt)
        if self.agent is None or self.result is not None:
            return
        state = self.state
        pace = max(state.combat_speed, 1.0)  # 준비·정산 연출 시간도 배속에 맞춰 줄인다

        if state.phase == GamePhase.WAVE_ACTIVE:
            if state.wave_elapsed > self.wave_time_limit:
                self.error = f"{state.current_stage}번째 소동이 {self.wave_time_limit:.0f}초 안에 끝나지 않았습니다."
                self._finish()
            return
        if state.phase == GamePhase.SETTLEMENT:
            if self._settle_timer is None:
                self._settle_timer = self.settle_seconds
                self.events.append(("wave_end", state.wave_result))
            self._settle_timer -= dt * pace
            if self._settle_timer <= 0:
                self._settle_timer = None
                if state.current_stage >= self.stages:
                    # GuardianEnv._play_wave와 같이 마지막 소동을 버티면 승리. 화면은 승리 장면으로 넘긴다.
                    self.env.won = True
                    self.game.step(Action(ActionType.CONTINUE))
                    self._finish()
                else:
                    self.game.step(Action(ActionType.CONTINUE))
            return
        if state.phase in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
            self.events.append(("wave_end", None))
            self._finish()
            return
        if state.phase != GamePhase.PREPARATION:
            return

        if self.pending is None:
            self._decide()
            self._timer = self.think_seconds
        self._timer -= dt * pace
        if self._timer <= 0:
            self._execute()

    def _decide(self) -> None:
        obs = self.env.observe()
        mask = self.env.valid_action_mask()
        self.pending = self.agent.decide(obs, mask)
        self.events.append(("decide", self.pending))

    def _execute(self) -> None:
        decision = self.pending
        state = self.state
        kind = self.ppo.action_kind(decision.action)
        if not self.env.valid_action_mask()[decision.action]:
            raise RuntimeError(f"고른 뒤 실행할 수 없게 된 행동: {self.ppo.action_name(decision.action)}")
        stage, gold_before = state.current_stage, state.gold
        slot = self.action_slot(decision.action)
        tower_type, level_after = "", 0

        if kind == "start":
            # GuardianEnv._play_wave처럼 소환 연출이 끝난 뒤 시작한다(준비 단계에서는 전투 시간이 흐르지 않음).
            if state.summons:
                return
            self.game.step(Action(ActionType.START_WAVE))
            # 전투 중 오른쪽 패널에 보스 정보가 보이도록 선택만 해제한다(게임 결과와 무관).
            self.game.step(Action(ActionType.SELECT_SLOT, slot_id=None))
            detail = f"{stage}번째 소동 시작"
        else:
            before = dict(state.towers.get(slot) or {})
            refund = self.game.economy.get_sell_refund(state, slot) if kind == "sell" else 0
            self.env.step(decision.action)
            after = state.towers.get(slot)
            if kind == "buy":
                tower_type, level_after = after["type"], after["level"]
                detail = f"슬롯 {slot + 1}에 {Tower.display_name(tower_type)} 소환"
            elif kind == "upgrade":
                tower_type, level_after = after["type"], after["level"]
                detail = f"슬롯 {slot + 1} {Tower.display_name(tower_type)} 강화 Lv.{before['level']}→{level_after}"
            else:
                tower_type = before["type"]
                detail = f"슬롯 {slot + 1} {Tower.display_name(tower_type)} Lv.{before['level']} 판매 +{refund}G"

        self.counter["length"] += 1
        self.counter[kind] += 1
        record = ActionRecord(
            game=self.games_played, seed=self.seed, step=self.counter["length"], stage=stage, kind=kind,
            action=decision.action, slot=slot, probability=decision.probability, detail=detail,
            gold_before=gold_before, gold_after=state.gold, tower_type=tower_type, level_after=level_after,
        )
        self.stats.add(record)
        self.logger.action(record)
        self.events.append(("action", record))
        self.last_decision, self.last_record = decision, record
        self.pending = None

    def _finish(self) -> None:
        if self.result is not None:
            return
        result = {
            "game": self.games_played,
            "seed": self.seed,
            "model": self.model_name,
            "policy": "greedy" if self.agent and self.agent.greedy else "sampling",
            **self.env.episode_result(),
            **self.counter,
        }
        if self.error:
            result["error"] = self.error
        self.result = result
        self.pending = None
        self.stats.results.append(result)
        self.events.append(("game_end", result))

    def log_result(self, recorded_match: Optional[bool]) -> None:
        if self.result is not None:
            self.result["recorded_match"] = "" if recorded_match is None else recorded_match
            self.logger.episode(self.result)
