"""
시연 환경과 기존 PPO 평가 환경이 같은 행동·같은 게임 결과를 내는지 화면 없이 확인한다.

  A. scripts/ppo.py의 play_one() (학습 때 평가에 쓴 함수 그대로)
  B. ai_demo의 DemoController (시연 화면과 같은 진행기). 프레임 길이를 무작위로 바꾸고 배속도 중간중간 바꾼다
  C. final_eval.csv에 기록된 결과 (ppo_policy.pt + 같은 시드 + 같은 행동 선택 방식일 때만)

실행 예:
  python -m ai_demo.verify --run results/seungyeon_1300k --model ppo_policy.pt --seeds 102026 102029
"""

import argparse
import random
import sys
import time
from pathlib import Path

from ai_demo.controller import DemoController
from ai_demo.experiment import DEFAULT_RUN, load_experiment
from ai_demo.ppo_bridge import PolicyAgent, load_policy, load_ppo_module, resolve_model_path
from ai_demo.stats import DemoStats

COMPARE_KEYS = ("won", "reached", "cleared", "life", "gold", "length", "buy", "upgrade", "sell")


def run_reference(ppo, model, seed, greedy):
    """play_one()을 그대로 돌리면서 고른 행동 번호만 옆에서 기록한다."""
    actions = []
    original_step = ppo.GuardianEnv.step

    def recording_step(env, action):
        actions.append(action)
        return original_step(env, action)

    saved_greedy = ppo.EVAL_GREEDY
    ppo.GuardianEnv.step = recording_step
    ppo.EVAL_GREEDY = greedy
    try:
        result = ppo.play_one(model, seed)
    finally:
        ppo.GuardianEnv.step = original_step
        ppo.EVAL_GREEDY = saved_greedy
    return result, actions


def run_demo(ppo, model, seed, greedy, frame_seed):
    """시연 진행기를 프레임 단위로 돌린다. 프레임 길이(1/240~0.1초)와 배속을 무작위로 바꾼다."""
    agent = PolicyAgent(ppo, model, greedy=greedy)
    controller = DemoController(ppo, agent, DemoStats(), think_seconds=0.0, settle_seconds=0.0)
    controller.new_game(seed)
    jitter = random.Random(frame_seed)
    actions, frames = [], 0
    while controller.result is None:
        if jitter.random() < 0.002:
            controller.cycle_speed()
        controller.update(jitter.uniform(1 / 240, 0.1))
        frames += 1
        for name, payload in controller.events:
            if name == "action":
                actions.append(payload.action)
        controller.events.clear()
    return controller.result, actions, frames


def main(argv=None):
    parser = argparse.ArgumentParser(description="시연 환경과 PPO 평가 환경의 일치 확인")
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN, help="학습 결과 폴더")
    parser.add_argument("--model", default="ppo_policy.pt", help="모델 파일 이름 또는 경로")
    parser.add_argument("--seeds", type=int, nargs="+", default=None,
                        help="확인할 시드들(기본: 실험의 평가 시드 앞 2개)")
    parser.add_argument("--greedy", action="store_true", help="확률이 가장 큰 행동만 고르기")
    args = parser.parse_args(argv)

    ppo = load_ppo_module()
    experiment = load_experiment(args.run)
    model_path = resolve_model_path(args.run, args.model)
    model = load_policy(ppo, model_path)
    seeds = args.seeds or [experiment.eval_seed_base or 102026, (experiment.eval_seed_base or 102026) + 1]
    print(f"모델: {model_path}  /  행동 선택: {'greedy' if args.greedy else 'sampling'}")

    failures = 0
    for seed in seeds:
        started = time.perf_counter()
        reference, reference_actions = run_reference(ppo, model, seed, args.greedy)
        demo, demo_actions, frames = run_demo(ppo, model, seed, args.greedy, frame_seed=seed * 7 + 1)
        same_actions = reference_actions == demo_actions
        diff = {key: (reference[key], demo[key]) for key in COMPARE_KEYS if reference[key] != demo[key]}
        recorded = experiment.recorded_result(model_path, seed, args.greedy)
        recorded_diff = None
        if recorded is not None:
            recorded_diff = {key: (recorded[key], demo[key]) for key in COMPARE_KEYS if recorded[key] != demo[key]}
        ok = same_actions and not diff and not recorded_diff
        failures += not ok
        summary = ", ".join(f"{key}={demo[key]}" for key in COMPARE_KEYS)
        print(f"[{'일치' if ok else '불일치'}] seed {seed}: 행동 {len(demo_actions)}개 "
              f"{'같음' if same_actions else '다름'}, 결과 {summary} "
              f"(프레임 {frames}, {time.perf_counter() - started:.1f}초)")
        if not same_actions:
            first = next((i for i, (a, b) in enumerate(zip(reference_actions, demo_actions)) if a != b),
                         min(len(reference_actions), len(demo_actions)))
            print(f"    첫 차이: {first}번째 결정 (평가 {reference_actions[first:first + 3]} / 시연 {demo_actions[first:first + 3]})")
        if diff:
            print(f"    play_one과 다른 값: {diff}")
        if recorded is None:
            print("    final_eval.csv 대조: 해당 없음(ppo_policy.pt·같은 시드·같은 선택 방식일 때만 가능)")
        else:
            print(f"    final_eval.csv 대조: {'일치' if not recorded_diff else f'불일치 {recorded_diff}'}")
    print(f"\n{len(seeds) - failures}/{len(seeds)}개 시드 일치")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
