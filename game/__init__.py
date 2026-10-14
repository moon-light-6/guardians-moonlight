"""
[담당: 이서진 - 게임 엔진/통합]

Game 패키지: Pygame에 의존하지 않는 순수 게임 로직 모듈

공개 API:
- Game: 게임 엔진 메인 클래스
- GameState, GamePhase: 게임 상태 정의
- Action, ActionType: 게임 행동 정의
"""

from game.engine import Game
from game.state import GameState, GamePhase
from game.actions import Action, ActionType

__all__ = [
    "Game",
    "GameState",
    "GamePhase",
    "Action",
    "ActionType",
]
