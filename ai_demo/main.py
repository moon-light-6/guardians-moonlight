"""
월하사신 PPO 발표 시연 프로그램 실행 진입점.

  python -m ai_demo.main
  python -m ai_demo.main --run results/seungyeon_1300k --model ppo_best.pt --seed 102026 --speed 2

조작
  F1 / F2 (또는 Tab)  AI 플레이 / 학습 그래프 화면 (그래프 화면에서는 플레이가 잠시 멈춤)
  Space   일시정지      S  배속(1 -> 1.5 -> 2 -> 5)      H  게임판 위 슬롯별 소환 횟수
  T       전략 분석 범위(이번 판 / 시연 누적)          D  맵 디버그(기존 게임 기능)
  N       다음 시드로 새 게임      R  같은 시드로 다시      F11  전체 화면
  G, ← →  (그래프 화면) 원본 PNG 보기 / 넘기기          ESC 두 번  종료
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ai_demo import ROOT


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m ai_demo.main",
        description="학습된 PPO 모델이 월하사신을 자동으로 플레이하는 발표 시연 프로그램",
    )
    parser.add_argument("--run", type=Path, default=None,
                        help="학습 결과 폴더 (기본: results/seungyeon_1300k, --model이 경로면 그 폴더)")
    parser.add_argument("--model", default=None,
                        help="모델 파일 이름(ppo_best.pt / ppo_policy.pt) 또는 경로. 기본 ppo_best.pt")
    parser.add_argument("--seed", type=int, default=None,
                        help="첫 판 시드. 기본은 그 실험의 첫 평가 시드(run.seed + 100000)")
    parser.add_argument("--greedy", action="store_true", help="샘플링 대신 확률이 가장 큰 행동만 고르기")
    parser.add_argument("--speed", type=float, default=1.0, choices=(1.0, 1.5, 2.0, 5.0), help="시작 배속")
    parser.add_argument("--think", type=float, default=0.6,
                        help="준비 단계에서 고른 행동을 보여 주는 시간(초, 1배속 기준). 결과에는 영향 없음")
    parser.add_argument("--auto-next", type=float, default=0.0,
                        help="게임이 끝나고 이 초가 지나면 다음 시드로 자동 시작(0이면 N을 누를 때까지 대기)")
    parser.add_argument("--fullscreen", action="store_true", help="전체 화면으로 시작")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "ai_demo" / "logs",
                        help="시연 행동 기록 CSV 저장 위치 (학습 결과 폴더와 별개)")
    parser.add_argument("--no-log", action="store_true", help="시연 기록을 저장하지 않음")
    parser.add_argument("--list", action="store_true", help="results/의 실험과 실제 평가 수치를 보여 주고 종료")
    # 자동 검증용: 실제 화면 대신 고정 프레임으로 진행하고 화면을 PNG로 저장
    parser.add_argument("--test-seconds", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--capture", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--capture-every", type=float, default=20.0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def print_experiments() -> None:
    from ai_demo.experiment import list_experiments

    for exp in list_experiments():
        best = exp.best_record()
        rows = exp.final_policy_rows()
        final = f"{sum(bool(r['won']) for r in rows) / len(rows) * 100:.1f}% ({len(rows)}판)" if rows else "없음"
        best_text = f"{best['clear_rate']:.1f}% @ {best['timesteps']:,} Step" if best else "확인 불가"
        steps = f"{exp.total_steps:,}" if exp.total_steps is not None else "?"
        print(f"{exp.name:24s} 총 {steps:>10s} Step | ppo_best.pt 정기 평가 {best_text:24s} | "
              f"ppo_policy.pt 최종 평가 {final}")
        for warning in exp.warnings:
            print(f"    ! {warning}")


@dataclass
class ViewInfo:
    experiment: object
    model_info: object
    model_path: Path
    greedy: bool
    load_error: Optional[str] = None
    recorded_match: Optional[bool] = None
    auto_next_left: Optional[float] = None


def _enable_dpi_awareness() -> None:
    # Windows 화면 배율(125% 등)에서 창이 흐릿하게 확대되지 않게 한다.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - 지원하지 않는 Windows면 그냥 넘어간다
            pass


class DemoApp:
    def __init__(self, args):
        import pygame

        from ai_demo.controller import DemoController
        from ai_demo.experiment import DEFAULT_RUN, load_experiment
        from ai_demo.ppo_bridge import PolicyAgent, PolicyLoadError, load_policy, load_ppo_module, resolve_model_path
        from ai_demo.stats import DemoStats, SessionLogger
        from ai_demo.theme import CANVAS_SIZE, Fonts

        self.pygame = pygame
        self.args = args
        self.test_mode = args.test_seconds is not None
        pygame.init()
        pygame.display.set_caption("월하사신 AI DEMO")
        self.windowed_size = self._initial_window_size(CANVAS_SIZE)
        self.fullscreen = False
        self._set_mode(args.fullscreen and not self.test_mode)
        self.canvas = pygame.Surface(CANVAS_SIZE).convert()
        self.game_surface = pygame.Surface((1280, 840)).convert()

        # 화면을 먼저 띄운 뒤(이미지 convert에 필요) 게임 렌더러를 기존 코드 그대로 만든다.
        from display.renderer import Renderer
        from ai_demo.graph_view import GraphView
        from ai_demo.play_view import PlayView

        self.fonts = Fonts()
        self.renderer = Renderer(self.game_surface)

        run_dir = args.run
        if run_dir is None:
            model_arg = Path(args.model) if args.model else None
            run_dir = model_arg.parent if model_arg and len(model_arg.parts) > 1 else DEFAULT_RUN
        run_dir = (ROOT / run_dir) if not Path(run_dir).is_absolute() and not Path(run_dir).exists() else Path(run_dir)
        self.experiment = load_experiment(run_dir)
        model_path = resolve_model_path(run_dir, args.model)

        load_error, agent, ppo = None, None, None
        try:
            ppo = load_ppo_module()
            model = load_policy(ppo, model_path)
            agent = PolicyAgent(ppo, model, greedy=args.greedy)
        except PolicyLoadError as error:
            load_error = str(error)
        if ppo is None:
            raise SystemExit(f"시연을 시작할 수 없습니다: {load_error}")

        model_info = self.experiment.model_info(model_path) if agent is not None else None
        self.info = ViewInfo(self.experiment, model_info, model_path, args.greedy, load_error)
        self.stats = DemoStats()
        logger = SessionLogger(None if args.no_log or self.test_mode else args.log_dir)
        self.controller = DemoController(ppo, agent, self.stats, logger, think_seconds=args.think,
                                         model_name=model_path.name)
        self.controller.combat_speed = args.speed
        self.play_view = PlayView(self.fonts, self.renderer)
        self.graph_view = GraphView(self.fonts, self.experiment, model_info)
        self.screen_name = "play"
        self.tabs = {}
        self.clock = pygame.time.Clock()
        self.now = 0.0
        self.quit_armed_until = -1.0
        self.toast: Optional[tuple] = None
        self.auto_next_left: Optional[float] = None

        base_seed = self.experiment.eval_seed_base or 102026
        self.controller.new_game(args.seed if args.seed is not None else base_seed)
        print(f"[ai_demo] 실험 {self.experiment.name} / 모델 {model_path}")
        if load_error:
            print(f"[ai_demo] 모델을 불러오지 못했습니다: {load_error}")
        for warning in self.experiment.warnings:
            print(f"[ai_demo] 주의: {warning}")

    # ----- 창 -----

    def _initial_window_size(self, canvas_size):
        sizes = self.pygame.display.get_desktop_sizes() if hasattr(self.pygame.display, "get_desktop_sizes") else []
        if not sizes:
            return canvas_size
        width, height = sizes[0]
        scale = min(1.0, width * 0.94 / canvas_size[0], height * 0.88 / canvas_size[1])
        return round(canvas_size[0] * scale), round(canvas_size[1] * scale)

    def _set_mode(self, fullscreen: bool) -> None:
        pygame = self.pygame
        self.fullscreen = fullscreen
        if fullscreen:
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.window = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)

    def _view_rect(self):
        """비율을 유지한 채 창 안에 캔버스를 놓을 자리."""
        width, height = self.window.get_size()
        cw, ch = self.canvas.get_size()
        scale = min(width / cw, height / ch)
        size = (max(1, round(cw * scale)), max(1, round(ch * scale)))
        return self.pygame.Rect((width - size[0]) // 2, (height - size[1]) // 2, *size)

    def _to_canvas(self, pos):
        rect = self._view_rect()
        return ((pos[0] - rect.x) * self.canvas.get_width() / rect.width,
                (pos[1] - rect.y) * self.canvas.get_height() / rect.height)

    def _present(self) -> None:
        rect = self._view_rect()
        if rect.size == self.canvas.get_size():
            self.window.blit(self.canvas, rect)
        else:
            self.window.fill((0, 0, 0))
            self.window.blit(self.pygame.transform.smoothscale(self.canvas, rect.size), rect)
        self.pygame.display.flip()

    # ----- 진행 -----

    def run(self) -> None:
        pygame = self.pygame
        next_capture = 0.0
        running = True
        while running:
            if self.test_mode:
                dt = 1 / 30
            else:
                dt = self.clock.tick(60) / 1000.0
            self.now += dt
            for event in pygame.event.get():
                running = self._handle_event(event) and running
            on_graphs = self.screen_name == "graphs"
            if not on_graphs:
                self.controller.update(dt)
            self._drain_events()
            self._tick_auto_next(dt)
            self._draw()
            if not self.test_mode:
                self._present()
            if self.test_mode:
                if self.args.capture and self.now >= next_capture:
                    self._capture(f"play_{self.now:07.1f}s")
                    next_capture += self.args.capture_every
                if self.now >= self.args.test_seconds:
                    running = False
        if self.test_mode and self.args.capture:
            self._capture("play_final")
            self.screen_name = "graphs"
            self._draw()
            self._capture("graphs_csv")
            self.graph_view.toggle_mode()
            self._draw()
            self._capture("graphs_png")
        pygame.quit()

    def _capture(self, name: str) -> None:
        self.args.capture.mkdir(parents=True, exist_ok=True)
        self.pygame.image.save(self.canvas, str(self.args.capture / f"{name}.png"))

    def _drain_events(self) -> None:
        for name, payload in self.controller.events:
            if name == "action" and payload.kind == "upgrade":
                self.renderer.play_upgrade_effect(self.controller.state, payload.slot)
            if name == "game_end":
                self._on_game_end(payload)
            if name == "new_game":
                self.info.recorded_match = None
            self.play_view.on_event(name, payload, self.now)
        self.controller.events.clear()

    def _on_game_end(self, result) -> None:
        from ai_demo.verify import COMPARE_KEYS

        recorded = self.experiment.recorded_result(self.info.model_path, result["seed"], self.info.greedy)
        match = None
        if recorded is not None:
            match = all(recorded[key] == result[key] for key in COMPARE_KEYS)
        self.info.recorded_match = match
        self.controller.log_result(match)
        outcome = "클리어" if result["won"] else f"{result['reached']}소동 실패"
        print(f"[ai_demo] {result['game']}판(시드 {result['seed']}) {outcome}: 결계 {result['life']}, "
              f"골드 {result['gold']}, 소환 {result['buy']} 강화 {result['upgrade']} 판매 {result['sell']}"
              + ("" if match is None else f", final_eval.csv와 {'일치' if match else '불일치'}"))
        if self.args.auto_next > 0:
            self.auto_next_left = self.args.auto_next

    def _tick_auto_next(self, dt) -> None:
        if self.auto_next_left is None or self.controller.paused or self.screen_name != "play":
            self.info.auto_next_left = self.auto_next_left
            return
        self.auto_next_left -= dt
        if self.auto_next_left <= 0:
            self.auto_next_left = None
            self.controller.new_game(self.controller.seed + 1)
        self.info.auto_next_left = self.auto_next_left

    def _show_toast(self, message: str, seconds: float = 2.0) -> None:
        self.toast = (message, self.now + seconds)

    def _handle_event(self, event) -> bool:
        pygame = self.pygame
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = self._to_canvas(event.pos)
            for name, rect in self.tabs.items():
                if rect.collidepoint(pos):
                    self.screen_name = name
        if event.type != pygame.KEYDOWN:
            return True
        key = event.key
        controller = self.controller
        if key == pygame.K_ESCAPE:
            if self.now <= self.quit_armed_until:
                return False
            self.quit_armed_until = self.now + 2.5
            self._show_toast("한 번 더 ESC를 누르면 종료합니다", 2.5)
        elif key in (pygame.K_F1, pygame.K_1):
            self.screen_name = "play"
        elif key in (pygame.K_F2, pygame.K_2):
            self.screen_name = "graphs"
        elif key == pygame.K_TAB:
            self.screen_name = "graphs" if self.screen_name == "play" else "play"
        elif key == pygame.K_F11:
            self._set_mode(not self.fullscreen)
        elif self.screen_name == "graphs":
            if key == pygame.K_g:
                self.graph_view.toggle_mode()
            elif key in (pygame.K_LEFT, pygame.K_RIGHT):
                self.graph_view.turn_page(-1 if key == pygame.K_LEFT else 1)
        elif key == pygame.K_SPACE:
            controller.paused = not controller.paused
        elif key == pygame.K_s:
            self._show_toast(f"배속 ×{controller.cycle_speed():g}")
        elif key == pygame.K_h:
            self.play_view.heat_overlay = not self.play_view.heat_overlay
        elif key == pygame.K_t:
            self.play_view.scope = "session" if self.play_view.scope == "episode" else "episode"
        elif key == pygame.K_d:
            self.renderer.toggle_map_debug()
        elif key in (pygame.K_n, pygame.K_r):
            self.auto_next_left = None
            seed = controller.seed + 1 if key == pygame.K_n else controller.seed
            controller.new_game(seed)
            self._show_toast(f"새 게임 · 시드 {seed}")
        return True

    # ----- 그리기 -----

    def _draw(self) -> None:
        pygame = self.pygame
        from ai_demo.play_view import draw_header
        from ai_demo.theme import BACKGROUND, FRAME, GAME_RECT, HIGHLIGHT, TEXT, pill

        canvas = self.canvas
        canvas.fill(BACKGROUND)
        if self.screen_name == "play":
            state = self.controller.state
            self.renderer.render(state)
            self.play_view.draw_game_overlays(self.game_surface, self.controller, self.stats, self.now)
            if self.info.load_error:
                self._draw_load_error(self.game_surface)
            canvas.blit(pygame.transform.smoothscale(self.game_surface, GAME_RECT.size), GAME_RECT)
            pygame.draw.rect(canvas, FRAME, GAME_RECT.inflate(4, 4), 2, border_radius=4)
            self.play_view.draw_bottom(canvas, self.controller, self.stats, self.info, self.now)
            self.play_view.draw_side(canvas, self.stats)
        else:
            self.graph_view.draw(canvas)
            pill(canvas, self.fonts, canvas.get_width() - 640, 100, [("플레이 일시정지 중", HIGHLIGHT), ("F1로 돌아가기", TEXT)],
                 height=36, size=17)
        self.tabs = draw_header(canvas, self.fonts, self.info, self.controller, self.screen_name)
        if self.toast and self.now < self.toast[1]:
            width = self.fonts(22).size(self.toast[0])[0] + 28
            pill(canvas, self.fonts, (canvas.get_width() - width) // 2, 120, [(self.toast[0], TEXT)],
                 height=44, size=22, border=(*HIGHLIGHT, 200))

    def _draw_load_error(self, surface) -> None:
        from display.ui import draw_panel
        from ai_demo.theme import BAD, TEXT, TEXT_2, text
        from ai_demo.play_view import _wrap

        panel = self.pygame.Rect(240, 300, 800, 220)
        draw_panel(surface, panel)
        text(surface, self.fonts(30), "PPO 모델을 불러오지 못했습니다", (panel.centerx, panel.y + 36), BAD, "midtop")
        for i, line in enumerate(_wrap(self.fonts(18), self.info.load_error, 720)[:3]):
            text(surface, self.fonts(18), line, (panel.centerx, panel.y + 92 + i * 26), TEXT, "midtop")
        text(surface, self.fonts(16), "--run 실험 폴더와 --model 파일을 확인하세요 (python -m ai_demo.main --list)",
             (panel.centerx, panel.bottom - 40), TEXT_2, "midtop")


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.list:
        print_experiments()
        return 0
    if args.test_seconds is not None:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    else:
        _enable_dpi_awareness()
    started = time.perf_counter()
    app = DemoApp(args)
    if args.test_seconds is not None:
        print(f"[ai_demo] 준비 {time.perf_counter() - started:.1f}초")
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
