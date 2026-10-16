
import math
from pathlib import Path
from typing import List

import pygame

from config import (
    CELL_SIZE,
    COLOR_BLACK,
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GOLD,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_MINT,
    COLOR_MOON,
    COLOR_PANEL,
    COLOR_PANEL_DARK,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_WHITE,
    GRID_ORIGIN,
    PANEL_WIDTH,
    PANEL_X,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from display.ui import Button, ButtonLayer, draw_panel
from display.sprite_animation import TowerSpriteAnimator
from display.effect_animation import AttackEffectAnimator
from game.economy import Economy
from game.map import GameMap
from game.state import GamePhase, GameState
from game.tower import Tower
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
        self.boss_portraits = self._load_boss_portraits()
        self.tower_animator = TowerSpriteAnimator()
        self.effect_animator = AttackEffectAnimator()

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

    def _font(self, size: int) -> pygame.font.Font:
        return pygame.font.SysFont("malgungothic,arial", size)

    def render(self, state: GameState) -> None:
        self.screen.fill(COLOR_BLACK)
        self._draw_moonlit_background()
        if state.phase == GamePhase.TITLE:
            self._render_title()
        elif state.phase == GamePhase.HELP:
            self._render_help()
        elif state.phase in {GamePhase.GAME_OVER, GamePhase.VICTORY}:
            self._render_result(state)
        else:
            self._render_game(state)

    def _draw_moonlit_background(self) -> None:
        pygame.draw.circle(self.screen, COLOR_MOON, (1000, 88), 38)
        for x in range(0, SCREEN_WIDTH, 80):
            h = 40 + (x * 7) % 95
            pygame.draw.rect(self.screen, (13, 19, 34), (x, 92 - h // 2, 46, h))

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

    def _render_help(self) -> None:
        draw_panel(self.screen, pygame.Rect(310, 180, 660, 440))
        self._text("게임 방법", 360, 220, self.font_big, COLOR_WHITE)
        lines = [
            "01 빈 슬롯 선택: 100G로 사신 1종을 랜덤 소환합니다.",
            "02 사신 관리: 준비 단계에서 강화, 이동, 판매합니다.",
            "03 웨이브 시작: 악귀는 고정 경로, 사신은 자동 공격합니다.",
            "04 결계 수호: 30웨이브까지 방어하면 승리합니다.",
        ]
        for i, line in enumerate(lines):
            self._text(line, 360, 290 + i * 54, self.font_med, COLOR_WHITE)
        self.buttons.set_buttons([Button(pygame.Rect(520, 540, 240, 46), "알겠어요", "BACK_TO_TITLE")])
        self.buttons.render(self.screen, self.font_med)

    def _render_game(self, state: GameState) -> None:
        self._render_hud(state)
        self._render_board(state)
        self._render_side_panel(state)
        if state.phase == GamePhase.SELL_CONFIRM:
            self._render_sell_popup(state)
        self.buttons.render(self.screen, self.font_small)

    def _render_sell_popup(self, state: GameState) -> None:
        selected = state.pending_sell_slot
        if not state.has_tower(selected):
            return
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
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
        phase = "전투" if state.phase == GamePhase.WAVE_ACTIVE else "준비"
        if state.phase == GamePhase.SETTLEMENT:
            phase = "정산"
        self._text(f"웨이브 {state.current_stage:02d} / 30", 250, 46, self.font_med, COLOR_WHITE)
        self._text(f"결계 {state.life}", 430, 46, self.font_med, COLOR_MINT)
        self._text(f"{state.gold} G", 548, 46, self.font_med, COLOR_GOLD)
        self._text(phase, 680, 46, self.font_med, COLOR_CYAN)
        self._text(f"준비 행동 {state.actions_taken_this_wave} / 20", 760, 46, self.font_small, COLOR_GRAY)

    def _render_board(self, state: GameState) -> None:
        board = pygame.Rect(GRID_ORIGIN[0], GRID_ORIGIN[1], 20 * CELL_SIZE, 15 * CELL_SIZE)
        pygame.draw.rect(self.screen, (12, 19, 34), board, border_radius=10)
        for x in range(21):
            px = GRID_ORIGIN[0] + x * CELL_SIZE
            pygame.draw.line(self.screen, (28, 41, 66), (px, GRID_ORIGIN[1]), (px, GRID_ORIGIN[1] + 15 * CELL_SIZE))
        for y in range(16):
            py = GRID_ORIGIN[1] + y * CELL_SIZE
            pygame.draw.line(self.screen, (28, 41, 66), (GRID_ORIGIN[0], py), (GRID_ORIGIN[0] + 20 * CELL_SIZE, py))

        for cell in self.map.get_path():
            rect = pygame.Rect(GRID_ORIGIN[0] + cell[0] * CELL_SIZE + 3, GRID_ORIGIN[1] + cell[1] * CELL_SIZE + 3, CELL_SIZE - 6, CELL_SIZE - 6)
            pygame.draw.rect(self.screen, (48, 55, 78), rect, border_radius=8)

        for label, cell, color in (
            ("S", self.map.get_start_position(), COLOR_MINT),
            ("E", self.map.get_base_position(), COLOR_RED),
        ):
            center = self.map.grid_to_pixel(cell)
            self._text(label, center[0] - 12, center[1] - 13, self.font_med, color)

        # 현무의 연속 장판 애니메이션을 유닛 아래에 한 번만 표시합니다.
        for effect in state.effects:
            if effect["kind"] == "slow_field" and effect["age"] < effect["ttl"] - 1e-9:
                self._draw_effect(effect)

        for slot_id, bounds in self.map.slots.items():
            pos = self.map.grid_to_pixel(self.map.get_slot_position(slot_id))
            occupied = state.has_tower(slot_id)
            selected = state.selected_slot == slot_id
            moving = state.phase == GamePhase.MOVING_TOWER and state.is_slot_empty(slot_id)
            color = COLOR_MINT if moving else (COLOR_GOLD if selected else (85, 100, 131))
            pygame.draw.circle(self.screen, color, pos, 18, 3)
            if not occupied:
                self._text("+", pos[0] - 6, pos[1] - 15, self.font_med, color)

        if state.selected_slot is not None and state.has_tower(state.selected_slot):
            tower_data = state.towers[state.selected_slot]
            stats = Tower.from_data(tower_data).get_stats()
            center = self.map.grid_to_pixel(self.map.get_slot_position(state.selected_slot))
            pygame.draw.circle(self.screen, (97, 167, 213), center, int(stats["range"] * CELL_SIZE), 1)

        for slot_id, tower_data in state.towers.items():
            self._draw_tower(
                slot_id,
                tower_data,
                state.effects,
            )
        for enemy in state.enemies:
            self._draw_enemy(enemy)
        for effect in state.effects:
            if effect["kind"] != "slow_field":
                self._draw_effect(effect)

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
            midtop=(pos[0], pos[1] + 23)
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

    def _draw_enemy(self, enemy) -> None:
        pos = self.map.grid_to_pixel(enemy.get_current_position())
        if enemy.is_boss:
            radius = 30
            portrait = self.boss_portraits[enemy.name, 60]
            self.screen.blit(portrait, portrait.get_rect(center=pos))
        elif enemy.enemy_type.name == "FAST":
            color = (154, 86, 183)
            radius = 11
        elif enemy.enemy_type.name == "TANK":
            color = (69, 54, 92)
            radius = 15
        else:
            color = COLOR_PURPLE
            radius = 12
        if not enemy.is_boss:
            pygame.draw.circle(self.screen, color, pos, radius)
            pygame.draw.arc(self.screen, COLOR_BLACK, (pos[0] - radius, pos[1] - radius - 8, radius * 2, 14), math.pi, math.tau, 2)
        hp_ratio = max(0, enemy.health / enemy.max_health)
        pygame.draw.rect(self.screen, COLOR_RED, (pos[0] - 18, pos[1] - radius - 14, 36, 4))
        pygame.draw.rect(self.screen, COLOR_GREEN, (pos[0] - 18, pos[1] - radius - 14, int(36 * hp_ratio), 4))

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

    def _render_side_panel(self, state: GameState) -> None:
        panel = pygame.Rect(PANEL_X, 126, PANEL_WIDTH, 630)
        draw_panel(self.screen, panel)
        buttons: List[Button] = []
        y = 154

        if state.phase == GamePhase.SETTLEMENT:
            result = state.wave_result
            self._text(f"{result.stage}번째 웨이브 방어 성공", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
            if result.boss_name:
                boss_result = "처치 성공" if result.boss_kills else "결계 도달"
                self._text(f"{result.boss_name} · {boss_result}", PANEL_X + 24, y + 34, self.font_small, COLOR_MOON)
            rows = [
                (f"일반 적 처치 {result.normal_kills}마리", f"{result.kill_gold} G"),
                (f"보스 처치 {result.boss_kills}마리", f"{result.boss_gold} G"),
                ("웨이브 클리어", f"{result.clear_gold} G"),
                ("총 획득", f"{result.total_gold} G"),
                ("결계 변화", f"{result.life_before} -> {result.life_after}"),
            ]
            for i, (label, value) in enumerate(rows):
                self._text(label, PANEL_X + 24, y + 90 + i * 38, self.font_small, COLOR_GRAY)
                value_x = PANEL_X + PANEL_WIDTH - 24 - self.font_small.size(value)[0]
                self._text(value, value_x, y + 90 + i * 38, self.font_small, COLOR_GOLD)
            label = "최종 승리 확인" if state.current_stage == 30 else "다음 준비 단계로"
            buttons.append(Button(pygame.Rect(PANEL_X + 24, 672, 260, 42), label, "CONTINUE"))
        elif state.phase == GamePhase.WAVE_ACTIVE:
            alive = len([enemy for enemy in state.enemies if enemy.is_alive])
            boss = next((enemy for enemy in state.enemies if enemy.is_boss and enemy.is_alive), None)
            self._text("자동 전투 중", PANEL_X + 24, y, self.font_med, COLOR_WHITE)
            self._text("사신이 범위 내 적을 공격합니다", PANEL_X + 24, y + 34, self.font_small, COLOR_GRAY)
            self._text(f"화면의 악귀 {alive}마리", PANEL_X + 24, y + 80, self.font_small, COLOR_WHITE)
            self._text(f"이번 전투 처치 보상 +{state.wave_kill_gold + state.wave_boss_gold} G", PANEL_X + 24, y + 116, self.font_small, COLOR_GOLD)
            selected = state.selected_slot
            if state.has_tower(selected):
                if boss:
                    self._text(f"{boss.name} · HP {int(boss.health)}/{boss.max_health}", PANEL_X + 24, y + 152, self.font_small, COLOR_MOON)
                self._render_tower_information(state.towers[selected], y + 186)
                cost = self.economy.get_upgrade_cost(state, selected)
                buttons.append(Button(pygame.Rect(PANEL_X + 24, 510, 260, 40), f"강화 {cost} G", "UPGRADE", self.economy.can_upgrade(state, selected)))
            elif boss:
                self._text(boss.name, PANEL_X + 24, y + 170, self.font_med, COLOR_MOON)
                self._text(f"보스 HP {int(boss.health)} / {boss.max_health}", PANEL_X + 24, y + 204, self.font_small, COLOR_RED)
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
        else:
            self._render_management_panel(state, buttons, y)

        if state.message:
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
        self._text("다음 웨이브", PANEL_X + 24, 624, self.font_small, COLOR_GRAY)
        self._text(desc, PANEL_X + 24, 650, self.font_small, COLOR_WHITE)
        buttons.append(Button(pygame.Rect(PANEL_X + 24, 682, 260, 40), f"{state.current_stage}번째 웨이브 시작", "START_WAVE"))

    def _render_result(self, state: GameState) -> None:
        if state.phase == GamePhase.GAME_OVER:
            title = "결계가 무너졌어요"
            result = "패배"
        else:
            title = "도시를 지켜냈어요"
            result = "승리"
        self._text(title, 470, 270, self.font_title, COLOR_WHITE)
        self._text(result, 520, 340, self.font_big, COLOR_MOON)
        self._text(f"남은 결계 {state.life}", 550, 402, self.font_med, COLOR_MINT)
        self.buttons.set_buttons([
            Button(pygame.Rect(500, 492, 130, 44), "다시 시작", "RESTART"),
            Button(pygame.Rect(650, 492, 130, 44), "타이틀로", "BACK_TO_TITLE"),
        ])
        self.buttons.render(self.screen, self.font_med)

    def _text(self, value: str, x: int, y: int, font: pygame.font.Font, color) -> None:
        self.screen.blit(font.render(value, True, color), (x, y))
