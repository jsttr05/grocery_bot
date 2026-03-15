from typing import Dict, Any, List, Tuple, Optional

from ..core.pathfinding import next_action_toward, adjacent_walkable
from ..core.state import GameState, get_needed_items, nearest_drop_off
from ..core.actions import random_move_action, deliver_toward
from .base import BaseAgent, DecisionContext
from .obstacle import yield_move


class DecisionAgent(BaseAgent):
    """Main decision-making agent for bot actions."""

    def decide(
        self, bot: Dict[str, Any], state: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"bot": bot["id"], "action": "wait"}


def decision_impl(
    bot: Dict[str, Any], state: GameState, ctx: DecisionContext
) -> Dict[str, Any]:
    """Core decision logic for a single bot."""
    x, y = bot["position"]
    pos = [x, y]
    # Use precomputed walls (walls + item positions) from ctx if available
    walls = ctx.full_walls if ctx.full_walls is not None else (state.walls + [i["position"] for i in state.items])
    wall_set = ctx.wall_set
    width = state.width
    height = state.height
    drop_off = ctx.zone_assignment if ctx.zone_assignment is not None else nearest_drop_off(pos, state)
    inventory = bot["inventory"]
    other_bots = [b for b in state.bots if b["id"] != bot["id"]]

    active = state.get_active_order()
    preview = state.get_preview_order()
    order_needed = get_needed_items(active) if active else []
    has_useful = any(t in order_needed for t in inventory)
    my_priority = ctx.priorities.get(bot["id"], 0)
    dist_to_drop = abs(drop_off[0] - x) + abs(drop_off[1] - y)
    rounds_remaining = ctx.rounds_remaining

    # End-game: if we can't make it to drop-off and back, deliver now
    if inventory and has_useful and rounds_remaining <= dist_to_drop + 3:
        return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

    # Round 0: spread bots across 4 directions (5 bots per direction)
    if state.round == 0:
        spread = [
            (0, -1, "move_up"),
            (1, 0, "move_right"),
            (0, 1, "move_down"),
            (-1, 0, "move_left"),
        ]
        dx, dy, aname = spread[bot["id"] % len(spread)]
        nx, ny = x + dx, y + dy
        _wset = wall_set if wall_set is not None else set(map(tuple, walls))
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in _wset:
            return {"bot": bot["id"], "action": aname}

    # Yield to higher-priority bot claiming our cell
    my_pos = (x, y)
    occupant_id = ctx.will_be_at.get(my_pos)
    if occupant_id is not None and occupant_id != bot["id"]:
        occupant_priority = ctx.priorities.get(occupant_id, 0)
        if occupant_priority > my_priority:
            occupant = next((b for b in state.bots if b["id"] == occupant_id), None)
            if occupant:
                return yield_move(
                    bot["id"], pos, occupant["position"],
                    walls, ctx.will_be_at, width, height,
                )

    # Stuck bots: random move to break deadlock
    if bot["id"] in ctx.stuck_bots:
        return random_move_action(bot["id"], pos, walls, width, height)

    # At drop-off: deliver or step away
    if [x, y] == drop_off:
        if inventory and has_useful:
            return {"bot": bot["id"], "action": ctx.deliver_action}
        _wset = wall_set if wall_set is not None else set(map(tuple, walls))
        other_positions = {tuple(b["position"]) for b in other_bots}
        for ddx, ddy, aname in [
            (0, -1, "move_up"),
            (1, 0, "move_right"),
            (-1, 0, "move_left"),
            (0, 1, "move_down"),
        ]:
            npos = (x + ddx, y + ddy)
            if npos not in _wset and npos not in other_positions:
                return {"bot": bot["id"], "action": aname}
        return {"bot": bot["id"], "action": "wait"}

    # Full inventory: deliver immediately
    if len(inventory) >= 3:
        return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

    # Very close to drop-off with useful items: deliver now rather than detour
    if has_useful and dist_to_drop <= 3:
        return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

    # No active order — fall through to preview pre-fetch
    if not active:
        pass

    order_fully_covered = not ctx.global_remaining

    # Before delivering: if there's room and a preview item is adjacent, grab it first
    if has_useful and len(inventory) < 3 and preview:
        preview_needed = get_needed_items(preview)
        for item in state.items:
            if item["type"] in preview_needed and item["id"] not in ctx.claimed:
                ix, iy = item["position"]
                if abs(ix - x) + abs(iy - y) == 1:
                    ctx.claimed.add(item["id"])
                    ctx.preview_covered.append(item["type"])
                    return {"bot": bot["id"], "action": "pick_up", "item_id": item["id"]}

    if order_fully_covered:
        if has_useful:
            return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)
    else:
        # Follow pre-computed multi-item route if available
        if ctx.assignment:
            item_ids_on_floor = {i["id"] for i in state.items}
            for assigned_item, adj_target in ctx.assignment:
                if assigned_item["id"] not in item_ids_on_floor:
                    continue  # Already picked up or taken by another bot

                ix, iy = assigned_item["position"]
                if abs(ix - x) + abs(iy - y) == 1:
                    return {"bot": bot["id"], "action": "pick_up", "item_id": assigned_item["id"]}

                if adj_target is not None:
                    return next_action_toward(bot["id"], pos, adj_target, walls, width, height, wall_set=wall_set)
                else:
                    adjs = adjacent_walkable(assigned_item["position"], walls, width, height, wall_set=wall_set)
                    if adjs:
                        target = min(adjs, key=lambda a: abs(a[0] - x) + abs(a[1] - y))
                        return next_action_toward(bot["id"], pos, target, walls, width, height, wall_set=wall_set)
            # All route items gone — fall through to greedy

        # Fallback greedy: what still needs collecting
        want = list(ctx.global_remaining)
        for t in ctx.covered_types:
            if t in want:
                want.remove(t)

        # Pick up adjacent unclaimed wanted item immediately
        for item in state.items:
            if item["type"] in want and item["id"] not in ctx.claimed:
                ix, iy = item["position"]
                if abs(ix - x) + abs(iy - y) == 1:
                    ctx.claimed.add(item["id"])
                    ctx.covered_types.append(item["type"])
                    return {"bot": bot["id"], "action": "pick_up", "item_id": item["id"]}

        # Deliver if useful and nothing left uncovered for this bot
        if has_useful and not want:
            return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

        # Move toward nearest unclaimed wanted item (A* to adjacent cell)
        best_item = None
        best_dist = float("inf")
        for item in state.items:
            if item["type"] in want and item["id"] not in ctx.claimed:
                adjs = adjacent_walkable(item["position"], walls, width, height, wall_set=wall_set)
                d = min(
                    (abs(a[0] - x) + abs(a[1] - y) for a in adjs), default=float("inf")
                )
                if d < best_dist:
                    best_dist = d
                    best_item = item

        if best_item:
            ctx.claimed.add(best_item["id"])
            ctx.covered_types.append(best_item["type"])
            adjs = adjacent_walkable(best_item["position"], walls, width, height, wall_set=wall_set)
            if adjs:
                target = min(adjs, key=lambda a: abs(a[0] - x) + abs(a[1] - y))
                return next_action_toward(bot["id"], pos, target, walls, width, height, wall_set=wall_set)

        if inventory and has_useful:
            return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

    # Preview pre-fetch: keep idle bots busy with the upcoming order.
    # Don't subtract all_inv_flat — allows redundant collection so more bots stay active.
    # ctx.preview_covered (within-round claims) still limits to needed count per type.
    if preview and len(inventory) < 3:
        preview_remaining = list(get_needed_items(preview))
        for t in ctx.preview_covered:
            if t in preview_remaining:
                preview_remaining.remove(t)

        best_item = None
        best_dist = float("inf")
        for item in state.items:
            if item["type"] in preview_remaining and item["id"] not in ctx.claimed:
                adjs = adjacent_walkable(item["position"], walls, width, height, wall_set=wall_set)
                d = min(
                    (abs(a[0] - x) + abs(a[1] - y) for a in adjs), default=float("inf")
                )
                if d < best_dist:
                    best_dist = d
                    best_item = item

        if best_item:
            ctx.claimed.add(best_item["id"])
            ctx.preview_covered.append(best_item["type"])
            ix, iy = best_item["position"]
            if abs(ix - x) + abs(iy - y) == 1:
                return {"bot": bot["id"], "action": "pick_up", "item_id": best_item["id"]}
            adjs = adjacent_walkable(best_item["position"], walls, width, height, wall_set=wall_set)
            if adjs:
                target = min(adjs, key=lambda a: abs(a[0] - x) + abs(a[1] - y))
                return next_action_toward(bot["id"], pos, target, walls, width, height, wall_set=wall_set)

    return {"bot": bot["id"], "action": "wait"}
