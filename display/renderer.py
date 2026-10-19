
from pathlib import Path
from typing import List

import pygame

from config import (
    BOSS_KILL_GOLD,
    BOARD_BOTTOM_WIDTH,
    BOARD_BOTTOM_Y,
    BOARD_TILE_DEPTH,
    BOARD_TOP_WIDTH,
    BOARD_TOP_Y,
    CELL_SIZE,
    COLOR_BLACK,
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_FRAME_GOLD,
    COLOR_FRAME_INNER,
    COLOR_GOLD,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_MINT,
    COLOR_MOON,
    COLOR_OVERLAY,
    COLOR_PANEL,
    COLOR_PANEL_DARK,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_WHITE,
    GRID_ORIGIN,
    KILL_GOLD,
    MAX_ACTIONS_PER_WAVE,
    MAX_STAGES,
    MAX_TOWER_LEVEL,
    PANEL_WIDTH,
    PANEL_X,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SELL_REFUND_RATE,
    SUMMON_COST,
    UPGRADE_COSTS,
    MURAL_ORIGINS,
    SUMMON_CORE_COLOR,
    SUMMON_GATHER_SECONDS,
    SUMMON_GLOW_COLOR,
    SUMMON_TOTAL_SECONDS,
    SUMMON_TRAVEL_SECONDS,
    SUMMON_WAKE_SECONDS,
)
from display.ui import HELP_PAGE_COUNT, Button, ButtonLayer, draw_panel, draw_title_ornament
from display.sprite_animation import TowerSpriteAnimator
from display.boss_animation import BossSpriteAnimator
from display.effect_animation import AttackEffectAnimator
from display.enemy_animation import EnemySpriteAnimator
from display.render_sizes import TOWER_BOTTOM_OFFSET, TOWER_LEVEL_GAP
from game.economy import Economy
from game.enemy import Enemy, EnemyType
from game.map import GameMap
from game.state import GamePhase, GameState
from game.tower import Tower, TowerType
from game.wave import WaveManager


class Renderer:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.map = GameMap()
        self.buttons = ButtonLayer()
        self.font_title = self._font(54)
        self.font_big = self._font(32)
        self.font_med = self._font(22)
        self.font_small = self._font(16)
        self.economy = Economy()
        self.background = self._load_background()
        self.boss_portraits = self._load_boss_portraits()
        self.tower_animator = TowerSpriteAnimator()
        self.boss_animator = BossSpriteAnimator()
        self.effect_animator = AttackEffectAnimator()
        self.enemy_animator = EnemySpriteAnimator()
        self._help_sprite_cache = {}

    def _load_boss_portraits(self) -> dict:
        sheet = pygame.image.load(str(Path(__file__).resolve().parents[1] / "data" / "boss_roster.png"))
        regions = {
            "먹그림자": (24, 400, 402, 365),
            "철갓장군": (448, 396, 408, 370),
            "서리석귀": (869, 400, 385, 365),
            "홍염귀왕": (20, 770, 394, 410),
            "흑운이무기": (432, 770, 437, 433),
            "월식대왕": (864, 754, 390, 433),
        }
        portraits = {}
        for name, region in regions.items():
            for size in (60, 130):
                portrait = pygame.transform.smoothscale(sheet.subsurface(region), (size, size))
                masked = pygame.Surface((size, size), pygame.SRCALPHA)
                masked.blit(portrait, (0, 0))
                mask = pygame.Surface((size, size), pygame.SRCALPHA)
                pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
                masked.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                portraits[name, size] = masked
        return portraits

    def _load_background(self) -> pygame.Surface:
        """원본 달빛 뜰 배경을 게임 해상도에 맞춰 한 번만 준비합니다."""
        path = Path(__file__).resolve().parents[1] / "assets" / "backgrounds" / "moonlit-courtyard.png"
        image = pygame.image.load(str(path)).convert()
        return pygame.transform.smoothscale(image, (SCREEN_WIDTH, SCREEN_HEIGHT))

    def _font(self, size: int) -> pygame.font.Font:
        # 한국어 글씨체 - 맥북 운영체제
        for font_name in (
            "Apple SD Gothic Neo",  # macOS
            "AppleGothic",          # older macOS versions
            "Malgun Gothic",        # Windows
            "NanumGothic",          # common Korean Linux font
        ):
            font_path = pygame.font.match_font(font_name)
            if font_path:
                return pygame.font.Font(font_path, size)

        return pygame.font.Font(None, size)

    def render(self, state: GameState, quit_confirm: bool = False, help_page: int = 0) -> None:
        self.screen.fill(COLOR_BLACK)
        self._draw_moonlit_background()
        if state.phase == GamePhase.TITLE:
            self._render_title()
        elif state.phase == GamePhase.HELP:
            self._render_help(help_page)
        else:
            self._render_game(state)
        if quit_confirm:
            self._render_quit_popup()

    def _draw_moonlit_background(self) -> None:
        # 사신 벽화도 원본에 포함되어 있으므로 별도의 도형으로 덮어쓰지 않습니다.
        self.screen.blit(self.background, (0, 0))

    def _render_title(self) -> None:
        title = self.font_title.render("월하사신", True, COLOR_WHITE)
        subtitle = self.font_med.render("달이 뜨면, 벽화 속 수호신이 깨어난다", True, COLOR_MOON)
        self.screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 240)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(SCREEN_WIDTH // 2, 300)))
        buttons = [
            Button(pygame.Rect(520, 380, 240, 46), "게임 시작", "START_GAME"),
            Button(pygame.Rect(520, 438, 240, 46), "게임 방법", "SHOW_HELP"),
            Button(pygame.Rect(520, 496, 240, 46), "종료", "QUIT"),
        ]
        self.buttons.set_buttons(buttons)
        self.buttons.render(self.screen, self.font_med)

    def _render_quit_popup(self) -> None:
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill(COLOR_OVERLAY)
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(430, 280, 420, 200)
        draw_panel(self.screen, panel)
        message = self.font_med.render("게임을 종료하시겠습니까?", True, COLOR_WHITE)
        self.screen.blit(message, message.get_rect(center=(panel.centerx, panel.y + 66)))
        self.buttons.set_buttons([
            Button(pygame.Rect(454, 410, 174, 42), "아니요", "QUIT_NO"),
            Button(pygame.Rect(652, 410, 174, 42), "예", "QUIT_YES"),
        ])
        self.buttons.render(self.screen, self.font_med)

    # ===== 게임 방법 (3페이지) =====

    HELP_PAGE_TITLES = ("플레이 순서", "사신 4종", "악귀와 보스")
    HELP_GUARDIAN_ORDER = ("LIGHTNING", "ARCHER", "CANNON", "ICE")

    def _render_help(self, page: int = 0) -> None:
        page = max(0, min(HELP_PAGE_COUNT - 1, page))
        panel = pygame.Rect(90, 40, 1100, 760)
        draw_panel(self.screen, panel)
        cx = panel.centerx
        self._text_center("게임 방법", cx, 62, self.font_big, COLOR_MOON)
        draw_title_ornament(self.screen, cx, 104, 220)
        self._text_center(f"{page + 1} / {HELP_PAGE_COUNT}  ·  {self.HELP_PAGE_TITLES[page]}",
                          cx, 118, self.font_small, COLOR_GOLD)

        (self._render_help_steps, self._render_help_guardians, self._render_help_enemies)[page]()

        # 페이지 점
        for i in range(HELP_PAGE_COUNT):
            center = (cx - (HELP_PAGE_COUNT - 1) * 12 + i * 24, 700)
            if i == page:
                pygame.draw.circle(self.screen, COLOR_GOLD, center, 6)
            else:
                pygame.draw.circle(self.screen, COLOR_FRAME_INNER, center, 5, 1)

        self.buttons.set_buttons([
            Button(pygame.Rect(370, 724, 170, 46), "◀ 이전", "HELP_PREV", page > 0),
            Button(pygame.Rect(555, 724, 170, 46), "알겠어요", "BACK_TO_TITLE"),
            Button(pygame.Rect(740, 724, 170, 46), "다음 ▶", "HELP_NEXT", page < HELP_PAGE_COUNT - 1),
        ])
        self.buttons.render(self.screen, self.font_med)

    def _render_help_steps(self) -> None:
        steps = [
            ("사신 소환", ["빈 슬롯 + 를 누르고", f"{SUMMON_COST}G로 사신을 소환해요", "4종 중 1종이 랜덤!"]),
            ("준비 단계", ["사신을 눌러 강화·이동·판매", "강화할수록 피해가 커져요", f"소동마다 행동 {MAX_ACTIONS_PER_WAVE}회까지"]),
            ("소동 시작", ["악귀가 길을 따라 와요", "사신이 자동으로 공격!", "전투 중에도 강화 가능"]),
            ("결계 수호", ["악귀가 E에 닿으면", "결계가 줄어들어요", f"{MAX_STAGES}소동을 버티면 승리!"]),
        ]
        for i, (title, lines) in enumerate(steps):
            card = pygame.Rect(130 + i * 260, 160, 240, 340)
            self._help_card(card)
            badge = (card.x + 28, card.y + 28)
            pygame.draw.circle(self.screen, COLOR_FRAME_GOLD, badge, 15)
            self._text_center(str(i + 1), badge[0], badge[1] - self.font_small.get_height() // 2,
                              self.font_small, COLOR_PANEL_DARK)
            art_y = card.y + 112
            if i == 0:
                slot = pygame.Rect(0, 0, 50, 40)
                slot.center = (card.centerx - 58, art_y)
                pygame.draw.rect(self.screen, (52, 60, 88), slot, border_radius=4)
                pygame.draw.rect(self.screen, (150, 160, 190), slot, 1, border_radius=4)
                self._text_center("+", slot.centerx, slot.y + 6, self.font_med, COLOR_WHITE)
                self._text_center("→", card.centerx - 4, art_y - 14, self.font_med, COLOR_GOLD)
                self._blit_center(self._help_guardian("CANNON", 1.2), (card.centerx + 56, art_y))
            elif i == 1:
                self._blit_center(self._help_guardian("LIGHTNING", 1.3), (card.centerx - 42, art_y))
                self._text_center("Lv.1", card.centerx + 54, art_y - 34, self.font_small, COLOR_GRAY)
                self._text_center("▼", card.centerx + 54, art_y - 12, self.font_small, COLOR_GOLD)
                self._text_center("Lv.2", card.centerx + 54, art_y + 10, self.font_small, COLOR_MOON)
            elif i == 2:
                frames = self.enemy_animator.frames[EnemyType.BASIC, "front"]
                tick = pygame.time.get_ticks() * self.enemy_animator.ANIMATION_FPS // 1000
                for j in range(3):
                    self._blit_center(frames[(tick + j) % len(frames)], (card.centerx - 72 + j * 46, art_y))
                self._text_center("→", card.centerx + 84, art_y - 14, self.font_med, COLOR_RED)
            else:
                self._blit_center(self.boss_portraits["월식대왕", 60], (card.centerx - 44, art_y))
                self._text_center("결계", card.centerx + 46, art_y - 28, self.font_small, COLOR_GRAY)
                self._text_center("20", card.centerx + 46, art_y - 6, self.font_big, COLOR_MINT)
            self._text_center(title, card.centerx, card.y + 196, self.font_med, COLOR_MOON)
            for j, line in enumerate(lines):
                self._text_center(line, card.centerx, card.y + 238 + j * 28, self.font_small,
                                  COLOR_WHITE if j == 0 else COLOR_GRAY)

        # 한 소동의 흐름
        flow = ["수호 준비", "소동 (자동 전투)", "정산", "다음 준비"]
        widths = [self.font_small.size(label)[0] + 36 for label in flow]
        arrow_w = 34
        x = 640 - (sum(widths) + arrow_w * (len(flow) - 1)) // 2
        for i, (label, width) in enumerate(zip(flow, widths)):
            pill = pygame.Rect(x, 530, width, 38)
            pygame.draw.rect(self.screen, COLOR_PANEL, pill, border_radius=19)
            pygame.draw.rect(self.screen, COLOR_FRAME_GOLD, pill, 1, border_radius=19)
            self._text_center(label, pill.centerx, pill.y + 9, self.font_small, COLOR_MOON)
            x += width
            if i < len(flow) - 1:
                self._text_center("→", x + arrow_w // 2, 538, self.font_small, COLOR_GOLD)
                x += arrow_w
        self._text_center(f"이 흐름을 {MAX_STAGES}번 반복해요. 소환·이동·판매는 준비 단계에서만, 강화는 언제든 할 수 있어요.",
                          640, 600, self.font_small, COLOR_GRAY)

    def _render_help_guardians(self) -> None:
        for i, tower_type in enumerate(self.HELP_GUARDIAN_ORDER):
            card = pygame.Rect(130 + i * 260, 160, 240, 410)
            self._help_card(card)
            stats = Tower.BASE_STATS[TowerType[tower_type]]
            kind, _, effect = stats["description"].partition(" · ")
            self._blit_center(self._help_guardian(tower_type, 1.6), (card.centerx, card.y + 96))
            self._text_center(stats["guardian"], card.centerx, card.y + 178, self.font_big, COLOR_MOON)
            self._text_center(kind, card.centerx, card.y + 226, self.font_small, COLOR_GOLD)
            self._text_center(effect, card.centerx, card.y + 252, self.font_small, COLOR_WHITE)
            pygame.draw.line(self.screen, COLOR_FRAME_INNER, (card.x + 24, card.y + 292), (card.right - 24, card.y + 292), 1)
            rows = [
                ("피해", f"{stats['damage']:g}"),
                ("공격 간격", f"{stats['attack_interval']:g}초"),
                ("사거리", f"{stats['range']:g}칸"),
            ]
            for j, (label, value) in enumerate(rows):
                y = card.y + 308 + j * 30
                self._text(label, card.x + 30, y, self.font_small, COLOR_GRAY)
                self._text(value, card.right - 30 - self.font_small.size(value)[0], y, self.font_small, COLOR_WHITE)

        info = pygame.Rect(130, 590, 1020, 84)
        self._help_card(info)
        upgrade_costs = " / ".join(str(UPGRADE_COSTS[level]) for level in sorted(UPGRADE_COSTS))
        self._text_center(f"소환 {SUMMON_COST}G · 4종 각 25% 랜덤      판매하면 투자한 골드의 {round(SELL_REFUND_RATE * 100)}% 환급",
                          640, info.y + 16, self.font_small, COLOR_WHITE)
        self._text_center(f"강화 비용 {upgrade_costs}G · 최대 Lv.{MAX_TOWER_LEVEL} · 레벨이 오를수록 피해가 커져요",
                          640, info.y + 46, self.font_small, COLOR_GRAY)

    def _render_help_enemies(self) -> None:
        self._text("일반 악귀", 130, 150, self.font_small, COLOR_GOLD)
        tick = pygame.time.get_ticks() * self.enemy_animator.ANIMATION_FPS // 1000
        for i, (enemy_type, first_stage) in enumerate(((EnemyType.BASIC, 1), (EnemyType.FAST, 2), (EnemyType.TANK, 3))):
            card = pygame.Rect(130 + i * 345, 174, 330, 140)
            self._help_card(card)
            frames = self.enemy_animator.frames[enemy_type, "front"]
            image = pygame.transform.smoothscale(frames[tick % len(frames)], (76, 76))
            self._blit_center(image, (card.x + 64, card.centery))
            visual = Enemy.VISUALS[enemy_type]
            self._text(visual["name"], card.x + 124, card.y + 20, self.font_med, COLOR_MOON)
            self._text(f"속도 {visual['speed']:g}칸/초", card.x + 124, card.y + 56, self.font_small, COLOR_WHITE)
            self._text(f"닿으면 결계 -{visual['life_damage']}", card.x + 124, card.y + 82, self.font_small, COLOR_RED)
            self._text(f"{first_stage}소동부터 등장", card.x + 124, card.y + 108, self.font_small, COLOR_GRAY)

        self._text("보스 악귀 · 5소동마다 등장", 130, 330, self.font_small, COLOR_GOLD)
        for i, (stage, boss) in enumerate(sorted(WaveManager.BOSSES.items())):
            card = pygame.Rect(130 + i * 172, 354, 160, 160)
            self._help_card(card)
            self._blit_center(self.boss_portraits[boss["name"], 60], (card.centerx, card.y + 48))
            self._text_center(boss["name"], card.centerx, card.y + 88, self.font_small, COLOR_MOON)
            self._text_center(f"{stage}소동", card.centerx, card.y + 112, self.font_small, COLOR_GOLD)
            self._text_center(f"결계 -{boss['life_damage']}", card.centerx, card.y + 134, self.font_small, COLOR_RED)

        tip = pygame.Rect(130, 532, 1020, 142)
        self._help_card(tip)
        self._text("TIP", tip.x + 24, tip.y + 18, self.font_med, COLOR_GOLD)
        tips = [
            (f"일반 악귀 처치 +{KILL_GOLD}G · 보스 처치 +{BOSS_KILL_GOLD}G · 소동을 해결하면 보너스 골드", COLOR_WHITE),
            ("보스는 체력이 높으니 강화한 사신을 길목에 모아 두세요", COLOR_WHITE),
            ("단축키   Space 소동 시작   ·   Enter 정산 확인   ·   ESC 뒤로 / 종료   ·   ← → 페이지 넘기기", COLOR_GRAY),
        ]
        for j, (line, color) in enumerate(tips):
            self._text(line, tip.x + 90, tip.y + 22 + j * 36, self.font_small, color)

    def _help_guardian(self, tower_type: str, scale: float) -> pygame.Surface:
        """대기 모션 현재 프레임을 확대해서 돌려줍니다(크기별로 캐시)."""
        frames = self.tower_animator.frames[(tower_type, "idle", "SE")]
        index = pygame.time.get_ticks() // self.tower_animator.IDLE_FRAME_MS % len(frames)
        cache = self._help_sprite_cache
        key = (tower_type, index, scale)
        if key not in cache:
            image = frames[index]
            size = (round(image.get_width() * scale), round(image.get_height() * scale))
            cache[key] = pygame.transform.smoothscale(image, size)
        return cache[key]

    def _help_card(self, rect: pygame.Rect) -> None:
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(surface, (*COLOR_PANEL, 220), surface.get_rect(), border_radius=8)
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(self.screen, COLOR_FRAME_INNER, rect, 1, border_radius=8)

    def _blit_center(self, image: pygame.Surface, center) -> None:
        self.screen.blit(image, image.get_rect(center=center))

    def _text_center(self, value: str, center_x: int, y: int, font: pygame.font.Font, color) -> None:
        surface = font.render(value, True, color)
        self.screen.blit(surface, (center_x - surface.get_width() // 2, y))

    def _render_game(self, state: GameState) -> None:
        self._render_hud(state)
        self._render_board(state)
        # 기존 관리 패널의 코드와 동작을 그대로 유지합니다.
        self._render_side_panel(state)
        if state.phase == GamePhase.SELL_CONFIRM:
            self._render_sell_popup(state)
        elif state.phase == GamePhase.SETTLEMENT:
            self._render_settlement_popup(state)
        elif state.phase in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
            self._render_result(state)
        self.buttons.render(self.screen, self.font_small)

    def _render_settlement_popup(self, state: GameState) -> None:
        result = state.wave_result
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill(COLOR_OVERLAY)
        self.screen.blit(overlay, (0, 0))

        width, height = 560, 480
        panel = pygame.Rect((SCREEN_WIDTH - width) // 2, (SCREEN_HEIGHT - height) // 2, width, height)
        draw_panel(self.screen, panel)
        left, right = panel.x + 40, panel.right - 40

        title = self.font_big.render(f"{result.stage}번째 소동 해결!", True, COLOR_MOON)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 48)))
        draw_title_ornament(self.screen, panel.centerx, panel.y + 74, 200)
        if result.boss_name:
            boss_result = "처치 성공" if result.boss_kills else "결계 도달"
            boss_line = self.font_small.render(f"{result.boss_name} · {boss_result}", True, COLOR_MOON)
            self.screen.blit(boss_line, boss_line.get_rect(center=(panel.centerx, panel.y + 92)))

        rows = [
            (f"일반 악귀 {result.normal_kills}마리 처치 보상", f"{result.kill_gold} G"),
            (f"보스 악귀 {result.boss_kills}마리 처치 보상", f"{result.boss_gold} G"),
            ("소동 해결 보상", f"{result.clear_gold} G"),
            ("총 획득 보상", f"{result.total_gold} G"),
            ("결계 변화", f"{result.life_before} → {result.life_after}"),
        ]
        row_y = panel.y + 130
        for i, (label, value) in enumerate(rows):
            y = row_y + i * 46
            if label == "총 획득 보상":
                # 합계 줄: 위에 구분선을 긋고 값을 크게 강조합니다.
                pygame.draw.line(self.screen, COLOR_FRAME_INNER, (left, y - 10), (right, y - 10), 1)
                self._text(label, left, y, self.font_med, COLOR_MOON)
                value_y = y + (self.font_med.get_height() - self.font_big.get_height()) // 2
                self._text(value, right - self.font_big.size(value)[0], value_y, self.font_big, COLOR_GOLD)
                continue
            self._text(label, left, y, self.font_med, COLOR_GRAY)
            self._text(value, right - self.font_med.size(value)[0], y, self.font_med, COLOR_GOLD)

        label = "최종 승리 확인" if state.current_stage == 30 else "다음 수호 준비 단계로"
        self.buttons.set_buttons([Button(pygame.Rect(panel.centerx - 140, panel.bottom - 80, 280, 46), label, "CONTINUE")])

    def _render_sell_popup(self, state: GameState) -> None:
        selected = state.pending_sell_slot
        if not state.has_tower(selected):
            return
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill(COLOR_OVERLAY)
        self.screen.blit(overlay, (0, 0))
        draw_panel(self.screen, pygame.Rect(430, 310, 420, 220))
        tower = state.towers[selected]
        refund = self.economy.get_sell_refund(state, selected)
        self._text(f"{Tower.display_name(tower['type'])} Lv.{tower['level']} 판매", 454, 338, self.font_med, COLOR_WHITE)
        self._text(f"환급 {refund} G", 454, 388, self.font_med, COLOR_GOLD)
        self.buttons.set_buttons([
            Button(pygame.Rect(454, 460, 174, 42), "취소", "CANCEL"),
            Button(pygame.Rect(652, 460, 174, 42), "판매 확정", "CONFIRM_SELL", self.economy.can_confirm_sell(state, selected)),
        ])

    def _render_hud(self, state: GameState) -> None:
        self._text("월하사신", 42, 34, self.font_big, COLOR_WHITE)
        is_preparing = state.phase not in {
            GamePhase.WAVE_ACTIVE, GamePhase.SETTLEMENT, GamePhase.GAME_OVER, GamePhase.VICTORY
        }
        if state.phase == GamePhase.WAVE_ACTIVE:
            phase = "소동 발생"
        elif state.phase == GamePhase.SETTLEMENT:
            phase = "정산"
        elif state.phase == GamePhase.GAME_OVER:
            phase = "패배"
        elif state.phase == GamePhase.VICTORY:
            phase = "승리"
        else:
            phase = "수호 준비"
        self._text(f"소동 {state.current_stage:02d} / 30", 250, 46, self.font_med, COLOR_WHITE)
        self._text(f"결계 {state.life}", 430, 46, self.font_med, COLOR_MINT)
        self._text(f"{state.gold} G", 548, 46, self.font_med, COLOR_GOLD)
        self._text(phase, 680, 46, self.font_med, COLOR_CYAN)
        if is_preparing:
            count_x = 680 + self.font_med.size(phase)[0] + 12
            self._text(f"{state.actions_taken_this_wave} / 20", count_x, 50, self.font_small, COLOR_GRAY)

    def _render_board(self, state: GameState) -> None:
        # map.path(87칸)와 map.slots(24칸)를 그대로 투영합니다. 이곳에서 좌표를
        # 새로 만들지 않으므로, 보드 외형이 바뀌어도 이동/배치/판정 수는 유지됩니다.
        board = self.map.board_polygon()
        pygame.draw.polygon(self.screen, (4, 8, 17), self._offset_polygon(board, 10))
        pygame.draw.polygon(self.screen, (13, 22, 39), board)
        pygame.draw.polygon(self.screen, (62, 79, 108), board, 2)

        # 희미한 줄눈으로 뜰의 깊이만 주고, 경로 타일은 별도로 명확히 구분합니다.
        for row in range(1, self.map.map_height):
            left = self.map.cell_polygon(0, row)[0]
            right = self.map.cell_polygon(self.map.map_width - 1, row)[1]
            pygame.draw.line(self.screen, (20, 34, 58), left, right, 1)

        for cell in self.map.get_path():
            self._draw_path_tile(cell)

        for label, cell, color in (
            ("S", self.map.get_start_position(), COLOR_MINT),
            ("E", self.map.get_base_position(), COLOR_RED),
        ):
            center = self.map.grid_to_pixel(cell)
            self._text(label, center[0] - 12, center[1] - 13, self.font_med, color)

        # 현무의 연속 장판 애니메이션을 유닛 아래에 한 번만 표시합니다.
        target_positions = {enemy.enemy_id: enemy.get_current_position()
                            for enemy in state.enemies if enemy.enemy_id is not None}
        effects = [self.effect_animator.resolve_targets(effect, target_positions)
                   for effect in state.effects]
        for effect in effects:
            if effect["kind"] == "slow_field" and effect["age"] < effect["ttl"] - 1e-9:
                self._draw_effect(effect)

        pending_slots = {summon["slot_id"] for summon in state.summons}
        for slot_id in self.map.slots:
            pos = self.map.grid_to_pixel(self.map.get_slot_position(slot_id))
            occupied = state.has_tower(slot_id) or slot_id in pending_slots
            selected = state.selected_slot == slot_id
            moving = state.phase == GamePhase.MOVING_TOWER and state.is_slot_empty(slot_id)
            self._draw_slot_tile(slot_id, selected, moving, occupied)
            color = COLOR_MINT if moving else (COLOR_GOLD if selected else (123, 145, 180))
            if not occupied:
                self._text("+", pos[0] - 6, pos[1] - 12, self.font_med, color)

        if (state.selected_slot is not None
                and state.has_tower(state.selected_slot)
                and state.selected_slot not in pending_slots):
            tower_data = state.towers[state.selected_slot]
            stats = Tower.from_data(tower_data).get_stats()
            center = self.map.grid_to_pixel(self.map.get_slot_position(state.selected_slot))
            self._draw_projected_range(center, stats["range"])

        for summon in state.summons:
            self._draw_summon_effect(summon)

        for slot_id, tower_data in state.towers.items():
            if slot_id in pending_slots:
                continue
            self._draw_tower(
                slot_id,
                tower_data,
                effects,
            )
        for enemy in state.enemies:
            self._draw_enemy(enemy, state.wave_elapsed)
        for effect in effects:
            if effect["kind"] != "slow_field":
                self._draw_effect(effect)

    @staticmethod
    def _offset_polygon(points, y_offset: int):
        return [(x, y + y_offset) for x, y in points]

    def _draw_path_tile(self, cell) -> None:
        """기존 경로의 한 칸을 두께 있는 돌 타일로 표현합니다."""
        polygon = self.map.cell_polygon(cell[0] + 0.06, cell[1] + 0.08, 0.88, 0.82)
        pygame.draw.polygon(self.screen, (22, 28, 43), self._offset_polygon(polygon, BOARD_TILE_DEPTH))
        pygame.draw.polygon(self.screen, (72, 80, 105), polygon)
        pygame.draw.polygon(self.screen, (124, 133, 157), polygon, 1)

    def _draw_slot_tile(self, slot_id: int, selected: bool, moving: bool, occupied: bool) -> None:
        polygon = self.map.slot_polygon(slot_id)
        if selected:
            glow = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(glow, (244, 210, 112, 70), polygon)
            self.screen.blit(glow, (0, 0))
        side_color = (38, 52, 77)
        face_color = (57, 75, 108) if occupied else (47, 63, 92)
        border = COLOR_MINT if moving else (COLOR_GOLD if selected else (118, 140, 174))
        pygame.draw.polygon(self.screen, side_color, self._offset_polygon(polygon, BOARD_TILE_DEPTH))
        pygame.draw.polygon(self.screen, face_color, polygon)
        pygame.draw.polygon(self.screen, border, polygon, 2)

    def _draw_projected_range(self, center, logical_range: float) -> None:
        # 전투 판정은 논리 좌표에서 유지하고, 표시만 현 행의 사다리꼴 비율에 맞춘 타원으로 냅니다.
        row_ratio = (center[1] - BOARD_TOP_Y) / (BOARD_BOTTOM_Y - BOARD_TOP_Y)
        cell_width = (BOARD_TOP_WIDTH + (BOARD_BOTTOM_WIDTH - BOARD_TOP_WIDTH) * row_ratio) / self.map.map_width
        cell_height = (BOARD_BOTTOM_Y - BOARD_TOP_Y) / self.map.map_height
        rect = pygame.Rect(
            round(center[0] - logical_range * cell_width),
            round(center[1] - logical_range * cell_height),
            round(logical_range * cell_width * 2),
            round(logical_range * cell_height * 2),
        )
        pygame.draw.ellipse(self.screen, (97, 167, 213), rect, 1)

    def _draw_summon_effect(self, summon: dict) -> None:
        """벽화의 빛 → 달빛 덩어리 → 도착지 수렴. 캐릭터는 완료 전 보이지 않습니다."""
        elapsed = summon["elapsed"]
        origin = pygame.Vector2(MURAL_ORIGINS[summon["tower_type"]])
        target = pygame.Vector2(self.map.grid_to_pixel(self.map.get_slot_position(summon["slot_id"])))

        if elapsed < SUMMON_WAKE_SECONDS:
            progress = elapsed / SUMMON_WAKE_SECONDS
            position = origin
            radius = 8 + 22 * progress
            strength = progress
        elif elapsed < SUMMON_WAKE_SECONDS + SUMMON_TRAVEL_SECONDS:
            progress = (elapsed - SUMMON_WAKE_SECONDS) / SUMMON_TRAVEL_SECONDS
            smooth = progress * progress * (3 - 2 * progress)
            position = origin.lerp(target, smooth)
            radius = 24 - 7 * smooth
            strength = 1.0
        else:
            progress = min(1.0, (elapsed - SUMMON_WAKE_SECONDS - SUMMON_TRAVEL_SECONDS) / SUMMON_GATHER_SECONDS)
            position = target
            radius = 18 + 22 * (1 - progress)
            strength = 1.0 - progress * 0.25

        # Pygame에는 블러 필터가 없으므로, 알파가 연속적으로 바뀌는 미세한 원을
        # 바깥에서 안쪽으로 겹쳐 부드러운 달빛 번짐으로 보이게 합니다.
        blur_radius = max(12, round(radius * 1.8))
        soft_glow = pygame.Surface((blur_radius * 2, blur_radius * 2), pygame.SRCALPHA)
        glow_center = (blur_radius, blur_radius)
        for ring_radius in range(blur_radius, 0, -1):
            toward_center = 1 - ring_radius / blur_radius
            alpha = round(145 * strength * toward_center ** 1.7)
            pygame.draw.circle(
                soft_glow,
                (*SUMMON_GLOW_COLOR, alpha),
                glow_center,
                ring_radius,
            )
        self.screen.blit(
            soft_glow,
            (round(position.x) - blur_radius, round(position.y) - blur_radius),
        )

        # 중심의 흰빛만 작고 선명하게 남깁니다.
        pygame.draw.circle(
            self.screen,
            (*SUMMON_CORE_COLOR, round(230 * strength)),
            (round(position.x), round(position.y)),
            max(3, round(radius * 0.3)),
        )

    def _draw_tower(
        self,
        slot_id: int,
        tower_data: dict,
        effects: list,
    ) -> None:
        tower_pos = self.map.get_slot_position(slot_id)
        pos = self.map.grid_to_pixel(tower_pos)

        tower_type = tower_data["type"]

        # PNG 프레임 애니메이션 출력
        animated = self.tower_animator.draw(
            screen=self.screen,
            slot_id=slot_id,
            tower_type=tower_type,
            pixel_pos=pos,
            tower_pos=tower_pos,
            effects=effects,
        )

        # 애니메이션이 없는 타워는 기존 원형 디자인 유지
        if not animated:
            colors = {
                "LIGHTNING": COLOR_CYAN,
                "ARCHER": COLOR_GOLD,
                "CANNON": (230, 112, 82),
                "ICE": COLOR_MINT,
            }

            pygame.draw.circle(
                self.screen,
                colors[tower_type],
                pos,
                15,
            )

            pygame.draw.circle(
                self.screen,
                COLOR_WHITE,
                (pos[0] - 4, pos[1] - 4),
                2,
            )

        # 모든 타워 아래에 레벨 표시
        level_text = f"Lv.{tower_data['level']}"

        text_surface = self.font_small.render(
            level_text,
            True,
            COLOR_WHITE,
        )

        text_rect = text_surface.get_rect(
            midtop=(pos[0], pos[1] + TOWER_BOTTOM_OFFSET + TOWER_LEVEL_GAP)
        )

        # 검은 그림자
        shadow_surface = self.font_small.render(
            level_text,
            True,
            COLOR_BLACK,
        )

        self.screen.blit(
            shadow_surface,
            text_rect.move(1, 1),
        )

        self.screen.blit(
            text_surface,
            text_rect,
        )

    def _draw_enemy(self, enemy, animation_time: float = 0.0) -> None:
        pos = self.map.grid_to_pixel(enemy.get_current_position())
        if enemy.is_boss:
            sprite_rect = self.boss_animator.draw(self.screen, enemy, pos, animation_time)
        else:
            sprite_rect = self.enemy_animator.draw(self.screen, enemy, pos, animation_time)
        hp_ratio = max(0, enemy.health / enemy.max_health)
        hp_top = sprite_rect.top - 14
        pygame.draw.rect(self.screen, COLOR_RED, (pos[0] - 18, hp_top, 36, 4))
        pygame.draw.rect(self.screen, COLOR_GREEN, (pos[0] - 18, hp_top, int(36 * hp_ratio), 4))

    def _draw_effect(self, effect: dict) -> None:
        # water 이벤트는 현무 본체의 공격 모션에만 사용합니다.
        if effect["kind"] == "water":
            return
        if effect["kind"] == "slow_field":
            self.effect_animator.draw(self.screen, effect, self.map)
            return
        alpha = 1.0 - effect["age"] / effect["ttl"]

        # 공격 이펙트 출력
        if effect["kind"] in (
            "lightning",
            "claw",
            "fire",
        ):
            if self.effect_animator.draw(
                self.screen,
                effect,
                self.map,
            ):
                return
        alpha = 1.0 - effect["age"] / effect["ttl"]

        if effect["kind"] == "lightning":
            points = [self.map.grid_to_pixel(effect["from"])] + [self.map.grid_to_pixel(p) for p in effect["points"]]
            if len(points) > 1:
                pygame.draw.lines(self.screen, COLOR_CYAN, False, points, max(1, int(4 * alpha)))
        elif effect["kind"] == "fire":
            end = self.map.grid_to_pixel(effect["to"])
            pygame.draw.circle(self.screen, (239, 101, 78), end, int(22 * alpha), 2)
        else:
            start = self.map.grid_to_pixel(effect["from"])
            end = self.map.grid_to_pixel(effect["to"])
            pygame.draw.line(self.screen, COLOR_GOLD, start, end, 4)

    def _render_bottom_panel(self, state: GameState) -> None:
        """보드를 가리지 않는 하단 조작부입니다."""
        panel = pygame.Rect(42, 728, SCREEN_WIDTH - 84, 92)
        draw_panel(self.screen, panel)
        buttons: List[Button] = []
        selected = state.selected_slot
        pending_slots = {summon["slot_id"] for summon in state.summons}

        if state.phase == GamePhase.SETTLEMENT:
            result = state.wave_result
            self._text(f"{result.stage}번째 웨이브 방어 성공", 66, 744, self.font_med, COLOR_WHITE)
            rewards = f"일반 적 처치 {result.normal_kills}마리  +{result.kill_gold} G   ·   보스 처치 {result.boss_kills}마리  +{result.boss_gold} G   ·   클리어 +{result.clear_gold} G"
            self._text(rewards, 66, 779, self.font_small, COLOR_MOON)
            label = "최종 승리 확인" if state.current_stage == 30 else "다음 준비 단계로"
            buttons.append(Button(pygame.Rect(1022, 765, 188, 38), label, "CONTINUE"))
        elif state.phase == GamePhase.WAVE_ACTIVE:
            self._text("자동 전투 중 · 선택한 사신만 강화할 수 있습니다", 66, 745, self.font_small, COLOR_GRAY)
            if state.has_tower(selected):
                tower = state.towers[selected]
                self._text(f"{Tower.display_name(tower['type'])} Lv.{tower['level']}", 66, 778, self.font_med, COLOR_WHITE)
                cost = self.economy.get_upgrade_cost(state, selected)
                buttons.append(Button(pygame.Rect(290, 765, 168, 38), f"강화 {cost} G", "UPGRADE", self.economy.can_upgrade(state, selected)))
            buttons.append(Button(pygame.Rect(1022, 765, 188, 38), f"배속 ×{state.combat_speed:g}", "CYCLE_SPEED"))
        elif state.phase == GamePhase.MOVING_TOWER:
            self._text("사신 이동 · 옮길 빈 돌판을 선택하세요", 66, 752, self.font_med, COLOR_WHITE)
            buttons.append(Button(pygame.Rect(1022, 765, 188, 38), "취소", "CANCEL"))
        elif selected in pending_slots:
            self._text("벽화의 달빛이 선택한 돌판으로 이동 중입니다", 66, 752, self.font_med, COLOR_MOON)
            buttons.extend([
                Button(pygame.Rect(760, 765, 116, 38), "이동", "BEGIN_RELOCATE", self.economy.can_take_preparation_action(state)),
                Button(pygame.Rect(886, 765, 126, 38), "소환 취소", "SELL", self.economy.can_sell(state, selected)),
                Button(pygame.Rect(1022, 765, 188, 38), f"{state.current_stage}번째 웨이브 시작", "START_WAVE"),
            ])
        elif state.has_tower(selected):
            tower = state.towers[selected]
            self._text(f"{Tower.display_name(tower['type'])}  Lv.{tower['level']}", 66, 744, self.font_med, COLOR_WHITE)
            self._text(Tower.from_data(tower).get_stats()["description"], 66, 779, self.font_small, COLOR_GRAY)
            cost = self.economy.get_upgrade_cost(state, selected)
            buttons.extend([
                Button(pygame.Rect(290, 765, 150, 38), f"강화 {cost} G", "UPGRADE", self.economy.can_upgrade(state, selected)),
                Button(pygame.Rect(450, 765, 116, 38), "이동", "BEGIN_RELOCATE", self.economy.can_take_preparation_action(state)),
                Button(pygame.Rect(576, 765, 116, 38), "판매", "SELL", self.economy.can_sell(state, selected)),
                Button(pygame.Rect(1022, 765, 188, 38), f"{state.current_stage}번째 웨이브 시작", "START_WAVE"),
            ])
        else:
            self._text("빈 돌판을 선택해 벽화 속 사신을 소환하세요", 66, 744, self.font_med, COLOR_WHITE)
            self._text("청룡 · 백호 · 주작 · 현무 중 하나가 달빛을 타고 도착합니다", 66, 779, self.font_small, COLOR_GRAY)
            buttons.extend([
                Button(pygame.Rect(570, 765, 222, 38), "랜덤 사신 소환 100 G", "BUY", selected is not None and self.economy.can_buy(state, selected)),
                Button(pygame.Rect(1022, 765, 188, 38), f"{state.current_stage}번째 웨이브 시작", "START_WAVE"),
            ])

        if state.message:
            message = self.font_small.render(state.message, True, COLOR_MOON)
            self.screen.blit(message, message.get_rect(topright=(996, 744)))
        self.buttons.set_buttons(buttons)

    def _render_side_panel(self, state: GameState) -> None:
        panel = pygame.Rect(PANEL_X, 126, PANEL_WIDTH, 630)
        draw_panel(self.screen, panel)
        buttons: List[Button] = []
        y = 154

        if state.phase == GamePhase.WAVE_ACTIVE:
            alive = len([enemy for enemy in state.enemies if enemy.is_alive])
            boss = next((enemy for enemy in state.enemies if enemy.is_boss and enemy.is_alive), None)
            self._text("소동 해결 중", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
            self._text("사신이 범위 내 적을 공격합니다", PANEL_X + 24, y + 34, self.font_small, COLOR_GRAY)
            self._text(f"남은 악귀 {alive}마리", PANEL_X + 24, y + 80, self.font_small, COLOR_WHITE)
            self._text(f"이번 소동 처치 보상 +{state.wave_kill_gold + state.wave_boss_gold} G", PANEL_X + 24, y + 116, self.font_small, COLOR_GOLD)
            selected = state.selected_slot
            if state.has_tower(selected):
                if boss:
                    self._text(f"{boss.name} · HP {int(boss.health)}/{boss.max_health}", PANEL_X + 24, y + 152, self.font_small, COLOR_MOON)
                self._render_tower_information(state.towers[selected], y + 186)
                cost = self.economy.get_upgrade_cost(state, selected)
                buttons.append(Button(pygame.Rect(PANEL_X + 24, 510, 260, 40), f"강화 {cost} G", "UPGRADE", self.economy.can_upgrade(state, selected)))
            elif boss:
                self._text(boss.name, PANEL_X + 24, y + 170, self.font_med, COLOR_MOON)
                self._text(f"보스 악귀 HP {int(boss.health)} / {boss.max_health}", PANEL_X + 24, y + 204, self.font_small, COLOR_RED)
                portrait = self.boss_portraits[boss.name, 130]
                self.screen.blit(portrait, portrait.get_rect(center=(PANEL_X + PANEL_WIDTH // 2, 450)))
                hp_ratio = max(0, boss.health / boss.max_health)
                pygame.draw.rect(self.screen, COLOR_PANEL, (PANEL_X + 24, 542, 260, 10))
                pygame.draw.rect(self.screen, COLOR_PURPLE, (PANEL_X + 24, 542, int(260 * hp_ratio), 10))
            buttons.extend([
                Button(pygame.Rect(PANEL_X + 24, 558, 126, 40), "이동", "BEGIN_RELOCATE", False),
                Button(pygame.Rect(PANEL_X + 158, 558, 126, 40), "판매", "SELL", False),
                Button(pygame.Rect(PANEL_X + 24, 606, 260, 40), "랜덤 사신 소환 100 G", "BUY", False),
            ])
            buttons.append(Button(pygame.Rect(PANEL_X + 24, 672, 260, 42), f"배속 ×{state.combat_speed:g}", "CYCLE_SPEED"))
        elif state.phase == GamePhase.SETTLEMENT:
            self._text("정산 중", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
            self._text("소동 해결 결과를 확인하세요", PANEL_X + 24, y + 34, self.font_small, COLOR_GRAY)
        elif state.phase in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
            self._text("게임 종료", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
        else:
            self._render_management_panel(state, buttons, y)

        if state.message and state.phase != GamePhase.SETTLEMENT:
            self._text(state.message, PANEL_X + 24, 728, self.font_small, COLOR_MOON)
        self.buttons.set_buttons(buttons)

    def _render_tower_information(self, tower: dict, y: int) -> None:
        stats = Tower.from_data(tower).get_stats()
        self._text(f"{Tower.display_name(tower['type'])}  Lv.{tower['level']}", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
        self._text(stats["description"], PANEL_X + 24, y + 34, self.font_small, COLOR_GRAY)
        self._text(f"피해 {stats['damage']:.1f}", PANEL_X + 24, y + 70, self.font_small, COLOR_WHITE)
        self._text(f"공격 간격 {stats['attack_interval']}초", PANEL_X + 24, y + 100, self.font_small, COLOR_WHITE)
        self._text(f"사거리 {stats['range']}칸", PANEL_X + 24, y + 130, self.font_small, COLOR_WHITE)

    def _render_management_panel(self, state: GameState, buttons: List[Button], y: int) -> None:
        selected = state.selected_slot
        if state.phase == GamePhase.MOVING_TOWER:
            self._text("사신 이동", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
            self._text("옮길 빈 슬롯을 선택하세요", PANEL_X + 24, y + 38, self.font_small, COLOR_GRAY)
            buttons.append(Button(pygame.Rect(PANEL_X + 24, 666, 260, 40), "취소", "CANCEL"))
            return
        if state.phase == GamePhase.SELL_CONFIRM and selected is not None and state.has_tower(selected):
            tower = state.towers[selected]
            refund = self.economy.get_sell_refund(state, selected)
            self._text(f"{Tower.display_name(tower['type'])}를 판매할까요?", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
            self._text(f"환급 {refund} G", PANEL_X + 24, y + 40, self.font_small, COLOR_GOLD)
            return

        self._text("사신 소환", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
        self._text("빈 슬롯 선택 후 랜덤 소환", PANEL_X + 24, y + 34, self.font_small, COLOR_GRAY)
        self._text("청룡 · 백호 · 주작 · 현무 각 25%", PANEL_X + 24, y + 66, self.font_small, COLOR_MOON)
        buttons.append(Button(pygame.Rect(PANEL_X + 24, y + 102, 260, 40), "랜덤 사신 소환 100 G", "BUY", selected is not None and self.economy.can_buy(state, selected)))

        if selected is not None and state.has_tower(selected):
            tower = state.towers[selected]
            refund = self.economy.get_sell_refund(state, selected)
            self._render_tower_information(tower, y + 170)
            self._text(f"판매 환급 {refund} G", PANEL_X + 24, y + 330, self.font_small, COLOR_GOLD)
            cost = self.economy.get_upgrade_cost(state, selected)
            buttons.append(Button(pygame.Rect(PANEL_X + 24, y + 370, 260, 40), f"강화 {cost} G", "UPGRADE", self.economy.can_upgrade(state, selected)))
            buttons.append(Button(pygame.Rect(PANEL_X + 24, y + 418, 126, 40), "이동", "BEGIN_RELOCATE", self.economy.can_take_preparation_action(state)))
            buttons.append(Button(pygame.Rect(PANEL_X + 158, y + 418, 126, 40), "판매", "SELL", self.economy.can_sell(state, selected)))

        desc = WaveManager().describe_stage(state.current_stage)
        self._text("다음 소동", PANEL_X + 24, 624, self.font_small, COLOR_GRAY)
        self._text(desc, PANEL_X + 24, 650, self.font_small, COLOR_WHITE)
        buttons.append(Button(pygame.Rect(PANEL_X + 24, 682, 260, 40), f"{state.current_stage}번째 소동 시작", "START_WAVE"))

    def _render_result(self, state: GameState) -> None:
        if state.phase == GamePhase.GAME_OVER:
            title = "소동 해결 실패"
        else:
            title = "결계를 지켜냈어요"
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill(COLOR_OVERLAY)
        self.screen.blit(overlay, (0, 0))

        width, height = 560, 400
        panel = pygame.Rect((SCREEN_WIDTH - width) // 2, (SCREEN_HEIGHT - height) // 2, width, height)
        draw_panel(self.screen, panel)

        title_color = COLOR_RED if state.phase == GamePhase.GAME_OVER else COLOR_MOON
        title_surface = self.font_big.render(title, True, title_color)
        self.screen.blit(title_surface, title_surface.get_rect(center=(panel.centerx, panel.y + 70)))
        draw_title_ornament(self.screen, panel.centerx, panel.y + 100, 200)
        if state.phase == GamePhase.VICTORY:
            lines = [
                (f"{MAX_STAGES}번째 소동까지 모두 해결했어요", self.font_med, COLOR_WHITE),
                (f"남은 결계 {state.life}   ·   보유 골드 {state.gold} G", self.font_med, COLOR_GOLD),
                ("달이 지고, 사신들은 다시 벽화 속으로 잠든다…", self.font_small, COLOR_MOON),
            ]
            for i, (text, font, color) in enumerate(lines):
                surface = font.render(text, True, color)
                self.screen.blit(surface, surface.get_rect(center=(panel.centerx, panel.y + 150 + i * 50)))
        if state.phase == GamePhase.GAME_OVER:
            fail_text = f"{state.current_stage}번째 소동에서 실패했어요"
            fail_surface = self.font_med.render(fail_text, True, COLOR_WHITE)
            self.screen.blit(fail_surface, fail_surface.get_rect(center=(panel.centerx, panel.y + 150)))
            hint_surface = self.font_small.render("이런, 잡귀들을 막아내지 못했다… 다시 결계를 지켜볼까?", True, COLOR_MOON)
            self.screen.blit(hint_surface, hint_surface.get_rect(center=(panel.centerx, panel.y + 205)))

        button_y = panel.bottom - 80
        self.buttons.set_buttons([
            Button(pygame.Rect(panel.centerx - 184, button_y, 174, 46), "다시 도전하기", "RESTART"),
            Button(pygame.Rect(panel.centerx + 10, button_y, 174, 46), "처음으로", "BACK_TO_TITLE"),
        ])

    def _text(self, value: str, x: int, y: int, font: pygame.font.Font, color) -> None:
        self.screen.blit(font.render(value, True, color), (x, y))
