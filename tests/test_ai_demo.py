"""ai_demo(PPO 발표 시연) 검증: 집계, 학습 기록 읽기, 평가 환경과의 행동·결과 일치."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from ai_demo.charts import moving_average, nice_ticks
from ai_demo.experiment import DEFAULT_RUN, RESULTS_DIR, load_experiment
from ai_demo.stats import ActionRecord, ActionStats

HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_RUN = (DEFAULT_RUN / "ppo_policy.pt").is_file()


def record(kind, slot=None, stage=1, level=0, tower=""):
    return ActionRecord(game=1, seed=1, step=1, stage=stage, kind=kind, action=0, slot=slot, probability=0.5,
                        detail="", gold_before=0, gold_after=0, tower_type=tower, level_after=level)


class TestActionStats(unittest.TestCase):
    def test_ratio_uses_only_buy_upgrade_sell(self):
        stats = ActionStats()
        for item in (record("buy", 3, tower="ICE"), record("buy", 3, tower="ARCHER"), record("upgrade", 3, level=2),
                     record("sell", 3), record("start", stage=1)):
            stats.add(item)
        self.assertEqual(stats.build_total, 4)
        self.assertAlmostEqual(stats.ratio("buy"), 0.5)
        self.assertEqual(stats.counts["start"], 1)
        self.assertEqual(stats.slot_counts["buy"][3], 2)
        self.assertEqual(stats.upgrade_levels[2], 1)
        self.assertEqual(stats.stage_counts[1]["sell"], 1)

    def test_empty_ratio_is_zero(self):
        self.assertEqual(ActionStats().ratio("buy"), 0.0)


class TestCharts(unittest.TestCase):
    def test_ticks_cover_range(self):
        for low, high in ((0, 5), (-3.3, 2.1), (0.0001, 0.0123), (0, 30)):
            ticks = nice_ticks(low, high, 3)
            self.assertLessEqual(ticks[0], low)
            self.assertGreaterEqual(ticks[-1], high)

    def test_moving_average_matches_ppo_definition(self):
        self.assertEqual(moving_average([2, 4, 6, 8], 2), [2, 3, 5, 7])


class TestExperiment(unittest.TestCase):
    def test_missing_folder_is_reported_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            experiment = load_experiment(Path(folder) / "없는_실험")
            self.assertIsNone(experiment.episodes)
            self.assertIsNone(experiment.total_steps)
            info = experiment.model_info(Path(folder) / "없는_실험" / "ppo_best.pt")
            self.assertIsNone(info.clear_rate)
            self.assertTrue(experiment.warnings)

    @unittest.skipUnless(HAS_TORCH and HAS_RUN, "학습 결과 또는 torch 없음")
    def test_model_info_reads_real_files(self):
        experiment = load_experiment(DEFAULT_RUN)
        best = experiment.model_info(DEFAULT_RUN / "ppo_best.pt")
        self.assertEqual(best.steps, experiment.checkpoint_run["best"]["timesteps"])
        self.assertIn(best.steps, [row["timesteps"] for row in experiment.evaluations])
        final = experiment.model_info(DEFAULT_RUN / "ppo_policy.pt")
        rows = experiment.final_policy_rows()
        self.assertAlmostEqual(final.clear_rate, sum(bool(r["won"]) for r in rows) / len(rows) * 100)

    @unittest.skipUnless(HAS_TORCH and (RESULTS_DIR / "jeabin_ppo_tune_v1").is_dir(), "비교용 실험 없음")
    def test_inconsistent_checkpoint_is_not_trusted(self):
        # 이 폴더의 checkpoint.pt는 CSV보다 학습 Step이 많다(다른 실험에서 덮어쓴 흔적). 저장 시점을 지어내지 않는다.
        experiment = load_experiment(RESULTS_DIR / "jeabin_ppo_tune_v1")
        self.assertIsNone(experiment.best_record())
        self.assertIsNone(experiment.model_info(RESULTS_DIR / "jeabin_ppo_tune_v1" / "ppo_best.pt").steps)


@unittest.skipUnless(HAS_TORCH and HAS_RUN, "학습 결과 또는 torch 없음")
class TestParityWithEvaluation(unittest.TestCase):
    def test_demo_matches_play_one_and_recorded_eval(self):
        from ai_demo.ppo_bridge import load_policy, load_ppo_module
        from ai_demo.verify import COMPARE_KEYS, run_demo, run_reference

        ppo = load_ppo_module()
        model_path = DEFAULT_RUN / "ppo_policy.pt"
        model = load_policy(ppo, model_path)
        experiment = load_experiment(DEFAULT_RUN)
        seed = experiment.eval_seed_base + 3  # 기록상 7소동에서 끝나는 짧은 판
        reference, reference_actions = run_reference(ppo, model, seed, greedy=False)
        demo, demo_actions, _ = run_demo(ppo, model, seed, greedy=False, frame_seed=11)
        self.assertEqual(reference_actions, demo_actions)
        for key in COMPARE_KEYS:
            self.assertEqual(reference[key], demo[key], key)
        recorded = experiment.recorded_result(model_path, seed, greedy=False)
        self.assertIsNotNone(recorded)
        for key in COMPARE_KEYS:
            self.assertEqual(recorded[key], demo[key], key)

    def test_missing_model_gives_clear_error(self):
        from ai_demo.ppo_bridge import PolicyLoadError, load_policy, load_ppo_module

        with self.assertRaises(PolicyLoadError):
            load_policy(load_ppo_module(), DEFAULT_RUN / "없는_모델.pt")


if __name__ == "__main__":
    unittest.main()
