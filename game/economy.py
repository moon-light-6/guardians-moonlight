from typing import Optional

from config import (
    CLEAR_GOLD_BASE,
    CLEAR_GOLD_BONUS,
    CLEAR_GOLD_BONUS_STAGES,
    CLEAR_GOLD_PER_STAGE,
    MAX_ACTIONS_PER_WAVE,
    MAX_TOWER_LEVEL,
    SELL_REFUND_RATE,
    SUMMON_COST,
)
from game.enemy import Enemy
from game.state import GamePhase, GameState
from game.tower import Tower


class Economy:
    TOWER_BUY_COST = SUMMON_COST
    SELL_REFUND_RATE = SELL_REFUND_RATE

    def on_enemy_killed(self, state: GameState, enemy: Enemy) -> bool:
        if state.phase != GamePhase.WAVE_ACTIVE or enemy.is_alive or enemy.reached_base or enemy.reward_paid:
            return False
        enemy.reward_paid = True
        reward = enemy.gold_reward
        state.gold += reward
        if enemy.is_boss:
            state.bosses_killed += 1
            state.wave_boss_gold += reward
        else:
            state.enemies_killed += 1
            state.wave_kill_gold += reward
        return True

    def on_stage_clear(self, state: GameState) -> bool:
        stage = state.current_stage
        if (
            state.phase != GamePhase.WAVE_ACTIVE
            or state.life <= 0
            or stage in state.clear_rewarded_stages
            or any(enemy.is_alive for enemy in state.enemies)
        ):
            return False
        reward = CLEAR_GOLD_BASE + stage * CLEAR_GOLD_PER_STAGE
        if stage in CLEAR_GOLD_BONUS_STAGES:
            reward += CLEAR_GOLD_BONUS
        state.clear_rewarded_stages.add(stage)
        state.wave_clear_gold = reward
        state.gold += reward
        # Advance only after the player confirms the settlement screen.
        return True

    def can_take_preparation_action(self, state: GameState) -> bool:
        return state.phase == GamePhase.PREPARATION and state.actions_taken_this_wave < MAX_ACTIONS_PER_WAVE

    def can_buy(self, state: GameState, slot_id: Optional[int]) -> bool:
        return (
            self.can_take_preparation_action(state)
            and state.is_valid_slot(slot_id)
            and state.is_slot_empty(slot_id)
            and state.gold >= self.TOWER_BUY_COST
        )

    def can_upgrade(self, state: GameState, slot_id: Optional[int]) -> bool:
        allowed_phase = self.can_take_preparation_action(state) or state.phase == GamePhase.WAVE_ACTIVE
        if not allowed_phase or not state.is_valid_slot(slot_id) or not state.has_tower(slot_id):
            return False
        tower = state.towers[slot_id]
        return tower["level"] < MAX_TOWER_LEVEL and state.gold >= self.get_upgrade_cost(state, slot_id)

    def can_sell(self, state: GameState, slot_id: Optional[int]) -> bool:
        return (
            self.can_take_preparation_action(state)
            and state.is_valid_slot(slot_id)
            and state.selected_slot == slot_id
            and state.has_tower(slot_id)
        )

    def can_confirm_sell(self, state: GameState, slot_id: Optional[int]) -> bool:
        return (
            state.phase == GamePhase.SELL_CONFIRM
            and state.actions_taken_this_wave < MAX_ACTIONS_PER_WAVE
            and state.is_valid_slot(slot_id)
            and state.pending_sell_slot == slot_id == state.selected_slot
            and state.has_tower(slot_id)
        )

    def can_relocate(self, state: GameState, from_slot: Optional[int], to_slot: Optional[int]) -> bool:
        return (
            (self.can_take_preparation_action(state) or (
                state.phase == GamePhase.MOVING_TOWER
                and state.actions_taken_this_wave < MAX_ACTIONS_PER_WAVE
                and state.moving_from_slot == from_slot
            ))
            and state.is_valid_slot(from_slot)
            and state.is_valid_slot(to_slot)
            and from_slot != to_slot
            and state.has_tower(from_slot)
            and state.is_slot_empty(to_slot)
        )

    def can_start_wave(self, state: GameState) -> bool:
        return state.phase == GamePhase.PREPARATION

    def get_upgrade_cost(self, state: GameState, slot_id: int) -> int:
        if not state.has_tower(slot_id):
            return 0
        return Tower.get_upgrade_cost(state.towers[slot_id]["level"])

    def get_total_investment(self, state: GameState, slot_id: int) -> int:
        if not state.has_tower(slot_id):
            return 0
        level = state.towers[slot_id]["level"]
        return SUMMON_COST + sum(Tower.get_upgrade_cost(lv) for lv in range(1, level))

    def get_sell_refund(self, state: GameState, slot_id: int) -> int:
        return int(self.get_total_investment(state, slot_id) * self.SELL_REFUND_RATE)

    def buy_random_tower(self, rng) -> str:
        return rng.choice(Tower.all_types())
