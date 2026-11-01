"""
시연 중 AI가 실제로 한 행동의 기록. 학습 기록(experiment.py)과 따로 관리한다.

행동 비율·슬롯 히트맵·소동별 행동 구성은 모두 여기 쌓인 실제 실행 횟수로만 계산한다.
"""

import csv
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import SLOT_COUNT

KIND_LABELS = {"start": "소동 시작", "buy": "소환", "upgrade": "강화", "sell": "판매"}
BUILD_KINDS = ("buy", "upgrade", "sell")  # 행동 비율에 넣는 행동(소동 시작은 따로 센다)


@dataclass
class ActionRecord:
    game: int               # 이번 시연에서 몇 번째 판인지(1부터)
    seed: int
    step: int               # 그 판에서 몇 번째 결정인지(1부터)
    stage: int
    kind: str               # start / buy / upgrade / sell
    action: int             # PPO 행동 번호(0~72)
    slot: Optional[int]     # 0부터 시작하는 슬롯 번호. 화면에는 +1 해서 보여 준다
    probability: float      # 고른 행동의 정책 확률
    detail: str
    gold_before: int
    gold_after: int
    tower_type: str = ""
    level_after: int = 0


class ActionStats:
    """행동 횟수 집계. 한 판(episode)용과 시연 전체(session)용을 따로 둔다."""

    def __init__(self):
        self.counts = Counter()
        self.slot_counts = {kind: [0] * SLOT_COUNT for kind in BUILD_KINDS}
        self.stage_counts: Dict[int, Counter] = defaultdict(Counter)
        self.upgrade_levels = Counter()  # 강화 후 레벨
        self.summon_types = Counter()    # 소환된 사신 종류(게임 난수로 정해짐)

    def add(self, record: ActionRecord) -> None:
        self.counts[record.kind] += 1
        self.stage_counts[record.stage][record.kind] += 1
        if record.kind in self.slot_counts and record.slot is not None:
            self.slot_counts[record.kind][record.slot] += 1
        if record.kind == "upgrade":
            self.upgrade_levels[record.level_after] += 1
        if record.kind == "buy" and record.tower_type:
            self.summon_types[record.tower_type] += 1

    @property
    def build_total(self) -> int:
        return sum(self.counts[kind] for kind in BUILD_KINDS)

    def ratio(self, kind: str) -> float:
        total = self.build_total
        return self.counts[kind] / total if total else 0.0


class DemoStats:
    def __init__(self, recent: int = 6):
        self.episode = ActionStats()
        self.session = ActionStats()
        self.recent = deque(maxlen=recent)
        self.results: List[dict] = []

    def new_game(self) -> None:
        self.episode = ActionStats()
        self.recent.clear()

    def add(self, record: ActionRecord) -> None:
        self.episode.add(record)
        self.session.add(record)
        self.recent.appendleft(record)


class SessionLogger:
    """시연 기록을 ai_demo/logs/에 CSV로 남긴다(학습 결과 폴더에는 쓰지 않는다)."""

    EPISODE_FIELDS = ("game", "seed", "model", "policy", "won", "reached", "cleared", "life", "gold",
                      "length", "start", "buy", "upgrade", "sell", "recorded_match")

    def __init__(self, directory: Optional[Path]):
        self.directory = Path(directory) if directory else None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.action_path = self.episode_path = None
        if self.directory:
            self.action_path = self.directory / f"session_{stamp}_actions.csv"
            self.episode_path = self.directory / f"session_{stamp}_episodes.csv"

    def _append(self, path: Optional[Path], fieldnames, row: dict) -> None:
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            new = not path.exists()
            with path.open("a", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
                if new:
                    writer.writeheader()
                writer.writerow(row)
        except OSError:
            # 기록 실패가 시연을 멈추면 안 된다. 다음부터 기록하지 않는다.
            self.action_path = self.episode_path = None

    def action(self, record: ActionRecord) -> None:
        self._append(self.action_path, [f.name for f in fields(ActionRecord)], asdict(record))

    def episode(self, result: dict) -> None:
        self._append(self.episode_path, self.EPISODE_FIELDS, result)
