import asyncio
import json
import websockets
import heapq
import random

WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJmZTI1M2E4Yy1iZGE4LTQ1ZGQtOTYwYS00Yzc4YjgxNDFjZjYiLCJ0ZWFtX2lkIjoiMmMxMGRjOTEtNTU0NC00MWMzLTkxNDctMDk1NjE2MmE0MDdkIiwibWFwX2lkIjoiMDVkZGMyODMtOTA5Ny00MzE0LTgyNGMtOTBiMzI2OWEzZDk1IiwibWFwX3NlZWQiOjcwMDMsImRpZmZpY3VsdHkiOiJoYXJkIiwiZXhwIjoxNzczNDAwMTIwfQ.9lc6uEu51iIJQuxM60XLiTlz4rX6M3aiKLmi64414ps"


def astar(start, goal, walls, width, height):
    wall_set = set(map(tuple, walls))

    def heuristic(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    start = tuple(start)
    goal = tuple(goal)

    open_set = []
    heapq.heappush(open_set, (0, start))
    came_from = {}
    g_score = {start: 0}

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == goal:
            path = []
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
            if tentative_g < g_score.get(neighbor, float('inf')):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + heuristic(neighbor, goal)
                heapq.heappush(open_set, (f, neighbor))

    return []

def random_move_action(bot_id, pos, walls, width, height):
    """Return a random valid move action, else wait."""
    wall_set = set(map(tuple, walls))
    x, y = pos
    directions = [(0, -1, "move_up"), (0, 1, "move_down"),
                  (-1, 0, "move_left"), (1, 0, "move_right")]
    random.shuffle(directions)
    for dx, dy, action_name in directions:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in wall_set:
            return {"bot": bot_id, "action": action_name}
    return {"bot": bot_id, "action": "wait"}


def next_action_toward(bot_id, pos, target, walls, width, height):
    path = astar(pos, target, walls, width, height)
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


def get_needed_items(order):
    needed = list(order["items_required"])
    for d in order["items_delivered"]:
        if d in needed:
            needed.remove(d)
    return needed


def nearest_drop_off(pos, state):
    zones = state.get("drop_off_zones", [state["drop_off"]])
    x, y = pos
    return min(zones, key=lambda z: abs(z[0] - x) + abs(z[1] - y))


def adjacent_walkable(item_pos, walls, width, height):
    """Walkable floor tiles adjacent to a shelf item."""
    wall_set = set(map(tuple, walls))
    ix, iy = item_pos
    result = []
    for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
        nx, ny = ix + dx, iy + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in wall_set:
            result.append([nx, ny])
    return result


def global_assign(collecting_bots, remaining_types, all_items, static_walls, width, height):
    """
    Optimal bot-to-item assignment minimising the bottleneck (max A* distance).

    Uses actual A* distances — valid because we're well within the 2-second budget.
    Only considers the closest items per type per bot to keep A* calls bounded.

    Returns {bot_id: (item, adj_target)}.
    """
    from itertools import combinations, permutations

    if not collecting_bots or not remaining_types:
        return {}

    # Brute-force is only tractable for small bot counts.
    # For larger counts (hard/expert/nightmare) return {} and let greedy fallback handle it.
    if len(collecting_bots) > 5:
        return {}

    # Count how many of each type we still need
    type_counts = {}
    for t in remaining_types:
        type_counts[t] = type_counts.get(t, 0) + 1

    # Items on the floor per type
    items_by_type = {}
    for item in all_items:
        if item["type"] in type_counts:
            items_by_type.setdefault(item["type"], []).append(item)

    # Build slot list (one slot per needed item, respecting caps by available items)
    slots = []
    for t, cnt in type_counts.items():
        avail = len(items_by_type.get(t, []))
        slots.extend([t] * min(cnt, avail))
    if not slots:
        return {}

    k = min(len(collecting_bots), len(slots))
    slots = slots[:k]

    # Precompute A* dist: (bot_id, item_id) -> (dist, best_adj)
    # Limit to the TOP_K nearest items per type per bot (by manhattan) to cap A* calls.
    TOP_K = 4
    astar_cache = {}
    for bot in collecting_bots:
        bx, by = bot["position"]
        for t in set(slots):
            items = items_by_type.get(t, [])
            # Pre-filter by manhattan before running A*
            sorted_items = sorted(items,
                key=lambda i: abs(i["position"][0]-bx) + abs(i["position"][1]-by))
            for item in sorted_items[:TOP_K]:
                key = (bot["id"], item["id"])
                if key in astar_cache:
                    continue
                adjs = adjacent_walkable(item["position"], static_walls, width, height)
                best_d, best_a = float('inf'), None
                for a in adjs:
                    path = astar(bot["position"], a, static_walls, width, height)
                    d = len(path) if path else float('inf')
                    if d < best_d:
                        best_d, best_a = d, a
                astar_cache[key] = (best_d, best_a)

    # Brute-force over bot subsets × slot permutations; minimise bottleneck.
    bot_ids = [b["id"] for b in collecting_bots]
    best_bottleneck = float('inf')
    best_assign = {}

    for bot_combo in combinations(range(len(collecting_bots)), k):
        for slot_perm in permutations(range(len(slots)), k):
            bottleneck = 0
            candidate = {}
            type_used = {}   # type -> set of item_ids already taken in this candidate
            valid = True

            for bi_idx, si in zip(bot_combo, slot_perm):
                bot_id = bot_ids[bi_idx]
                t = slots[si]
                used = type_used.setdefault(t, set())
                available = [i for i in items_by_type[t]
                             if i["id"] not in used
                             and (bot_id, i["id"]) in astar_cache]
                if not available:
                    valid = False
                    break
                best_item = min(available, key=lambda i: astar_cache[(bot_id, i["id"])][0])
                d, a = astar_cache[(bot_id, best_item["id"])]
                if d == float('inf'):
                    valid = False
                    break
                used.add(best_item["id"])
                bottleneck = max(bottleneck, d)
                candidate[bot_id] = (best_item, a)

            if valid and bottleneck < best_bottleneck:
                best_bottleneck = bottleneck
                best_assign = dict(candidate)

    return best_assign


def compute_priority(bot, order_needed, global_remaining):
    """Higher score = higher right-of-way. Delivering bots beat collecting bots."""
    has_useful = any(t in order_needed for t in bot["inventory"])
    if has_useful and not global_remaining:
        return 3  # delivering the last needed items — most critical
    if has_useful:
        return 2  # delivering something useful
    if bot["inventory"]:
        return 1  # has items (useless for current order)
    return 0      # empty, collecting


def get_next_pos(pos, action):
    x, y = pos
    return {"move_up": (x, y-1), "move_down": (x, y+1),
            "move_left": (x-1, y), "move_right": (x+1, y)}.get(action, (x, y))


def yield_move(bot_id, pos, blocker_pos, walls, will_be_at, width, height):
    """
    Move out of a higher-priority bot's path.
    Tries: cascade (same direction as blocker), perpendicular, then any free cell.
    """
    x, y = pos
    bx, by = blocker_pos
    # Vector from blocker toward me — moving in this direction cascades the queue
    dx_in, dy_in = x - bx, y - by
    options = [
        (dx_in, dy_in),    # cascade: keep moving in blocker's direction
        (dy_in, dx_in),    # perpendicular
        (-dy_in, -dx_in),  # perpendicular other side
        (-dx_in, -dy_in),  # retreat toward blocker (last resort)
    ]
    wall_set = set(map(tuple, walls))
    action_map = {(0,-1):"move_up",(0,1):"move_down",(-1,0):"move_left",(1,0):"move_right"}
    for ddx, ddy in options:
        if (ddx, ddy) == (0, 0) or (ddx, ddy) not in action_map:
            continue
        nx, ny = x + ddx, y + ddy
        npos = (nx, ny)
        if (0 <= nx < width and 0 <= ny < height
                and npos not in wall_set and npos not in will_be_at):
            return {"bot": bot_id, "action": action_map[(ddx, ddy)]}
    return {"bot": bot_id, "action": "wait"}


def deliver_toward(bot_id, pos, drop_off, walls, width, height, other_bots):
    """Navigate to drop-off, routing around other bots if possible."""
    other_pos = [b["position"] for b in other_bots]
    action = next_action_toward(bot_id, pos, drop_off, walls + other_pos, width, height)
    if action["action"] == "wait":  # blocked — try ignoring other bots
        action = next_action_toward(bot_id, pos, drop_off, walls, width, height)
    return action


def decide(bot, state, global_remaining, claimed=None, covered_types=None,
           priorities=None, will_be_at=None, stuck_bots=None, preview_covered=None,
           assignment=None):
    """
    Per-bot decision logic.
    global_remaining: order types still needed minus ALL bot inventories (pre-computed).
    claimed: set of item_ids targeted by other bots this round (fallback for unassigned bots).
    covered_types: item types other bots are committed to collecting this round.
    preview_covered: item types other bots are already fetching for the preview order.
    assignment: (item, adj_target) pre-computed by global_assign for this bot, or None.
    """
    if claimed is None:
        claimed = set()
    if covered_types is None:
        covered_types = []
    if preview_covered is None:
        preview_covered = []
    x, y = bot["position"]
    pos = [x, y]
    walls_base = state["grid"]["walls"]
    walls = walls_base + [item["position"] for item in state["items"]]
    width = state["grid"]["width"]
    height = state["grid"]["height"]
    drop_off = nearest_drop_off(pos, state)
    inventory = bot["inventory"]
    other_bots = [b for b in state["bots"] if b["id"] != bot["id"]]

    active = next((o for o in state["orders"] if o["status"] == "active"), None)
    preview = next((o for o in state["orders"] if o["status"] == "preview"), None)
    order_needed = get_needed_items(active) if active else []
    has_useful = any(t in order_needed for t in inventory)
    my_priority = (priorities or {}).get(bot["id"], 0)

    # On round 0, spread bots from spawn
    if state["round"] == 0:
        spread = [(0, -1, "move_up"), (-1, 0, "move_left"), (1, 0, "move_right")]
        dx, dy, aname = spread[bot["id"] % len(spread)]
        nx, ny = x + dx, y + dy
        wall_set = set(map(tuple, walls))
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in wall_set:
            return {"bot": bot["id"], "action": aname}

    # Yield to a higher-priority bot that has already claimed our cell this round
    if will_be_at is not None and priorities is not None:
        my_pos = (x, y)
        occupant_id = will_be_at.get(my_pos)
        if occupant_id is not None and occupant_id != bot["id"]:
            occupant_priority = priorities.get(occupant_id, 0)
            if occupant_priority > my_priority:
                occupant = next((b for b in state["bots"] if b["id"] == occupant_id), None)
                if occupant:
                    return yield_move(bot["id"], pos, occupant["position"],
                                      walls, will_be_at, width, height)

    # Stuck with equal-priority neighbors — random move to break deadlock
    if stuck_bots and bot["id"] in stuck_bots:
        return random_move_action(bot["id"], pos, walls, width, height)

    # At drop-off: deliver if we have matching items, otherwise step away
    if [x, y] == drop_off:
        if inventory and has_useful:
            return {"bot": bot["id"], "action": "drop_off"}
        wall_set = set(map(tuple, walls))
        other_positions = {tuple(b["position"]) for b in other_bots}
        for ddx, ddy, aname in [(0, -1, "move_up"), (1, 0, "move_right"),
                                 (-1, 0, "move_left"), (0, 1, "move_down")]:
            npos = (x + ddx, y + ddy)
            if npos not in wall_set and npos not in other_positions:
                return {"bot": bot["id"], "action": aname}
        return {"bot": bot["id"], "action": "wait"}

    # Full inventory → deliver
    if len(inventory) >= 3:
        return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

    # No active order — fall through to preview pre-fetch; don't hard-stop
    if not active:
        pass  # handled below

    # Order fully covered by collective inventories — no more active collection needed
    order_fully_covered = not global_remaining

    if order_fully_covered:
        if has_useful:
            return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)
        # Fall through to preview pre-fetch instead of idling
    else:
        # --- Use pre-computed global assignment if available ---
        if assignment is not None:
            assigned_item, adj_target = assignment
            # Confirm the item is still on the floor
            item_ids_on_floor = {i["id"] for i in state["items"]}
            if assigned_item["id"] in item_ids_on_floor and adj_target is not None:
                ix, iy = assigned_item["position"]
                if abs(ix - x) + abs(iy - y) == 1:
                    return {"bot": bot["id"], "action": "pick_up",
                            "item_id": assigned_item["id"]}
                return next_action_toward(bot["id"], pos, adj_target, walls, width, height)
            # Item gone — fall through to greedy below

        # Fallback greedy: what still needs collecting (for bots without an assignment)
        want = list(global_remaining)
        for t in covered_types:
            if t in want:
                want.remove(t)

        # Pick up adjacent unclaimed wanted item immediately
        for item in state["items"]:
            if item["type"] in want and item["id"] not in claimed:
                ix, iy = item["position"]
                if abs(ix - x) + abs(iy - y) == 1:
                    claimed.add(item["id"])
                    covered_types.append(item["type"])
                    return {"bot": bot["id"], "action": "pick_up", "item_id": item["id"]}

        # Deliver if useful items and nothing left uncovered for this bot to collect
        if has_useful and not want:
            return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

        # Move toward nearest unclaimed wanted item (A* to adj cell, not item pos)
        best_item = None
        best_dist = float('inf')
        for item in state["items"]:
            if item["type"] in want and item["id"] not in claimed:
                adjs = adjacent_walkable(item["position"], walls, width, height)
                d = min((abs(a[0]-x) + abs(a[1]-y) for a in adjs), default=float('inf'))
                if d < best_dist:
                    best_dist = d
                    best_item = item

        if best_item:
            claimed.add(best_item["id"])
            covered_types.append(best_item["type"])
            adjs = adjacent_walkable(best_item["position"], walls, width, height)
            if adjs:
                target = min(adjs, key=lambda a: abs(a[0] - x) + abs(a[1] - y))
                return next_action_toward(bot["id"], pos, target, walls, width, height)

        # Nothing to collect for active order — deliver what we have or fall through
        if inventory and has_useful:
            return deliver_toward(bot["id"], pos, drop_off, walls, width, height, other_bots)

    # --- Preview pre-fetch: keep idle bots busy with the upcoming order ---
    if preview and len(inventory) < 3:
        # What preview still needs, minus what all bots already carry or committed to fetch
        all_inv_flat = [t for b in state["bots"] for t in b["inventory"]]
        preview_remaining = list(get_needed_items(preview))
        for t in all_inv_flat + preview_covered:
            if t in preview_remaining:
                preview_remaining.remove(t)

        best_item = None
        best_dist = float('inf')
        for item in state["items"]:
            if item["type"] in preview_remaining and item["id"] not in claimed:
                dist = abs(item["position"][0] - x) + abs(item["position"][1] - y)
                if dist < best_dist:
                    best_dist = dist
                    best_item = item

        if best_item:
            claimed.add(best_item["id"])
            preview_covered.append(best_item["type"])
            ix, iy = best_item["position"]
            if abs(ix - x) + abs(iy - y) == 1:
                return {"bot": bot["id"], "action": "pick_up", "item_id": best_item["id"]}
            adjs = adjacent_walkable(best_item["position"], walls, width, height)
            if adjs:
                target = min(adjs, key=lambda a: abs(a[0] - x) + abs(a[1] - y))
                return next_action_toward(bot["id"], pos, target, walls, width, height)

    return {"bot": bot["id"], "action": "wait"}


def visualize(state):
    w = state["grid"]["width"]
    h = state["grid"]["height"]
    grid = [["." for _ in range(w)] for _ in range(h)]

    for wall in state["grid"]["walls"]:
        grid[wall[1]][wall[0]] = "#"
    for item in state["items"]:
        grid[item["position"][1]][item["position"][0]] = "I"
    dx, dy = state["drop_off"]
    grid[dy][dx] = "D"
    for bot in state["bots"]:
        bx, by = bot["position"]
        grid[by][bx] = str(bot["id"])

    print(f"\n--- Round {state['round']} | Score: {state['score']} ---")
    for row in grid:
        print(" ".join(row))

    active = next((o for o in state["orders"] if o["status"] == "active"), None)
    preview = next((o for o in state["orders"] if o["status"] == "preview"), None)
    if active:
        needed = get_needed_items(active)
        print(f"Active:  {active['items_required']} | Needed: {needed}")
    if preview:
        print(f"Preview: {preview['items_required']}")
    for bot in state["bots"]:
        print(f"  Bot {bot['id']} @ {bot['position']} | inventory: {bot['inventory']}")


async def play():
    async with websockets.connect(WS_URL) as ws:
        prev_positions = {}      # bot_id -> pos from last round
        prev_prev_positions = {} # bot_id -> pos from two rounds ago

        while True:
            msg = json.loads(await ws.recv())

            if msg["type"] == "game_over":
                print(f"\nGame over! Final score: {msg['score']}")
                break

            state = msg
            visualize(state)

            # Global remaining: what the order still needs minus all inventories
            active = next((o for o in state["orders"] if o["status"] == "active"), None)
            order_needed = get_needed_items(active) if active else []
            all_inv = [t for b in state["bots"] for t in b["inventory"]]
            global_remaining = list(order_needed)
            for t in all_inv:
                if t in global_remaining:
                    global_remaining.remove(t)

            # Priority score for each bot
            priorities = {b["id"]: compute_priority(b, order_needed, global_remaining)
                          for b in state["bots"]}

            # Stuck detection: same position for 2+ rounds OR A↔B oscillation
            stuck_bots = set()
            for b in state["bots"]:
                cur = tuple(b["position"])
                prev = prev_positions.get(b["id"])
                pp = prev_prev_positions.get(b["id"])
                if prev == cur and pp == cur:        # frozen 2+ rounds
                    stuck_bots.add(b["id"])
                elif pp == cur and prev != cur:      # bouncing A→B→A
                    stuck_bots.add(b["id"])

            # Update position history
            prev_prev_positions = dict(prev_positions)
            prev_positions = {b["id"]: tuple(b["position"]) for b in state["bots"]}

            # Optimal global assignment: use actual A* distances to minimise the
            # bottleneck (last bot to deliver). Only assign bots that still need
            # to collect (no useful inventory yet, not full).
            width = state["grid"]["width"]
            height = state["grid"]["height"]
            full_walls = state["grid"]["walls"] + [i["position"] for i in state["items"]]
            collecting_bots = [b for b in state["bots"]
                               if not any(t in order_needed for t in b["inventory"])
                               and len(b["inventory"]) < 3]
            assignments = global_assign(collecting_bots, list(global_remaining),
                                        state["items"], full_walls, width, height)

            # will_be_at: maps cell -> bot_id that will occupy it next round.
            # Initialised to current positions; updated as each bot decides.
            will_be_at = {tuple(b["position"]): b["id"] for b in state["bots"]}

            # Process highest-priority bots first so their moves are visible
            # to lower-priority bots when they decide whether to yield.
            claimed = set()
            covered_types = []
            preview_covered = []
            bot_actions = {}
            for bot in sorted(state["bots"], key=lambda b: -priorities[b["id"]]):
                action = decide(bot, state, global_remaining, claimed, covered_types,
                                priorities, will_be_at, stuck_bots, preview_covered,
                                assignment=assignments.get(bot["id"]))
                bot_actions[bot["id"]] = action
                # Register where this bot intends to be next round
                curr = tuple(bot["position"])
                nxt = get_next_pos(bot["position"], action["action"])
                if will_be_at.get(curr) == bot["id"]:
                    del will_be_at[curr]
                will_be_at[nxt] = bot["id"]

            # Send actions in ascending bot-ID order (server requirement)
            actions = [bot_actions[b["id"]] for b in state["bots"]]
            await ws.send(json.dumps({"actions": actions}))


asyncio.run(play())
