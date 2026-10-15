from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ActionType(Enum):
    START_GAME = "START_GAME"
    SHOW_HELP = "SHOW_HELP"
    BACK_TO_TITLE = "BACK_TO_TITLE"
    CONTINUE = "CONTINUE"
    RESTART = "RESTART"
    SELECT_SLOT = "SELECT_SLOT"
    BUY = "BUY"
    UPGRADE = "UPGRADE"
    SELL = "SELL"
    CONFIRM_SELL = "CONFIRM_SELL"
    BEGIN_RELOCATE = "BEGIN_RELOCATE"
    RELOCATE = "RELOCATE"
    CANCEL = "CANCEL"
    START_WAVE = "START_WAVE"
    CYCLE_SPEED = "CYCLE_SPEED"


@dataclass
class Action:
    action_type: ActionType
    slot_id: Optional[int] = None
    from_slot_id: Optional[int] = None
    to_slot_id: Optional[int] = None

    @property
    def type(self) -> str:
        return self.action_type.value


class ActionValidator:
    @staticmethod
    def is_valid_action(action: Action, state) -> bool:
        from game.economy import Economy

        economy = Economy()
        if action.action_type == ActionType.BUY:
            return economy.can_buy(state, action.slot_id)
        if action.action_type == ActionType.UPGRADE:
            return economy.can_upgrade(state, action.slot_id)
        if action.action_type == ActionType.SELL:
            return economy.can_sell(state, action.slot_id)
        if action.action_type == ActionType.CONFIRM_SELL:
            return economy.can_confirm_sell(state, action.slot_id)
        if action.action_type == ActionType.CYCLE_SPEED:
            from game.state import GamePhase

            return state.phase == GamePhase.WAVE_ACTIVE
        if action.action_type == ActionType.RELOCATE:
            return economy.can_relocate(state, action.from_slot_id, action.to_slot_id)
        if action.action_type == ActionType.BEGIN_RELOCATE:
            return economy.can_take_preparation_action(state) and state.has_tower(action.slot_id)
        if action.action_type == ActionType.START_WAVE:
            return economy.can_start_wave(state)
        return True

    @staticmethod
    def get_all_valid_actions(state) -> list:
        from game.economy import Economy
        from game.state import GamePhase

        economy = Economy()
        if state.phase not in {GamePhase.PREPARATION, GamePhase.WAVE_ACTIVE}:
            return []

        valid_actions = []
        for slot_id in range(24):
            if economy.can_buy(state, slot_id):
                valid_actions.append(Action(ActionType.BUY, slot_id=slot_id))
            if economy.can_upgrade(state, slot_id):
                valid_actions.append(Action(ActionType.UPGRADE, slot_id=slot_id))
            if economy.can_sell(state, slot_id):
                valid_actions.append(Action(ActionType.SELL, slot_id=slot_id))

        for from_slot in range(24):
            for to_slot in range(24):
                if economy.can_relocate(state, from_slot, to_slot):
                    valid_actions.append(
                        Action(ActionType.RELOCATE, from_slot_id=from_slot, to_slot_id=to_slot)
                    )

        if economy.can_start_wave(state):
            valid_actions.append(Action(ActionType.START_WAVE))
        return valid_actions
