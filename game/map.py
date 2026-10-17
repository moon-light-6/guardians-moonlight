"""One source of truth for the painted map and its game coordinates.

``data/map.json`` intentionally stores *source-image pixels*. Rendering,
click hit-testing, route debugging, and gameplay positions all derive from
those coordinates through this class; no code recreates the painted road or
platforms from a grid.
"""

import json
import math
import os
from typing import Dict, List, Tuple

from config import MAP_COMBAT_PIXELS_PER_UNIT, SCREEN_HEIGHT, SCREEN_WIDTH, SLOT_COUNT


Point = Tuple[float, float]


class GameMap:
    SLOT_COUNT = SLOT_COUNT

    def __init__(self):
        self.source_width = 1548
        self.source_height = 1016
        self.combat_pixels_per_unit = MAP_COMBAT_PIXELS_PER_UNIT
        self.combat_origin: Point = (0.0, 0.0)
        self.source_path: List[Point] = []
        self.source_slots: Dict[int, Point] = {}
        self._load_from_json(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "map.json"))
        self._configure_transform()
        self._validate_map()

    def _configure_transform(self) -> None:
        """Fit without cropping or independent x/y stretching."""
        self.display_scale = min(SCREEN_WIDTH / self.source_width, SCREEN_HEIGHT / self.source_height)
        self.display_size = (
            self.source_width * self.display_scale,
            self.source_height * self.display_scale,
        )
        self.display_offset = (
            (SCREEN_WIDTH - self.display_size[0]) / 2,
            (SCREEN_HEIGHT - self.display_size[1]) / 2,
        )

    def _load_from_json(self, json_file: str) -> None:
        with open(json_file, "r", encoding="utf-8") as file:
            data = json.load(file)
        size = data.get("image_size")
        if not isinstance(size, list) or len(size) != 2:
            raise ValueError("map.json requires image_size: [width, height]")
        self.source_width, self.source_height = (int(size[0]), int(size[1]))
        self.combat_pixels_per_unit = float(data.get("combat_pixels_per_unit", MAP_COMBAT_PIXELS_PER_UNIT))
        origin = data.get("combat_origin", [0, 0])
        if not isinstance(origin, list) or len(origin) != 2:
            raise ValueError("combat_origin must be [x, y]")
        self.combat_origin = tuple(map(float, origin))
        self.source_path = [tuple(map(float, point)) for point in data.get("path", [])]
        raw_slots = data.get("slots", {})
        self.source_slots = {int(slot_id): tuple(map(float, point)) for slot_id, point in raw_slots.items()}

    def load_from_json(self, json_file: str) -> None:
        """Atomically replace map data only after parsing and validation pass."""
        candidate = object.__new__(GameMap)
        candidate.source_width = self.source_width
        candidate.source_height = self.source_height
        candidate.combat_pixels_per_unit = self.combat_pixels_per_unit
        candidate.combat_origin = self.combat_origin
        candidate.source_path = []
        candidate.source_slots = {}
        candidate._load_from_json(json_file)
        candidate._configure_transform()
        candidate._validate_map()
        self.source_width = candidate.source_width
        self.source_height = candidate.source_height
        self.combat_pixels_per_unit = candidate.combat_pixels_per_unit
        self.combat_origin = candidate.combat_origin
        self.source_path = candidate.source_path
        self.source_slots = candidate.source_slots
        self._configure_transform()

    def _validate_map(self) -> None:
        if self.source_width <= 0 or self.source_height <= 0:
            raise ValueError("Image dimensions must be positive")
        if self.combat_pixels_per_unit <= 0:
            raise ValueError("combat_pixels_per_unit must be positive")
        if set(self.source_slots) != set(range(self.SLOT_COUNT)):
            raise ValueError("Slot IDs must be 0 through SLOT_COUNT - 1")
        if len(self.source_path) < 2:
            raise ValueError("Path must contain at least two waypoints")
        if any(not self._inside_source(point) for point in self.source_path):
            raise ValueError("Path waypoint is outside source image bounds")
        if any(not self._inside_source(point) for point in self.source_slots.values()):
            raise ValueError("Slot is outside source image bounds")
        if any(math.dist(start, end) < 0.001 for start, end in zip(self.source_path, self.source_path[1:])):
            raise ValueError("Path must not contain repeated consecutive waypoints")

    def _inside_source(self, point: Point) -> bool:
        return 0 <= point[0] <= self.source_width and 0 <= point[1] <= self.source_height

    @property
    def path(self) -> List[Point]:
        """Game-space route, retaining the old distance-based combat balance."""
        return [self.source_to_game(point) for point in self.source_path]

    @property
    def slots(self) -> Dict[int, Point]:
        """Game-space anchor points for combat, effects, and tower rendering."""
        return {slot_id: self.source_to_game(point) for slot_id, point in self.source_slots.items()}

    def source_to_game(self, point: Point) -> Point:
        return (
            (point[0] - self.combat_origin[0]) / self.combat_pixels_per_unit,
            (point[1] - self.combat_origin[1]) / self.combat_pixels_per_unit,
        )

    def game_to_source(self, point: Point) -> Point:
        return (
            point[0] * self.combat_pixels_per_unit + self.combat_origin[0],
            point[1] * self.combat_pixels_per_unit + self.combat_origin[1],
        )

    def source_to_pixel(self, point: Point) -> Tuple[int, int]:
        return (
            round(self.display_offset[0] + point[0] * self.display_scale),
            round(self.display_offset[1] + point[1] * self.display_scale),
        )

    def pixel_to_source(self, point: Point) -> Point:
        return (
            (point[0] - self.display_offset[0]) / self.display_scale,
            (point[1] - self.display_offset[1]) / self.display_scale,
        )

    def grid_to_pixel(self, pos: Point) -> Tuple[int, int]:
        """Compatibility name: game-space position -> screen position."""
        return self.source_to_pixel(self.game_to_source(pos))

    def pixel_to_game(self, point: Point) -> Point:
        return self.source_to_game(self.pixel_to_source(point))

    def units_to_pixels(self, units: float) -> float:
        return units * self.combat_pixels_per_unit * self.display_scale

    def is_valid_slot(self, slot_id: int) -> bool:
        return type(slot_id) is int and slot_id in self.source_slots

    def get_slot_position(self, slot_id: int) -> Point:
        return self.source_to_game(self.source_slots[slot_id]) if self.is_valid_slot(slot_id) else (0.0, 0.0)

    def get_slot_source_position(self, slot_id: int) -> Point:
        return self.source_slots[slot_id] if self.is_valid_slot(slot_id) else (0.0, 0.0)

    def get_path(self) -> List[Point]:
        return list(self.path)

    def get_source_path(self) -> List[Point]:
        return list(self.source_path)

    def get_start_position(self) -> Point:
        return self.path[0]

    def get_base_position(self) -> Point:
        return self.path[-1]

    def get_start_source_position(self) -> Point:
        return self.source_path[0]

    def get_base_source_position(self) -> Point:
        return self.source_path[-1]

    def pixel_to_slot(self, pos: Tuple[int, int]) -> int | None:
        """Inverse-transform the click, then use each painted platform's ellipse."""
        x, y = self.pixel_to_source(pos)
        candidates = []
        for slot_id, (center_x, anchor_y) in self.source_slots.items():
            # Source slots are the painted upper-face centres, shared by the
            # sprite-foot anchor, selection ring, debug cross, and click area.
            normalized = ((x - center_x) / 51) ** 2 + ((y - anchor_y) / 31) ** 2
            if normalized <= 1:
                candidates.append((normalized, slot_id))
        return min(candidates)[1] if candidates else None

    def export_to_json(self, json_file: str) -> None:
        self._validate_map()
        data = {
            "image_size": [self.source_width, self.source_height],
            "combat_pixels_per_unit": self.combat_pixels_per_unit,
            "combat_origin": list(self.combat_origin),
            "path": self.source_path,
            "slots": {str(slot_id): list(point) for slot_id, point in self.source_slots.items()},
        }
        with open(json_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
