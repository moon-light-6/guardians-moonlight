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
        self.load_from_json(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "map.json"))

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
        """최신 정수 격자 좌표와 슬롯 경계 형식으로 맵을 검증합니다."""
        if (type(self.map_width) is not int or type(self.map_height) is not int
                or self.map_width != self.MAP_WIDTH or self.map_height != self.MAP_HEIGHT):
            raise ValueError("Map dimensions must match configured dimensions")
        if set(self.slots) != set(range(self.SLOT_COUNT)):
            raise ValueError("Slot IDs must be 0 through SLOT_COUNT - 1")
        if len(self.path) < 2:
            raise ValueError("Path must contain at least two cells")
        for point in self.path:
            if len(point) != 2 or not all(type(value) is int for value in point):
                raise ValueError("Path coordinates must be integer cell indices")
            x, y = point
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                raise ValueError("Path cell is outside map bounds")
        if len(set(self.path)) != len(self.path):
            raise ValueError("Path cells must not repeat")
        for start, end in zip(self.path, self.path[1:]):
            if abs(start[0] - end[0]) + abs(start[1] - end[1]) != 1:
                raise ValueError("Path cells must be orthogonally adjacent")
        bounds_list = []
        for bounds in self.slots.values():
            if len(bounds) != 4 or not all(type(value) is int for value in bounds):
                raise ValueError("Slot bounds must contain four integer values")
            x, y, width, height = bounds
            if not (width > 0 and height > 0 and x >= 0 and y >= 0
                    and x + width <= self.map_width and y + height <= self.map_height):
                raise ValueError("Slot is outside map bounds")
            for bx, by, bw, bh in bounds_list:
                if x < bx + bw and bx < x + width and y < by + bh and by < y + height:
                    raise ValueError("Slots must not overlap")
            bounds_list.append(bounds)
            if any(x <= px < x + width and y <= py < y + height for px, py in self.path):
                raise ValueError("Slot overlaps a path cell")

    def is_valid_slot(self, slot_id: int) -> bool:
        return type(slot_id) is int and slot_id in self.slots

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
        return list(self.path)

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
        # 검증이 실패하면 기존 맵을 유지합니다. 최신 부분 로딩 방식도 지원합니다.
        candidate = object.__new__(GameMap)
        candidate.map_width = data.get("width", self.map_width)
        candidate.map_height = data.get("height", self.map_height)
        candidate.path = [tuple(point) for point in data.get("path", self.path)]
        slots = data.get("slots", self.slots)
        candidate.slots = {int(slot_id): tuple(bounds) for slot_id, bounds in slots.items()}
        if len(candidate.slots) != len(slots):
            raise ValueError("Duplicate slot IDs after integer conversion")
        candidate._validate_map()
        self.map_width, self.map_height = candidate.map_width, candidate.map_height
        self.path, self.slots = candidate.path, candidate.slots

    def export_to_json(self, json_file: str) -> None:
        self._validate_map()
        data = {
            "width": self.map_width,
            "height": self.map_height,
            "path": self.path,
            "slots": {str(slot_id): list(bounds) for slot_id, bounds in self.slots.items()},
        }
        os.makedirs(os.path.dirname(os.path.abspath(json_file)), exist_ok=True)
        with open(json_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
