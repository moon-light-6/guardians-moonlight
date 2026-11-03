"""
학습 결과 폴더(results/<실험>/)를 읽는다. 이 모듈의 값은 모두 "학습 기록"이며 시연 중 행동 데이터와 섞지 않는다.

scripts/ppo.py가 저장하는 파일:
  config.json      실제로 쓴 설정
  episodes.csv     학습 중 끝난 판마다 보상·도달 소동
  evaluations.csv  정기 평가(고정 시드)와 마지막 최종 평가의 클리어율 등
  updates.csv      PPO 업데이트마다 approx_kl, clip_fraction, explained_variance
  final_eval.csv   최종 평가(ppo_policy.pt)의 판별 결과. 무작위 정책 비교 포함
  checkpoint.pt    run["best"]: ppo_best.pt를 저장한 시점과 성적
  1_*.png ~ 7_*.png 그래프
없는 파일은 None으로 두고 화면에 "데이터 없음"으로 표시한다(임의로 만들지 않는다).
"""

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ai_demo import ROOT

RESULTS_DIR = ROOT / "results"
DEFAULT_RUN = RESULTS_DIR / "seungyeon_1300k"
PPO_POLICY_NAMES = {"ppo_policy.pt": "final", "ppo_best.pt": "best"}
FINAL_EVAL_POLICY = "PPO 정책"


def _number(value: str):
    if value in ("True", "False"):
        return value == "True"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() and "." not in value and "e" not in value.lower() else number


def read_csv(path: Path) -> Optional[List[Dict]]:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [{key: _number(value) for key, value in row.items()} for row in csv.DictReader(file)]


def columns(rows: Optional[List[Dict]], *keys) -> Optional[Dict[str, List]]:
    if not rows or any(key not in rows[0] for key in keys):
        return None
    return {key: [row[key] for row in rows] for key in keys}


@dataclass
class ModelInfo:
    """헤더에 보여 줄 모델 정보. 값이 None이면 화면에 '확인 불가'로 표시한다."""
    file_name: str
    kind: Optional[str]                 # "best" / "final" / None(알 수 없는 파일)
    steps: Optional[int] = None         # 이 신경망이 저장된 시점의 학습 Step
    total_steps: Optional[int] = None   # 실험 전체 학습 Step
    clear_rate: Optional[float] = None  # 그 시점 평가 클리어율(%)
    avg_reached: Optional[float] = None
    eval_games: Optional[int] = None
    source: str = ""                    # 값을 어디서 읽었는지


@dataclass
class Experiment:
    run_dir: Path
    config: Optional[dict] = None
    episodes: Optional[List[Dict]] = None
    evaluations: Optional[List[Dict]] = None
    updates: Optional[List[Dict]] = None
    final_eval: Optional[List[Dict]] = None
    checkpoint_run: Optional[dict] = None
    pngs: List[Path] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.run_dir.name

    @property
    def exists(self) -> bool:
        return self.run_dir.is_dir()

    @property
    def total_steps(self) -> Optional[int]:
        for rows in (self.updates, self.evaluations):
            if rows:
                return int(rows[-1]["timesteps"])
        return None

    @property
    def eval_games(self) -> Optional[int]:
        return (self.config or {}).get("eval", {}).get("games")

    @property
    def eval_greedy(self) -> Optional[bool]:
        return (self.config or {}).get("eval", {}).get("greedy")

    @property
    def eval_seed_base(self) -> Optional[int]:
        seed = (self.config or {}).get("run", {}).get("seed")
        # scripts/ppo.py: EVAL_SEED_BASE = RANDOM_SEED + 100_000
        return None if seed is None else seed + 100_000

    def best_record(self) -> Optional[dict]:
        """ppo_best.pt를 저장한 시점. checkpoint.pt의 run["best"]가 CSV와 맞을 때만 그 값을 쓴다."""
        best = (self.checkpoint_run or {}).get("best")
        eval_steps = {int(row["timesteps"]) for row in self.evaluations or []}
        if best and int(best["timesteps"]) in eval_steps and \
                (self.checkpoint_run or {}).get("timesteps") == self.total_steps:
            return {**best, "source": "checkpoint.pt run.best"}
        return None

    def final_policy_rows(self) -> Optional[List[Dict]]:
        if not self.final_eval:
            return None
        rows = [row for row in self.final_eval if row.get("policy") == FINAL_EVAL_POLICY]
        return rows or None

    def model_info(self, model_path: Path) -> ModelInfo:
        name = Path(model_path).name
        kind = PPO_POLICY_NAMES.get(name) if Path(model_path).parent.resolve() == self.run_dir.resolve() else None
        info = ModelInfo(name, kind, total_steps=self.total_steps, eval_games=self.eval_games)
        if kind == "best":
            best = self.best_record()
            if best:
                info.steps, info.clear_rate = int(best["timesteps"]), float(best["clear_rate"])
                info.avg_reached = float(best["avg_reached"])
                info.source = f"{best['source']} (정기 평가)"
        elif kind == "final":
            rows = self.final_policy_rows()
            if rows:
                info.steps = self.total_steps
                info.clear_rate = sum(bool(r["won"]) for r in rows) / len(rows) * 100
                info.avg_reached = sum(r["reached"] for r in rows) / len(rows)
                info.eval_games = len(rows)
                info.source = "final_eval.csv (최종 평가)"
        return info

    def recorded_result(self, model_path: Path, seed: int, greedy: bool) -> Optional[Dict]:
        """ppo_policy.pt로 같은 시드·같은 행동 선택 방식이면 final_eval.csv에 기록된 결과를 돌려준다(시연 결과 대조용)."""
        if PPO_POLICY_NAMES.get(Path(model_path).name) != "final" or self.eval_greedy is None \
                or bool(self.eval_greedy) != bool(greedy):
            return None
        if Path(model_path).parent.resolve() != self.run_dir.resolve():
            return None
        for row in self.final_policy_rows() or []:
            if int(row["seed"]) == seed:
                return row
        return None


def _load_checkpoint_run(path: Path, warnings: List[str]) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        import torch

        # 팀이 scripts/ppo.py로 저장한 파일. 기록(dict)과 난수 상태가 함께 있어 weights_only=False로 읽는다.
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        run = checkpoint.get("run", {})
        return {"timesteps": run.get("timesteps"), "best": run.get("best")}
    except Exception as error:  # noqa: BLE001
        warnings.append(f"checkpoint.pt를 읽지 못했습니다({error.__class__.__name__}).")
        return None


def load_experiment(run_dir: Path) -> Experiment:
    run_dir = Path(run_dir)
    experiment = Experiment(run_dir)
    if not run_dir.is_dir():
        experiment.warnings.append(f"학습 결과 폴더가 없습니다: {run_dir}")
        return experiment
    config_path = run_dir / "config.json"
    if config_path.is_file():
        experiment.config = json.loads(config_path.read_text(encoding="utf-8"))
    experiment.episodes = read_csv(run_dir / "episodes.csv")
    experiment.evaluations = read_csv(run_dir / "evaluations.csv")
    experiment.updates = read_csv(run_dir / "updates.csv")
    experiment.final_eval = read_csv(run_dir / "final_eval.csv")
    experiment.pngs = sorted(run_dir.glob("[0-9]_*.png"))
    for name, value in (("config.json", experiment.config), ("episodes.csv", experiment.episodes),
                        ("evaluations.csv", experiment.evaluations), ("updates.csv", experiment.updates),
                        ("final_eval.csv", experiment.final_eval)):
        if value is None:
            experiment.warnings.append(f"{name} 없음")

    experiment.checkpoint_run = _load_checkpoint_run(run_dir / "checkpoint.pt", experiment.warnings)
    if experiment.checkpoint_run and experiment.total_steps is not None \
            and experiment.checkpoint_run.get("timesteps") != experiment.total_steps:
        experiment.warnings.append(
            f"checkpoint.pt({experiment.checkpoint_run.get('timesteps')} Step)와 CSV({experiment.total_steps} Step)의 "
            "학습 Step이 다릅니다. ppo_best.pt 저장 시점은 확인 불가로 표시합니다."
        )
    return experiment


def list_experiments() -> List[Experiment]:
    """results/ 아래에서 PPO 모델이 있는 실험 폴더."""
    if not RESULTS_DIR.is_dir():
        return []
    return [load_experiment(path) for path in sorted(RESULTS_DIR.iterdir())
            if path.is_dir() and any((path / name).is_file() for name in PPO_POLICY_NAMES)]
