import argparse
import csv
import json
from pathlib import Path

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MAX_STAGES
from game.actions import Action, ActionType
from game.engine import Game
from game.state import GamePhase


class BalanceAnalyzer:
    def __init__(self, num_games: int = 10, stages_per_game: int = 30):
        if type(num_games) is not int or num_games <= 0:
            raise ValueError("num_games must be a positive integer")
        if type(stages_per_game) is not int or not 1 <= stages_per_game <= MAX_STAGES:
            raise ValueError(f"stages_per_game must be between 1 and {MAX_STAGES}")
        self.num_games = num_games
        self.stages_per_game = stages_per_game
        self.results = []

    def run_simulation(self) -> None:
        print(f"밸런스 시뮬레이션: {self.num_games}판, 목표 {self.stages_per_game}웨이브")
        self.results = []
        for seed in range(self.num_games):
            result = self._run_single_game(seed)
            self.results.append(result)
            print(
                f"[{seed + 1:02d}] 도달 {result['stage']}웨이브, "
                f"라이프 {result['life']}, 골드 {result['gold']}G, 처치 {result['kills']}"
            )
            if result["status"] == "error":
                print(f"  실행 오류: {result['error']}")

    def _run_single_game(self, seed: int) -> dict:
        rng = random.Random(seed)
        game = Game()
        state = game.reset(seed=seed, start_at_title=False)

        survived_stages = 0
        stage_results = []
        status, error = "completed", ""
        try:
            while state.phase not in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
                if state.phase != GamePhase.PREPARATION:
                    raise RuntimeError(f"Unexpected phase before wave: {state.phase.value}")
                stage = state.current_stage
                gold_before, life_before = state.gold, state.life
                self._prepare(game, state, rng)
                game.step(Action(ActionType.START_WAVE))
                state = game.get_state()
                if state.phase != GamePhase.WAVE_ACTIVE:
                    raise RuntimeError("Wave did not start")
                # 엔진 내부 고정 스텝을 사용합니다. 600초 이후에도 진행 중이면 오류입니다.
                for _ in range(6000):
                    game.update(0.1)
                    state = game.get_state()
                    if state.phase != GamePhase.WAVE_ACTIVE:
                        break
                else:
                    raise RuntimeError("Wave timed out after 600 seconds")
                completed = state.phase in {GamePhase.SETTLEMENT, GamePhase.VICTORY}
                stage_results.append({
                    "stage": stage, "gold_before": gold_before, "gold_after": state.gold,
                    "life_lost": life_before - state.life, "completed": completed,
                })
                if completed:
                    survived_stages += 1
                elif state.phase != GamePhase.GAME_OVER:
                    raise RuntimeError(f"Unexpected phase after wave: {state.phase.value}")
                if state.phase == GamePhase.SETTLEMENT:
                    game.step(Action(ActionType.CONTINUE))
                    state = game.get_state()
                    if state.phase != GamePhase.VICTORY and (
                        state.phase != GamePhase.PREPARATION or state.current_stage <= stage
                    ):
                        raise RuntimeError("CONTINUE did not advance to the next wave")
                if survived_stages >= self.stages_per_game:
                    break
            if state.phase == GamePhase.GAME_OVER:
                status = "game_over"
        except (TypeError, AttributeError, RuntimeError, ValueError) as exc:
            status, error = "error", str(exc)

        # 최신 main의 결과 키를 유지하고 기존 분석 기능을 추가합니다.
        return {
            "stage": state.current_stage,
            "life": state.life,
            "gold": state.gold,
            "kills": state.enemies_killed + state.bosses_killed,
            "phase": state.phase.value,
            "seed": seed,
            "status": status,
            "error": error,
            "survived_stages": survived_stages,
            "stage_results": stage_results,
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
        if not self.results:
            print("실행 결과가 없습니다.")
            return
        results = [item for item in self.results if item["status"] != "error"]
        errors = len(self.results) - len(results)
        print(f"실행 오류: {errors}판 (통계에서 제외)")
        if not results:
            print("유효한 결과가 없어 클리어율을 계산하지 않습니다.")
            return
        cleared = sum(item["survived_stages"] >= self.stages_per_game for item in results)
        avg_life = sum(item["life"] for item in results) / len(results)
        avg_stages = sum(item["survived_stages"] for item in results) / len(results)
        print(f"목표 {self.stages_per_game}웨이브 클리어: {cleared}/{len(results)} ({cleared / len(results):.1%})")
        print(f"평균 완료 웨이브: {avg_stages:.1f}")
        print(f"평균 남은 라이프: {avg_life:.1f}")


def main():
    parser = argparse.ArgumentParser(description="Headless balance simulation")
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--stages", type=int, default=30)
    parser.add_argument("--output", help="JSON output path (also writes CSV)")
    args = parser.parse_args()
    analyzer = BalanceAnalyzer(num_games=args.games, stages_per_game=args.stages)
    analyzer.run_simulation()
    analyzer.print_statistics()
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(analyzer.results, ensure_ascii=False, indent=2), encoding="utf-8")
        fields = [key for key in analyzer.results[0] if key != "stage_results"]
        with output.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(analyzer.results)
    return 1 if any(item["status"] == "error" for item in analyzer.results) else 0


if __name__ == "__main__":
    sys.exit(main())
