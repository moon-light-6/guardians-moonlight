
from pathlib import Path

import pygame


class AttackEffectAnimator:
    """청룡·현무 공격 이펙트 스프라이트를 표시합니다."""

    # rows, cols는 원본 PNG의 실제 배열에 맞게 조정
    EFFECT_CONFIG = {
        "lightning": {
            "path": (
                "청룡",
                "8프레임 블루 번개 이펙트 시트.png",
            ),
            "rows": 1,
            "cols": 8,
            "frame_count": 8,
            "size": (78, 78),
        },
        "water": {
            "path": (
                "현무",
                "마법의 얼음 물결 이펙트 스프라이트 시트.png",
            ),
            "rows": 2,
            "cols": 4,
            "frame_count": 8,
            "size": (82, 82),
        },
    }

    def __init__(self):
        self.root = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "sprites"
        )

        self.frames = {}
        self._load_all()

    
    def _load_all(self):
        for kind, config in self.EFFECT_CONFIG.items():
            path = self.root.joinpath(*config["path"])

            if not path.is_file():
                raise FileNotFoundError(
                    f"이펙트 이미지가 없습니다: {path}"
                )

            sheet = pygame.image.load(
                str(path)
            ).convert_alpha()

            width, height = sheet.get_size()
            rows = config["rows"]
            cols = config["cols"]

            if config["frame_count"] > rows * cols:
                raise ValueError(
                    f"{kind}: 프레임 개수가 배열보다 많습니다."
                )

            loaded = []

            for index in range(config["frame_count"]):
                col = index % cols
                row = index // cols

                # 이미지 크기가 균등하게 나누어지지 않아도
                # 각 프레임의 시작/끝 좌표를 계산
                x1 = round(col * width / cols)
                x2 = round((col + 1) * width / cols)

                y1 = round(row * height / rows)
                y2 = round((row + 1) * height / rows)

                rect = pygame.Rect(
                    x1,
                    y1,
                    x2 - x1,
                    y2 - y1,
                )

                frame = sheet.subsurface(rect).copy()

                frame = pygame.transform.smoothscale(
                    frame,
                    config["size"],
                )

                loaded.append(frame)

            self.frames[kind] = loaded

            print(
                f"[Effect] {kind}: "
                f"sheet={width}x{height}, "
                f"grid={cols}x{rows}, "
                f"frames={len(loaded)}"
            )

    def draw(self, screen, effect, game_map):
        kind = effect.get("kind")

        if kind not in self.frames:
            return False

        age = effect.get("age", 0.0)
        ttl = effect.get("ttl", 0.0)

        if ttl <= 0 or age >= ttl:
            return True

        progress = max(
            0.0,
            min(age / ttl, 0.999999),
        )

        frames = self.frames[kind]
        index = min(
            int(progress * len(frames)),
            len(frames) - 1,
        )

        image = frames[index]

        # 청룡은 연쇄 공격으로 여러 적을 타격할 수 있음
        if kind == "lightning":
            targets = effect.get("points", [])

        # 현무는 공격 대상 위치에 이펙트 표시
        elif kind == "water":
            target = effect.get("to")
            targets = [target] if target is not None else []

        else:
            targets = []

        for target in targets:
            pos = game_map.grid_to_pixel(target)

            rect = image.get_rect(center=pos)
            screen.blit(image, rect)

        return True
