"""
학습 그래프 화면. results/<실험>/의 CSV를 그대로 읽어 그리고(G로 scripts/ppo.py가 저장한 원본 PNG 보기),
CSV가 없는 항목은 '데이터 없음'으로만 표시한다. 시연 중 행동 데이터는 이 화면에 쓰지 않는다.
"""

from typing import Dict, Optional

import pygame

from config import MAX_STAGES
from display.ui import draw_panel

from ai_demo.charts import Plot, moving_average, nice_ticks
from ai_demo.experiment import Experiment
from ai_demo.theme import (
    CANVAS_SIZE, HEADER_HEIGHT, HIGHLIGHT, LINE_MAIN, LINE_RAW, MOON, MUTED, TEXT, TEXT_2,
    Fonts, fit_text, format_int, pill, section_title, text,
)

MOVING_AVERAGE = 20  # scripts/ppo.py의 MOVING_AVERAGE(이동평균 판 수)와 같게
RANDOM_POLICY = "무작위 정책"
CONTENT = pygame.Rect(0, HEADER_HEIGHT, CANVAS_SIZE[0], CANVAS_SIZE[1] - HEADER_HEIGHT)


class GraphView:
    def __init__(self, fonts: Fonts, experiment: Experiment, model_info):
        self.fonts = fonts
        self.experiment = experiment
        self.model_info = model_info
        self.mode = "charts"  # charts / png
        self.png_index = 0
        self._charts: Optional[pygame.Surface] = None
        self._png_cache: Dict[int, pygame.Surface] = {}

    def toggle_mode(self) -> None:
        self.mode = "png" if self.mode == "charts" else "charts"

    def turn_page(self, step: int) -> None:
        if self.experiment.pngs:
            self.png_index = (self.png_index + step) % len(self.experiment.pngs)

    def draw(self, canvas) -> None:
        if self.mode == "png":
            self._draw_png(canvas)
            return
        if self._charts is None:
            # 학습 기록은 바뀌지 않으므로 처음 한 번만 그려 둔다.
            self._charts = pygame.Surface(CONTENT.size)
            self._charts.fill((9, 12, 26))
            self._render_charts(self._charts)
        canvas.blit(self._charts, CONTENT)

    # ----- CSV 차트 -----

    def _render_charts(self, surface) -> None:
        f = self.fonts
        exp = self.experiment
        text(surface, f(30), "PPO 학습 결과", (28, 14), MOON)
        text(surface, f(17), f"학습 기록 · results/{exp.name}/ 의 CSV를 그대로 사용 (시연 중 행동 데이터와 별개)",
             (240, 24), TEXT_2)
        pill(surface, f, CANVAS_SIZE[0] - 330, 32, [("G", HIGHLIGHT), ("원본 PNG 그래프 보기", TEXT_2)], size=17)

        self._render_cards(surface, pygame.Rect(24, 62, CANVAS_SIZE[0] - 48, 112))
        top, gap = 190, 16
        width = (CANVAS_SIZE[0] - 48 - gap) // 2
        height = (CONTENT.height - top - 16 - gap) // 2
        cells = [pygame.Rect(24 + (i % 2) * (width + gap), top + (i // 2) * (height + gap), width, height)
                 for i in range(4)]
        self._chart_reward(surface, cells[0])
        self._chart_reached(surface, cells[1])
        self._chart_clear_rate(surface, cells[2])
        self._chart_stability(surface, cells[3])

    def _render_cards(self, surface, rect) -> None:
        exp = self.experiment
        f = self.fonts
        best = exp.best_record()
        final_rows = exp.final_policy_rows()
        random_rows = [r for r in exp.final_eval or [] if r.get("policy") == RANDOM_POLICY]

        def rate(rows):
            return f"{sum(bool(r['won']) for r in rows) / len(rows) * 100:.1f}%" if rows else "데이터 없음"

        def reached(rows):
            return f"{sum(r['reached'] for r in rows) / len(rows):.1f}" if rows else "데이터 없음"

        cards = [
            ("총 학습 Step", format_int(exp.total_steps) if exp.total_steps is not None else "데이터 없음", "updates.csv"),
            ("학습 판 수", format_int(len(exp.episodes)) if exp.episodes else "데이터 없음", "episodes.csv"),
            ("정기 평가 최고 클리어율",
             f"{best['clear_rate']:.1f}%" if best else "확인 불가",
             f"ppo_best.pt · {format_int(best['timesteps'])} Step" if best else "checkpoint.pt와 CSV 불일치/없음"),
            ("최종 평가 클리어율", rate(final_rows),
             f"ppo_policy.pt · 고정 시드 {len(final_rows)}판" if final_rows else "final_eval.csv"),
            ("무작위 정책 클리어율", rate(random_rows), f"같은 시드 {len(random_rows)}판" if random_rows else "final_eval.csv"),
            ("최종 평가 평균 도달 소동", reached(final_rows),
             f"무작위 정책 {reached(random_rows)}" if random_rows else "final_eval.csv"),
        ]
        gap = 12
        width = (rect.width - gap * (len(cards) - 1)) // len(cards)
        for i, (label, value, note) in enumerate(cards):
            card = pygame.Rect(rect.x + i * (width + gap), rect.y, width, rect.height)
            draw_panel(surface, card)
            text(surface, f(16), label, (card.x + 20, card.y + 16), MUTED)
            highlight = i in (2, 3) and value.endswith("%")
            text(surface, f(32), value, (card.x + 20, card.y + 40), HIGHLIGHT if highlight else TEXT)
            text(surface, f(14), fit_text(f(14), note, width - 40), (card.x + 20, card.y + 82), TEXT_2)

    def _frame(self, surface, rect, title, note, source) -> pygame.Rect:
        draw_panel(surface, rect)
        section_title(surface, self.fonts, title, rect.x + 22, rect.y + 16, note)
        text(surface, self.fonts(14), f"출처: {source}", (rect.right - 22, rect.y + 22), MUTED, "topright")
        return pygame.Rect(rect.x + 78, rect.y + 64, rect.width - 110, rect.height - 118)

    def _missing(self, surface, plot_rect, name) -> None:
        text(surface, self.fonts(22), f"데이터 없음 · {name}", plot_rect.center, TEXT_2, "center")

    def _legend(self, surface, x, y, items) -> None:
        for label, color, thick in items:
            pygame.draw.line(surface, color, (x, y + 9), (x + 26, y + 9), thick)
            x = text(surface, self.fonts(15), label, (x + 34, y), TEXT_2).right + 22

    def _episode_chart(self, surface, rect, key, title, note, y_range=None):
        plot_rect = self._frame(surface, rect, title, note, "episodes.csv")
        rows = self.experiment.episodes
        if not rows or key not in rows[0]:
            self._missing(surface, plot_rect, "episodes.csv")
            return
        xs = [r["episode"] for r in rows]
        ys = [float(r[key]) for r in rows]
        average = moving_average(ys, MOVING_AVERAGE)
        low, high = y_range or (min(ys), max(ys))
        if y_range is None:
            pad = (high - low) * 0.05 or 1
            low, high = low - pad, high + pad
        ticks = nice_ticks(low, high, 4)
        plot = Plot(surface, plot_rect, self.fonts, (xs[0], xs[-1]), (min(low, ticks[0]), max(high, ticks[-1])),
                    y_ticks=ticks, y_format=lambda v: f"{v:g}")
        plot.draw_axes("Episode")
        plot.envelope(xs, ys, LINE_RAW, alpha=0.28)
        plot.sampled_line(xs, average, LINE_MAIN, 2)
        plot.label(xs[-1], average[-1], f"{average[-1]:.2f}" if y_range is None else f"{average[-1]:.1f}",
                   TEXT, offset=(-24, -10))
        self._legend(surface, plot_rect.x, rect.bottom - 30,
                     [("판별 값", LINE_RAW, 1), (f"최근 {MOVING_AVERAGE}판 이동평균", LINE_MAIN, 3)])

    def _chart_reward(self, surface, rect) -> None:
        reward = (self.experiment.config or {}).get("reward", {})
        note = f"보상 설정 {reward.get('profile', '?')} · scale {reward.get('scale', '?')}" if reward else ""
        self._episode_chart(surface, rect, "reward", "Episode Reward (판별 누적)", note)

    def _chart_reached(self, surface, rect) -> None:
        self._episode_chart(surface, rect, "reached", "Episode별 도달 소동", "학습 중 끝난 판",
                            y_range=(0, MAX_STAGES))

    def _chart_clear_rate(self, surface, rect) -> None:
        exp = self.experiment
        games = exp.eval_games
        note = f"고정 시드 {games}판 평가" if games else ""
        plot_rect = self._frame(surface, rect, "학습 Step별 클리어율", note, "evaluations.csv")
        rows = exp.evaluations
        if not rows:
            self._missing(surface, plot_rect, "evaluations.csv")
            return
        xs = [r["timesteps"] for r in rows]
        ys = [float(r["clear_rate"]) for r in rows]
        plot = Plot(surface, plot_rect, self.fonts, (0, max(xs)), (0, 100), y_ticks=[0, 25, 50, 75, 100],
                    y_format=lambda v: f"{v:g}%")
        plot.draw_axes("Total Timesteps")
        plot.line(xs, ys, LINE_MAIN, 2)
        best = exp.best_record()
        if best:
            plot.markers([best["timesteps"]], [best["clear_rate"]], HIGHLIGHT, 6)
            plot.label(best["timesteps"], best["clear_rate"], f"최고 {best['clear_rate']:.1f}% (ppo_best.pt)",
                       TEXT, offset=(-60, -10))
        plot.markers([xs[-1]], [ys[-1]], LINE_MAIN, 6)
        plot.label(xs[-1], ys[-1], f"마지막 {ys[-1]:.1f}%", TEXT, offset=(-40, 34))
        items = [("클리어율", LINE_MAIN, 2)]
        self._legend(surface, plot_rect.x, rect.bottom - 30, items)
        if best:
            pygame.draw.circle(surface, HIGHLIGHT, (plot_rect.x + 150, rect.bottom - 21), 6)
            text(surface, self.fonts(15), "ppo_best.pt 저장 시점", (plot_rect.x + 164, rect.bottom - 30), TEXT_2)

    def _chart_stability(self, surface, rect) -> None:
        plot_rect = self._frame(surface, rect, "PPO 안정성 지표", "업데이트마다 · 지표별로 축을 따로 둠", "updates.csv")
        rows = self.experiment.updates
        keys = ("approx_kl", "clip_fraction", "explained_variance")
        if not rows or any(key not in rows[0] for key in keys):
            self._missing(surface, plot_rect, "updates.csv")
            return
        xs = [r["timesteps"] for r in rows]
        panels = (("approx_kl", "approx_kl", 1, "{:.3f}"), ("clip_fraction", "clip_fraction %", 100, "{:.0f}"),
                  ("explained_variance", "explained_var.", 1, "{:.1f}"))
        gap = 14
        height = (plot_rect.height - 6 - gap * 2) // 3
        for i, (key, label, factor, fmt) in enumerate(panels):
            values = [float(r[key]) * factor for r in rows if r[key] != "" and r[key] == r[key]]
            sub = pygame.Rect(plot_rect.x, plot_rect.y + i * (height + gap), plot_rect.width, height - 8)
            clean = [v for v in values if v == v]
            low, high = (min(clean), max(clean)) if clean else (0, 1)
            if key == "clip_fraction":
                low = 0
            ticks = nice_ticks(low, high, 2)
            plot = Plot(surface, sub, self.fonts, (0, max(xs)), (ticks[0], ticks[-1]), y_ticks=ticks,
                        y_format=lambda v, fmt=fmt: fmt.format(v), tick_size=13)
            plot.draw_axes("Total Timesteps" if i == 2 else "", show_x=i == 2)
            pairs = [(x, v) for x, v in zip(xs, values) if v == v]
            plot.envelope([p[0] for p in pairs], [p[1] for p in pairs], LINE_RAW, alpha=0.25)
            plot.sampled_line([p[0] for p in pairs], moving_average([p[1] for p in pairs], MOVING_AVERAGE), LINE_MAIN, 2)
            text(surface, self.fonts(14), label, (sub.x + 8, sub.y + 2), MOON)
        self._legend(surface, plot_rect.x, rect.bottom - 30,
                     [("업데이트별 값", LINE_RAW, 1), (f"최근 {MOVING_AVERAGE}회 이동평균", LINE_MAIN, 3)])

    # ----- 원본 PNG -----

    def _draw_png(self, canvas) -> None:
        f = self.fonts
        canvas.fill((9, 12, 26), CONTENT)
        pngs = self.experiment.pngs
        text(canvas, f(30), "원본 학습 그래프", (28, CONTENT.y + 14), MOON)
        pill(canvas, f, CANVAS_SIZE[0] - 360, CONTENT.y + 32,
             [("G", HIGHLIGHT), ("CSV 차트", TEXT_2), ("·  ← →", HIGHLIGHT), ("넘기기", TEXT_2)], size=17)
        if not pngs:
            text(canvas, f(24), f"데이터 없음 · results/{self.experiment.name}/ 에 PNG 그래프가 없습니다",
                 CONTENT.center, TEXT_2, "center")
            return
        path = pngs[self.png_index]
        text(canvas, f(18), f"{path.name}   ({self.png_index + 1} / {len(pngs)})  ·  scripts/ppo.py가 저장한 그림",
             (300, CONTENT.y + 26), TEXT_2)
        area = pygame.Rect(28, CONTENT.y + 70, CANVAS_SIZE[0] - 56, CONTENT.height - 90)
        if self.png_index not in self._png_cache:
            image = pygame.image.load(str(path)).convert()
            scale = min(area.width / image.get_width(), area.height / image.get_height())
            size = (round(image.get_width() * scale), round(image.get_height() * scale))
            self._png_cache[self.png_index] = pygame.transform.smoothscale(image, size)
        image = self._png_cache[self.png_index]
        canvas.blit(image, image.get_rect(center=area.center))
