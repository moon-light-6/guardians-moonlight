"""Direction-aware normal enemy sprites, independent of game simulation."""

from pathlib import Path
import re

import pygame

from display.render_sizes import NORMAL_ENEMY_DIAMETER
from game.enemy import EnemyType


class EnemySpriteAnimator:
    # Use the supplied on-disk names without renaming the source assets.
    ENEMY_FOLDERS = {
        EnemyType.BASIC: "갓귀",
        EnemyType.FAST: "질풍귀",
        EnemyType.TANK: "철갑귀",
    }
    DIRECTIONS = ("front", "left", "right")
    ANIMATION_FPS = 8
    SPRITE_SIZE = (NORMAL_ENEMY_DIAMETER, NORMAL_ENEMY_DIAMETER)

    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else (
            Path(__file__).resolve().parents[1] / "assets" / "sprites" / "enemy"
        )
        self.frames = {}
        for enemy_type, folder in self.ENEMY_FOLDERS.items():
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
                    raise FileNotFoundError(f"No enemy animation frames: {directory}")
                raw[direction] = [pygame.image.load(str(path)).convert_alpha()
                                  for _, path in paths]
            for direction, frames in self._align_frames(raw).items():
                self.frames[enemy_type, direction] = frames

    @classmethod
    def _align_frames(cls, frames):
        """Keep one canvas, crop and scale for all frames/directions of a type.

        The FAST source canvases differ by direction. Center them on a shared
        canvas first, then remove only margins transparent in every frame.
        Never recenter or resize individual poses using their changing bounds.
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
            raise ValueError("Enemy animation contains no visible pixels")
        scale = min(cls.SPRITE_SIZE[0] / bounds.width,
                    cls.SPRITE_SIZE[1] / bounds.height)
        target = (max(1, round(bounds.width * scale)),
                  max(1, round(bounds.height * scale)))
        return {
            direction: [pygame.transform.smoothscale(image.subsurface(bounds), target)
                        for image in sequence]
            for direction, sequence in aligned.items()
        }

    @staticmethod
    def direction(enemy) -> str:
        if len(enemy.path) < 2:
            return "front"
        index = min(max(enemy.path_index, 0), len(enemy.path) - 2)
        start, end = enemy.path[index:index + 2]
        if end[0] > start[0]:
            return "right"
        if end[0] < start[0]:
            return "left"
        # Downward movement and any future upward movement use front assets.
        return "front"

    def draw(self, screen, enemy, pixel_pos, animation_time: float) -> pygame.Rect:
        frames = self.frames[enemy.enemy_type, self.direction(enemy)]
        # Same simulation clock as bosses/effects: speed-up applies, slows and
        # individual enemy movement speeds do not control animation FPS.
        index = int(max(0.0, animation_time) * self.ANIMATION_FPS) % len(frames)
        image = frames[index]
        rect = image.get_rect(center=pixel_pos)
        screen.blit(image, rect)
        return rect
