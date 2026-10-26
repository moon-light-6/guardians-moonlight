import unittest

from game.enemy import EnemyType
from game.map import GameMap
from game.wave import WaveManager


class TestWave(unittest.TestCase):
    COUNTS = [8, 10, 12, 14, 10, 16, 18, 20, 22, 15, 24, 26, 28, 30, 20,
              32, 34, 36, 38, 25, 40, 42, 44, 46, 30, 48, 50, 52, 54, 35]
    HP = [30, 50, 105, 170, 350, 470, 590, 680, 770, 860, 1110, 1200, 1350, 1470, 1638,
          1870, 2000, 2220, 2340, 2379, 2610, 2760, 2860, 3010, 3160, 3480, 3620, 3850, 4050, 4400]

    def test_all_stage_data_and_spawned_hp_match_plan(self):
        self.assertEqual(set(WaveManager.STAGE_HP), set(range(1, 31)))
        for stage, (count, hp) in enumerate(zip(self.COUNTS, self.HP), 1):
            with self.subTest(stage=stage):
                wave = WaveManager()
                wave.start_wave(stage)
                spawned = wave.update(100, GameMap().get_path())
                normal = [enemy for enemy in spawned if not enemy.is_boss]
                self.assertEqual(len(normal), count)
                self.assertTrue(all(enemy.max_health == hp for enemy in normal))
                self.assertEqual(sum(enemy.is_boss for enemy in spawned), int(stage % 5 == 0))

    def test_all_six_bosses_match_plan(self):
        expected = [
            (5, "먹그림자", 1620, 3), (10, "철갓장군", 3500, 4),
            (15, "서리석귀", 7500, 5), (20, "홍염귀왕", 13500, 5),
            (25, "흑운이무기", 18000, 7), (30, "월식대왕", 23000, 20),
        ]
        for stage, name, hp, damage in expected:
            with self.subTest(stage=stage):
                wave = WaveManager()
                wave.start_wave(stage)
                boss = next(enemy for enemy in wave.update(100, GameMap().get_path()) if enemy.is_boss)
                self.assertEqual((boss.name, boss.max_health, boss.life_damage), (name, hp, damage))
                start = boss.get_current_position()
                boss.move(1)
                self.assertNotEqual(boss.get_current_position(), start)
                boss.take_damage(25)
                self.assertEqual(boss.health, hp - 25)

    def test_invalid_stage_is_rejected(self):
        for stage in (0, 31):
            with self.assertRaises(ValueError):
                WaveManager().start_wave(stage)

    def test_stage_five_has_boss(self):
        wave = WaveManager()
        wave.start_wave(5)
        self.assertTrue(any(item["type"] == EnemyType.BOSS for item in wave.spawn_queue))

    def test_spawn_uses_stage_hp(self):
        wave = WaveManager()
        game_map = GameMap()
        wave.start_wave(1)
        spawned = wave.update(1.0, game_map.get_path())
        self.assertTrue(spawned)
        self.assertEqual(spawned[0].max_health, WaveManager.STAGE_HP[1])


if __name__ == "__main__":
    unittest.main()
