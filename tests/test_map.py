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
                game_map.slots[0] = (0, 2, 1, 1)
            elif kind == "slot_ids":
                game_map.slots[24] = game_map.slots.pop(0)
            else:
                game_map.slots[0] = (20, 0, 1, 1)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                game_map._validate_map()

    def test_latest_coordinates_and_pixel_conversion(self):
        game_map = GameMap()
        self.assertEqual(game_map.get_start_position(), (0, 2))
        self.assertEqual(game_map.get_base_position(), (19, 10))
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


if __name__ == "__main__":
    unittest.main()
