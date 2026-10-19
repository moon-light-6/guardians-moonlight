from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

from config import COLOR_BLUE, COLOR_GRAY, COLOR_PANEL_DARK, COLOR_WHITE


@dataclass
class Button:
    rect: pygame.Rect
    text: str
    action: str
    enabled: bool = True
    secondary: bool = False

    def render(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        # 보조 버튼은 주 버튼보다 눈에 덜 띄는 톤으로 그린다.
        base, hover = ((70, 88, 124), (92, 112, 150)) if self.secondary else (COLOR_BLUE, (105, 162, 215))
        color = base if self.enabled else (67, 73, 91)
        mouse_pos = pygame.mouse.get_pos()
        if self.enabled and self.rect.collidepoint(mouse_pos):
            color = hover
        pygame.draw.rect(screen, color, self.rect, border_radius=8)
        pygame.draw.rect(screen, (156, 178, 205), self.rect, 1, border_radius=8)
        text = font.render(self.text, True, COLOR_WHITE if self.enabled else COLOR_GRAY)
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


def panel_rect(x: int, y: int, w: int, h: int) -> pygame.Rect:
    return pygame.Rect(x, y, w, h)


def draw_panel(screen: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(screen, COLOR_PANEL_DARK, rect, border_radius=8)
    pygame.draw.rect(screen, (70, 86, 120), rect, 1, border_radius=8)
