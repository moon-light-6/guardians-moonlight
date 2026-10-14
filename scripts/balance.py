import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.actions import Action, ActionType
from game.engine import Game
from game.state import GamePhase


class BalanceAnalyzer:
    def __init__(self, num_games: int = 10, stages_per_game: int = 30):
        self.num_games = num_games
        self.stages_per_game = stages_per_game
        self.results = []

    def run_simulation(self) -> None:
        print(f"밸런스 시뮬레이션: {self.num_games}판, 목표 {self.stages_per_game}웨이브")
        for seed in range(self.num_games):
            result = self._run_single_game(seed)
            self.results.append(result)
            print(
                f"[{seed + 1:02d}] 도달 {result['stage']}웨이브, "
                f"라이프 {result['life']}, 골드 {result['gold']}G, 처치 {result['kills']}"
            )

    def _run_single_game(self, seed: int) -> dict:
        rng = random.Random(seed)
        game = Game()
        state = game.reset(seed=seed, start_at_title=False)

        while state.phase not in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
            self._prepare(game, state, rng)
            game.step(Action(ActionType.START_WAVE))
            for _ in range(1200):
                game.update(0.1)
                if state.phase != GamePhase.WAVE_ACTIVE:
                    break
            if state.phase == GamePhase.SETTLEMENT:
                game.step(Action(ActionType.CONTINUE))
            if state.current_stage > self.stages_per_game and state.phase == GamePhase.PREPARATION:
                break

        return {
            "stage": state.current_stage,
            "life": state.life,
            "gold": state.gold,
            "kills": state.enemies_killed + state.bosses_killed,
            "phase": state.phase.value,
        }

    def _prepare(self, game: Game, state, rng: random.Random) -> None:
        if state.phase != GamePhase.PREPARATION:
            return
        useful_slots = [6, 7, 8, 9, 12, 13, 14, 15, 16, 20, 21]
        rng.shuffle(useful_slots)
        for slot in useful_slots:
            if state.gold >= 100 and state.is_slot_empty(slot):
                game.step(Action(ActionType.BUY, slot_id=slot))
            if state.actions_taken_this_wave >= 8:
                break
        for slot in list(state.towers):
            if state.gold <= 80:
                break
            game.step(Action(ActionType.UPGRADE, slot_id=slot))

    def print_statistics(self) -> None:
        cleared = sum(1 for item in self.results if item["phase"] == "victory")
        avg_life = sum(item["life"] for item in self.results) / len(self.results)
        print(f"30웨이브 승리: {cleared}/{len(self.results)}")
        print(f"평균 남은 라이프: {avg_life:.1f}")


def main():
    analyzer = BalanceAnalyzer()
    analyzer.run_simulation()
    analyzer.print_statistics()


if __name__ == "__main__":
    main()
