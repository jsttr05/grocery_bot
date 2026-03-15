from typing import Dict, Any, List, Tuple, Set

from .base import BaseAgent


class ObstacleAgent(BaseAgent):
    """Agent for obstacle avoidance and collision handling."""

    def decide(
        self, bot: Dict[str, Any], state: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"bot": bot["id"], "action": "wait"}


def yield_move(
    bot_id: int,
    pos: List[int],
    blocker_pos: List[int],
    walls: List[List[int]],
    will_be_at: Dict[Tuple[int, int], int],
    width: int,
    height: int,
) -> Dict[str, Any]:
    """
    Move out of a higher-priority bot's path.
    Tries: cascade, perpendicular, then any free cell.
    """
    x, y = pos
    bx, by = blocker_pos

    dx_in = x - bx
    dy_in = y - by

    options = [
        (dx_in, dy_in),
        (dy_in, dx_in),
        (-dy_in, -dx_in),
        (-dx_in, -dy_in),
    ]

    wall_set = set(map(tuple, walls))
    action_map: Dict[Tuple[int, int], str] = {
        (0, -1): "move_up",
        (0, 1): "move_down",
        (-1, 0): "move_left",
        (1, 0): "move_right",
    }

    for ddx, ddy in options:
        if (ddx, ddy) == (0, 0) or (ddx, ddy) not in action_map:
            continue
        nx, ny = x + ddx, y + ddy
        npos = (nx, ny)
        if (
            0 <= nx < width
            and 0 <= ny < height
            and npos not in wall_set
            and npos not in will_be_at
        ):
            return {"bot": bot_id, "action": action_map[(ddx, ddy)]}

    return {"bot": bot_id, "action": "wait"}


def detect_stuck_bots(
    bots: List[Dict[str, Any]],
    prev_positions: Dict[int, Tuple[int, int]],
    prev_prev_positions: Dict[int, Tuple[int, int]],
) -> Set[int]:
    """Detect bots that are stuck (same pos 2+ rounds or oscillating)."""
    stuck: Set[int] = set()
    for b in bots:
        cur = tuple(b["position"])
        prev = prev_positions.get(b["id"])
        pp = prev_prev_positions.get(b["id"])
        if prev == cur and pp == cur:
            stuck.add(b["id"])
        elif pp == cur and prev != cur:
            stuck.add(b["id"])
    return stuck
