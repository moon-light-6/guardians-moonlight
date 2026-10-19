"""Character sizes in screen pixels; these never affect game coordinates."""

from config import CELL_SIZE


TOWER_BASE_SIZE = (58, 58)
TOWER_SCALE = 1.25
TOWER_SIZE = tuple(round(side * TOWER_SCALE) for side in TOWER_BASE_SIZE)
# 맵의 기준 좌표는 게임보드 발판 윗면의 중심을 나타냄.
# 타워 이미지의 발끝을 해당 좌표에 직접 맞춤.
# 이미지를 중심 기준으로 정렬하면 타워가 발판 안으로 파묻혀 보일 수 있음.
TOWER_BOTTOM_OFFSET = 0
TOWER_LEVEL_GAP = 2

# 타워 종류별 화면 픽셀 단위 위치 보정값
# 양수(+)는 아래로, 음수(-)는 위로 이동
# 딕셔너리의 키는 tower_data["type"]에 저장된 문자열과 일치해야 함.
TOWER_Y_OFFSETS = {
    "LIGHTNING": +8,  # 청룡
    "ARCHER": +18,     # 백호
    "CANNON": +10,     # 주작
    "ICE": +15,       # 현무
}

NORMAL_ENEMY_TILE_RATIO = 1.15
NORMAL_ENEMY_DIAMETER = round(CELL_SIZE * NORMAL_ENEMY_TILE_RATIO)
NORMAL_ENEMY_RADIUS = NORMAL_ENEMY_DIAMETER // 2

LATE_BOSS_TOWER_RATIO = 1.4
LATE_BOSS_STAGES = (20, 25, 30)
# Round only the final result: 58 * 1.2 * 1.3 = 90.48 -> 90px.
LATE_BOSS_SIZE = tuple(
    round(side * TOWER_SCALE * LATE_BOSS_TOWER_RATIO) for side in TOWER_BASE_SIZE
)
