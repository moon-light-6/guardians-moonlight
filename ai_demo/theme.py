"""시연 화면 공통: 글꼴, 색, 배치 상수, 작은 그리기 도구. 패널 테두리는 게임의 display.ui.draw_panel을 그대로 쓴다."""

from pathlib import Path
from typing import Dict, Tuple

import pygame

from config import COLOR_FRAME_GOLD, COLOR_FRAME_INNER, COLOR_GOLD, COLOR_MINT, COLOR_MOON, COLOR_RED

from ai_demo import ROOT

# ----- 화면 배치(논리 해상도). 창 크기에 맞춰 비율을 유지한 채 확대/축소해서 보여 준다 -----
CANVAS_SIZE = (1920, 1080)
HEADER_HEIGHT = 68
GAME_SCALE = 0.9                                  # 기존 게임 화면(1280x840)을 0.9배로 축소해 배치
GAME_RECT = pygame.Rect(24, 80, 1152, 756)
BOTTOM_RECT = pygame.Rect(24, 848, 1152, 208)
SIDE_RECT = pygame.Rect(1196, 80, 700, 976)

# ----- 색 -----
BACKGROUND = (9, 12, 26)
SURFACE = (15, 19, 32)          # 패널 안쪽(config.COLOR_PANEL_DARK)
TEXT = (240, 239, 236)
TEXT_2 = (195, 194, 183)
MUTED = (138, 145, 166)
GRID = (44, 52, 76)
AXIS = (86, 96, 124)
# 행동 종류(범주형). dataviz 기준 팔레트의 어두운 배경용 1~3번(3개까지 서로 구별되게 검증된 조합)
KIND_COLORS = {
    "buy": (57, 135, 229),      # #3987e5
    "upgrade": (217, 89, 38),   # #d95926
    "sell": (25, 158, 112),     # #199e70
    "start": COLOR_GOLD,
}
# 히트맵(연속 값): 한 색상 계열, 0은 배경 쪽, 많을수록 밝게
HEAT_RAMPS = {
    "buy": [(16, 36, 64), (24, 79, 149), (57, 135, 229), (134, 182, 239), (205, 226, 251)],
    "upgrade": [(48, 26, 18), (120, 48, 20), (217, 89, 38), (240, 150, 105), (252, 214, 190)],
}
LINE_MAIN = (109, 167, 236)     # #6da7ec
LINE_RAW = (57, 135, 229)
HIGHLIGHT = COLOR_GOLD
GOOD = COLOR_MINT
BAD = COLOR_RED
FRAME = COLOR_FRAME_GOLD
FRAME_INNER = COLOR_FRAME_INNER
MOON = COLOR_MOON

FONT_PATH = ROOT / "assets" / "fonts" / "LevelUp-Regular.ttf"


class Fonts:
    """게임과 같은 글꼴(LevelUp)을 크기별로 한 번만 만든다."""

    def __init__(self):
        self._cache: Dict[int, pygame.font.Font] = {}

    def __call__(self, size: int) -> pygame.font.Font:
        if size not in self._cache:
            if Path(FONT_PATH).is_file():
                self._cache[size] = pygame.font.Font(str(FONT_PATH), size)
            else:
                path = pygame.font.match_font("Malgun Gothic") or pygame.font.match_font("AppleGothic")
                self._cache[size] = pygame.font.Font(path, size)
        return self._cache[size]


def text(surface: pygame.Surface, font: pygame.font.Font, value: str, pos, color=TEXT,
         anchor: str = "topleft") -> pygame.Rect:
    image = font.render(str(value), True, color)
    rect = image.get_rect(**{anchor: pos})
    surface.blit(image, rect)
    return rect


def fit_text(font: pygame.font.Font, value: str, width: int) -> str:
    """폭을 넘으면 뒤를 잘라 '…'을 붙인다."""
    if font.size(value)[0] <= width:
        return value
    while value and font.size(value + "…")[0] > width:
        value = value[:-1]
    return value + "…"


def lerp_color(a, b, t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp_color(ramp, t: float):
    t = max(0.0, min(1.0, t))
    position = t * (len(ramp) - 1)
    index = min(int(position), len(ramp) - 2)
    return lerp_color(ramp[index], ramp[index + 1], position - index)


def section_title(surface, fonts: Fonts, label: str, x: int, y: int, note: str = "") -> int:
    """◆ 제목 + (오른쪽에 작은 설명). 다음 줄 y를 돌려준다."""
    pygame.draw.polygon(surface, HIGHLIGHT, [(x + 6, y + 5), (x + 11, y + 12), (x + 6, y + 19), (x + 1, y + 12)])
    rect = text(surface, fonts(24), label, (x + 20, y), TEXT)
    if note:
        text(surface, fonts(16), note, (rect.right + 12, rect.bottom - 3), MUTED, "bottomleft")
    return rect.bottom + 10


def pill(surface, fonts: Fonts, x: int, cy: int, parts, height: int = 36, size: int = 18,
         border=(150, 175, 230, 40), fill=(10, 16, 34, 200)) -> pygame.Rect:
    """게임 HUD와 같은 모양의 정보 칸. parts = [(글자, 색), ...]. 차지한 Rect를 돌려준다."""
    font = fonts(size)
    images = [font.render(value, True, color) for value, color in parts]
    pad, gap = 14, 8
    width = pad * 2 + sum(i.get_width() for i in images) + gap * (len(images) - 1)
    rect = pygame.Rect(x, cy - height // 2, width, height)
    box = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(box, fill, box.get_rect(), border_radius=10)
    pygame.draw.rect(box, border, box.get_rect(), 1, border_radius=10)
    surface.blit(box, rect)
    cx = rect.x + pad
    for image in images:
        surface.blit(image, image.get_rect(midleft=(cx, cy)))
        cx += image.get_width() + gap
    return rect


def kind_swatch(surface, kind: str, rect: pygame.Rect) -> None:
    pygame.draw.rect(surface, KIND_COLORS[kind], rect, border_radius=3)


def format_int(value) -> str:
    return f"{int(value):,}"
