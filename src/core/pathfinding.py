import heapq
from typing import List, Tuple, Dict, Any, Optional, Set, cast


def astar(
    start: Tuple[int, int],
    goal: Tuple[int, int],
    walls: List[List[int]],
    width: int,
    height: int,
    wall_set: Optional[Set[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    """A* pathfinding algorithm. Returns list of (x, y) tuples forming the path."""
    if wall_set is None:
        wall_set = set(map(tuple, walls))

    def heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    start = tuple(start)  # type: ignore[assignment]
    goal = tuple(goal)  # type: ignore[assignment]

    open_set: List[Tuple[float, Tuple[int, int]]] = []
    heapq.heappush(open_set, (0, start))
    came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
    g_score: Dict[Tuple[int, int], float] = {start: 0}

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == goal:
            path: List[Tuple[int, int]] = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path

        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            neighbor = (current[0] + dx, current[1] + dy)
            if not (0 <= neighbor[0] < width and 0 <= neighbor[1] < height):
                continue
            if neighbor in wall_set:
                continue

            tentative_g = g_score[current] + 1
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + heuristic(neighbor, goal)
                heapq.heappush(open_set, (f, neighbor))

    return []


def next_action_toward(
    bot_id: int,
    pos: List[int],
    target: List[int],
    walls: List[List[int]],
    width: int,
    height: int,
    wall_set: Optional[Set[Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    """Returns the first action to take to move toward target using A*."""
    path = astar(
        cast(Tuple[int, int], tuple(pos)),
        cast(Tuple[int, int], tuple(target)),
        walls,
        width,
        height,
        wall_set=wall_set,
    )
    if not path:
        return {"bot": bot_id, "action": "wait"}

    nx, ny = path[0]
    x, y = pos
    if nx == x and ny == y - 1:
        return {"bot": bot_id, "action": "move_up"}
    if nx == x and ny == y + 1:
        return {"bot": bot_id, "action": "move_down"}
    if nx == x - 1 and ny == y:
        return {"bot": bot_id, "action": "move_left"}
    if nx == x + 1 and ny == y:
        return {"bot": bot_id, "action": "move_right"}
    return {"bot": bot_id, "action": "wait"}


def adjacent_walkable(
    item_pos: List[int],
    walls: List[List[int]],
    width: int,
    height: int,
    wall_set: Optional[Set[Tuple[int, int]]] = None,
) -> List[List[int]]:
    """Returns list of walkable floor tiles adjacent to a shelf item."""
    if wall_set is None:
        wall_set = set(map(tuple, walls))
    ix, iy = item_pos
    result: List[List[int]] = []
    for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
        nx, ny = ix + dx, iy + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in wall_set:
            result.append([nx, ny])
    return result
