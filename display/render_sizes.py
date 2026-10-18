"""Character sizes in screen pixels; these never affect game coordinates."""

from config import CELL_SIZE


TOWER_BASE_SIZE = (58, 58)
TOWER_SCALE = 1.2
TOWER_SIZE = tuple(round(side * TOWER_SCALE) for side in TOWER_BASE_SIZE)
# Map anchors are the painted platform's upper-face centres. Anchor sprite feet
# there directly; centering the sprite would sink it into the platform.
TOWER_BOTTOM_OFFSET = 0
TOWER_LEVEL_GAP = 2

NORMAL_ENEMY_TILE_RATIO = 1
NORMAL_ENEMY_DIAMETER = round(CELL_SIZE * NORMAL_ENEMY_TILE_RATIO)
NORMAL_ENEMY_RADIUS = NORMAL_ENEMY_DIAMETER // 2

LATE_BOSS_TOWER_RATIO = 1.3
LATE_BOSS_STAGES = (20, 25, 30)
# Round only the final result: 58 * 1.2 * 1.3 = 90.48 -> 90px.
LATE_BOSS_SIZE = tuple(
    round(side * TOWER_SCALE * LATE_BOSS_TOWER_RATIO) for side in TOWER_BASE_SIZE
)
