from itertools import combinations, permutations
from typing import List, Dict, Any, Tuple, Optional, cast

from ..core.pathfinding import astar, adjacent_walkable
from .base import BaseAgent


class AssignmentAgent(BaseAgent):
    """Agent for optimal bot-to-item assignment (bottleneck minimization)."""

    def decide(
        self, bot: Dict[str, Any], state: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"bot": bot["id"], "action": "wait"}


def global_assign(
    collecting_bots: List[Dict[str, Any]],
    remaining_types: List[str],
    all_items: List[Dict[str, Any]],
    base_walls: List[List[int]],
    width: int,
    height: int,
    zones: Optional[List[List[int]]] = None,
) -> Dict[int, List[Tuple[Dict[str, Any], Optional[List[int]]]]]:
    """
    Assigns each collecting bot a multi-item route (up to 3 items).

    Uses brute-force for ≤6 bots (bottleneck-optimal, single item),
    and greedy auction + route extension for larger counts.

    Args:
        base_walls: Static walls only (no items). Used for adjacency.

    Returns:
        Dict mapping bot_id -> [(item, adj_target), ...]
    """
    if not collecting_bots or not remaining_types:
        return {}

    # Count needed types
    type_counts: Dict[str, int] = {}
    for t in remaining_types:
        type_counts[t] = type_counts.get(t, 0) + 1

    # Items on floor per type
    items_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for item in all_items:
        if item["type"] in type_counts:
            items_by_type.setdefault(item["type"], []).append(item)

    # Build slot list (one slot per needed item, capped by availability)
    slots: List[str] = []
    for t, cnt in type_counts.items():
        avail = len(items_by_type.get(t, []))
        slots.extend([t] * min(cnt, avail))
    if not slots:
        return {}

    k = min(len(collecting_bots), len(slots))
    slots = slots[:k]

    # Items are walls for A* (bots can't walk through them)
    full_walls = base_walls + [i["position"] for i in all_items]

    # Delivery cost: manhattan from item position to its nearest drop-off zone.
    # Encourages bots near each zone to collect items in that zone's area.
    _zones = zones or [[1, 16]]

    def delivery_cost(item_pos: List[int]) -> float:
        ix, iy = item_pos
        return min(abs(z[0] - ix) + abs(z[1] - iy) for z in _zones)

    # Precompute A* distances: (bot_id, item_id) -> (total_trip_cost, best_adj)
    # total_trip_cost = dist(bot→item_adj) + dist(item→nearest_zone)
    # Pre-filter by manhattan to cap A* calls.
    TOP_K = 4
    astar_cache: Dict[Tuple[int, int], Tuple[float, Optional[List[int]]]] = {}

    for bot in collecting_bots:
        bx, by = bot["position"]
        for t in set(type_counts.keys()):
            items = items_by_type.get(t, [])
            sorted_items = sorted(
                items,
                key=lambda i: abs(i["position"][0] - bx) + abs(i["position"][1] - by),
            )
            for item in sorted_items[:TOP_K]:
                key = (bot["id"], item["id"])
                if key in astar_cache:
                    continue
                adjs = adjacent_walkable(item["position"], full_walls, width, height)
                best_d: float = float("inf")
                best_a: Optional[List[int]] = None
                for a in adjs:
                    path = astar(
                        bot["position"],
                        cast(Tuple[int, int], tuple(a)),
                        full_walls,
                        width,
                        height,
                    )
                    d = len(path) if path else float("inf")
                    if d < best_d:
                        best_d, best_a = d, a
                # Total trip cost: travel to item + deliver to nearest zone
                total = best_d + delivery_cost(item["position"]) if best_d < float("inf") else float("inf")
                astar_cache[key] = (total, best_a)

    if len(collecting_bots) <= 6:
        return _brute_force_assign(collecting_bots, slots, items_by_type, astar_cache)
    return _greedy_assign(
        collecting_bots, type_counts, items_by_type, astar_cache, k, full_walls, width, height
    )


def _brute_force_assign(
    collecting_bots: List[Dict[str, Any]],
    slots: List[str],
    items_by_type: Dict[str, List[Dict[str, Any]]],
    astar_cache: Dict[Tuple[int, int], Tuple[float, Optional[List[int]]]],
) -> Dict[int, List[Tuple[Dict[str, Any], Optional[List[int]]]]]:
    """Brute-force optimal assignment minimizing bottleneck. Used for ≤6 bots."""
    k = len(slots)
    bot_ids = [b["id"] for b in collecting_bots]
    best_bottleneck: float = float("inf")
    best_assign: Dict[int, List[Tuple[Dict[str, Any], Optional[List[int]]]]] = {}

    for bot_combo in combinations(range(len(collecting_bots)), k):
        for slot_perm in permutations(range(k), k):
            bottleneck = 0.0
            candidate: Dict[int, Tuple[Dict[str, Any], Optional[List[int]]]] = {}
            type_used: Dict[str, set] = {}
            valid = True

            for bi_idx, si in zip(bot_combo, slot_perm):
                bot_id = bot_ids[bi_idx]
                t = slots[si]
                used = type_used.setdefault(t, set())
                available = [
                    i
                    for i in items_by_type[t]
                    if i["id"] not in used and (bot_id, i["id"]) in astar_cache
                ]
                if not available:
                    valid = False
                    break
                best_item = min(
                    available, key=lambda i: astar_cache[(bot_id, i["id"])][0]
                )
                d, a = astar_cache[(bot_id, best_item["id"])]
                if d == float("inf"):
                    valid = False
                    break
                used.add(best_item["id"])
                bottleneck = max(bottleneck, d)
                candidate[bot_id] = (best_item, a)

            if valid and bottleneck < best_bottleneck:
                best_bottleneck = bottleneck
                # Wrap single item in list for uniform interface
                best_assign = {bid: [val] for bid, val in candidate.items()}

    return best_assign


def _greedy_assign(
    collecting_bots: List[Dict[str, Any]],
    type_counts: Dict[str, int],
    items_by_type: Dict[str, List[Dict[str, Any]]],
    astar_cache: Dict[Tuple[int, int], Tuple[float, Optional[List[int]]]],
    k: int,
    full_walls: List[List[int]],
    width: int,
    height: int,
) -> Dict[int, List[Tuple[Dict[str, Any], Optional[List[int]]]]]:
    """
    Greedy multi-item route assignment for large bot counts (nightmare: 20 bots).

    Phase 1: Assign the closest first item to each bot (min A* distance).
    Phase 2: Extend each bot's route with additional items (up to capacity)
             nearest to the previous item's position (manhattan).
    """
    assigned: Dict[int, List[Tuple[Dict[str, Any], Optional[List[int]]]]] = {}
    assigned_bot_ids: set = set()
    assigned_item_ids: set = set()
    type_remaining = dict(type_counts)

    # --- Phase 1: First item per bot ---
    for _ in range(k):
        best_cost: float = float("inf")
        best_bot: Optional[Dict[str, Any]] = None
        best_item: Optional[Dict[str, Any]] = None
        best_adj: Optional[List[int]] = None

        for bot in collecting_bots:
            if bot["id"] in assigned_bot_ids:
                continue
            for t in list(type_remaining.keys()):
                for item in items_by_type.get(t, []):
                    if item["id"] in assigned_item_ids:
                        continue
                    key = (bot["id"], item["id"])
                    if key not in astar_cache:
                        continue
                    d, adj = astar_cache[key]
                    if d < best_cost:
                        best_cost = d
                        best_bot = bot
                        best_item = item
                        best_adj = adj

        if best_bot is None or best_item is None:
            break

        assigned[best_bot["id"]] = [(best_item, best_adj)]
        assigned_bot_ids.add(best_bot["id"])
        assigned_item_ids.add(best_item["id"])
        t = best_item["type"]
        type_remaining[t] -= 1
        if type_remaining[t] <= 0:
            del type_remaining[t]

    # --- Phase 2: Extend routes with additional items (up to bot capacity) ---
    for bot in collecting_bots:
        if bot["id"] not in assigned or not type_remaining:
            continue

        route = assigned[bot["id"]]
        # Remaining capacity: total 3 minus already-in-inventory minus assigned route
        capacity_left = 3 - len(bot["inventory"]) - len(route)

        for _ in range(capacity_left):
            if not type_remaining:
                break

            # Navigate from the pickup position of the last assigned item
            lx, ly = route[-1][0]["position"]

            best_cost = float("inf")
            best_item = None
            best_adj = None

            for t in list(type_remaining.keys()):
                for item in items_by_type.get(t, []):
                    if item["id"] in assigned_item_ids:
                        continue
                    ix, iy = item["position"]
                    # Manhattan from last item's position (fast proxy for route cost)
                    d = abs(ix - lx) + abs(iy - ly)
                    if d < best_cost:
                        best_cost = d
                        best_item = item
                        # Prefer cached adj; fall back to computed adjacency
                        key = (bot["id"], item["id"])
                        if key in astar_cache:
                            best_adj = astar_cache[key][1]
                        else:
                            adjs = adjacent_walkable(item["position"], full_walls, width, height)
                            best_adj = (
                                min(adjs, key=lambda a: abs(a[0] - lx) + abs(a[1] - ly))
                                if adjs else None
                            )

            if best_item is None:
                break

            route.append((best_item, best_adj))
            assigned_item_ids.add(best_item["id"])
            t = best_item["type"]
            type_remaining[t] -= 1
            if type_remaining[t] <= 0:
                del type_remaining[t]

    return assigned
