
from pathlib import Path

import pygame


class TowerSpriteAnimator:
    """청룡과 현무의 대기/공격 애니메이션을 담당합니다."""

    SPRITE_CONFIG = {
        "LIGHTNING": {
            "folder": "청룡",
            "effect": "lightning",
            "idle_start": 0,
        },
        "ICE": {
            "folder": "현무",
            "effect": "water",
            "idle_start": 1,
        },
    }

    DIRECTIONS = ("NE", "NW", "SE", "SW")
    FRAME_COUNT = 4

    SPRITE_SIZE = (58, 58)
    IDLE_FRAME_MS = 180

    def __init__(self):
        self.root = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "sprites"
        )

        # 한 번 불러온 이미지는 메모리에 저장합니다.
        self.frames = {}
        self.last_directions = {}

        self._load_all_frames()

    def _load_all_frames(self):
        """타워별 대기/공격 이미지를 불러옵니다."""

        for tower_type, config in self.SPRITE_CONFIG.items():
            guardian = config["folder"]

            for motion, folder_name in (
                ("idle", f"{guardian}_대기_프레임"),
                ("attack", f"{guardian}_공격_프레임"),
            ):
                folder = (
                    self.root
                    / guardian
                    / folder_name
                    / "frames"
                )

                for direction in self.DIRECTIONS:
                    loaded_frames = []

                    for index in range(self.FRAME_COUNT):
                        frame_number = index

                        # 현무 대기 이미지는 1~4번으로 저장됨
                        if motion == "idle":
                            frame_number += config["idle_start"]

                        filename = f"{direction}_{frame_number}.png"
                        path = folder / filename

                        if not path.is_file():
                            raise FileNotFoundError(
                                f"스프라이트 파일을 찾을 수 없습니다: {path}"
                            )

                        image = pygame.image.load(
                            str(path)
                        ).convert_alpha()

                        image = pygame.transform.smoothscale(
                            image,
                            self.SPRITE_SIZE,
                        )

                        loaded_frames.append(image)

                    self.frames[
                        (tower_type, motion, direction)
                    ] = loaded_frames

    @staticmethod
    def _get_direction(start, end):
        """타워에서 공격 대상까지의 방향을 계산합니다."""

        dx = end[0] - start[0]
        dy = end[1] - start[1]

        vertical = "N" if dy < 0 else "S"
        horizontal = "W" if dx < 0 else "E"

        return vertical + horizontal

    @staticmethod
    def _same_position(pos1, pos2):
        """해당 공격 이펙트가 이 타워에서 발생했는지 확인합니다."""

        return (
            abs(pos1[0] - pos2[0]) < 0.001
            and abs(pos1[1] - pos2[1]) < 0.001
        )

    def _find_attack_effect(self, tower_type, tower_pos, effects):
        """현재 타워에 해당하는 공격 이펙트를 찾습니다."""

        effect_kind = self.SPRITE_CONFIG[tower_type]["effect"]

        for effect in reversed(effects):
            if effect.get("kind") != effect_kind:
                continue

            if effect.get("age", 0) >= effect.get("ttl", 0):
                continue

            effect_from = effect.get("from")

            if effect_from is None:
                continue

            if self._same_position(effect_from, tower_pos):
                return effect

        return None

    @staticmethod
    def _get_target_position(effect):
        """공격 이펙트에서 대상 좌표를 가져옵니다."""

        if effect["kind"] == "lightning":
            points = effect.get("points", [])
            return points[0] if points else None

        return effect.get("to")

    def draw(
        self,
        screen,
        slot_id,
        tower_type,
        pixel_pos,
        tower_pos,
        effects,
    ):
        """
        해당 타워를 애니메이션으로 그립니다.
        지원하지 않는 타워는 False를 반환합니다.
        """

        if tower_type not in self.SPRITE_CONFIG:
            return False

        effect = self._find_attack_effect(
            tower_type,
            tower_pos,
            effects,
        )

        direction_key = (slot_id, tower_type)

        if effect is not None:
            motion = "attack"

            target_pos = self._get_target_position(effect)

            if target_pos is not None:
                direction = self._get_direction(
                    tower_pos,
                    target_pos,
                )
                self.last_directions[direction_key] = direction
            else:
                direction = self.last_directions.get(
                    direction_key, "SE"
                )

            ttl = max(effect["ttl"], 0.001)
            progress = max(
                0.0,
                min(effect["age"] / ttl, 0.999999),
            )

            frame_index = int(progress * self.FRAME_COUNT)

        else:
            motion = "idle"

            direction = self.last_directions.get(
                direction_key, "SE"
            )

            frame_index = (
                pygame.time.get_ticks()
                // self.IDLE_FRAME_MS
            ) % self.FRAME_COUNT

        image = self.frames[
            (tower_type, motion, direction)
        ][frame_index]

        # 캐릭터가 슬롯 중심보다 살짝 위에 위치하도록 조정
        draw_pos = (
            pixel_pos[0],
            pixel_pos[1] - 8,
        )

        rect = image.get_rect(center=draw_pos)
        screen.blit(image, rect)

        return True
