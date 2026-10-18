"""Boss movement sprites; all animation decisions stay in the display layer."""

import re
from pathlib import Path

import pygame

from display.render_sizes import LATE_BOSS_SIZE, LATE_BOSS_STAGES
from game.wave import WaveManager


class BossSpriteAnimator:
    BOSS_FOLDERS = {
        "먹그림자": "01_먹그림자",
        "철갓장군": "02_철갓장군",
        "서리석귀": "03_서리석귀",
        "홍염귀왕": "04_홍염귀왕",
        "흑운이무기": "05_흑운이무기",
        # The supplied directory is named 월식대장, while the game uses 월식대왕.
        "월식대왕": "06_월식대장",
    }
    DIRECTIONS = ("down", "left", "right")
    ANIMATION_FPS = 8
    SPRITE_SIZE = (64, 64)

    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else (
            Path(__file__).resolve().parents[1] / "assets" / "sprites" / "boss"
        )
        self.frames = {}
        late_boss_names = {boss["name"] for stage, boss in WaveManager.BOSSES.items()
                           if stage in LATE_BOSS_STAGES}
        for name, folder in self.BOSS_FOLDERS.items():
            raw = {}
            for direction in self.DIRECTIONS:
                directory = self.root / folder / direction
                pattern = re.compile(rf"{direction}_(\d+)\.png", re.IGNORECASE)
                paths = sorted(
                    ((int(match.group(1)), path) for path in directory.iterdir()
                     if path.is_file() and (match := pattern.fullmatch(path.name))),
                    key=lambda item: item[0],
                )
                if not paths:
                    raise FileNotFoundError(f"No boss animation frames: {directory}")
                raw[direction] = [pygame.image.load(str(path)).convert_alpha()
                                  for _, path in paths]
            sprite_size = LATE_BOSS_SIZE if name in late_boss_names else self.SPRITE_SIZE
            for direction, frames in self._align_frames(raw, sprite_size).items():
                self.frames[name, direction] = frames

    @classmethod
    def _align_frames(cls, frames, sprite_size=None):
        """Use one crop and uniform scale per boss, preserving source motion.

        Only shared transparent margins are removed. Per-frame cropping/scaling
        would make the character jump or change size as limbs and effects move.
        """
        images = [image for sequence in frames.values() for image in sequence]
        size = (max(image.get_width() for image in images),
                max(image.get_height() for image in images))
        aligned = {}
        bounds = pygame.Rect(0, 0, 0, 0)
        for direction, sequence in frames.items():
            aligned[direction] = []
            for image in sequence:
                canvas = pygame.Surface(size, pygame.SRCALPHA)
                canvas.blit(image, image.get_rect(center=canvas.get_rect().center))
                visible = canvas.get_bounding_rect()
                if visible.width and visible.height:
                    bounds = bounds.union(visible) if bounds.width else visible
                aligned[direction].append(canvas)
        if not bounds.width or not bounds.height:
            raise ValueError("Boss animation contains no visible pixels")
        sprite_size = sprite_size if sprite_size is not None else cls.SPRITE_SIZE
        scale = min(sprite_size[0] / bounds.width,
                    sprite_size[1] / bounds.height)
        target = (max(1, round(bounds.width * scale)),
                  max(1, round(bounds.height * scale)))
        return {
            direction: [pygame.transform.smoothscale(image.subsurface(bounds), target)
                        for image in sequence]
            for direction, sequence in aligned.items()
        }

    @staticmethod
    def direction(enemy) -> str:
        # Read the same segment Enemy.move/get_current_position use. At the
        # endpoint keep the final segment's facing; never modify the enemy.
        if len(enemy.path) < 2:
            return "down"
        index = min(max(enemy.path_index, 0), len(enemy.path) - 2)
        start, end = enemy.path[index:index + 2]
        if end[0] > start[0]:
            return "right"
        if end[0] < start[0]:
            return "left"
        # No up assets exist. Any future upward segment also uses down.
        return "down"

    def draw(self, screen, enemy, pixel_pos, animation_time: float) -> pygame.Rect:
        frames = self.frames[enemy.name, self.direction(enemy)]
        # wave_elapsed is the existing simulation clock: combat speed applies,
        # but enemy speed, slows, distance and render frequency do not set FPS.
        index = int(max(0.0, animation_time) * self.ANIMATION_FPS) % len(frames)
        image = frames[index]
        # The route describes the contact point on the ground, including for
        # larger bosses, so sprites share the normal enemy foot anchor.
        rect = image.get_rect(midbottom=pixel_pos)
        screen.blit(image, rect)
        return rect
