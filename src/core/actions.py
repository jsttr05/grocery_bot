import random
from typing import List, Dict, Any, Tuple

from .pathfinding import next_action_toward


def random_move_action(
    bot_id: int, pos: List[int], walls: List[List[int]], width: int, height: int
) -> Dict[str, Any]:
    """Return a random valid move action, else wait."""
    wall_set = set(map(tuple, walls))
    x, y = pos
    directions = [
        (0, -1, "move_up"),
        (0, 1, "move_down"),
        (-1, 0, "move_left"),
        (1, 0, "move_right"),
    ]
    random.shuffle(directions)
    for dx, dy, action_name in directions:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in wall_set:
            return {"bot": bot_id, "action": action_name}
    return {"bot": bot_id, "action": "wait"}


def get_next_pos(pos: List[int], action: str) -> Tuple[int, int]:
    """Calculate the next position based on the action."""
    x, y = pos
    return {
        "move_up": (x, y - 1),
        "move_down": (x, y + 1),
        "move_left": (x - 1, y),
        "move_right": (x + 1, y),
    }.get(action, (x, y))


def deliver_toward(
    bot_id: int,
    pos: List[int],
    drop_off: List[int],
    walls: List[List[int]],
    width: int,
    height: int,
    other_bots: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Navigate to drop-off, routing around other bots if possible."""
    other_pos = [b["position"] for b in other_bots]
    action = next_action_toward(bot_id, pos, drop_off, walls + other_pos, width, height)
    if action["action"] == "wait":
        action = next_action_toward(bot_id, pos, drop_off, walls, width, height)
    return action
