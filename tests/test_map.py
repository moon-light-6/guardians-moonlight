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


if __name__ == "__main__":
    unittest.main()
