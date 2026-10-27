from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from config import INITIAL_GOLD, INITIAL_LIFE, SLOT_COUNT


class GamePhase(Enum):
    TITLE = "title"
    HELP = "help"
    PREPARATION = "preparation"
    SUMMON_CONFIRM = "summon_confirm"
    MOVING_TOWER = "moving_tower"
    SELL_CONFIRM = "sell_confirm"
    WAVE_ACTIVE = "wave_active"
    SETTLEMENT = "settlement"
    GAME_OVER = "game_over"
    VICTORY = "victory"


@dataclass
class WaveResult:
    stage: int = 0
    normal_kills: int = 0
    boss_kills: int = 0
    kill_gold: int = 0
    boss_gold: int = 0
    clear_gold: int = 0
    total_gold: int = 0
    life_before: int = 0
    life_after: int = 0
    reached_base: int = 0
    boss_name: Optional[str] = None


@dataclass
class GameState:
    current_stage: int = 1
    current_wave: int = 0
    phase: GamePhase = GamePhase.TITLE
    gold: int = INITIAL_GOLD
    life: int = INITIAL_LIFE
    towers: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    tower_slots: List[bool] = field(default_factory=lambda: [False] * SLOT_COUNT)
    # 실제 타워를 만들기 전, 벽화에서 배치 칸으로 이동 중인 달빛 연출입니다.
    # tower_slots는 즉시 점유해 같은 칸에 중복 소환되는 것을 막습니다.
    summons: List[Dict[str, Any]] = field(default_factory=list)
    enemies: List[Any] = field(default_factory=list)
    effects: List[Dict[str, Any]] = field(default_factory=list)
    enemies_killed: int = 0
    bosses_killed: int = 0
    enemies_reached_base: int = 0
    actions_taken_this_wave: int = 0
    selected_slot: Optional[int] = None
    moving_from_slot: Optional[int] = None
    pending_sell_slot: Optional[int] = None
    message: str = ""
    wave_result: WaveResult = field(default_factory=WaveResult)
    wave_elapsed: float = 0.0
    wave_life_before: int = INITIAL_LIFE
    wave_kill_gold: int = 0
    wave_boss_gold: int = 0
    wave_clear_gold: int = 0
    clear_rewarded_stages: set[int] = field(default_factory=set)
    wave_reached_base: int = 0
    # 마지막 악귀 처치 후 정산까지 빈 게임판을 보여준 시간. 소동이 끝나기 전에는 None.
    wave_clear_elapsed: Optional[float] = None
    combat_speed: float = 1.0

    def is_valid_slot(self, slot_id: int) -> bool:
        return isinstance(slot_id, int) and 0 <= slot_id < SLOT_COUNT

    def is_slot_empty(self, slot_id: int) -> bool:
        return self.is_valid_slot(slot_id) and not self.tower_slots[slot_id]

    def has_tower(self, slot_id: int) -> bool:
        return slot_id in self.towers

    def get_observation(self) -> Dict[str, Any]:
        return {
            "stage": self.current_stage,
            "gold": self.gold,
            "life": self.life,
            "phase": self.phase.value,
            "actions": self.actions_taken_this_wave,
            "towers": {
                slot: {"type": data["type"], "level": data["level"]}
                for slot, data in self.towers.items()
            },
            "enemy_count": len([enemy for enemy in self.enemies if enemy.is_alive]),
            "combat_speed": self.combat_speed,
        }
