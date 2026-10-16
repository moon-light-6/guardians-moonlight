import unittest

from game.map import GameMap


class TestMap(unittest.TestCase):
    def test_map_shape_and_slots(self):
        game_map = GameMap()
        self.assertEqual(game_map.map_width, 20)
        self.assertEqual(game_map.map_height, 15)
        self.assertEqual(len(game_map.slots), 24)

    def test_slots_do_not_overlap_path(self):
        game_map = GameMap()
        path = set(game_map.get_path())
        for x, y, _w, _h in game_map.slots.values():
            self.assertNotIn((x, y), path)


class TestMapDataSafety(unittest.TestCase):
    def test_json_roundtrip_and_atomic_load(self):
        import json
        import tempfile
        from pathlib import Path
        game_map = GameMap()
        original = game_map.get_path()
        with tempfile.TemporaryDirectory() as directory:
            filename = str(Path(directory) / "map.json")
            game_map.export_to_json(filename)
            loaded = GameMap()
            loaded.load_from_json(filename)
            self.assertEqual(loaded.path, original)
            self.assertEqual(loaded.slots, game_map.slots)
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            data["path"][0] = [20, 15]
            Path(filename).write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                loaded.load_from_json(filename)
            self.assertEqual(loaded.path, original)

    def test_invalid_geometry(self):
        for kind in ("disconnected", "overlap", "slot_ids", "bounds"):
            game_map = GameMap()
            if kind == "disconnected":
                game_map.path.pop(1)
            elif kind == "overlap":
                game_map.slots[0] = (0, 1, 1, 1)
            elif kind == "slot_ids":
                game_map.slots[24] = game_map.slots.pop(0)
            else:
                game_map.slots[0] = (20, 0, 1, 1)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                game_map._validate_map()

    def test_latest_coordinates_and_pixel_conversion(self):
        game_map = GameMap()
        self.assertEqual(game_map.get_start_position(), (19, 1))
        self.assertEqual(game_map.get_base_position(), (19, 13))
        for slot_id, (x, y, _w, _h) in game_map.slots.items():
            self.assertEqual(game_map.pixel_to_slot(game_map.grid_to_pixel((x, y))), slot_id)
        game_map.get_path().clear()
        self.assertGreater(len(game_map.path), 2)
        for value in (None, "0", True, 1.5, -1, 24):
            self.assertFalse(game_map.is_valid_slot(value))

    def test_default_data_matches_latest_layout(self):
        game_map = GameMap()
        self.assertEqual(game_map.path, game_map._initialize_path())
        self.assertEqual(game_map.slots, game_map._initialize_slots())


class TestSerpentineLayout(unittest.TestCase):
    def test_all_tower_centers_and_click_regions_match(self):
        game_map = GameMap()
        for slot_id, (x, y, width, height) in game_map.slots.items():
            center = game_map.grid_to_pixel(game_map.get_slot_position(slot_id))
            # 2.5D 사다리꼴 투영에서도 같은 슬롯의 중심을 클릭할 수 있어야 합니다.
            self.assertEqual(game_map.pixel_to_slot(center), slot_id)
            self.assertTrue(game_map._point_in_polygon(center, game_map.slot_polygon(slot_id)))

    def test_every_tower_type_can_reach_path_from_every_slot(self):
        import math
        from game.tower import Tower
        game_map = GameMap()
        for slot_id in game_map.slots:
            position = game_map.get_slot_position(slot_id)
            distance = min(math.dist(position, cell) for cell in game_map.get_path())
            for stats in Tower.BASE_STATS.values():
                self.assertLessEqual(distance, stats["range"])

    def test_path_turns_and_continuity(self):
        game_map = GameMap()
        path = game_map.get_path()
        for point in [(19, 1), (0, 1), (0, 5), (18, 5), (18, 9), (0, 9), (0, 13), (19, 13)]:
            self.assertIn(point, path)
        self.assertEqual(len(path), 87)
        game_map._validate_map()


class TestSharedLaneCoverage(unittest.TestCase):
    def test_shifted_rows_reach_both_neighboring_lanes(self):
        import math
        from game.tower import Tower
        game_map = GameMap()
        for slot_id in range(6, 24):
            position = game_map.get_slot_position(slot_id)
            row = slot_id // 6
            self.assertEqual(position[1], row * 4 - 1)
            for lane_y in (row * 4 - 3, row * 4 + 1):
                lane = [point for point in game_map.path if point[1] == lane_y]
                distance = min(math.dist(position, point) for point in lane)
                for stats in Tower.BASE_STATS.values():
                    with self.subTest(slot_id=slot_id, lane_y=lane_y):
                        self.assertLessEqual(distance, stats["range"])
        self.assertTrue(all(game_map.slots[slot_id][1] == 0 for slot_id in range(6)))


if __name__ == "__main__":
    unittest.main()
