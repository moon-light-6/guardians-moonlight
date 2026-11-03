"""
scripts/ppo.py를 고치지 않고 그대로 불러와서, 학습·평가 때와 같은 관측값·행동 마스크·신경망·행동 뽑기를 쓴다.

- 관측값과 마스크: ppo.GuardianEnv.observe() / valid_action_mask()
- 소환·강화·판매: ppo.GuardianEnv.step() (판매의 "선택 -> 판매 -> 확인" 3단계 포함)
- 행동 뽑기: ppo.play_one()과 같은 식(마스크한 확률에서 판 시드로 고정한 torch.Generator로 multinomial)
"""

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ai_demo import ROOT

PPO_SCRIPT = ROOT / "scripts" / "ppo.py"
_MODULE_NAME = "ai_demo_scripts_ppo"


class PolicyLoadError(Exception):
    """모델을 불러올 수 없을 때. 메시지는 화면에 그대로 보여 준다."""


def load_ppo_module():
    """scripts/ppo.py를 모듈로 한 번만 불러온다(torch, numpy, matplotlib 필요)."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    if not PPO_SCRIPT.is_file():
        raise PolicyLoadError(f"scripts/ppo.py를 찾을 수 없습니다: {PPO_SCRIPT}")
    # ppo.py는 import될 때 명령줄의 --config/--set과 환경 변수 PPO_CONFIG_JSON을 읽는다.
    # 시연 프로그램의 인자와 섞이지 않게 비워 두고 기본 설정으로 불러온 뒤 되돌린다.
    # (기본 설정의 보상 값은 시연에 쓰이지 않는다. 행동 선택은 관측값·마스크·신경망만으로 정해진다.)
    saved_argv = sys.argv
    saved_config = os.environ.pop("PPO_CONFIG_JSON", None)
    sys.argv = [saved_argv[0]]
    try:
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, PPO_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError as error:
            del sys.modules[_MODULE_NAME]
            raise PolicyLoadError(
                f"PPO 실행에 필요한 패키지가 없습니다: {error.name}  (pip install -r requirements-ppo.txt)"
            ) from error
        except BaseException:
            del sys.modules[_MODULE_NAME]
            raise
    finally:
        sys.argv = saved_argv
        os.environ.pop("PPO_CONFIG_JSON", None)
        if saved_config is not None:
            os.environ["PPO_CONFIG_JSON"] = saved_config
    return module


def load_policy(ppo, model_path: Path):
    """ppo_policy.pt / ppo_best.pt(state_dict)를 ActorCritic에 불러온다. 크기는 파일에서 읽는다."""
    import torch

    model_path = Path(model_path)
    if not model_path.is_file():
        raise PolicyLoadError(f"모델 파일이 없습니다: {model_path}")
    try:
        weights = torch.load(model_path, map_location="cpu", weights_only=True)
    except Exception as error:  # noqa: BLE001 - 어떤 이유든 화면에 원인을 보여 준다
        raise PolicyLoadError(f"모델 파일을 읽을 수 없습니다: {model_path.name} ({error})") from error
    if not isinstance(weights, dict) or "body.0.weight" not in weights or "actor.weight" not in weights:
        raise PolicyLoadError(f"PPO ActorCritic 가중치 파일이 아닙니다: {model_path.name}")

    hidden, obs_dim = weights["body.0.weight"].shape
    n_actions = weights["actor.weight"].shape[0]
    if (obs_dim, n_actions) != (ppo.OBS_DIM, ppo.NUM_ACTIONS):
        raise PolicyLoadError(
            f"모델 입력/출력 크기({obs_dim}, {n_actions})가 현재 게임 환경"
            f"({ppo.OBS_DIM}, {ppo.NUM_ACTIONS})과 다릅니다: {model_path.name}"
        )
    model = ppo.ActorCritic(obs_dim=obs_dim, n_actions=n_actions, hidden=hidden)
    try:
        model.load_state_dict(weights)
    except RuntimeError as error:
        raise PolicyLoadError(f"모델 구조가 scripts/ppo.py의 ActorCritic과 다릅니다: {error}") from error
    model.eval()
    return model


@dataclass
class Decision:
    """정책이 한 번 고른 결과. probs는 마스크를 적용한 실제 정책 확률이다."""
    action: int
    probability: float
    top: List[Tuple[int, float]] = field(default_factory=list)  # 확률 상위 행동 (행동 번호, 확률)
    valid_count: int = 0


class PolicyAgent:
    """ppo.play_one()과 똑같은 방식으로 행동을 고른다. 같은 모델·같은 시드면 같은 행동열이 나온다."""

    def __init__(self, ppo, model, greedy: bool = False):
        import torch

        self.ppo = ppo
        self.model = model
        self.greedy = greedy
        self._torch = torch
        self.generator = torch.Generator()
        # 평가 프로세스(_eval_worker)와 같은 조건. 작은 신경망이라 속도 차이는 없다.
        torch.set_num_threads(1)

    def reset(self, seed: int) -> None:
        # play_one(): generator = torch.Generator().manual_seed(seed)
        self.generator = self._torch.Generator().manual_seed(seed)

    def decide(self, obs, mask) -> Decision:
        torch = self._torch
        with torch.no_grad():
            logits, _ = self.model(torch.as_tensor(obs, device=self.ppo.DEVICE).unsqueeze(0))
            probs = self.ppo.masked_dist(
                logits, torch.as_tensor(mask, device=self.ppo.DEVICE).unsqueeze(0)
            ).probs[0]
        if self.greedy:
            action = int(probs.argmax().item())
        else:
            action = int(torch.multinomial(probs, 1, generator=self.generator).item())
        values, indices = probs.topk(3)
        top = [(int(i), float(v)) for v, i in zip(values.tolist(), indices.tolist()) if v > 0]
        return Decision(action, float(probs[action].item()), top, int(sum(mask)))


def resolve_model_path(run_dir: Optional[Path], model: Optional[str]) -> Path:
    """--model이 파일 이름만이면 실험 폴더 안에서, 경로면 그 경로를 쓴다."""
    name = model or "ppo_best.pt"
    path = Path(name)
    if run_dir is not None and not path.is_absolute() and len(path.parts) == 1:
        return Path(run_dir) / path
    return path
