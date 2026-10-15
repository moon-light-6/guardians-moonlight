from pathlib import Path
import pygame


class AttackEffectAnimator:
    """공격 이펙트 4종 및 현무 지속 장판 렌더러."""

    EFFECT_CONFIG = {
        "lightning": {
            "path": ("청룡", "8프레임 블루 번개 이펙트 시트.png"),
            "rows": 1, "cols": 8, "frame_count": 8, "size": (78, 78),
        },
        "water": {
            "path": ("현무", "네온 초록 마법진 이펙트 스프라이트 시트.png"),
            "rows": 2, "cols": 4, "frame_count": 8, "size": (82, 82),
        },
        "claw": {
            "path": ("백호", "핑크 고양이 발바닥 임팩트 스프라이트.png"),
            "rows": 1, "cols": 8, "frame_count": 8, "size": (70, 70),
        },
        "fire": {
            "path": ("주작", "마법의 불꽃 폭발 8프레임 시트.png"),
            "rows": 1, "cols": 8, "frame_count": 8, "size": (90, 90),
        },
    }
    OUTPUT_FRAME_COUNT = 32
    FIELD_ALPHA = 170
    FIELD_CREATE_SECONDS = 0.4
    FIELD_HOLD_SECONDS = 1.2
    FIELD_HOLD_FRAME_SECONDS = 0.1
    FIELD_DISSOLVE_SECONDS = 0.4
    # 원본 1774×887 시트를 4×2로 나눈 각 칸의 바닥 마법진 범위(x, y, w, h).
    # 불꽃/입자와 투명 여백 대신 이 타원을 기준으로 위치와 크기를 맞춥니다.
    FIELD_RING_RECTS = (
        (112, 307, 267, 78), (92, 308, 273, 80),
        (77, 308, 282, 83), (70, 308, 276, 76),
        (109, 243, 271, 85), (88, 244, 283, 87),
        (78, 244, 283, 89), (71, 243, 275, 81),
    )
    FIELD_RING_SIZE = (50, 16)

    def __init__(self):
        self.root = Path(__file__).resolve().parents[1] / "assets" / "sprites"
        self.frames = {}
        self.field_anchor = (0, 0)
        self._load_all()

    def _align_field_frames(self, frames):
        """현무의 바닥 타원을 정규화하고 모든 프레임에 같은 캔버스/anchor를 사용합니다."""
        scaled_frames = []
        anchors = []
        for frame, (x, y, width, height) in zip(frames, self.FIELD_RING_RECTS):
            size = (round(frame.get_width() * self.FIELD_RING_SIZE[0] / width),
                    round(frame.get_height() * self.FIELD_RING_SIZE[1] / height))
            scaled_frames.append(pygame.transform.smoothscale(frame, size))
            anchors.append((round((x + width / 2) * size[0] / frame.get_width()),
                            round((y + height / 2) * size[1] / frame.get_height())))

        # 최대 여백을 함께 확보해 위치를 옮겨도 불꽃/입자가 잘리지 않게 합니다.
        self.field_anchor = (max(x for x, _ in anchors), max(y for _, y in anchors))
        size = (self.field_anchor[0] + max(frame.get_width() - anchor[0]
                                        for frame, anchor in zip(scaled_frames, anchors)),
                self.field_anchor[1] + max(frame.get_height() - anchor[1]
                                        for frame, anchor in zip(scaled_frames, anchors)))
        aligned = []
        for frame, anchor in zip(scaled_frames, anchors):
            canvas = pygame.Surface(size, pygame.SRCALPHA, 32)
            canvas.blit(frame, (self.field_anchor[0] - anchor[0], self.field_anchor[1] - anchor[1]))
            aligned.append(canvas)
        return aligned

    @staticmethod
    def _blend_frames(frames, output_count):
        """8장의 이미지 사이를 선형 보간해 32장의 중간 이미지를 생성."""
        if not frames:
            return []
        if len(frames) == 1:
            return frames * output_count

        result = []
        for index in range(output_count):
            position = index * (len(frames) - 1) / (output_count - 1)
            left = int(position)
            right = min(left + 1, len(frames) - 1)
            ratio = position - left
            if right == left or ratio == 0.0:
                result.append(frames[left].copy())
                continue

            # 각 PNG의 알파값도 보간. 기존 알파 위에 덧칠하는 방식보다
            # 동일 픽셀의 색/투명도 혼합이 안정적이다.
            a = pygame.surfarray.array3d(frames[left])
            b = pygame.surfarray.array3d(frames[right])
            aa = pygame.surfarray.array_alpha(frames[left])
            ab = pygame.surfarray.array_alpha(frames[right])
            import numpy as np
            rgb = np.clip(a.astype(np.float32) * (1 - ratio) + b.astype(np.float32) * ratio, 0, 255).astype(np.uint8)
            alpha = np.clip(aa.astype(np.float32) * (1 - ratio) + ab.astype(np.float32) * ratio, 0, 255).astype(np.uint8)
            mixed = pygame.Surface(frames[left].get_size(), pygame.SRCALPHA, 32)
            pygame.surfarray.blit_array(mixed, rgb)
            pygame.surfarray.pixels_alpha(mixed)[:] = alpha
            result.append(mixed)
        return result

    def _load_all(self):
        for kind, config in self.EFFECT_CONFIG.items():
            path = self.root.joinpath(*config["path"])
            if not path.is_file():
                raise FileNotFoundError(f"이펙트 이미지 없음: {path}")
            sheet = pygame.image.load(str(path)).convert_alpha()
            width, height = sheet.get_size()
            rows, cols = config["rows"], config["cols"]
            if config["frame_count"] > rows * cols:
                raise ValueError(f"{kind}: 지정 프레임 수가 배열 칸 수보다 큼")

            source = []
            for index in range(config["frame_count"]):
                col, row = index % cols, index // cols
                x1 = round(col * width / cols)
                x2 = round((col + 1) * width / cols)
                y1 = round(row * height / rows)
                y2 = round((row + 1) * height / rows)
                frame = sheet.subsurface(pygame.Rect(x1, y1, x2 - x1, y2 - y1)).copy()
                source.append(frame if kind == "water" else pygame.transform.smoothscale(frame, config["size"]))

            # 현무는 원본 8프레임을 사용하고 다른 사신의 보간 방식은 유지합니다.
            self.frames[kind] = self._align_field_frames(source) if kind == "water" else self._blend_frames(source, self.OUTPUT_FRAME_COUNT)
            print(f"[Effect] {kind}: {width}x{height}, {cols}x{rows}, {len(self.frames[kind])} frames")

    def draw(self, screen, effect, game_map):
        kind = effect.get("kind")

        # 현무 장판 하나로 생성 → 3·4번 프레임 왕복 → 소멸을 이어서 재생합니다.
        if kind == "slow_field":
            frames = self.frames.get("water")

            if not frames:
                return False

            age = effect.get("age", 0.0)
            ttl = effect.get("ttl", 0.0)

            # 엔진과 같은 오차 허용값으로 장판 표시도 2초 경계에서 끝냅니다.
            if ttl <= 0 or age >= ttl - 1e-9:
                return True

            cell = effect.get("cell")
            if cell is None:
                return True

            dissolve_start = self.FIELD_CREATE_SECONDS + self.FIELD_HOLD_SECONDS
            if age < self.FIELD_CREATE_SECONDS - 1e-9:
                index = min(int((age + 1e-9) / (self.FIELD_CREATE_SECONDS / 4)), 3)
            elif age < dissolve_start - 1e-9:
                hold_age = age - self.FIELD_CREATE_SECONDS
                index = 3 + int((hold_age + 1e-9) / self.FIELD_HOLD_FRAME_SECONDS) % 2
            else:
                index = 4 + min(int((age - dissolve_start + 1e-9) / (self.FIELD_DISSOLVE_SECONDS / 4)), 3)
            image = frames[index].copy()
            image.set_alpha(self.FIELD_ALPHA)

            pos = game_map.grid_to_pixel(cell)
            rect = image.get_rect(topleft=(pos[0] - self.field_anchor[0], pos[1] - self.field_anchor[1]))

            screen.blit(image, rect)
            return True

        age = effect.get("age", 0.0)
        ttl = effect.get("ttl", 0.0)
        if ttl <= 0 or age >= ttl:
            return kind in self.frames or kind == "slow_field"

        if kind not in self.frames:
            return False
        progress = max(0.0, min(age / ttl, 0.999999))
        frames = self.frames[kind]
        image = frames[min(int(progress * len(frames)), len(frames) - 1)]

        if kind == "lightning":
            targets = effect.get("points", [])
        else:
            target = effect.get("to")
            targets = [target] if target is not None else []

        for target in targets:
            pixel = game_map.grid_to_pixel(target)
            screen.blit(image, image.get_rect(center=pixel))
        return True
