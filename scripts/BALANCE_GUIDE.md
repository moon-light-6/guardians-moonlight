# 월하사신 맵 및 밸런스 도구

최신 guardians-moonlight/main의 인터페이스와 데이터 형식을 기준으로 한다.
GameMap의 정수 격자 경로, 슬롯 배치, grid_to_pixel/pixel_to_slot 변환을 유지한다.
data/*.json의 최신 수치와 스키마는 변경하지 않았다.
GameMap은 작업 디렉터리와 무관하게 data/map.json을 로드한다.
잘못된 경로, 슬롯 경계, 중복 및 경로 겹침은 ValueError로 거부하며 기존 맵을 보존한다.

## 실행

```sh
python scripts/balance.py --games 10 --stages 5 --output results/balance-latest.json
python scripts/balance.py --games 10 --stages 30 --output results/balance-30.json
python -m unittest discover -s tests -v
```

기본값은 최신 코드와 동일하게 10판, 30웨이브다.
최신 _prepare(game, state, rng) 정책과 reset(start_at_title=False),
정산 화면의 CONTINUE 처리를 사용한다. 스테이지와 보상은 엔진이 관리한다.
엔진 내부의 고정 시간 간격을 사용하며 한 웨이브는 최대 600초까지 진행한다.

결과의 stage/life/gold/kills/phase 키는 최신 main과 동일하다.
seed/status/error/survived_stages/stage_results는 분석용 추가 필드다.
stage는 엔진의 현재 웨이브 번호, survived_stages는 완료한 웨이브 수다.
5웨이브 완료 후 stage=6, survived_stages=5인 것은 정상이다.
목표 클리어율은 요청한 웨이브 수를 기준으로 계산한다.
게임 패배는 game_over, 실행 오류 및 시간 초과는 error로 구분하며
error 판은 통계에서 제외하고 프로그램 종료 코드 1을 반환한다.

JSON에는 웨이브별 골드 변화와 라이프 손실을 포함한다.
CSV에는 판별 요약을 저장한다. 구매/강화 정책의 결과이며 최적 전략의 성능은 아니다.
기존 results 파일과 가상환경은 덮어쓰지 않는다.

## 4줄 왕복 맵 적용

경로는 (19,1) → (0,1) → (0,5) → (18,5) → (18,9)
→ (0,9) → (0,13) → (19,13)으로 이어지는 87개 칸이다.
기존 24개 슬롯의 ID와 x 좌표를 유지한다. 첫째 줄 y=0은 유지하고
둘째~넷째 줄의 y를 4→3, 8→7, 12→11로 한 칸씩 올렸다.
경로와 타워의 전투 좌표는 모두 정수 좌표가 칸 중앙을 뜻한다.
get_slot_position은 1칸 슬롯에 (x,y)를 반환하고 grid_to_pixel에서
반 칸을 한 번만 더한다. 표시·클릭·공격 사거리가 같은 위치를 사용한다.
둘째~넷째 줄의 18개 슬롯은 위아래 수평 경로 모두 2~sqrt(5)칸 이내이며,
최소 사거리 2.5칸으로 양쪽 경로를 타격할 수 있다. 첫째 줄은 위쪽 경로를 담당한다.
경로가 길어졌으므로 이전 맵의 밸런스 통계와 구분해서 평가해야 한다.
