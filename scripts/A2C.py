"""월하사신 A2C 학습. 게임 환경과 보상은 ppo.py와 동일하게 재사용한다.

실행: python scripts/A2C.py
기본: penalty_detail.json의 공통 수치, 누적 100,000 Step, results/a2c_pgh.
예시: python scripts/A2C.py --total-timesteps 200000
      python scripts/A2C.py --output-dir results/a2c_test --set ppo.num_envs=2

동기식 병렬 수집 후 전체 배치로 한 번만 갱신한다. PPO ratio/clipping,
epochs/minibatch_size는 사용하지 않는다. GAE와 Adam은 PPO와 같은 설정이다.
--fresh는 기존 A2C 체크포인트를 읽지 않고 새로 시작한다.
"""

import argparse
import copy
import importlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=str(ROOT / 'scripts/ppo_configs/penalty_detail.json'))
    parser.add_argument('--total-timesteps', type=int, default=100_000, help='추가량이 아닌 누적 목표 Step')
    parser.add_argument('--output-dir', default=str(ROOT / 'results/a2c_pgh'))
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--set', action='append', default=[], metavar='SECTION.KEY=VALUE')
    return parser.parse_args(argv)


def load_core(args):
    """기존 설정 로더를 사용하고, spawn 워커에도 같은 설정을 전달한다."""
    if args.total_timesteps <= 0:
        raise ValueError('--total-timesteps는 양수여야 합니다.')
    original_argv = sys.argv
    os.environ.pop('PPO_CONFIG_JSON', None)
    sys.argv = [original_argv[0], '--config', str(Path(args.config).resolve())]
    for item in args.set:
        sys.argv += ['--set', item]
    # PPO 결과 폴더/학습량을 공유하지 않도록 별도 실행 인자로 덮어쓴다.
    for item in [f'run.total_timesteps={args.total_timesteps}',
                 'run.output_dir=' + json.dumps(str(Path(args.output_dir).resolve()))]:
        sys.argv += ['--set', item]
    if args.fresh:
        sys.argv += ['--set', 'run.resume=false']
    try:
        if 'scripts.ppo' in sys.modules:
            raise RuntimeError('설정 격리를 위해 A2C.py를 별도 프로세스로 실행하세요.')
        core = importlib.import_module('scripts.ppo')
    finally:
        sys.argv = original_argv
    for name in ['NUM_ENVS', 'ROLLOUT_STEPS', 'EVAL_GAMES', 'EVAL_EVERY_STEPS']:
        value = getattr(core, name)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f'{name}은 양의 정수여야 합니다.')
    return core


def a2c_update(model, optimizer, batch, advantages, returns, *, value_coef, entropy_coef, max_grad_norm):
    """L = -log pi(a|s) * A + c_v*(R-V)^2 - c_e*H. 배치당 optimizer.step 1회."""
    import numpy as np
    import torch
    from torch.distributions import Categorical

    device = next(model.parameters()).device
    obs = torch.as_tensor(np.asarray(batch['obs']), dtype=torch.float32, device=device)
    masks = torch.as_tensor(batch['masks'], dtype=torch.bool, device=device)
    actions = torch.as_tensor(batch['actions'], dtype=torch.long, device=device)
    targets = torch.as_tensor(returns, dtype=torch.float32, device=device).detach()
    adv = torch.as_tensor(advantages, dtype=torch.float32, device=device).detach()
    adv = (adv - adv.mean()) / (adv.std(unbiased=False) + 1e-8)
    logits, values = model(obs)
    distribution = Categorical(logits=logits.masked_fill(~masks, -1e9))
    actor_loss = -(distribution.log_prob(actions) * adv).mean()
    critic_loss = (targets - values).square().mean()
    entropy = distribution.entropy().mean()
    loss = actor_loss + value_coef * critic_loss - entropy_coef * entropy
    if not torch.isfinite(loss):
        raise RuntimeError('A2C 손실이 유한하지 않습니다.')
    optimizer.zero_grad()
    loss.backward()
    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
    if not torch.isfinite(grad_norm):
        raise RuntimeError('A2C gradient가 유한하지 않습니다.')
    optimizer.step()
    return dict(actor_loss=actor_loss.item(), critic_loss=critic_loss.item(),
                entropy=entropy.item(), grad_norm=float(grad_norm), total_loss=loss.item())


def save_config(core):
    used = copy.deepcopy(core.CONFIG)
    common = used.pop('ppo')
    for key in ['clip_eps', 'epochs', 'minibatch_size']:
        common.pop(key, None)
    common.update(optimizer='Adam', updates_per_rollout=1, normalize_advantage=True)
    used['a2c'] = common
    used['algorithm'] = 'A2C'
    used['config_source'] = os.environ.get('PPO_CONFIG_FILE')
    used['reward'] = {'profile': core.REWARD_PROFILE, **core.REWARD}
    used['a2c']['num_envs'] = core.NUM_ENVS
    used['a2c']['steps_per_env'] = core.ENV_STEPS
    used['a2c']['batch_steps'] = core.BATCH_STEPS
    core.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = core.OUTPUT_DIR / 'config.json'
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if previous.get('algorithm') != 'A2C':
            raise ValueError('기존 PPO 결과를 보존하려면 새로운 출력 폴더를 지정하세요.')
    path.write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding='utf-8')


def save_checkpoint(core, model, optimizer, run):
    core.torch.save({
        'algorithm': 'A2C', 'model': model.state_dict(), 'optimizer': optimizer.state_dict(), 'run': run,
        'rng': {'python': core.random.getstate(), 'numpy': core.np.random.get_state(),
                'torch': core.torch.get_rng_state()},
    }, core.OUTPUT_DIR / 'checkpoint.pt')


def restore(core, model, optimizer):
    path = core.OUTPUT_DIR / 'checkpoint.pt'
    if not core.RESUME or not path.exists():
        return core.new_run()
    checkpoint = core.torch.load(path, map_location=core.DEVICE, weights_only=False)
    if checkpoint.get('algorithm') != 'A2C':
        raise ValueError('A2C 체크포인트만 이어서 학습할 수 있습니다.')
    model.load_state_dict(checkpoint['model'])
    optimizer.load_state_dict(checkpoint['optimizer'])
    for group in optimizer.param_groups:
        group['lr'] = core.LR
    core.random.setstate(checkpoint['rng']['python'])
    core.np.random.set_state(checkpoint['rng']['numpy'])
    core.torch.set_rng_state(checkpoint['rng']['torch'])
    return checkpoint['run']


def save_best(core, model, run, summary):
    best = run.get('best')
    score = (summary['clear_rate'], summary['avg_reached'])
    if best and score <= (best['clear_rate'], best['avg_reached']):
        return
    run['best'] = {'timesteps': run['timesteps'], **summary}
    core.torch.save(model.state_dict(), core.OUTPUT_DIR / 'a2c_best.pt')


def train(core, pool):
    core.set_seed()
    core.torch.set_num_threads(1)
    model = core.ActorCritic().to(core.DEVICE)
    optimizer = core.torch.optim.Adam(model.parameters(), lr=core.LR)
    run = restore(core, model, optimizer)
    print(f'A2C | 목표 {core.TOTAL_TIMESTEPS:,} Step | 현재 {run["timesteps"]:,} Step', flush=True)
    print(f'설정: {os.environ.get("PPO_CONFIG_FILE")}\n저장: {core.OUTPUT_DIR}', flush=True)
    print(f'동기식 환경 {core.NUM_ENVS}개 × {core.ENV_STEPS} Step, 배치당 단일 갱신 (GAE + Adam)', flush=True)
    print('PPO clip_eps / epochs / minibatch_size는 사용하지 않습니다.', flush=True)
    print('보상(scale 적용 전): ' + json.dumps(core.REWARD, ensure_ascii=False), flush=True)
    pool.start(len(run['episodes']))
    while run['timesteps'] < core.TOTAL_TIMESTEPS:
        if run['timesteps'] >= run['next_eval']:
            summary = core.summarize(core.evaluate(model, pool))
            run['evals'].append({'timesteps': run['timesteps'], **summary})
            save_best(core, model, run, summary)
            core.print_eval('A2C 정기', run['timesteps'], summary)
            run['next_eval'] = run['timesteps'] + core.EVAL_EVERY_STEPS
        segments = pool.collect(model)
        parts = [core.compute_gae(s['batch']['rewards'], s['batch']['values'], s['batch']['dones'], s['last_value'])
                 for s in segments]
        advantages = core.np.concatenate([p[0] for p in parts])
        returns = core.np.concatenate([p[1] for p in parts])
        batch = {k: core.np.concatenate([s['batch'][k] for s in segments]) for k in segments[0]['batch']}
        stats = a2c_update(model, optimizer, batch, advantages, returns,
                           value_coef=core.VALUE_COEF, entropy_coef=core.ENTROPY_COEF,
                           max_grad_norm=core.MAX_GRAD_NORM)
        stats['explained_variance'] = core.explained_variance(batch['values'], returns)
        run['timesteps'] += len(batch['actions'])
        for segment in segments:
            for episode in segment['episodes']:
                run['episodes'].append({'episode': len(run['episodes']) + 1, 'timesteps': run['timesteps'], **episode})
        update = len(run['updates']) + 1
        run['updates'].append({'update': update, 'timesteps': run['timesteps'], **stats})
        save_checkpoint(core, model, optimizer, run)
        if update == 1 or update % core.LOG_EVERY == 0:
            recent = run['episodes'][-10:]
            text = (f'최근 {len(recent)}판 보상 {core.np.mean([e["reward"] for e in recent]):.3f}, '
                    f'도달 소동 {core.np.mean([e["reached"] for e in recent]):.2f}') if recent else '아직 끝난 판 없음'
            print(f'업데이트 {update}/{math.ceil(core.TOTAL_TIMESTEPS/core.BATCH_STEPS)} | '
                  f'{run["timesteps"]:,} Step | 끝난 판 {len(run["episodes"])} | {text} | '
                  f'EV {stats["explained_variance"]:.3f}', flush=True)
    core.torch.save(model.state_dict(), core.OUTPUT_DIR / 'a2c_policy.pt')
    return model, optimizer, run


def save_results(core, run, final):
    core.write_csv(core.OUTPUT_DIR / 'episodes.csv', run['episodes'],
                   ['episode','timesteps','reward','reached','cleared','won','life','gold','length','buy','upgrade','sell'])
    core.write_csv(core.OUTPUT_DIR / 'evaluations.csv', run['evals'],
                   ['timesteps','clear_rate','avg_reached','avg_life','avg_gold','avg_reward','avg_length','avg_buy','avg_upgrade','avg_sell'])
    core.write_csv(core.OUTPUT_DIR / 'updates.csv', run['updates'],
                   ['update','timesteps','actor_loss','critic_loss','entropy','total_loss','grad_norm','explained_variance'])
    core.write_csv(core.OUTPUT_DIR / 'final_eval.csv',
                   [{'policy': name, **result} for name, rs in final.items() for result in rs],
                   ['policy','seed','won','reached','cleared','life','gold','reward','length','buy','upgrade','sell'])
    core.setup_plot_style()
    core.plot_episode_trend(run, 'reward', '1. A2C 판별 누적 보상', '누적 보상', '1_episode_reward.png')
    core.plot_episode_trend(run, 'reached', '2. A2C 판별 도달 소동', '도달 소동', '2_episode_stage.png', ylim=(0,31))
    for key, title, filename in [('clear_rate','3. A2C 클리어율 (%)','3_clear_rate.png'),
                                 ('avg_life','4. A2C 평균 잔여 결계','4_remaining_life.png'),
                                 ('avg_gold','5. A2C 평균 잔여 골드','5_remaining_gold.png')]:
        core.plot_eval_trend(run, key, title, title, filename)
    fig, axes = core.plt.subplots(4, 1, figsize=(9,10), sharex=True)
    for ax, key in zip(axes, ['actor_loss','critic_loss','entropy','explained_variance']):
        ax.plot([u['timesteps'] for u in run['updates']], [u[key] for u in run['updates']])
        ax.set_ylabel(key)
    axes[0].set_title('6. A2C 학습 지표 (PPO KL / clip 지표 없음)')
    axes[-1].set_xlabel('Total Timesteps')
    fig.tight_layout()
    fig.savefig(core.OUTPUT_DIR / '6_a2c_stability.png')
    core.plt.close(fig)
    core.plot_final_summary(final, '7_final_summary.png')


def main(argv=None):
    args = parse_args(argv)
    core = load_core(args)
    save_config(core)
    with core.WorkerPool(core.NUM_ENVS) as pool:
        model, optimizer, run = train(core, pool)
        final = {}
        if core.COMPARE_RANDOM:
            final['무작위 정책'] = core.evaluate(None, pool)
        final['A2C 정책'] = core.evaluate(model, pool)
        summary = core.summarize(final['A2C 정책'])
        run['evals'] = [e for e in run['evals'] if e['timesteps'] != run['timesteps']]
        run['evals'].append({'timesteps': run['timesteps'], **summary})
        run['next_eval'] = run['timesteps'] + core.EVAL_EVERY_STEPS
        save_best(core, model, run, summary)
        save_checkpoint(core, model, optimizer, run)
        for name, results in final.items():
            core.print_eval(name, run['timesteps'], core.summarize(results))
        save_results(core, run, final)
    print(f'A2C 학습 및 평가 완료. CSV 4개, 그래프 7장 저장: {core.OUTPUT_DIR}', flush=True)


if __name__ == '__main__':
    main()
