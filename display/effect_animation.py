from pathlib import Path
import math
import pygame


class AttackEffectAnimator:
    """교체된 6×2 시트의 원본 12프레임을 재생합니다."""

    FRAME_COUNT = 12
    # 각 원본 칸 안의 타격/마법진 중심 좌표. 투명 여백은 기준에서 제외합니다.
    EFFECT_CONFIG = {
        "lightning": {
            "path": ("청룡", "푸른 번개 마법진 효과 스프라이트 시트.png"),
            "rows": 2, "cols": 6, "frame_count": FRAME_COUNT, "size": (78, 78),
            "anchors": ((176, 315), (166, 317), (160, 320), (160, 324),
                        (151, 324), (153, 325), (194, 278), (187, 279),
                        (184, 277), (180, 279), (170, 278), (175, 277)),
        },
        "water": {
            "path": ("현무", "네온 그린 마법 포털 스프라이트 시트.png"),
            "rows": 2, "cols": 6, "frame_count": FRAME_COUNT, "size": (82, 82),
            "anchors": ((177, 287), (167, 289), (165, 289), (170, 289),
                        (177, 288), (177, 289), (181, 236), (190, 239),
                        (193, 239), (195, 243), (187, 241), (181, 242)),
        },
        "claw": {
            "path": ("백호", "분홍빛 마법 고양이 발바닥 스프라이트 시트.png"),
            "rows": 2, "cols": 6, "frame_count": FRAME_COUNT, "size": (70, 70),
            "anchors": ((176, 220), (176, 220), (180, 220), (184, 220),
                        (184, 200), (186, 218), (181, 181), (180, 183),
                        (180, 183), (183, 183), (180, 184), (178, 184)),
        },
        "fire": {
            "path": ("주작", "투명 배경의 불꽃 연꽃 폭발 스프라이트 시트.png"),
            "rows": 2, "cols": 6, "frame_count": FRAME_COUNT, "size": (90, 90),
            "anchors": ((189, 273), (180, 270), (178, 262), (174, 262),
                        (178, 250), (179, 248), (185, 216), (184, 187),
                        (179, 182), (179, 183), (177, 186), (181, 190)),
        },
    }
    FIELD_ALPHA = 170
    FIELD_CREATE_SECONDS = 0.4
    FIELD_HOLD_SECONDS = 1.2
    FIELD_HOLD_FRAME_SECONDS = 0.1
    FIELD_DISSOLVE_SECONDS = 0.4
    FIELD_CREATE_FRAMES = (0, 1, 2, 3)
    FIELD_HOLD_FRAMES = (4, 5, 6, 7)
    FIELD_DISSOLVE_FRAMES = (8, 9, 10, 11)
    CHAIN_LINK_TRAVEL_SECONDS = 0.06
    CHAIN_LINK_FADE_SECONDS = 0.25

    def __init__(self):
        self.root = Path(__file__).resolve().parents[1] / "assets" / "sprites"
        self.frames = {}
        self.anchors = {}
        self._load_all()

    @staticmethod
    def _align_frames(frames, anchor_points, output_size):
        """공통 anchor/캔버스를 사용하며 원본의 성장·소멸 크기 변화는 보존합니다."""
        if len(frames) != len(anchor_points):
            raise ValueError("프레임 수와 anchor 수가 다릅니다")
        scaled_frames = []
        anchors = []
        for frame, (x, y) in zip(frames, anchor_points):
            scaled_frames.append(pygame.transform.smoothscale(frame, output_size))
            anchors.append((round(x * output_size[0] / frame.get_width()),
                            round(y * output_size[1] / frame.get_height())))

        # 모든 프레임의 여백을 함께 확보해 정렬 시 이미지가 잘리지 않게 합니다.
        common_anchor = (max(x for x, _ in anchors), max(y for _, y in anchors))
        size = (common_anchor[0] + max(frame.get_width() - anchor[0]
                                      for frame, anchor in zip(scaled_frames, anchors)),
                common_anchor[1] + max(frame.get_height() - anchor[1]
                                      for frame, anchor in zip(scaled_frames, anchors)))
        aligned = []
        for frame, anchor in zip(scaled_frames, anchors):
            canvas = pygame.Surface(size, pygame.SRCALPHA, 32)
            canvas.blit(frame, (common_anchor[0] - anchor[0], common_anchor[1] - anchor[1]))
            aligned.append(canvas)
        return aligned, common_anchor

    @staticmethod
    def _remove_edge_bleed(frame):
        """칸 경계에 걸친 이웃 프레임 조각만 지우고 본체와 내부 입자는 보존합니다."""
        components = pygame.mask.from_surface(frame, threshold=32).connected_components()
        if not components:
            return frame
        main = max(components, key=lambda component: component.count())
        for component in components:
            if component is main:
                continue
            rect = component.get_bounding_rects()[0]
            if (rect.left == 0 or rect.top == 0
                    or rect.right == frame.get_width() or rect.bottom == frame.get_height()):
                frame.fill((0, 0, 0, 0), rect.inflate(4, 4).clip(frame.get_rect()))
        return frame

    @staticmethod
    def _slice_sheet(sheet, rows, cols, frame_count):
        width, height = sheet.get_size()
        if frame_count != rows * cols:
            raise ValueError("프레임 수와 시트 배열 칸 수가 다릅니다")
        frames = []
        for index in range(frame_count):
            col, row = index % cols, index // cols
            x1, x2 = round(col * width / cols), round((col + 1) * width / cols)
            y1, y2 = round(row * height / rows), round((row + 1) * height / rows)
            frames.append(sheet.subsurface(pygame.Rect(x1, y1, x2 - x1, y2 - y1)).copy())
        return frames

    def _load_all(self):
        for kind, config in self.EFFECT_CONFIG.items():
            path = self.root.joinpath(*config["path"])
            if not path.is_file():
                raise FileNotFoundError(f"이펙트 이미지 없음: {path}")
            sheet = pygame.image.load(str(path)).convert_alpha()
            rows, cols = config["rows"], config["cols"]
            source = self._slice_sheet(sheet, rows, cols, config["frame_count"])
            source = [self._remove_edge_bleed(frame) for frame in source]
            self.frames[kind], self.anchors[kind] = self._align_frames(source, config["anchors"], config["size"])
            print(f"[Effect] {kind}: {sheet.get_width()}x{sheet.get_height()}, {cols}x{rows}, {len(self.frames[kind])} frames")

    @staticmethod
    def _draw_chain_link(screen, start, end, progress, opacity):
        """고정된 꺾임의 번개 라인을 진행 방향으로 펼치고 빛나는 중심선을 표시합니다."""
        if progress <= 0 or opacity <= 0 or start == end:
            return
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        segments = max(3, min(12, int(length / 18)))
        path = []
        for step in range(segments + 1):
            t = step / segments
            offset = 5 * math.sin(math.pi * t) * (1 if step % 2 else -1)
            path.append((start[0] + dx * t - dy / length * offset,
                         start[1] + dy * t + dx / length * offset))
        position = min(1.0, progress) * segments
        last = min(int(position), segments)
        visible = path[:last + 1]
        if last < segments:
            fraction = position - last
            visible.append((path[last][0] + (path[last + 1][0] - path[last][0]) * fraction,
                            path[last][1] + (path[last + 1][1] - path[last][1]) * fraction))
        left = math.floor(min(x for x, _ in visible)) - 6
        top = math.floor(min(y for _, y in visible)) - 6
        width = math.ceil(max(x for x, _ in visible)) - left + 7
        height = math.ceil(max(y for _, y in visible)) - top + 7
        glow = pygame.Surface((width, height), pygame.SRCALPHA, 32)
        points = [(round(x - left), round(y - top)) for x, y in visible]
        for color, thickness in (((30, 90, 255, int(65 * opacity)), 9),
                                 ((70, 190, 255, int(180 * opacity)), 5),
                                 ((235, 252, 255, int(255 * opacity)), 2)):
            pygame.draw.lines(glow, color, False, points, thickness)
        screen.blit(glow, (left, top))

    def _draw_lightning_chain(self, screen, effect, game_map):
        age = effect["age"]
        hit_ttl = effect.get("hit_ttl", effect["ttl"])
        stagger = effect.get("hit_stagger", 0.0)
        targets = [game_map.grid_to_pixel(point) for point in effect.get("points", [])]
        origin = effect.get("from")
        previous = game_map.grid_to_pixel(origin) if origin is not None else None
        # 연결선을 먼저 그려 타겟의 마법진/번개 PNG 뒤에 놓습니다.
        for index, target in enumerate(targets):
            local_age = age - index * stagger
            if previous is not None and -self.CHAIN_LINK_TRAVEL_SECONDS < local_age < hit_ttl - 1e-9:
                progress = min(1.0, 1 + local_age / self.CHAIN_LINK_TRAVEL_SECONDS)
                opacity = min(1.0, (hit_ttl - max(0.0, local_age)) / self.CHAIN_LINK_FADE_SECONDS)
                self._draw_chain_link(screen, previous, target, progress, opacity)
            previous = target

        frames = self.frames["lightning"]
        anchor = self.anchors["lightning"]
        for index, target in enumerate(targets):
            local_age = age - index * stagger
            if local_age < -1e-9 or local_age >= hit_ttl - 1e-9:
                continue
            frame = max(0, min(int(local_age / hit_ttl * len(frames) + 1e-9), len(frames) - 1))
            screen.blit(frames[frame], (target[0] - anchor[0], target[1] - anchor[1]))
        return True

    def draw(self, screen, effect, game_map):
        kind = effect.get("kind")
        age = effect.get("age", 0.0)
        ttl = effect.get("ttl", 0.0)
        if ttl <= 0 or age >= ttl - 1e-9:
            return kind in self.frames or kind == "slow_field"

        if kind == "slow_field":
            frames = self.frames.get("water")
            if not frames:
                return False
            cell = effect.get("cell")
            if cell is None:
                return True

            # 0~3 생성 → 4~7 유지 반복 → 8~11 소멸. 장판 좌표는 cell에 고정.
            dissolve_start = self.FIELD_CREATE_SECONDS + self.FIELD_HOLD_SECONDS
            if age < self.FIELD_CREATE_SECONDS - 1e-9:
                phase = self.FIELD_CREATE_FRAMES
                step = int((age + 1e-9) / (self.FIELD_CREATE_SECONDS / len(phase)))
                index = phase[min(step, len(phase) - 1)]
            elif age < dissolve_start - 1e-9:
                phase = self.FIELD_HOLD_FRAMES
                step = int((age - self.FIELD_CREATE_SECONDS + 1e-9) / self.FIELD_HOLD_FRAME_SECONDS)
                index = phase[step % len(phase)]
            else:
                phase = self.FIELD_DISSOLVE_FRAMES
                step = int((age - dissolve_start + 1e-9) / (self.FIELD_DISSOLVE_SECONDS / len(phase)))
                index = phase[min(step, len(phase) - 1)]
            image = frames[index].copy()
            image.set_alpha(self.FIELD_ALPHA)
            pos = game_map.grid_to_pixel(cell)
            anchor = self.anchors["water"]
            screen.blit(image, (pos[0] - anchor[0], pos[1] - anchor[1]))
            return True

        if kind not in self.frames:
            return False
        if kind == "lightning":
            return self._draw_lightning_chain(screen, effect, game_map)
        frames = self.frames[kind]
        # 원본 12프레임 전체에 ttl을 균등 배분하며 마지막 프레임도 한 구간 재생합니다.
        index = max(0, min(int(age / ttl * len(frames) + 1e-9), len(frames) - 1))
        image = frames[index]
        target = effect.get("to")
        targets = [target] if target is not None else []
        anchor = self.anchors[kind]
        for target in targets:
            pixel = game_map.grid_to_pixel(target)
            screen.blit(image, (pixel[0] - anchor[0], pixel[1] - anchor[1]))
        return True
