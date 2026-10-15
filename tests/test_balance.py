import unittest
from unittest.mock import patch

from game.engine import Game
from game.state import GamePhase
from scripts.balance import BalanceAnalyzer


class TestBalanceAnalyzer(unittest.TestCase):
    def test_invalid_settings(self):
        for games, stages in [(0, 5), (1, 0), (1, 31)]:
            with self.assertRaises(ValueError):
                BalanceAnalyzer(games, stages)

    def test_engine_error_is_not_a_clear(self):
        with patch.object(Game, "update", side_effect=RuntimeError("test failure")):
            result = BalanceAnalyzer(1, 5)._run_single_game(42)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["survived_stages"], 0)
        self.assertEqual(result["error"], "test failure")

    def test_engine_owns_progression_and_continue(self):
        def complete(game, dt):
            game.state.phase = GamePhase.SETTLEMENT
        with patch.object(Game, "update", autospec=True, side_effect=complete):
            result = BalanceAnalyzer(1, 5)._run_single_game(42)
        self.assertEqual(result["survived_stages"], 5)
        self.assertEqual(result["stage"], 6)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([item["stage"] for item in result["stage_results"]], [1, 2, 3, 4, 5])

    def test_timeout_is_bounded(self):
        with patch.object(Game, "update") as update:
            result = BalanceAnalyzer(1, 1)._run_single_game(42)
        self.assertEqual(update.call_count, 6000)
        self.assertEqual(result["status"], "error")
        self.assertIn("timed out", result["error"])

    def test_real_engine_seed_reproducibility(self):
        analyzer = BalanceAnalyzer(1, 1)
        first = analyzer._run_single_game(42)
        self.assertEqual(first, analyzer._run_single_game(42))
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["survived_stages"], 1)
        for key in ("stage", "life", "gold", "kills", "phase"):
            self.assertIn(key, first)
