
import argparse
import csv
import sys
from pathlib import Path

import torch

# 프로젝트 루트를 Python 모듈 검색 경로에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--games", type=int, default=40)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    config_path = run_dir / "config.json"
    model_path = run_dir / "ppo_policy.pt"

    if not config_path.is_file() or not model_path.is_file():
        raise FileNotFoundError(
            f"config.json 또는 ppo_policy.pt가 없습니다: {run_dir}"
        )

    # 저장된 실험 설정으로 PPO 모듈 불러오기
    sys.argv = ["ppo.py", "--config", str(config_path)]
    from scripts import ppo

    # 학습하지 않고 행동 선택 방식만 Greedy로 변경
    ppo.EVAL_GREEDY = True

    model = ppo.ActorCritic().to(ppo.DEVICE)
    model.load_state_dict(
        torch.load(model_path, map_location="cpu", weights_only=True)
    )
    model.eval()

    results = []
    for i in range(args.games):
        seed = ppo.EVAL_SEED_BASE + i
        result = ppo.play_one(model, seed, stages=30)
        results.append(result)
        print(f"{i + 1}/{args.games}판 완료", flush=True)

    summary = ppo.summarize(results)

    print("\n=== Greedy 최종 평가 ===")
    for key, value in summary.items():
        print(f"{key}: {value:.2f}")

    output_path = run_dir / "greedy_eval.csv"
    fields = [
        "seed", "won", "reached", "cleared", "life",
        "gold", "reward", "length", "buy", "upgrade", "sell"
    ]

    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"\n평가 결과 저장: {output_path}")


if __name__ == "__main__":
    main()
