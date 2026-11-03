"""
월하사신 PPO 발표 시연 프로그램

학습된 PPO 정책이 실제 월하사신 게임 화면에서 준비 단계 행동(소환·강화·판매·소동 시작)을 고르고,
전투는 기존 게임 엔진과 Pygame 애니메이션으로 진행한다.

실행: python -m ai_demo.main
"""

import sys
from pathlib import Path

# 저장소 루트(config.py, game/, display/, scripts/)를 어디서 실행하든 import할 수 있게 한다.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
