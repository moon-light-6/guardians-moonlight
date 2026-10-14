# Random Tower Defense

[담당: 이서진 - 게임 엔진/통합]

Pygame으로 구현한 랜덤 타워 디펜스 게임입니다. Python으로 순수 게임 로직을 구현하고, Pygame으로 UI를 담당합니다.

## 설치 및 실행

### 1. 환경 설정
```bash
# Python 3.8 이상 필요
pip install -r requirements.txt
```

### 2. 게임 실행
```bash
python main.py
```

### 3. UI 없이 게임 시뮬레이션 (밸런스 테스트)
```bash
python scripts/balance.py
```

## 프로젝트 구조

- **game/**: 게임 로직 (Pygame 의존하지 않음)
  - `engine.py`: 게임 상태 관리 및 루프
  - `state.py`: 공통 게임 상태 정의
  - `tower.py`, `combat.py`: 타워 및 전투 시스템
  - `enemy.py`, `wave.py`: 몬스터 및 웨이브 시스템
  - `economy.py`, `actions.py`: 경제 및 행동 관리
  - `map.py`: 맵 및 경로 데이터

- **display/**: UI 및 렌더링 (Pygame 의존)
  - `renderer.py`: 화면 그리기
  - `ui.py`: UI 요소 (버튼, 패널)
  - `input_handler.py`: 마우스/키보드 입력 처리

- **data/**: 게임 데이터 (JSON)
  - `map.json`: 맵 정보
  - `towers.json`: 타워 능력치
  - `enemies.json`: 몬스터 정보
  - `stages.json`: 스테이지별 웨이브 정보

- **scripts/**: 시뮬레이션 및 검증 도구
  - `balance.py`: 자동 게임 실행 및 통계

- **tests/**: 단위 및 통합 테스트

## 협업 규칙

### 기본 규칙
1. **파일 소유자 존중**: 공통 파일 변경 시 담당자에게 먼저 문의
   - config.py 수정 → 박건희에게 알림
   - requirements.txt 수정 → 이서진에게 알림
   - README.md 수정 → 이서진에게 알림

2. **인터페이스 우선**: 구현 전에 함수 계약 확정

3. **공유 상태는 엔진을 통해 변경**: display/에서 게임 상태를 직접 수정하지 않음

4. **테스트는 각자 책임**: 기능 변경 시 관련 테스트 갱신

5. **작은 단위로 병합**: 동작하는 기능 단위로 통합

### 공통 파일 관리
- **config.py** (박건희): 밸런스 수정 시 게임 상수도 함께 조정
- **requirements.txt** (이서진): 새 라이브러리 추가 시 담당자를 통해 요청
- **README.md** (이서진): 설치/실행 방법 변경 시 동기화

## 개발 팀 및 역할 분담

### 게임 로직 (game/)

| 담당자 | 역할 | 주요 파일 |
|--------|------|---------|
| 이서진 | 게임 엔진/통합 | engine.py, state.py, main.py |
| 오승아 | 타워/전투 | tower.py, combat.py |
| 이승연 | 몬스터/웨이브 | enemy.py, wave.py |
| 윤재빈 | 경제/타워관리 | economy.py, actions.py |
| 박건희 | 맵/데이터/밸런스 | map.py, config.py |

### UI/렌더링 (display/)

| 담당자 | 역할 | 주요 파일 |
|--------|------|---------|
| 박현규 | Pygame UI/입력 | renderer.py, ui.py, input_handler.py |

### 데이터 및 테스트

| 담당자 | 역할 | 주요 파일 |
|--------|------|---------|
| 박건희 | 데이터/밸런스 | data/*, scripts/balance.py |
| 각자 | 테스트 | tests/test_*.py |

### 공통 파일 관리

| 파일 | 담당자 |
|------|--------|
| config.py | 박건희 (게임 상수) |
| requirements.txt | 이서진 (의존성) |
| README.md | 이서진 (문서) |
| game/__init__.py | 이서진 (API) |
| display/__init__.py | 박현규 (API) |
