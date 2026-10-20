from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

from config import (
    COLOR_BUTTON,
    COLOR_BUTTON_HOVER,
    COLOR_FRAME_GOLD,
    COLOR_FRAME_INNER,
    COLOR_GRAY,
    COLOR_MOON,
    COLOR_PANEL_DARK,
)


# 게임 방법 화면 페이지 수 (renderer와 input_handler가 함께 사용)
HELP_PAGE_COUNT = 3


@dataclass
class Button:
    rect: pygame.Rect
    text: str
    action: str
    enabled: bool = True
    # 보조 버튼은 주 버튼보다 눈에 덜 띄는 톤(어두운 바탕 + 은은한 테두리)으로 그립니다.
    secondary: bool = False
    image: Optional[pygame.Surface] = None  # 있으면 글자 대신 아이콘 버튼으로 그립니다
    # (기본, 마우스 올림) 이미지 한 쌍. 있으면 사각형 대신 이미지 위에 글씨를 씁니다.
    skin: Optional[Tuple[pygame.Surface, pygame.Surface]] = None

    def render(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        hovered = self.enabled and self.rect.collidepoint(pygame.mouse.get_pos())
        if self.image is not None:
            # 남색 원 바탕 + 금빛 테두리 위에 아이콘. 마우스를 올리면 바탕과 테두리가 밝아집니다.
            radius = min(self.rect.size) // 2
            fill, border = (COLOR_BUTTON_HOVER, COLOR_MOON) if hovered else (COLOR_BUTTON, COLOR_FRAME_GOLD)
            pygame.draw.circle(screen, fill, self.rect.center, radius)
            pygame.draw.circle(screen, border, self.rect.center, radius, 2)
            screen.blit(self.image, self.image.get_rect(center=self.rect.center))
            return
        if self.skin:
            image = self.skin[1] if hovered else self.skin[0]
            screen.blit(image, image.get_rect(center=self.rect.center))
            text = font.render(self.text, True, COLOR_MOON if self.enabled else COLOR_GRAY)
            screen.blit(text, text.get_rect(center=self.rect.center))
            return
        if not self.enabled:
            fill, border, text_color = (30, 34, 48), (70, 74, 88), COLOR_GRAY
        elif self.secondary:
            fill = (36, 42, 62) if hovered else COLOR_PANEL_DARK
            border = COLOR_FRAME_GOLD if hovered else COLOR_FRAME_INNER
            text_color = COLOR_MOON if hovered else (196, 190, 160)
        elif hovered:
            fill, border, text_color = COLOR_BUTTON_HOVER, COLOR_MOON, COLOR_MOON
        else:
            fill, border, text_color = COLOR_BUTTON, COLOR_FRAME_GOLD, COLOR_MOON
        pygame.draw.rect(screen, fill, self.rect, border_radius=8)
        pygame.draw.rect(screen, border, self.rect, 1, border_radius=8)
        text = font.render(self.text, True, text_color)
        screen.blit(text, text.get_rect(center=self.rect.center))

    def hit(self, pos: Tuple[int, int]) -> Optional[str]:
        if self.enabled and self.rect.collidepoint(pos):
            return self.action
        return None


class ButtonLayer:
    def __init__(self):
        self.buttons: List[Button] = []

    def set_buttons(self, buttons: List[Button]) -> None:
        self.buttons = buttons

    def handle_click(self, pos: Tuple[int, int]) -> Optional[str]:
        for button in self.buttons:
            action = button.hit(pos)
            if action:
                return action
        return None

    def render(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        for button in self.buttons:
            button.render(screen, font)


def make_button_skin(frame: pygame.Surface, size: Tuple[int, int]) -> Tuple[pygame.Surface, pygame.Surface]:
    """버튼 크기에 맞춘 프레임 이미지와, 마우스를 올렸을 때 쓸 밝은 버전을 만듭니다."""
    normal = pygame.transform.smoothscale(frame, size)
    hover = normal.copy()
    hover.fill((40, 40, 40, 0), special_flags=pygame.BLEND_RGBA_ADD)
    return normal, hover


def panel_rect(x: int, y: int, w: int, h: int) -> pygame.Rect:
    return pygame.Rect(x, y, w, h)


def draw_panel(screen: pygame.Surface, rect: pygame.Rect) -> None:
    # 반투명 남색 바탕 + 금빛 이중 테두리 + 모서리 꺾쇠(단청 액자 느낌)
    surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(surface, (*COLOR_PANEL_DARK, 235), surface.get_rect(), border_radius=10)
    screen.blit(surface, rect.topleft)
    pygame.draw.rect(screen, COLOR_FRAME_GOLD, rect, 2, border_radius=10)
    pygame.draw.rect(screen, COLOR_FRAME_INNER, rect.inflate(-10, -10), 1, border_radius=7)

    size = min(14, rect.width // 6, rect.height // 6)
    inset = 6
    corners = (
        ((rect.left + inset, rect.top + inset), (1, 1)),
        ((rect.right - inset - 1, rect.top + inset), (-1, 1)),
        ((rect.left + inset, rect.bottom - inset - 1), (1, -1)),
        ((rect.right - inset - 1, rect.bottom - inset - 1), (-1, -1)),
    )
    for (x, y), (dx, dy) in corners:
        pygame.draw.lines(screen, COLOR_FRAME_GOLD, False,
                          [(x, y + dy * size), (x, y), (x + dx * size, y)], 2)


def draw_title_ornament(screen: pygame.Surface, center_x: int, y: int, width: int = 160) -> None:
    """제목 아래 장식선: ── ◆ ──"""
    half = width // 2
    pygame.draw.line(screen, COLOR_FRAME_GOLD, (center_x - half, y), (center_x - 10, y), 1)
    pygame.draw.line(screen, COLOR_FRAME_GOLD, (center_x + 10, y), (center_x + half, y), 1)
    pygame.draw.polygon(screen, COLOR_FRAME_GOLD,
                        [(center_x, y - 5), (center_x + 5, y), (center_x, y + 5), (center_x - 5, y)])
