import json
import math
import tempfile
import unittest
from pathlib import Path

from game.map import GameMap
from game.tower import Tower


class TestPaintedMap(unittest.TestCase):
    def setUp(self):
        self.game_map = GameMap()

    def test_attached_image_dimensions_and_slots(self):
        self.assertEqual((self.game_map.source_width, self.game_map.source_height), (1548, 1016))
        self.assertEqual(len(self.game_map.source_slots), 24)
        self.assertEqual(set(self.game_map.source_slots), set(range(24)))
        rows = [list(self.game_map.source_slots.values())[start:start + 6] for start in range(0, 24, 6)]
        self.assertEqual([len(row) for row in rows], [6, 6, 6, 6])
        self.assertGreater(rows[2][1][0] - rows[2][0][0], 250)

    def test_single_aspect_preserving_transform_round_trips(self):
        self.assertAlmostEqual(self.game_map.display_size[1], 840)
        self.assertAlmostEqual(
            self.game_map.display_size[0] / self.game_map.source_width,
            self.game_map.display_size[1] / self.game_map.source_height,
        )
        for source in self.game_map.source_slots.values():
            screen = self.game_map.source_to_pixel(source)
            restored = self.game_map.pixel_to_source(screen)
            self.assertAlmostEqual(source[0], restored[0], delta=0.7)
            self.assertAlmostEqual(source[1], restored[1], delta=0.7)

    def test_every_platform_anchor_clicks_its_own_slot(self):
        for slot_id in range(24):
            with self.subTest(slot_id=slot_id):
                anchor = self.game_map.get_slot_source_position(slot_id)
                self.assertEqual(self.game_map.pixel_to_slot(self.game_map.source_to_pixel(anchor)), slot_id)

    def test_route_is_painted_serpentine_with_dense_turn_waypoints(self):
        path = self.game_map.get_source_path()
        self.assertEqual(path[0], (973.0, 479.0))
        self.assertEqual(path[-1], (1018.0, 820.0))
        self.assertGreaterEqual(len(path), 55)
        self.assertGreaterEqual(sum(1 for x, _ in path if x < 110), 12)
        self.assertGreaterEqual(sum(1 for x, _ in path if x > 1000), 7)
        self.assertLess(max(math.dist(a, b) for a, b in zip(path, path[1:])), 115)

    def test_all_platforms_remain_in_combat_range(self):
        path = self.game_map.get_path()
        for slot_id in range(24):
            position = self.game_map.get_slot_position(slot_id)
            distance = min(math.dist(position, point) for point in path)
            for stats in Tower.BASE_STATS.values():
                with self.subTest(slot_id=slot_id, stats=stats):
                    self.assertLessEqual(distance, stats["range"])

    def test_json_roundtrip_and_atomic_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "map.json"
            self.game_map.export_to_json(str(filename))
            loaded = GameMap()
            loaded.load_from_json(str(filename))
            self.assertEqual(loaded.source_path, self.game_map.source_path)
            self.assertEqual(loaded.source_slots, self.game_map.source_slots)
            data = json.loads(filename.read_text(encoding="utf-8"))
            data["path"][0] = [-1, 0]
            filename.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                loaded.load_from_json(str(filename))
            self.assertEqual(loaded.source_path, self.game_map.source_path)


if __name__ == "__main__":
    unittest.main()
