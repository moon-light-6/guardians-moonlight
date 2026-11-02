"""
플레이 화면: 기존 게임 화면(Renderer가 그린 그대로) + AI 행동 패널(아래) + AI 전략 분석(오른쪽, 항상 표시).

전략 분석의 숫자는 모두 시연 중 실제로 실행된 행동 횟수(stats.ActionStats)로만 계산한다.
"""

import math
from pathlib import Path
from typing import Dict, List, Optional

import pygame

from config import MAX_ACTIONS_PER_WAVE, MAX_STAGES, SLOT_COUNT
from display.ui import draw_panel
from game.tower import Tower

from ai_demo import ROOT
from ai_demo.charts import nice_ticks
from ai_demo.controller import Status
from ai_demo.stats import BUILD_KINDS, KIND_LABELS, ActionStats
from ai_demo.theme import (
    BAD, BOTTOM_RECT, CANVAS_SIZE, FRAME, GAME_RECT, GOOD, GRID, HEADER_HEIGHT, HEAT_RAMPS, HIGHLIGHT,
    KIND_COLORS, MOON, MUTED, SIDE_RECT, SURFACE, TEXT, TEXT_2, Fonts, fit_text, format_int, kind_swatch,
    pill, ramp_color, section_title, text,
)

FLOATER_SECONDS = 1.6
LOG_ROW = 25  # 최근 행동 기록 한 줄 높이
GUARDIAN_ORDER = ("LIGHTNING", "ARCHER", "CANNON", "ICE")  # 청룡 · 백호 · 주작 · 현무


def draw_header(canvas, fonts: Fonts, info, controller, screen: str) -> Dict[str, pygame.Rect]:
    """두 화면 공통 상단 바. 탭 Rect를 돌려준다(마우스로 눌러 화면 전환)."""
    pygame.draw.rect(canvas, (12, 16, 34), (0, 0, CANVAS_SIZE[0], HEADER_HEIGHT))
    pygame.draw.line(canvas, FRAME, (0, HEADER_HEIGHT - 1), (CANVAS_SIZE[0], HEADER_HEIGHT - 1), 1)
    cy = HEADER_HEIGHT // 2
    title = text(canvas, fonts(34), "월하사신", (24, cy), MOON, "midleft")
    pygame.draw.line(canvas, FRAME, (title.right + 14, cy - 16), (title.right + 14, cy + 16), 2)
    title = text(canvas, fonts(30), "AI DEMO", (title.right + 28, cy), (134, 182, 239), "midleft")

    tabs = {}
    x = CANVAS_SIZE[0] - 24
    for key, label in (("graphs", "F2  학습 그래프"), ("play", "F1  AI 플레이")):
        active = key == screen
        width = fonts(19).size(label)[0] + 36
        rect = pygame.Rect(x - width, cy - 20, width, 40)
        pygame.draw.rect(canvas, (58, 68, 108) if active else (20, 26, 48), rect, border_radius=9)
        pygame.draw.rect(canvas, MOON if active else (92, 78, 52), rect, 1, border_radius=9)
        text(canvas, fonts(19), label, rect.center, MOON if active else TEXT_2, "center")
        tabs[key] = rect
        x = rect.left - 10

    model = info.model_info
    chips = [[("실험", MUTED), (info.experiment.name, TEXT)]]
    if model is not None:
        chips.append([("모델", MUTED), (model.file_name, TEXT), ("· 최댓값 선택" if info.greedy else "· 샘플링", TEXT_2)])
        if model.steps is not None:
            steps = [("학습 Step", MUTED), (format_int(model.steps), HIGHLIGHT)]
            if model.total_steps and model.total_steps != model.steps:
                steps.append((f"/ 총 {format_int(model.total_steps)}", TEXT_2))
            chips.append(steps)
        else:
            chips.append([("학습 Step", MUTED), ("확인 불가", TEXT_2)])
        if model.clear_rate is not None:
            chips.append([("평가 클리어율", MUTED), (f"{model.clear_rate:.1f}%", HIGHLIGHT),
                          (f"({model.eval_games}판)", TEXT_2)])
        else:
            chips.append([("평가 클리어율", MUTED), ("확인 불가", TEXT_2)])
    else:
        chips.append([("모델", MUTED), ("불러오지 못함", BAD)])
    chips.append([("시드", MUTED), (str(controller.seed), TEXT), (f"· {controller.games_played}번째 판", TEXT_2)])

    x = title.right + 26
    for parts in chips:
        width = sum(fonts(17).size(v)[0] for v, _ in parts) + 28 + 8 * (len(parts) - 1)
        if x + width > tabs["play"].left - 16:
            break  # 창이 좁아 다 못 넣으면 뒤쪽 칩은 생략
        x = pill(canvas, fonts, x, cy, parts, height=36, size=17).right + 8
    return tabs


class PlayView:
    def __init__(self, fonts: Fonts, renderer):
        self.fonts = fonts
        self.renderer = renderer
        self.map = renderer.map
        self.scope = "episode"     # 전략 분석 범위: episode(이번 판) / session(시연 누적)
        self.heat_overlay = False  # H: 게임판 위에 슬롯별 소환 횟수 표시
        self.floaters: List[dict] = []
        self.log_rect: Optional[pygame.Rect] = None  # 최근 행동 기록 영역(그려졌을 때만)
        self.log_scroll = 0  # 위에서부터 가린 픽셀. 0이면 최신 기록이 맨 위
        self._log_count = 0
        self.thumb = self._load_thumbnail((320, 210))

    # ----- 준비 -----

    def _load_thumbnail(self, size):
        """전략 분석 히트맵 바탕: 실제 게임판 그림을 축소하고 어둡게 한 것(슬롯 위치를 그대로 쓰기 위해)."""
        path = Path(ROOT) / "assets" / "backgrounds" / "map_background.png"
        image = pygame.image.load(str(path)).convert()
        image = pygame.transform.smoothscale(image, size)
        shade = pygame.Surface(size, pygame.SRCALPHA)
        shade.fill((8, 12, 26, 170))
        image.blit(shade, (0, 0))
        return image

    def stats_for_scope(self, stats) -> ActionStats:
        return stats.session if self.scope == "session" else stats.episode

    def scope_label(self) -> str:
        return "시연 누적" if self.scope == "session" else "이번 판"

    def slot_pixel(self, slot: int):
        return self.renderer.projection.game_to_pixel(self.map.get_slot_position(slot))

    def scroll_log(self, pos, wheel: int) -> None:
        """마우스가 최근 행동 기록 위에 있을 때만 스크롤한다. 휠 위로 = 최신 쪽."""
        if self.log_rect is not None and self.log_rect.collidepoint(pos):
            self.log_scroll -= wheel * LOG_ROW

    def on_event(self, name: str, payload, now: float) -> None:
        if name == "new_game":
            self.floaters.clear()
        if name != "action" or payload.slot is None:
            return
        record = payload
        name_text = Tower.display_name(record.tower_type) if record.tower_type else ""
        label = {
            "buy": f"소환 · {name_text}",
            "upgrade": f"강화 Lv.{record.level_after}",
            "sell": f"판매 +{record.gold_after - record.gold_before}G",
        }[record.kind]
        self.floaters.append({"slot": record.slot, "text": label, "kind": record.kind, "born": now})

    # ----- 게임판 위 표시(1280x840 게임 화면 좌표) -----

    def draw_game_overlays(self, surface, controller, stats, now: float) -> None:
        if self.heat_overlay:
            self._draw_heat_overlay(surface, self.stats_for_scope(stats))
        decision = controller.pending
        if decision is not None and controller.status in {Status.DECIDING, Status.WAITING_SUMMON}:
            kind = controller.action_kind(decision.action)
            slot = controller.action_slot(decision.action)
            if slot is not None:
                center = self.slot_pixel(slot)
                pulse = 0.5 + 0.5 * math.sin(now * 9)
                color = KIND_COLORS[kind]
                ring = pygame.Rect(0, 0, 70 + 10 * pulse, 36 + 6 * pulse)
                ring.center = (center[0], center[1] + 2)
                pygame.draw.ellipse(surface, color, ring, 3)
                tag = self._tag(f"AI  {KIND_LABELS[kind]}", color)
                surface.blit(tag, tag.get_rect(midbottom=(center[0], center[1] - 54)))
            else:
                waiting = controller.status == Status.WAITING_SUMMON
                label = f"AI 선택 · {controller.state.current_stage}번째 소동 시작" + (" (소환 연출 후)" if waiting else "")
                tag = self._tag(label, KIND_COLORS["start"], size=22)
                surface.blit(tag, tag.get_rect(midbottom=(560, 812)))
        alive = []
        for floater in self.floaters:
            age = now - floater["born"]
            if age >= FLOATER_SECONDS or floater["slot"] not in range(SLOT_COUNT):
                continue
            alive.append(floater)
            center = self.slot_pixel(floater["slot"])
            image = self._tag(floater["text"], KIND_COLORS[floater["kind"]], size=18)
            image.set_alpha(round(255 * min(1.0, (FLOATER_SECONDS - age) / 0.5)))
            surface.blit(image, image.get_rect(midbottom=(center[0], center[1] - 70 - 34 * age)))
        self.floaters = alive

    def _tag(self, label: str, color, size: int = 17) -> pygame.Surface:
        font = self.fonts(size)
        image = font.render(label, True, TEXT)
        box = pygame.Surface((image.get_width() + 24, image.get_height() + 10), pygame.SRCALPHA)
        pygame.draw.rect(box, (10, 14, 30, 225), box.get_rect(), border_radius=8)
        pygame.draw.rect(box, color, box.get_rect(), 2, border_radius=8)
        box.blit(image, (12, 5))
        return box

    def _draw_heat_overlay(self, surface, stats: ActionStats) -> None:
        counts = stats.slot_counts["buy"]
        peak = max(counts) or 1
        layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for slot in range(SLOT_COUNT):
            x, y = self.slot_pixel(slot)
            color = ramp_color(HEAT_RAMPS["buy"], counts[slot] / peak) if counts[slot] else (60, 66, 90)
            pygame.draw.ellipse(layer, (*color, 150), (x - 34, y - 17, 68, 34))
        surface.blit(layer, (0, 0))
        for slot in range(SLOT_COUNT):
            x, y = self.slot_pixel(slot)
            text(surface, self.fonts(17), f"{slot + 1}번 · {counts[slot]}", (x, y), TEXT, "center")
        text(surface, self.fonts(18), f"슬롯별 소환 횟수 ({self.scope_label()}) · H로 끄기",
             (640, 108), MOON, "midtop")

    # ----- 아래: 현재 AI 행동 -----

    def draw_bottom(self, canvas, controller, stats, info, now: float) -> None:
        rect = BOTTOM_RECT
        draw_panel(canvas, rect)
        self.log_rect = None
        if controller.result is not None:
            self._draw_result(canvas, rect, controller, stats, info)
            return
        f = self.fonts
        x, y = rect.x + 26, rect.y + 18
        title = text(canvas, f(24), "현재 AI 행동", (x, y), TEXT)
        status, color = self._status_text(controller, info)
        pill(canvas, f, title.right + 14, y + 15, [(status, color)], height=30, size=16)

        decision = controller.pending or controller.last_decision
        if info.load_error:
            text(canvas, f(20), "AI 정지 · 모델을 불러오지 못했습니다", (x, y + 50), BAD)
            for i, line in enumerate(_wrap(f(16), info.load_error, 500)[:3]):
                text(canvas, f(16), line, (x, y + 84 + i * 22), TEXT_2)
        elif decision is not None:
            kind = controller.action_kind(decision.action)
            if controller.pending is not None:
                label = controller.describe_action(decision.action)
            else:
                label = controller.last_record.detail
            kind_swatch(canvas, kind, pygame.Rect(x, y + 48, 8, 30))
            text(canvas, f(26), fit_text(f(26), label, 500), (x + 18, y + 46), TEXT)
            how = "확률이 가장 큰 행동" if controller.agent.greedy else "정책 확률대로 샘플링"
            text(canvas, f(16), f"선택 확률 {decision.probability * 100:.1f}%  ·  가능한 행동 {decision.valid_count}개 중 {how}",
                 (x, y + 88), TEXT_2)
            if controller.status == Status.WAVE:
                text(canvas, f(16), "전투는 게임 엔진이 자동으로 진행합니다.", (x, y + 122), MOON)
                text(canvas, f(16), "AI는 전투 중 결정하지 않고, 다음 준비 단계에서 다시 행동을 고릅니다.",
                     (x, y + 146), MOON)
            else:
                text(canvas, f(15), "정책 확률 상위", (x, y + 124), MUTED)
                cx = x + 104
                for action, probability in decision.top:
                    chip = f"{_short_action(controller, action)} {probability * 100:.0f}%"
                    if cx + f(15).size(chip)[0] + 28 > rect.x + 556:
                        break  # 다음 칸(최근 행동 기록)을 넘지 않게
                    cx = pill(canvas, f, cx, y + 133, [(chip, TEXT_2)], height=26, size=15).right + 6
        else:
            text(canvas, f(20), "첫 행동을 고르는 중…", (x, y + 56), TEXT_2)

        # 최근 행동 기록
        lx = rect.x + 580
        pygame.draw.line(canvas, (92, 78, 52), (lx - 18, rect.y + 20), (lx - 18, rect.bottom - 20), 1)
        text(canvas, f(20), "최근 행동 기록", (lx, y + 2), TEXT)
        self._draw_log(canvas, stats.recent, pygame.Rect(lx, y + 36, 312, rect.bottom - 12 - (y + 36)))

        # 이번 판 누적
        cx = rect.x + 912
        pygame.draw.line(canvas, (92, 78, 52), (cx - 18, rect.y + 20), (cx - 18, rect.bottom - 20), 1)
        text(canvas, f(20), "이번 판 누적", (cx, y + 2), TEXT)
        for i, kind in enumerate(("buy", "upgrade", "sell", "start")):
            ry = y + 38 + i * 30
            kind_swatch(canvas, kind, pygame.Rect(cx, ry + 4, 12, 12))
            text(canvas, f(18), KIND_LABELS[kind], (cx + 22, ry), TEXT_2)
            text(canvas, f(20), f"{stats.episode.counts[kind]}회", (cx + 214, ry - 1), TEXT, "topright")
        state = controller.state
        text(canvas, f(15), f"결정 {controller.counter['length']}회 · 이번 준비 {state.actions_taken_this_wave}/{MAX_ACTIONS_PER_WAVE}",
             (cx, y + 160), MUTED)

    def _draw_log(self, canvas, records, area: pygame.Rect) -> None:
        """이번 판 전체 행동 기록(최신이 위). 과거를 보는 중에는 새 기록이 와도 보던 위치를 유지한다."""
        f = self.fonts
        count = len(records)
        if count < self._log_count:
            self.log_scroll = 0  # 새 게임
        elif self.log_scroll > 0:
            self.log_scroll += (count - self._log_count) * LOG_ROW  # 위에 끼어든 만큼 내려 보던 줄 고정
        self._log_count = count
        content = count * LOG_ROW
        self.log_scroll = max(0, min(self.log_scroll, content - area.height))
        self.log_rect = area

        previous = canvas.get_clip()
        canvas.set_clip(area)
        first = self.log_scroll // LOG_ROW
        last = min(count, (self.log_scroll + area.height) // LOG_ROW + 1)
        for i in range(first, last):
            record = records[i]
            ry = area.y + i * LOG_ROW - self.log_scroll
            kind_swatch(canvas, record.kind, pygame.Rect(area.x, ry + 5, 10, 10))
            text(canvas, f(15), f"{record.step:>3}", (area.x + 18, ry), MUTED)
            text(canvas, f(16), fit_text(f(16), f"{record.stage}소동 · {record.detail}", 240), (area.x + 52, ry), TEXT_2)
        canvas.set_clip(previous)

        if content > area.height:
            track = pygame.Rect(area.right - 4, area.y + 2, 4, area.height - 4)
            pygame.draw.rect(canvas, (36, 42, 66), track, border_radius=2)
            height = max(18, round(track.height * area.height / content))
            top = track.y + round((track.height - height) * self.log_scroll / (content - area.height))
            pygame.draw.rect(canvas, (128, 116, 86), (track.x, top, track.width, height), border_radius=2)

    def _status_text(self, controller, info):
        speed = f" · 배속 ×{controller.combat_speed:g}"
        if info.load_error:
            return "AI 정지", BAD
        if controller.paused:
            return "일시정지 (Space)", HIGHLIGHT
        status = controller.status
        if status == Status.WAVE:
            return f"전투 진행 중 · 게임 엔진 자동 전투{speed}", (134, 182, 239)
        if status == Status.SETTLEMENT:
            return f"정산 · 곧 다음 준비 단계{speed}", MOON
        if status == Status.WAITING_SUMMON:
            return f"준비 단계 · 소환 연출이 끝나면 소동 시작{speed}", HIGHLIGHT
        if status == Status.FINISHED:
            return "게임 종료", MOON
        return f"준비 단계 · AI가 행동 선택 중{speed}", GOOD

    def _draw_result(self, canvas, rect, controller, stats, info) -> None:
        f = self.fonts
        result = controller.result
        x, y = rect.x + 26, rect.y + 18
        text(canvas, f(24), "게임 결과", (x, y), TEXT)
        if result.get("error"):
            headline, color = f"진행 오류 · {result['error']}", BAD
        elif result["won"]:
            headline, color = f"{MAX_STAGES}소동 클리어 · 결계 수호 성공", GOOD
        else:
            headline, color = f"{result['reached']}번째 소동에서 실패", BAD
        text(canvas, f(28), fit_text(f(28), headline, 520), (x, y + 40), color)
        rows = [("도달 소동", f"{result['reached']} / {MAX_STAGES}"), ("잔여 결계", str(result["life"])),
                ("잔여 골드", f"{result['gold']} G"), ("총 결정", f"{result['length']}회")]
        for i, (label, value) in enumerate(rows):
            rx, ry = x + (i % 2) * 260, y + 92 + (i // 2) * 34
            text(canvas, f(17), label, (rx, ry), MUTED)
            text(canvas, f(20), value, (rx + 230, ry - 2), TEXT, "topright")

        lx = rect.x + 580
        pygame.draw.line(canvas, (92, 78, 52), (lx - 18, rect.y + 20), (lx - 18, rect.bottom - 20), 1)
        text(canvas, f(20), "행동 횟수", (lx, y + 2), TEXT)
        for i, kind in enumerate(("buy", "upgrade", "sell", "start")):
            ry = y + 36 + i * 28
            kind_swatch(canvas, kind, pygame.Rect(lx, ry + 4, 12, 12))
            text(canvas, f(18), KIND_LABELS[kind], (lx + 22, ry), TEXT_2)
            text(canvas, f(20), f"{result[kind]}회", (lx + 200, ry - 1), TEXT, "topright")
        match = info.recorded_match
        if match is not None:
            label = "기록된 최종 평가(final_eval.csv)와 결과 일치" if match else "기록된 최종 평가와 결과가 다름"
            text(canvas, f(15), label, (lx, y + 156), GOOD if match else BAD)

        cx = rect.x + 912
        pygame.draw.line(canvas, (92, 78, 52), (cx - 18, rect.y + 20), (cx - 18, rect.bottom - 20), 1)
        text(canvas, f(20), "이번 시연 기록", (cx, y + 2), TEXT)
        for i, past in enumerate(stats.results[-4:][::-1]):
            outcome = "클리어" if past["won"] else f"{past['reached']}소동 실패"
            text(canvas, f(15), fit_text(f(15), f"{past['game']}판 · 시드 {past['seed']} · {outcome}", 220),
                 (cx, y + 34 + i * 22), TEXT_2)
        hint = "N 다음 시드  ·  R 같은 시드 다시"
        if info.auto_next_left is not None:
            hint = f"{math.ceil(info.auto_next_left)}초 뒤 다음 시드 · " + hint
        text(canvas, f(15), hint, (cx, y + 158), MOON)

    # ----- 오른쪽: AI 전략 분석 -----

    def draw_side(self, canvas, stats) -> None:
        # 행동이 실행될 때만 내용이 바뀌므로, 그때만 다시 그리고 나머지 프레임은 저장해 둔 그림을 쓴다.
        data = self.stats_for_scope(stats)
        key = (self.scope, id(data), sum(data.counts.values()))
        if getattr(self, "_side_key", None) != key:
            self._side_key = key
            self._side_cache = pygame.Surface(SIDE_RECT.inflate(8, 8).size)
            self._side_cache.fill(canvas.get_at(SIDE_RECT.inflate(8, 8).topleft))
            offset = SIDE_RECT.inflate(8, 8).topleft
            local = pygame.Surface(CANVAS_SIZE)  # 좌표를 그대로 쓰기 위해 같은 크기에 그린 뒤 잘라 온다
            local.fill(self._side_cache.get_at((0, 0)))
            self._render_side(local, data)
            self._side_cache.blit(local, (0, 0), SIDE_RECT.inflate(8, 8))
            self._side_offset = offset
        canvas.blit(self._side_cache, self._side_offset)

    def _render_side(self, canvas, data: ActionStats) -> None:
        rect = SIDE_RECT
        draw_panel(canvas, rect)
        f = self.fonts
        x, y = rect.x + 28, rect.y + 20
        text(canvas, f(30), "AI 전략 분석", (x, y), MOON)
        parts = [(self.scope_label(), HIGHLIGHT), ("· T로 전환", MUTED)]
        width = sum(f(16).size(v)[0] for v, _ in parts) + 36
        pill(canvas, f, rect.right - 28 - width, y + 18, parts, height=32, size=16)
        text(canvas, f(15), "시연 중 실제로 실행된 행동 횟수로만 계산합니다", (x, y + 42), MUTED)

        y = self._draw_ratio(canvas, data, x, y + 76, rect.width - 56)
        y = self._draw_heatmaps(canvas, data, x, y + 14)
        y = self._draw_stage_bars(canvas, data, x, y + 14, rect.width - 56)
        self._draw_outcomes(canvas, data, x, y + 12, rect.width - 56)

    def _draw_ratio(self, canvas, data: ActionStats, x, y, width) -> int:
        f = self.fonts
        y = section_title(canvas, f, "행동 선택 비율", x, y, "소환 · 강화 · 판매")
        center, outer, inner = (x + 110, y + 84), 80, 50
        total = data.build_total
        if total == 0:
            pygame.draw.circle(canvas, (40, 46, 66), center, outer, outer - inner)
        else:
            start = -math.pi / 2
            for kind in BUILD_KINDS:
                span = 2 * math.pi * data.counts[kind] / total
                if span > 0:
                    _ring_segment(canvas, center, outer, inner, start, start + span, KIND_COLORS[kind])
                    start += span
            if sum(1 for kind in BUILD_KINDS if data.counts[kind]) > 1:
                angle = -math.pi / 2
                for kind in BUILD_KINDS:  # 조각 사이 2px 간격
                    angle += 2 * math.pi * data.counts[kind] / total
                    pygame.draw.line(canvas, SURFACE, _polar(center, inner - 1, angle), _polar(center, outer + 1, angle), 3)
        text(canvas, f(16), "총 행동", (center[0], center[1] - 22), TEXT_2, "center")
        text(canvas, f(26), f"{format_int(total)}회", (center[0], center[1] + 8), TEXT, "center")

        lx = x + 250
        for i, kind in enumerate(BUILD_KINDS):
            ry = y + 14 + i * 42
            kind_swatch(canvas, kind, pygame.Rect(lx, ry + 3, 22, 22))
            text(canvas, f(21), KIND_LABELS[kind], (lx + 36, ry), TEXT)
            text(canvas, f(18), f"{data.counts[kind]}회", (lx + 220, ry + 2), TEXT_2, "topright")
            text(canvas, f(22), f"{data.ratio(kind) * 100:.1f}%", (lx + 380, ry), TEXT, "topright")
            if i < 2:
                pygame.draw.line(canvas, GRID, (lx, ry + 34), (lx + 380, ry + 34), 1)
        text(canvas, f(15), f"소동 시작 {data.counts['start']}회는 비율 계산에서 제외", (lx, y + 140), MUTED)
        return y + 172

    def _draw_heatmaps(self, canvas, data: ActionStats, x, y) -> int:
        f = self.fonts
        y = section_title(canvas, f, "슬롯별 선택 빈도", x, y, "실제 게임판 슬롯 위치")
        thumb_w, thumb_h = self.thumb.get_size()
        scale = thumb_w / self.map.source_width
        for i, kind in enumerate(("buy", "upgrade")):
            ox = x + i * (thumb_w + 16)
            counts = data.slot_counts[kind]
            peak = max(counts)
            text(canvas, f(18), KIND_LABELS[kind], (ox, y), TEXT)
            text(canvas, f(15), f"최다 {peak}회" if peak else "아직 없음", (ox + thumb_w, y + 2), MUTED, "topright")
            area = pygame.Rect(ox, y + 26, thumb_w, thumb_h)
            canvas.blit(self.thumb, area)
            pygame.draw.rect(canvas, (92, 78, 52), area, 1)
            for slot in range(SLOT_COUNT):
                sx, sy = self.map.get_slot_source_position(slot)
                center = (round(area.x + sx * scale), round(area.y + sy * scale))
                if counts[slot]:
                    color = ramp_color(HEAT_RAMPS[kind], 0.15 + 0.85 * counts[slot] / peak)
                    pygame.draw.circle(canvas, SURFACE, center, 14)
                    pygame.draw.circle(canvas, color, center, 12)
                    label_color = (12, 16, 30) if counts[slot] / peak > 0.55 else TEXT
                else:
                    pygame.draw.circle(canvas, (70, 76, 100), center, 12, 1)
                    label_color = MUTED
                text(canvas, f(13), str(slot + 1), center, label_color, "center")
            # 색 막대(낮음 -> 높음)
            bar = pygame.Rect(ox, area.bottom + 10, thumb_w, 8)
            for px in range(bar.width):
                pygame.draw.line(canvas, ramp_color(HEAT_RAMPS[kind], 0.15 + 0.85 * px / bar.width),
                                 (bar.x + px, bar.y), (bar.x + px, bar.bottom))
            text(canvas, f(13), "1회", (bar.x, bar.bottom + 3), MUTED)
            text(canvas, f(13), f"{peak}회" if peak else "-", (bar.right, bar.bottom + 3), MUTED, "topright")
        text(canvas, f(14), "숫자 = 슬롯 번호(게임판 디버그 표시와 같음) · 빈 원 = 0회", (x, y + 26 + thumb_h + 40), MUTED)
        return y + 26 + thumb_h + 62

    def _draw_stage_bars(self, canvas, data: ActionStats, x, y, width) -> int:
        f = self.fonts
        y = section_title(canvas, f, "소동별 행동 구성", x, y, "각 소동 준비 단계에서 고른 소환·강화·판매")
        plot = pygame.Rect(x + 34, y + 8, width - 40, 104)
        totals = [sum(data.stage_counts[s][k] for k in BUILD_KINDS) for s in range(1, MAX_STAGES + 1)]
        ticks = nice_ticks(0, max(max(totals), 4), 3)
        top = ticks[-1]
        for tick in ticks:
            ty = plot.bottom - tick / top * plot.height
            pygame.draw.line(canvas, GRID, (plot.left, ty), (plot.right, ty), 1)
            text(canvas, f(13), f"{tick:g}", (plot.left - 6, ty), MUTED, "midright")
        slot_w = plot.width / MAX_STAGES
        for stage in range(1, MAX_STAGES + 1):
            bx = plot.left + (stage - 1) * slot_w + 2
            bw = max(3, slot_w - 5)
            base = plot.bottom
            for kind in BUILD_KINDS:
                count = data.stage_counts[stage][kind]
                if not count:
                    continue
                height = count / top * plot.height
                pygame.draw.rect(canvas, KIND_COLORS[kind], (bx, base - height + 1, bw, height - 1))
                base -= height
            if stage in (1, 5, 10, 15, 20, 25, 30):
                text(canvas, f(13), str(stage), (bx + bw / 2, plot.bottom + 4), MUTED, "midtop")
        lx = plot.left
        for kind in BUILD_KINDS:
            kind_swatch(canvas, kind, pygame.Rect(lx, plot.bottom + 26, 10, 10))
            lx = text(canvas, f(14), KIND_LABELS[kind], (lx + 15, plot.bottom + 23), TEXT_2).right + 16
        text(canvas, f(14), "소동", (plot.right, plot.bottom + 23), MUTED, "topright")
        return plot.bottom + 46

    def _draw_outcomes(self, canvas, data: ActionStats, x, y, width) -> None:
        f = self.fonts
        text(canvas, f(17), "강화 후 레벨", (x, y), TEXT)
        cx = x + 130
        for level in range(2, 6):
            cx = text(canvas, f(16), f"Lv.{level} {data.upgrade_levels[level]}회", (cx, y + 1), TEXT_2).right + 18
        text(canvas, f(17), "소환된 사신", (x, y + 30), TEXT)
        cx = x + 130
        for kind in GUARDIAN_ORDER:
            cx = text(canvas, f(16), f"{Tower.display_name(kind)} {data.summon_types[kind]}", (cx, y + 31), TEXT_2).right + 18
        text(canvas, f(14), "AI는 소환할 슬롯만 고르고 사신 종류는 게임 난수로 정해집니다", (x, y + 58), MUTED)


def _polar(center, radius, angle):
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))


def _ring_segment(surface, center, outer, inner, start, end, color) -> None:
    steps = max(2, int((end - start) / (math.pi / 90)))
    points = [_polar(center, outer, start + (end - start) * i / steps) for i in range(steps + 1)]
    points += [_polar(center, inner, end - (end - start) * i / steps) for i in range(steps + 1)]
    pygame.draw.polygon(surface, color, points)


def _short_action(controller, action: int) -> str:
    kind = controller.action_kind(action)
    if kind == "start":
        return "소동 시작"
    return f"슬롯{controller.action_slot(action) + 1} {KIND_LABELS[kind]}"


def _wrap(font, value: str, width: int) -> List[str]:
    lines, line = [], ""
    for char in value:
        if font.size(line + char)[0] > width:
            lines.append(line)
            line = ""
        line += char
    return lines + ([line] if line else [])
