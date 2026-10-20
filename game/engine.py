import random
from typing import Optional

from config import (
    BOSS_KILL_GOLD,
    COMBAT_SPEEDS,
    INITIAL_GOLD,
    INITIAL_LIFE,
    KILL_GOLD,
    MAX_STAGES,
    SIMULATION_STEP,
    SUMMON_TOTAL_SECONDS,
)
from game.actions import Action, ActionType
from game.combat import Combat
from game.economy import Economy
from game.map import GameMap
from game.state import GamePhase, GameState, WaveResult
from game.tower import Tower
from game.wave import WaveManager


class Game:
    def __init__(self):
        self.state = GameState()
        self.map = GameMap()
        self.combat = Combat()
        self.wave_manager = WaveManager()
        self.economy = Economy()
        self.rng = random.Random()
        self._simulation_accumulator = 0.0
        self._next_enemy_id = 1

    def reset(self, seed: Optional[int] = None, start_at_title: bool = True) -> GameState:
        self.rng = random.Random(seed)
        self.wave_manager.reset()
        self.state = GameState()
        self._simulation_accumulator = 0.0
        self._next_enemy_id = 1
        if not start_at_title:
            self._new_run()
        return self.state

    def step(self, action: Action) -> GameState:
        kind = action.action_type

        if kind == ActionType.START_GAME:
            self._new_run()
            
        elif kind == ActionType.SHOW_HELP:
            self.state.phase = GamePhase.HELP
        elif kind == ActionType.BACK_TO_TITLE:
            self.state.phase = GamePhase.TITLE
            self.state.combat_speed = 1.0
        elif kind == ActionType.RESTART:
            self._new_run()
        elif kind == ActionType.CONTINUE:
            self._continue_after_settlement()
        elif kind == ActionType.CYCLE_SPEED and self.state.phase == GamePhase.WAVE_ACTIVE:
            index = COMBAT_SPEEDS.index(self.state.combat_speed)
            self.state.combat_speed = COMBAT_SPEEDS[(index + 1) % len(COMBAT_SPEEDS)]
        elif kind == ActionType.CANCEL and self.state.phase in {
            GamePhase.SELL_CONFIRM, GamePhase.MOVING_TOWER, GamePhase.SUMMON_CONFIRM
        }:
            self.state.phase = GamePhase.PREPARATION
            self.state.moving_from_slot = None
            self.state.pending_sell_slot = None
        elif kind == ActionType.SELECT_SLOT:
            self._select_slot(action.slot_id)
        elif kind == ActionType.UPGRADE:
            self._handle_upgrade(action.slot_id)
        elif self.state.phase == GamePhase.PREPARATION:
            if kind == ActionType.BUY:
                self._handle_buy(action.slot_id)
            elif kind == ActionType.SELL:
                self._begin_sell(action.slot_id)
            elif kind == ActionType.BEGIN_RELOCATE:
                self._begin_relocate(action.slot_id)
            elif kind == ActionType.START_WAVE:
                self._start_wave()
        elif self.state.phase == GamePhase.SELL_CONFIRM and kind == ActionType.CONFIRM_SELL:
            self._handle_sell(action.slot_id)
        elif self.state.phase == GamePhase.MOVING_TOWER and kind == ActionType.RELOCATE:
            self._handle_relocate(action.from_slot_id, action.to_slot_id)

        return self.state

    def update(self, dt: float) -> None:
        if dt <= 0:
            return

        # 준비/전투 여부와 무관하게 진행합니다. 소환 중에도 이벤트 루프와 화면은
        # 멈추지 않으며, 완료 순간에만 실제 타워를 한 번 생성합니다.
        self._update_summons(dt)

        if self.state.phase != GamePhase.WAVE_ACTIVE:
            return

        # Keep every combat system on the same clock and avoid skipping range checks.
        self._simulation_accumulator += dt * self.state.combat_speed
        while self._simulation_accumulator + 1e-9 >= SIMULATION_STEP:
            self._simulation_accumulator = max(0.0, self._simulation_accumulator - SIMULATION_STEP)
            self._update_combat(SIMULATION_STEP)
            if self.state.phase != GamePhase.WAVE_ACTIVE:
                self._simulation_accumulator = 0.0
                break

    def _update_combat(self, dt: float) -> None:
        self.state.wave_elapsed += dt
        self.state.effects = [
            {**effect, "age": effect["age"] + dt}
            for effect in self.state.effects
            if effect["age"] + dt < effect["ttl"] - 1e-9
        ]

        self.state.enemies.extend(self.wave_manager.update(dt, self.map.get_path()))
        self._assign_enemy_ids()
        self._move_enemies(dt)
        # Capture arrival/death positions before enemies leave the state, even
        # when several simulation steps run between rendered frames.
        self._update_effect_targets()
        if self.state.life <= 0:
            self.state.phase = GamePhase.GAME_OVER
            self.state.message = "소동 해결 실패"
            return
        self._update_towers(dt)
        self._collect_dead_enemies()

        alive = [enemy for enemy in self.state.enemies if enemy.is_alive]
        if self.wave_manager.is_wave_complete(alive):
            self._transition_to_settlement()

    def get_state(self) -> GameState:
        return self.state

    def _update_summons(self, dt: float) -> None:
        pending = []
        for summon in self.state.summons:
            summon = {**summon, "elapsed": summon["elapsed"] + dt}
            if summon["elapsed"] < SUMMON_TOTAL_SECONDS:
                pending.append(summon)
                continue

            slot_id = summon["slot_id"]
            # 타워는 구매 때 한 번만 만들고, 연출이 끝난 순간 전투/렌더링에 참여시킵니다.
            tower = self.state.towers.get(slot_id)
            if tower is not None:
                tower.pop("summoning", None)
                self.state.message = f"{Tower.display_name(tower['type'])} Lv.1 소환 완료"
        self.state.summons = pending

    def _new_run(self) -> None:
        self.wave_manager.reset()
        self._simulation_accumulator = 0.0
        self._next_enemy_id = 1
        self.state = GameState(phase=GamePhase.PREPARATION, gold=INITIAL_GOLD, life=INITIAL_LIFE)
        self.state.message = "빈 슬롯을 선택해 사신을 소환하세요"

    def _select_slot(self, slot_id: Optional[int]) -> None:
        if self.state.phase == GamePhase.WAVE_ACTIVE and slot_id is None:
            # 전투 중 사신이 없는 곳을 누르면 선택을 해제해 보스 정보가 다시 보이게 한다.
            self.state.selected_slot = None
            return
        if self.state.phase not in {GamePhase.PREPARATION, GamePhase.MOVING_TOWER, GamePhase.WAVE_ACTIVE}:
            return
        if not self.state.is_valid_slot(slot_id):
            return
        if self.state.phase == GamePhase.WAVE_ACTIVE and not self.state.has_tower(slot_id):
            return
        self.state.selected_slot = slot_id
        if self.state.phase == GamePhase.MOVING_TOWER and self.state.moving_from_slot is not None:
            self._handle_relocate(self.state.moving_from_slot, slot_id)

    def _handle_buy(self, slot_id: Optional[int]) -> None:
        if not self.economy.can_buy(self.state, slot_id):
            self.state.message = "소환할 수 없습니다"
            return
        tower_type = self.economy.buy_random_tower(self.rng)
        self.state.gold -= self.economy.TOWER_BUY_COST
        self.state.tower_slots[slot_id] = True
        # 게임 규칙상 타워는 즉시 한 번 생성하되, 3초 동안은 렌더링·공격에서 제외합니다.
        # 따라서 연출용/실제 사신이 중복 생성되지 않습니다.
        self.state.towers[slot_id] = {
            "type": tower_type,
            "level": 1,
            "slot_id": slot_id,
            "cooldown": 999.0,
            "summoning": True,
        }
        self.state.summons.append({
            "slot_id": slot_id,
            "tower_type": tower_type,
            "elapsed": 0.0,
        })
        self.state.actions_taken_this_wave += 1
        self.state.selected_slot = slot_id
        self.state.message = f"{Tower.display_name(tower_type)} 벽화에서 소환 중"

    def _handle_upgrade(self, slot_id: Optional[int]) -> None:
        if not self.economy.can_upgrade(self.state, slot_id):
            self.state.message = "강화할 수 없습니다"
            return
        cost = self.economy.get_upgrade_cost(self.state, slot_id)
        self.state.gold -= cost
        self.state.towers[slot_id]["level"] += 1
        if self.state.phase == GamePhase.PREPARATION:
            self.state.actions_taken_this_wave += 1
        tower = self.state.towers[slot_id]
        self.state.message = f"{Tower.display_name(tower['type'])} Lv.{tower['level']} 강화"

    def _begin_sell(self, slot_id: Optional[int]) -> None:
        if self.economy.can_sell(self.state, slot_id):
            self.state.selected_slot = slot_id
            self.state.pending_sell_slot = slot_id
            self.state.phase = GamePhase.SELL_CONFIRM
            self.state.message = "판매를 확인하세요"

    def _handle_sell(self, slot_id: Optional[int]) -> None:
        if not self.economy.can_confirm_sell(self.state, slot_id):
            self.state.phase = GamePhase.PREPARATION
            self.state.pending_sell_slot = None
            return
        refund = self.economy.get_sell_refund(self.state, slot_id)
        tower_type = self.state.towers[slot_id]["type"]
        self.state.gold += refund
        del self.state.towers[slot_id]
        self.state.summons = [
            summon for summon in self.state.summons if summon["slot_id"] != slot_id
        ]
        self.state.tower_slots[slot_id] = False
        self.state.actions_taken_this_wave += 1
        self.state.phase = GamePhase.PREPARATION
        self.state.selected_slot = None
        self.state.pending_sell_slot = None
        self.state.moving_from_slot = None
        self.state.message = f"{Tower.display_name(tower_type)} 판매 +{refund}G"

    def _begin_relocate(self, slot_id: Optional[int]) -> None:
        if self.state.has_tower(slot_id) and self.economy.can_take_preparation_action(self.state):
            self.state.moving_from_slot = slot_id
            self.state.phase = GamePhase.MOVING_TOWER
            self.state.message = "옮길 빈 슬롯을 선택하세요"

    def _handle_relocate(self, from_slot: Optional[int], to_slot: Optional[int]) -> None:
        if not self.economy.can_relocate(self.state, from_slot, to_slot):
            self.state.message = "이동할 수 없습니다"
            return
        tower = self.state.towers.pop(from_slot)
        tower["slot_id"] = to_slot
        self.state.towers[to_slot] = tower
        for summon in self.state.summons:
            if summon["slot_id"] == from_slot:
                summon["slot_id"] = to_slot
        self.state.tower_slots[from_slot] = False
        self.state.tower_slots[to_slot] = True
        self.state.selected_slot = to_slot
        self.state.moving_from_slot = None
        self.state.actions_taken_this_wave += 1
        self.state.phase = GamePhase.PREPARATION
        self.state.message = "사신 이동 완료"

    def _start_wave(self) -> None:
        if not self.economy.can_start_wave(self.state):
            return
        self.state.phase = GamePhase.WAVE_ACTIVE
        self.state.current_wave = self.state.current_stage
        self.state.wave_elapsed = 0.0
        self.state.wave_life_before = self.state.life
        self.state.wave_kill_gold = 0
        self.state.wave_boss_gold = 0
        self.state.wave_clear_gold = 0
        self.state.wave_reached_base = 0
        self._simulation_accumulator = 0.0
        self.state.enemies = []
        self.state.effects = []
        self.state.message = "소동 해결 중"
        self.wave_manager.start_wave(self.state.current_stage)

    def _assign_enemy_ids(self) -> None:
        """Run-local monotonic IDs; preserve IDs in restored/injected state."""
        used = [enemy.enemy_id for enemy in self.state.enemies if enemy.enemy_id is not None]
        for effect in self.state.effects:
            used.extend(value for value in effect.get("target_ids", []) if value is not None)
            if effect.get("target_id") is not None:
                used.append(effect["target_id"])
        self._next_enemy_id = max(self._next_enemy_id, max(used, default=0) + 1)
        for enemy in self.state.enemies:
            if enemy.enemy_id is None:
                enemy.enemy_id = self._next_enemy_id
                self._next_enemy_id += 1

    def _update_effect_targets(self) -> None:
        """Update only visual fallback coordinates; impact coordinates stay fixed."""
        positions = {enemy.enemy_id: enemy.get_current_position()
                     for enemy in self.state.enemies if enemy.enemy_id is not None}
        for effect in self.state.effects:
            if effect["kind"] in {"claw", "fire"}:
                target_id = effect.get("target_id")
                if target_id in positions:
                    effect["last_target_position"] = positions[target_id]
            elif effect["kind"] == "lightning":
                points = effect.get("points", [])
                last = effect.get("last_target_positions", points)
                ids = effect.get("target_ids", [])
                effect["last_target_positions"] = [
                    positions.get(ids[index], last[index]) if index < len(ids) else last[index]
                    for index in range(len(points))
                ]

    def _move_enemies(self, dt: float) -> None:
        for enemy in list(self.state.enemies):
            if not enemy.is_alive:
                continue
            speed_modifier = min(
                enemy.get_speed_modifier(self.state.wave_elapsed),
                self.combat.get_field_speed_modifier(enemy.get_current_position(), self.state.effects),
            )
            if enemy.move(dt, speed_modifier):
                self.state.life -= enemy.life_damage
                self.state.enemies_reached_base += 1
                self.state.wave_reached_base += 1
                if self.state.life <= 0:
                    break

    def _update_towers(self, dt: float) -> None:
        for slot_id, tower_data in self.state.towers.items():
            tower_data["cooldown"] = tower_data.get("cooldown", 999.0) + dt
            tower = Tower.from_data(tower_data)
            if not tower.can_attack():
                continue
            tower_pos = self.map.get_slot_position(slot_id)
            effects = self.combat.attack(tower_data, tower_pos, self.state.enemies, self.state.wave_elapsed)
            self.state.effects.extend(effects)

    def _collect_dead_enemies(self) -> None:
        remaining = []
        for enemy in self.state.enemies:
            if enemy.is_alive:
                remaining.append(enemy)
            else:
                self.economy.on_enemy_killed(self.state, enemy)
        self.state.enemies = remaining

    def _transition_to_settlement(self) -> None:
        if (
            self.state.phase != GamePhase.WAVE_ACTIVE
            or self.state.life <= 0
            or not self.wave_manager.is_wave_complete(self.state.enemies)
        ):
            return
        self.state.effects = []
        stage = self.state.current_stage
        self.economy.on_stage_clear(self.state)
        clear_gold = self.state.wave_clear_gold
        boss_name = WaveManager.BOSSES.get(stage, {}).get("name")
        self.state.wave_result = WaveResult(
            stage=stage,
            normal_kills=self.state.wave_kill_gold // KILL_GOLD,
            boss_kills=self.state.wave_boss_gold // BOSS_KILL_GOLD,
            kill_gold=self.state.wave_kill_gold,
            boss_gold=self.state.wave_boss_gold,
            clear_gold=clear_gold,
            total_gold=self.state.wave_kill_gold + self.state.wave_boss_gold + clear_gold,
            life_before=self.state.wave_life_before,
            life_after=self.state.life,
            reached_base=self.state.wave_reached_base,
            boss_name=boss_name,
        )
        self.state.phase = GamePhase.SETTLEMENT
        self.state.message = f"{stage}번째 소동 해결!"

    def _continue_after_settlement(self) -> None:
        if self.state.phase != GamePhase.SETTLEMENT:
            return
        if self.state.current_stage >= MAX_STAGES:
            self.state.phase = GamePhase.VICTORY
            self.state.message = "결계 수호 성공!"
            return
        self.state.current_stage += 1
        self.state.actions_taken_this_wave = 0
        self.state.selected_slot = None
        self.state.phase = GamePhase.PREPARATION
        self.state.message = "다음 수호 준비 단계"
