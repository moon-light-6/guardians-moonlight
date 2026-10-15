from pathlib import Path
import pygame


class TowerSpriteAnimator:
    """사신 4종의 대기/공격 애니메이션을 그리는 뷰 전용 클래스."""

    SPRITE_CONFIG = {
        "LIGHTNING": {"folder": "청룡", "effect": "lightning", "idle_start": 0, "attack_start": 0},
        "ICE": {"folder": "현무", "effect": "water", "idle_start": 0, "attack_start": 0},
        "ARCHER": {"folder": "백호", "effect": "claw", "idle_start": 0, "attack_start": 1},
        "CANNON": {"folder": "주작", "effect": "fire", "idle_start": 0, "attack_start": 0},
    }
    DIRECTIONS = ("NE", "NW", "SE", "SW")
    FRAME_COUNT = 4
    SPRITE_SIZE = (58, 58)
    IDLE_FRAME_MS = 180

    def __init__(self):
        self.root = Path(__file__).resolve().parents[1] / "assets" / "sprites"
        self.frames = {}
        self.last_directions = {}
        self._load_all_frames()

    def _load_all_frames(self):
        for tower_type, config in self.SPRITE_CONFIG.items():
            guardian = config["folder"]
            for motion, folder_name in (
                ("idle", f"{guardian}_대기_프레임"),
                ("attack", f"{guardian}_공격_프레임"),
            ):
                folder = self.root / guardian / folder_name / "frames"
                start_index = config[f"{motion}_start"]
                for direction in self.DIRECTIONS:
                    images = []
                    for index in range(self.FRAME_COUNT):
                        path = folder / f"{direction}_{index + start_index}.png"
                        if not path.is_file():
                            raise FileNotFoundError(f"스프라이트 파일 없음: {path}")
                        image = pygame.image.load(str(path)).convert_alpha()
                        images.append(pygame.transform.smoothscale(image, self.SPRITE_SIZE))
                    self.frames[(tower_type, motion, direction)] = images

    @staticmethod
    def _direction(start, end):
        dx, dy = end[0] - start[0], end[1] - start[1]
        return ("N" if dy < 0 else "S") + ("W" if dx < 0 else "E")

    @staticmethod
    def _same_position(a, b):
        return abs(a[0] - b[0]) < 0.001 and abs(a[1] - b[1]) < 0.001

    def _active_attack(self, tower_type, tower_pos, effects):
        kind = self.SPRITE_CONFIG[tower_type]["effect"]
        for effect in reversed(effects):
            if effect.get("kind") != kind:
                continue
            if effect.get("age", 0.0) >= effect.get("ttl", 0.0):
                continue
            origin = effect.get("from")
            if origin is not None and self._same_position(origin, tower_pos):
                return effect
        return None

    @staticmethod
    def _target_position(effect):
        if effect["kind"] == "lightning":
            points = effect.get("points", [])
            return points[0] if points else None
        return effect.get("to")

    def draw(self, screen, slot_id, tower_type, pixel_pos, tower_pos, effects):
        if tower_type not in self.SPRITE_CONFIG:
            return False

        direction_key = (slot_id, tower_type)
        effect = self._active_attack(tower_type, tower_pos, effects)
        direction = self.last_directions.get(direction_key, "SE")

        if effect:
            motion = "attack"
            target = self._target_position(effect)
            if target is not None:
                direction = self._direction(tower_pos, target)
                self.last_directions[direction_key] = direction
            progress = max(0.0, min(effect["age"] / max(effect["ttl"], 0.001), 0.999999))
            index = min(int(progress * self.FRAME_COUNT), self.FRAME_COUNT - 1)
        else:
            motion = "idle"
            index = (pygame.time.get_ticks() // self.IDLE_FRAME_MS) % self.FRAME_COUNT

        image = self.frames[(tower_type, motion, direction)][index]
        screen.blit(image, image.get_rect(center=(pixel_pos[0], pixel_pos[1] - 8)))
        return True