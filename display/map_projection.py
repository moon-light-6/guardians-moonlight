"""그림으로 된 맵을 화면 좌표로 변환하는 모듈입니다.

게임 로직은 원본 이미지 좌표와 게임 좌표만 사용합니다. 창 크기, 화면 배율,
마우스 클릭 영역은 이 모듈에서만 처리하므로 ``game``은 렌더러 없이도 실행할 수
있습니다.
"""

from __future__ import annotations

from typing import Tuple

from config import SCREEN_HEIGHT, SCREEN_WIDTH
from game.map import GameMap, Point


Pixel = Tuple[int, int]


class MapProjection:
    """렌더링과 입력에 공통으로 쓰는 비율 유지형 맵 변환입니다."""

    # 그림 속 플랫폼 윗면과 일치하는 원본 이미지 픽셀 기준 타원 반지름입니다.
    SLOT_HIT_RADIUS = (51.0, 31.0)

    def __init__(
        self,
        game_map: GameMap,
        viewport_size: Tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    ) -> None:
        self.map = game_map
        self.viewport_size = viewport_size
        self._configure_transform()

    def _configure_transform(self) -> None:
        viewport_width, viewport_height = self.viewport_size
        self.display_scale = min(
            viewport_width / self.map.source_width,
            viewport_height / self.map.source_height,
        )
        self.display_size = (
            self.map.source_width * self.display_scale,
            self.map.source_height * self.display_scale,
        )
        self.display_offset = (
            (viewport_width - self.display_size[0]) / 2,
            (viewport_height - self.display_size[1]) / 2,
        )

    def source_to_pixel(self, point: Point) -> Pixel:
        return (
            round(self.display_offset[0] + point[0] * self.display_scale),
            round(self.display_offset[1] + point[1] * self.display_scale),
        )

    def pixel_to_source(self, point: Tuple[float, float]) -> Point:
        return (
            (point[0] - self.display_offset[0]) / self.display_scale,
            (point[1] - self.display_offset[1]) / self.display_scale,
        )

    def game_to_pixel(self, point: Point) -> Pixel:
        return self.source_to_pixel(self.map.game_to_source(point))

    def pixel_to_game(self, point: Tuple[float, float]) -> Point:
        return self.map.source_to_game(self.pixel_to_source(point))

    def units_to_pixels(self, units: float) -> float:
        return units * self.map.combat_pixels_per_unit * self.display_scale

    def pixel_to_slot(self, pos: Pixel) -> int | None:
        """화면 클릭이 그림 속 플랫폼 윗면 타원에 닿았는지 판정합니다."""
        x, y = self.pixel_to_source(pos)
        radius_x, radius_y = self.SLOT_HIT_RADIUS
        candidates = []
        for slot_id, (center_x, anchor_y) in self.map.source_slots.items():
            normalized = ((x - center_x) / radius_x) ** 2 + ((y - anchor_y) / radius_y) ** 2
            if normalized <= 1:
                candidates.append((normalized, slot_id))
        return min(candidates)[1] if candidates else None
