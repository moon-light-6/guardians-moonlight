"""Pygame용 작은 차트 도구. 축 하나(이중 축 없음), 옅은 격자, 2px 선."""

import math
from typing import Callable, List, Optional, Sequence

import pygame

from ai_demo.theme import AXIS, GRID, MUTED, TEXT_2, Fonts, lerp_color, text


def nice_ticks(low: float, high: float, count: int = 5) -> List[float]:
    if high <= low:
        high = low + 1
    raw = (high - low) / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.floor(low / step + 1e-9) * step  # 첫 눈금이 최솟값 아래에서 시작하도록
    ticks, value = [], start
    while value <= high + step * 1e-6:
        ticks.append(round(value, 10))
        value += step
    if ticks[-1] < high - step * 1e-6:  # 마지막 눈금이 최댓값을 덮도록
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def format_steps(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:g}k"
    return f"{value:g}"


def moving_average(values: Sequence[float], window: int) -> List[float]:
    """scripts/ppo.py의 moving_average와 같은 정의(앞부분은 있는 만큼만 평균)."""
    out, total = [], 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        out.append(total / min(i + 1, window))
    return out


class Plot:
    def __init__(self, surface: pygame.Surface, rect: pygame.Rect, fonts: Fonts,
                 x_range, y_range, x_format: Callable = format_steps, y_format: Callable = lambda v: f"{v:g}",
                 x_ticks: Optional[List[float]] = None, y_ticks: Optional[List[float]] = None,
                 tick_size: int = 15):
        self.surface, self.rect, self.fonts = surface, rect, fonts
        self.x0, self.x1 = x_range
        self.y0, self.y1 = y_range
        if self.x1 <= self.x0:
            self.x1 = self.x0 + 1
        if self.y1 <= self.y0:
            self.y1 = self.y0 + 1
        self.x_format, self.y_format = x_format, y_format
        self.x_ticks = x_ticks if x_ticks is not None else nice_ticks(self.x0, self.x1, 5)
        self.y_ticks = y_ticks if y_ticks is not None else nice_ticks(self.y0, self.y1, 4)
        self.tick_size = tick_size

    def px(self, x: float) -> float:
        return self.rect.left + (x - self.x0) / (self.x1 - self.x0) * self.rect.width

    def py(self, y: float) -> float:
        return self.rect.bottom - (y - self.y0) / (self.y1 - self.y0) * self.rect.height

    def draw_axes(self, x_label: str = "", show_x: bool = True) -> None:
        font = self.fonts(self.tick_size)
        for tick in self.y_ticks:
            if self.y0 - 1e-9 <= tick <= self.y1 + 1e-9:
                y = round(self.py(tick))
                pygame.draw.line(self.surface, GRID, (self.rect.left, y), (self.rect.right, y), 1)
                text(self.surface, font, self.y_format(tick), (self.rect.left - 8, y), MUTED, "midright")
        pygame.draw.line(self.surface, AXIS, self.rect.bottomleft, self.rect.bottomright, 1)
        if show_x:
            for tick in self.x_ticks:
                if self.x0 - 1e-9 <= tick <= self.x1 + 1e-9:
                    x = round(self.px(tick))
                    pygame.draw.line(self.surface, AXIS, (x, self.rect.bottom), (x, self.rect.bottom + 4), 1)
                    text(self.surface, font, self.x_format(tick), (x, self.rect.bottom + 6), MUTED, "midtop")
            if x_label:
                text(self.surface, font, x_label, (self.rect.right, self.rect.bottom + 26), MUTED, "topright")

    def _clipped(self):
        """데이터 선이 다른 그래프 영역으로 넘어가지 않게 그리는 동안만 그리기 영역을 제한한다."""
        previous = self.surface.get_clip()
        self.surface.set_clip(self.rect.inflate(4, 4))
        return previous

    def line(self, xs, ys, color, width: int = 2) -> None:
        points = [(self.px(x), self.py(y)) for x, y in zip(xs, ys) if y is not None and not _nan(y)]
        if len(points) >= 2:
            previous = self._clipped()
            pygame.draw.lines(self.surface, color, False, points, width)
            self.surface.set_clip(previous)

    def sampled_line(self, xs, ys, color, width: int = 2) -> None:
        """점이 많으면 화면 픽셀 열마다 마지막 값만 써서 그린다."""
        columns = {}
        for x, y in zip(xs, ys):
            columns[round(self.px(x))] = self.py(y)
        points = sorted(columns.items())
        if len(points) >= 2:
            previous = self._clipped()
            pygame.draw.lines(self.surface, color, False, points, width)
            self.surface.set_clip(previous)

    def envelope(self, xs, ys, color, alpha: float = 0.3) -> None:
        """원본 값: 픽셀 열마다 최소~최대를 옅은 세로선으로(수천 판을 한 화면에 그릴 때)."""
        columns = {}
        for x, y in zip(xs, ys):
            column = round(self.px(x))
            low, high = columns.get(column, (y, y))
            columns[column] = (min(low, y), max(high, y))
        faded = lerp_color((15, 19, 32), color, alpha)
        previous = self._clipped()
        for column, (low, high) in columns.items():
            pygame.draw.line(self.surface, faded, (column, self.py(low)), (column, self.py(high)), 1)
        self.surface.set_clip(previous)

    def markers(self, xs, ys, color, radius: int = 4, ring=(15, 19, 32)) -> None:
        for x, y in zip(xs, ys):
            center = (round(self.px(x)), round(self.py(y)))
            pygame.draw.circle(self.surface, ring, center, radius + 2)
            pygame.draw.circle(self.surface, color, center, radius)

    def label(self, x, y, value: str, color=TEXT_2, offset=(0, -12), size: int = 16) -> None:
        position = (round(self.px(x)) + offset[0], round(self.py(y)) + offset[1])
        rect = self.fonts(size).render(value, True, color).get_rect(midbottom=position)
        rect.clamp_ip(self.rect.inflate(40, 30))
        text(self.surface, self.fonts(size), value, rect.topleft, color)


def _nan(value) -> bool:
    return isinstance(value, float) and math.isnan(value)
