import json
import os
from typing import Dict, List, Tuple

from config import CELL_SIZE, GRID_ORIGIN, MAP_HEIGHT, MAP_WIDTH, SLOT_COUNT


class GameMap:
    MAP_WIDTH = MAP_WIDTH
    MAP_HEIGHT = MAP_HEIGHT
    SLOT_COUNT = SLOT_COUNT

    def __init__(self):
        self.map_width = self.MAP_WIDTH
        self.map_height = self.MAP_HEIGHT
        self.path = self._initialize_path()
        self.slots = self._initialize_slots()
        self._validate_map()

    def _initialize_path(self) -> List[Tuple[int, int]]:
        cells = []
        cells += [(x, 2) for x in range(0, 18)]
        cells += [(17, y) for y in range(3, 7)]
        cells += [(x, 6) for x in range(16, 3, -1)]
        cells += [(4, y) for y in range(7, 11)]
        cells += [(x, 10) for x in range(5, 20)]
        return cells

    def _initialize_slots(self) -> Dict[int, Tuple[int, int, int, int]]:
        coords = [
            (2, 0), (5, 0), (8, 0), (11, 0), (14, 0), (18, 0),
            (1, 4), (4, 4), (7, 4), (10, 4), (13, 4), (19, 4),
            (1, 8), (7, 8), (10, 8), (13, 8), (16, 8), (19, 8),
            (1, 12), (4, 12), (7, 12), (10, 12), (13, 12), (16, 12),
        ]
        return {index: (x, y, 1, 1) for index, (x, y) in enumerate(coords)}

    def _validate_map(self) -> None:
        assert len(self.slots) == self.SLOT_COUNT
        assert len(self.path) >= 2
        path_cells = set(self.path)
        for x, y in self.path:
            assert 0 <= x < self.map_width and 0 <= y < self.map_height
        for slot_id, (x, y, _w, _h) in self.slots.items():
            assert (x, y) not in path_cells, f"slot {slot_id} overlaps path"

    def is_valid_slot(self, slot_id: int) -> bool:
        return 0 <= slot_id < self.SLOT_COUNT

    def get_slot_position(self, slot_id: int) -> Tuple[float, float]:
        if not self.is_valid_slot(slot_id):
            return (0.0, 0.0)
        x, y, width, height = self.slots[slot_id]
        return (x + width / 2, y + height / 2)

    def get_slot_bounds(self, slot_id: int) -> Tuple[float, float, float, float]:
        if not self.is_valid_slot(slot_id):
            return (0.0, 0.0, 0.0, 0.0)
        return self.slots[slot_id]

    def get_path(self) -> List[Tuple[int, int]]:
        return self.path

    def grid_to_pixel(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        x, y = pos
        return (
            int(GRID_ORIGIN[0] + x * CELL_SIZE + CELL_SIZE / 2),
            int(GRID_ORIGIN[1] + y * CELL_SIZE + CELL_SIZE / 2),
        )

    def pixel_to_slot(self, pos: Tuple[int, int]) -> int | None:
        mx, my = pos
        for slot_id, (x, y, width, height) in self.slots.items():
            left = GRID_ORIGIN[0] + x * CELL_SIZE
            top = GRID_ORIGIN[1] + y * CELL_SIZE
            if left <= mx <= left + width * CELL_SIZE and top <= my <= top + height * CELL_SIZE:
                return slot_id
        return None

    def get_start_position(self) -> Tuple[float, float]:
        return self.path[0]

    def get_base_position(self) -> Tuple[float, float]:
        return self.path[-1]

    def load_from_json(self, json_file: str) -> None:
        if not os.path.exists(json_file):
            return
        with open(json_file, "r", encoding="utf-8") as file:
            data = json.load(file)
        self.path = [tuple(point) for point in data.get("path", self.path)]
        self.slots = {
            int(slot_id): tuple(bounds)
            for slot_id, bounds in data.get("slots", self.slots).items()
        }
        self._validate_map()

    def export_to_json(self, json_file: str) -> None:
        data = {
            "width": self.map_width,
            "height": self.map_height,
            "path": self.path,
            "slots": {str(slot_id): list(bounds) for slot_id, bounds in self.slots.items()},
        }
        os.makedirs(os.path.dirname(json_file), exist_ok=True)
        with open(json_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
