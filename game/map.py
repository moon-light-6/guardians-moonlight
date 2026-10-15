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
        # 4줄 왕복 경로. 둘째~넷째 타워 줄은 두 수평 경로 사이에 배치합니다.
        cells = [(x, 1) for x in range(19, -1, -1)]
        cells += [(0, y) for y in range(2, 6)]
        cells += [(x, 5) for x in range(1, 19)]
        cells += [(18, y) for y in range(6, 10)]
        cells += [(x, 9) for x in range(17, -1, -1)]
        cells += [(0, y) for y in range(10, 14)]
        cells += [(x, 13) for x in range(1, 20)]
        return cells

    def _initialize_slots(self) -> Dict[int, Tuple[int, int, int, int]]:
        coords = [
            (2, 0), (5, 0), (8, 0), (11, 0), (14, 0), (18, 0),
            (1, 3), (4, 3), (7, 3), (10, 3), (13, 3), (19, 3),
            (1, 7), (7, 7), (10, 7), (13, 7), (16, 7), (19, 7),
            (1, 11), (4, 11), (7, 11), (10, 11), (13, 11), (16, 11),
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
        # 경로와 동일한 칸 중심 좌표계: 정수 (x, y)가 해당 칸의 중심입니다.
        # grid_to_pixel에서 반 칸을 더하므로 여기서는 중복 보정하지 않습니다.
        return (x + (width - 1) / 2, y + (height - 1) / 2)

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
            if left <= mx < left + width * CELL_SIZE and top <= my < top + height * CELL_SIZE:
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
