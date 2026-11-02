# 월하사신 PPO AI 발표 시연 (`ai_demo/`)

학습된 PPO 모델이 **실제 월하사신 게임 화면**에서 준비 단계 행동(소환·강화·판매·소동 시작)을 고르고,
전투는 기존 게임 엔진과 Pygame 애니메이션으로 진행되는 독립 실행 프로그램입니다.
기존 `main.py`, `game/`, `display/`, `scripts/ppo.py`, `results/`는 수정하지 않습니다.

## 실행

```bash
pip install -r requirements.txt -r requirements-ppo.txt   # pygame, torch, numpy, matplotlib

python -m ai_demo.main                                     # 기본: results/seungyeon_1300k/ppo_best.pt
python -m ai_demo.main --list                              # 실험 폴더별 실제 평가 수치 확인
python -m ai_demo.main --run results/hyeonkyu_1000k --model ppo_policy.pt --seed 7 --speed 2
python -m ai_demo.main --fullscreen --speed 5 --auto-next 8
```

| 인자 | 기본값 | 설명 |
|---|---|---|
| `--run` | `results/seungyeon_1300k` | 학습 결과 폴더 (`--model`에 경로를 주면 그 폴더) |
| `--model` | `ppo_best.pt` | 모델 파일 이름 또는 경로 (`ppo_policy.pt`도 가능) |
| `--seed` | 실험의 첫 평가 시드(`run.seed + 100000`) | 첫 판 시드. 같은 모델·시드면 같은 게임이 재현됩니다 |
| `--greedy` | 끔(샘플링) | 확률이 가장 큰 행동만 고르기 |
| `--speed` | `2` | 시작 배속 (1 / 1.5 / 2 / 5, 게임의 배속 단계와 같음) |
| `--think` | `0.6` | 고른 행동을 화면에 보여 주는 시간(초, 1배속 기준). 결과에는 영향 없음 |
| `--auto-next` | `0` | 게임이 끝나고 N초 뒤 다음 시드로 자동 시작 (0이면 N 키를 기다림) |
| `--fullscreen` | 끔 | 전체 화면으로 시작 |
| `--log-dir` / `--no-log` | `ai_demo/logs/` | 시연 행동 기록 CSV 저장 위치 / 저장 안 함 |

## 조작

| 키 | 동작 |
|---|---|
| `F1` / `F2` / `Tab` | AI 플레이 화면 / 학습 그래프 화면 (그래프 화면에서는 플레이가 잠시 멈춤) |
| `Space` | 일시정지 |
| `S` | 배속 변경 (전투 중에는 게임의 `CYCLE_SPEED`를 그대로 사용) |
| 마우스 휠 | (최근 행동 기록 위에서) 이번 판 전체 행동 기록 스크롤 |
| `H` | 게임판 위에 슬롯별 소환 횟수 표시 |
| `T` | 전략 분석 범위: 이번 판 ↔ 시연 누적 |
| `N` / `R` | 다음 시드로 새 게임 / 같은 시드로 다시 |
| `G`, `←` `→` | (그래프 화면) 원본 PNG 그래프 보기 / 넘기기 |
| `D` | 맵 디버그 (기존 게임 기능, 슬롯 번호 표시) |
| `F11` | 전체 화면 전환 |
| `ESC` 두 번 | 종료 |

## 화면 구성

- **상단**: 실험 이름, 모델 파일, 학습 Step, 평가 클리어율, 시드. 모두 결과 폴더의 실제 파일에서 읽고, 확인할 수 없으면 `확인 불가`로 표시합니다.
  - `ppo_best.pt`: `checkpoint.pt`의 `run.best`(저장 시점·정기 평가 클리어율). 단, checkpoint의 학습 Step이 CSV와 다르면 쓰지 않습니다.
  - `ppo_policy.pt`: `final_eval.csv`의 PPO 정책 결과로 계산한 최종 평가 클리어율.
- **가운데 왼쪽**: 기존 게임 화면(`display.renderer.Renderer`를 그대로 사용, 0.9배). AI가 고른 슬롯에 표시, 실행 결과(소환·강화·판매)가 떠오르는 표시.
- **아래**: 현재 AI 행동(고른 행동, 정책 확률, 확률 상위 3개), 최근 행동 기록, 이번 판 누적 횟수, 준비/전투/정산 상태. 게임이 끝나면 도달 소동·클리어 여부·잔여 결계·골드·행동 횟수.
- **오른쪽 – AI 전략 분석(항상 표시)**: 소환·강화·판매 비율, 실제 게임판 슬롯 위치 위의 소환/강화 히트맵, 소동별 행동 구성, 강화 후 레벨과 소환된 사신 분포.
- **학습 그래프(F2)**: `episodes.csv`(Episode Reward·도달 소동 + 20판 이동평균), `evaluations.csv`(Step별 클리어율, ppo_best 저장 시점), `updates.csv`(approx_kl·clip_fraction·explained_variance), `final_eval.csv`(PPO vs 무작위 정책). `G`로 `scripts/ppo.py`가 저장한 원본 PNG를 그대로 볼 수 있습니다.

## 데이터 구분

- **학습 기록**: `results/<실험>/`의 파일만 읽습니다. 쓰지 않습니다.
- **시연 기록**: 시연 중 실제로 실행된 행동만 집계하고 `ai_demo/logs/session_<시각>_actions.csv`, `_episodes.csv`에 저장합니다(`.gitignore`의 `logs/`에 포함).
- AI는 **소환할 슬롯**만 고릅니다. 사신 종류는 게임 난수(시드)로 정해집니다.
- AI는 **준비 단계에서만** 행동을 고릅니다. 전투는 게임 엔진이 자동으로 진행합니다.

## 평가 환경과 같은 결과가 나오는 이유

- 관측값·행동 마스크·소환/강화/판매 처리는 `scripts/ppo.py`의 `GuardianEnv`를 그대로 호출합니다(`ai_demo/ppo_bridge.py`).
- 행동 뽑기는 `play_one()`과 같은 식입니다: 마스크한 확률에서 판 시드로 고정한 `torch.Generator`로 `multinomial`.
- 소동 시작은 `_play_wave()`처럼 소환 연출이 끝난 뒤 `START_WAVE`, 정산 뒤 `CONTINUE`. 엔진은 고정 간격(1/120초)으로만 계산하므로 프레임 길이·배속·`--think`가 결과를 바꾸지 않습니다.

확인 방법:

```bash
python -m ai_demo.verify --model ppo_policy.pt --seeds 102026 102029   # play_one / final_eval.csv와 대조
python -m unittest tests.test_ai_demo
```

`ppo_policy.pt`로 평가 시드를 실행하면 게임 종료 화면에 `final_eval.csv`와의 일치 여부도 표시됩니다.

## 파일

| 파일 | 역할 |
|---|---|
| `main.py` | 실행 진입점, 창·화면 전환·키 입력 |
| `controller.py` | AI 자동 플레이 진행기 (Pygame 없음) |
| `ppo_bridge.py` | `scripts/ppo.py` 불러오기, 모델 로드, 행동 선택 |
| `experiment.py` | 학습 결과 폴더 읽기, 모델 정보 |
| `stats.py` | 시연 행동 집계·기록 |
| `play_view.py` | 플레이 화면 (AI 행동, 전략 분석) |
| `graph_view.py`, `charts.py` | 학습 그래프 화면 |
| `theme.py` | 글꼴·색·배치 |
| `verify.py` | 평가 환경과의 일치 확인 |
