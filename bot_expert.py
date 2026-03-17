import asyncio
import json
import websockets
import heapq
import random
from collections import Counter

WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJkMmU0YTY4MS1iNTQzLTQ5NzUtOTU5MS03Nzc1NDI1YjgxYjMiLCJ0ZWFtX2lkIjoiMmMxMGRjOTEtNTU0NC00MWMzLTkxNDctMDk1NjE2MmE0MDdkIiwibWFwX2lkIjoiYzdjN2Y1NjQtMjQ5Ni00YWIxLTkxNzktNzUzMjk3OWFkY2I0IiwibWFwX3NlZWQiOjcwMDQsImRpZmZpY3VsdHkiOiJleHBlcnQiLCJleHAiOjE3NzM1MzMzMDJ9.mbBVkcDAqv3IInznI1YCWCeLxY4TMKIUkDtgEFbtkz4"


# ---------------------------------------------------------------------------
# A* Pathfinding
# ---------------------------------------------------------------------------

def astar(start, goal, walls, width, height):
    goal_t  = tuple(goal)
    start_t = tuple(start)
    if start_t == goal_t:
        return []
    # Goal is always passable (drop-off zones may be wall tiles on some maps)
    blocked = frozenset(tuple(w) for w in walls if tuple(w) != goal_t)
    open_set = []
    heapq.heappush(open_set, (0, start_t))
    came_from = {}
    g_score = {start_t: 0}
    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == goal_t:
            path = []
            while cur in came_from:
                path.append(cur)
                cur = came_from[cur]
            path.reverse()
            return path
        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nb = (cur[0] + dx, cur[1] + dy)
            if not (0 <= nb[0] < width and 0 <= nb[1] < height):
                continue
            if nb in blocked:
                continue
            tg = g_score[cur] + 1
            if tg < g_score.get(nb, float('inf')):
                came_from[nb] = cur
                g_score[nb] = tg
                f = tg + abs(nb[0] - goal_t[0]) + abs(nb[1] - goal_t[1])
                heapq.heappush(open_set, (f, nb))
    return []


def mdist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_to_action(pos, nxt):
    x, y   = pos[0], pos[1]
    nx, ny = nxt[0], nxt[1]
    if nx == x and ny == y - 1: return "move_up"
    if nx == x and ny == y + 1: return "move_down"
    if nx == x - 1 and ny == y: return "move_left"
    if nx == x + 1 and ny == y: return "move_right"
    return "wait"


# ---------------------------------------------------------------------------
# Path cache — per-bot, keyed by target
# ---------------------------------------------------------------------------

class PathCache:
    def __init__(self):
        self._cache = {}

    def move_toward(self, bot_id, pos, target, walls, width, height):
        pos_t = (pos[0], pos[1])
        tgt_t = (target[0], target[1])
        if pos_t == tgt_t:
            self._cache.pop(bot_id, None)
            return None
        entry = self._cache.get(bot_id)
        if entry and entry["target"] == tgt_t and entry["path"]:
            path = entry["path"]
            if pos_t in path:
                idx = path.index(pos_t)
                path = path[idx + 1:]
                entry["path"] = path
            wall_set = frozenset(tuple(w) for w in walls if tuple(w) != tgt_t)
            if path and path[0] not in wall_set and mdist(path[0], pos_t) == 1:
                return step_to_action(pos_t, path[0])
        path = astar(pos, target, walls, width, height)
        if path:
            self._cache[bot_id] = {"target": tgt_t, "path": list(path)}
            return step_to_action(pos_t, path[0])
        self._cache.pop(bot_id, None)
        return None

    def invalidate(self, bot_id):
        self._cache.pop(bot_id, None)

    def clear(self):
        self._cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_needed(order):
    needed = list(order["items_required"])
    for d in order["items_delivered"]:
        if d in needed:
            needed.remove(d)
    return needed


def all_zones(state):
    if "drop_off_zones" in state:
        return [tuple(z) for z in state["drop_off_zones"]]
    return [tuple(state["drop_off"])]


def nearest_zone(pos, zones):
    return min(zones, key=lambda z: mdist(pos, z))


def floor_adj(pos, blocked_set, width, height):
    """Walkable tiles adjacent to pos (not in blocked_set)."""
    x, y = pos
    result = []
    for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in blocked_set:
            result.append((nx, ny))
    return result


def nav_target(item, all_walls_set, width, height, from_pos=None):
    """
    Returns the floor tile a bot should navigate TO in order to pick up this item.
    Items are impassable — always returns an ADJACENT floor tile, never the item position.
    all_walls_set must include item positions so adjacency is computed correctly.
    """
    ip = (item["position"][0], item["position"][1])
    adjs = floor_adj(ip, all_walls_set, width, height)
    if not adjs:
        return None
    if from_pos is not None:
        return min(adjs, key=lambda a: mdist(from_pos, a))
    return adjs[0]


# ---------------------------------------------------------------------------
# Persistent per-game state
# ---------------------------------------------------------------------------

_path_cache      = None
_bot_target      = {}   # bot_id -> item_id
_prev_pos        = {}
_prev_prev_pos   = {}
_stuck_count     = {}
_prev_item_ids   = set()
_active_req_key  = None


def _reset_game():
    global _bot_target, _prev_pos, _prev_prev_pos, _stuck_count, _prev_item_ids
    global _active_req_key
    _bot_target     = {}
    _prev_pos       = {}
    _prev_prev_pos  = {}
    _stuck_count    = {}
    _prev_item_ids  = set()
    _active_req_key = None


# ---------------------------------------------------------------------------
# Assignment engine
# ---------------------------------------------------------------------------

def assign_round(state, active, preview, wall_set, all_walls_set, width, height, stuck_bots):
    global _bot_target

    order_needed   = get_needed(active)  if active  else []
    preview_needed = get_needed(preview) if preview else []

    # Quota: how many of each type still need picking up from the floor.
    # IMPORTANT: Exclude STUCK bots' inventories — stuck bots might never deliver,
    # so counting their items as "covered" leaves quota fake-zero and idles spare bots.
    all_held = Counter()
    for b in state["bots"]:
        if b["id"] in stuck_bots:
            continue  # stuck bot's items don't count toward coverage
        for t in b["inventory"]:
            all_held[t] += 1

    quota_ctr = Counter(order_needed)
    for t, cnt in all_held.items():
        if t in quota_ctr:
            quota_ctr[t] = max(0, quota_ctr[t] - cnt)

    # Items available on floor matching remaining quota
    avail = {}
    for it in state["items"]:
        if quota_ctr.get(it["type"], 0) > 0:
            nt = nav_target(it, all_walls_set, width, height)
            if nt is not None:
                avail[it["id"]] = it

    # Bots that can collect: not delivering, inv < 3, not stuck
    collecting_bots = []
    for b in state["bots"]:
        inv = b["inventory"]
        if any(t in order_needed for t in inv):
            continue
        if len(inv) >= 3:
            continue
        if b["id"] in stuck_bots:
            continue
        collecting_bots.append(b)

    assignments = {}
    claimed     = set()

    # Carry forward valid stale assignments
    for bot_id, item_id in list(_bot_target.items()):
        if bot_id in stuck_bots:
            continue
        if item_id not in avail:
            continue
        item = avail[item_id]
        if quota_ctr.get(item["type"], 0) <= 0:
            continue
        bot = next((b for b in state["bots"] if b["id"] == bot_id), None)
        if bot is None or len(bot["inventory"]) >= 3:
            continue
        if any(t in order_needed for t in bot["inventory"]):
            continue
        nt = nav_target(item, all_walls_set, width, height, tuple(bot["position"]))
        if nt is None:
            continue
        assignments[bot_id] = {"item": item, "nav": nt, "for_preview": False}
        claimed.add(item_id)
        quota_ctr[item["type"]] = max(0, quota_ctr[item["type"]] - 1)

    # Assign unassigned bots greedily (nearest first)
    unassigned = [b for b in collecting_bots if b["id"] not in assignments]
    for bot in unassigned:
        if not any(v > 0 for v in quota_ctr.values()):
            break
        bp = tuple(bot["position"])
        best_item, best_nav, best_d = None, None, float('inf')
        for item_id, item in avail.items():
            if item_id in claimed:
                continue
            if quota_ctr.get(item["type"], 0) <= 0:
                continue
            nt = nav_target(item, all_walls_set, width, height, bp)
            if nt is None:
                continue
            d = mdist(bp, nt)
            if d < best_d:
                best_d, best_item, best_nav = d, item, nt
        if best_item is not None:
            assignments[bot["id"]] = {"item": best_item, "nav": best_nav, "for_preview": False}
            claimed.add(best_item["id"])
            quota_ctr[best_item["type"]] = max(0, quota_ctr[best_item["type"]] - 1)

    # Preview pre-fetch when active quota is fully covered
    if not any(v > 0 for v in quota_ctr.values()) and preview_needed:
        spare = [b for b in collecting_bots if b["id"] not in assignments]
        prev_ctr = Counter(preview_needed)
        for b in state["bots"]:
            if b["id"] in stuck_bots:
                continue  # exclude stuck bots from preview coverage too
            for t in b["inventory"]:
                if t in prev_ctr:
                    prev_ctr[t] = max(0, prev_ctr[t] - 1)

        for bot in spare:
            if len(bot["inventory"]) >= 3:
                continue
            if not any(v > 0 for v in prev_ctr.values()):
                break
            bp = tuple(bot["position"])
            best_item, best_nav, best_d = None, None, float('inf')
            for it in state["items"]:
                if it["id"] in claimed:
                    continue
                if prev_ctr.get(it["type"], 0) <= 0:
                    continue
                nt = nav_target(it, all_walls_set, width, height, bp)
                if nt is None:
                    continue
                d = mdist(bp, nt)
                if d < best_d and d <= 25:
                    best_d, best_item, best_nav = d, it, nt
            if best_item is not None:
                assignments[bot["id"]] = {"item": best_item, "nav": best_nav, "for_preview": True}
                claimed.add(best_item["id"])
                prev_ctr[best_item["type"]] = max(0, prev_ctr[best_item["type"]] - 1)

    _bot_target = {bid: a["item"]["id"] for bid, a in assignments.items()}
    return assignments, quota_ctr, len(avail)


# ---------------------------------------------------------------------------
# Per-bot decision function
# ---------------------------------------------------------------------------

def decide(bot, state, ctx, path_cache):
    bot_id = bot["id"]
    pos    = (bot["position"][0], bot["position"][1])
    x, y   = pos
    inv    = bot["inventory"]

    walls_base    = state["grid"]["walls"]
    wall_set      = ctx["wall_set"]
    item_walls    = ctx["item_walls"]      # frozenset of item positions (impassable)
    all_walls_set = ctx["all_walls_set"]   # wall_set | item_walls
    width         = state["grid"]["width"]
    height        = state["grid"]["height"]
    zones         = ctx["zones"]
    zone_set      = ctx["zone_set"]
    order_needed  = ctx["order_needed"]
    stuck_bots    = ctx["stuck_bots"]
    assignments   = ctx["assignments"]
    items_by_id   = ctx["items_by_id"]
    other_pos     = ctx["other_pos"]

    has_useful = any(t in order_needed for t in inv)
    drop_off   = nearest_zone(pos, zones)

    # Full nav walls = real walls + items + other bots / reserved cells
    full_nav_walls = walls_base + list(item_walls) + list(other_pos)

    # RULE 1 — At drop-off with useful items: deliver
    at_do = pos in zone_set
    if at_do and has_useful:
        return {"bot": bot_id, "action": "drop_off"}

    # At drop-off with nothing useful: step off to free the zone
    if at_do:
        for ddx, ddy, act in [(0, -1, "move_up"),  (1, 0, "move_right"),
                               (-1, 0, "move_left"), (0, 1, "move_down")]:
            npos = (x + ddx, y + ddy)
            if npos not in wall_set and npos not in item_walls and npos not in other_pos:
                return {"bot": bot_id, "action": act}
        return {"bot": bot_id, "action": "wait"}

    # RULE 2 — Stuck escape (only non-delivering bots).
    # Delivering bots (has_useful) skip this — random escape moves them AWAY from
    # the drop-off and makes things worse in congested corridors. They press forward
    # via RULE 3 which uses fresh A* every round.
    if bot_id in stuck_bots and not has_useful:
        path_cache.invalidate(bot_id)
        # Primary: navigate toward nearest open corridor row to escape narrow aisles.
        open_rows = ctx.get("open_rows", [])
        if open_rows and y not in open_rows:
            nearest_open = min(open_rows, key=lambda r: abs(r - y))
            act = path_cache.move_toward(bot_id, pos, (x, nearest_open),
                                         walls_base + list(item_walls), width, height)
            if act:
                return {"bot": bot_id, "action": act}
        # Fallback: deterministic direction rotation (avoids repeating the same blocked move)
        dirs = [(0, -1, "move_up"), (0, 1, "move_down"),
                (-1, 0, "move_left"), (1, 0, "move_right")]
        count = _stuck_count.get(bot_id, 3)
        dirs = dirs[count % 4:] + dirs[:count % 4]
        for dx, dy, act in dirs:
            npos = (x + dx, y + dy)
            if (0 <= npos[0] < width and 0 <= npos[1] < height
                    and npos not in wall_set and npos not in item_walls
                    and npos not in other_pos):
                return {"bot": bot_id, "action": act}
        for dx, dy, act in dirs:
            npos = (x + dx, y + dy)
            if (0 <= npos[0] < width and 0 <= npos[1] < height
                    and npos not in wall_set and npos not in item_walls):
                return {"bot": bot_id, "action": act}
        return {"bot": bot_id, "action": "wait"}

    # RULE 3 — Deliver: has useful items, head to nearest drop-off.
    # Always recompute A* fresh — cached paths lock in suboptimal routes from when
    # other bots were temporarily blocking the optimal corridor. Those bots have
    # since moved, but the stale path persists. Fresh A* (item_walls only, no other
    # bots) finds the globally optimal route; reservation system handles conflicts.
    if has_useful:
        path_cache.invalidate(bot_id)
        act = path_cache.move_toward(bot_id, pos, drop_off,
                                     walls_base + list(item_walls), width, height)
        if not act:
            for z in zones:
                if z != drop_off:
                    act = path_cache.move_toward(bot_id, pos, z,
                                                 walls_base + list(item_walls), width, height)
                    if act:
                        break
        if act:
            return {"bot": bot_id, "action": act}
        return _rand(bot_id, pos, wall_set, item_walls, width, height)

    # RULE 3.5 — Pre-deliver: when active quota is fully covered and this bot holds
    # preview-order items, drift toward the nearest drop-off so it can deliver the
    # instant the order changes.  Only fire when within 15 steps (no cross-map rush)
    # and stop when already within 4 steps (avoids crowding the delivery zone).
    if not has_useful and inv:
        quota_ctr = ctx.get("quota_ctr", {})
        if not any(v > 0 for v in quota_ctr.values()):
            preview_obj = next((o for o in state["orders"] if o["status"] == "preview"), None)
            if preview_obj:
                preview_needed = get_needed(preview_obj)
                if any(t in preview_needed for t in inv):
                    dist_to_do = mdist(pos, drop_off)
                    if 4 < dist_to_do <= 15:
                        act = path_cache.move_toward(bot_id, pos, drop_off,
                                                     walls_base + list(item_walls), width, height)
                        if act:
                            return {"bot": bot_id, "action": act}

    # RULE 4 — Collect: follow assignment
    if bot_id in assignments and len(inv) < 3:
        asgn = assignments[bot_id]
        item = asgn["item"]
        nav  = asgn["nav"]

        if item["id"] in items_by_id:
            ip = (items_by_id[item["id"]]["position"][0],
                  items_by_id[item["id"]]["position"][1])
            # Pick up when adjacent (items are impassable, so bot is always at mdist>=1)
            if mdist(ip, pos) == 1:
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}
            # Navigate to the adjacent-floor nav target
            act = path_cache.move_toward(bot_id, pos, nav, full_nav_walls, width, height)
            if not act:
                act = path_cache.move_toward(bot_id, pos, nav,
                                             walls_base + list(item_walls), width, height)
            if act:
                return {"bot": bot_id, "action": act}
        else:
            _bot_target.pop(bot_id, None)

    # RULE 5 — Idle: 5-sector distribution so idle bots spread evenly across the map.
    # bot_id % 5 maps 10 bots into 5 sectors (2 bots each), reducing per-corridor
    # congestion compared to a 2-half split where 5 bots flood one side.
    if len(inv) < 3:
        num_sectors  = 5
        sector_idx   = bot_id % num_sectors
        sector_size  = max((width - 2) // num_sectors, 1)
        sector_start = 1 + sector_idx * sector_size
        sector_end   = sector_start + sector_size

        best_nav     = None
        best_d       = float('inf')
        fallback_nav = None
        fallback_d   = float('inf')

        for it in state["items"]:
            nt = nav_target(it, all_walls_set, width, height, pos)
            if nt is None:
                continue
            d = mdist(pos, nt)
            if sector_start <= it["position"][0] < sector_end:
                if d < best_d:
                    best_d, best_nav = d, nt
            else:
                if d < fallback_d:
                    fallback_d, fallback_nav = d, nt

        target = best_nav if best_nav is not None else fallback_nav
        if target is not None and mdist(pos, target) > 0:
            act = path_cache.move_toward(bot_id, pos, target,
                                         walls_base + list(item_walls), width, height)
            if act:
                return {"bot": bot_id, "action": act}
    return {"bot": bot_id, "action": "wait"}


def _rand(bot_id, pos, wall_set, item_walls, width, height):
    x, y = pos
    dirs = [(0, -1, "move_up"), (0, 1, "move_down"),
            (-1, 0, "move_left"), (1, 0, "move_right")]
    random.shuffle(dirs)
    for dx, dy, act in dirs:
        nx, ny = x + dx, y + dy
        if (0 <= nx < width and 0 <= ny < height
                and (nx, ny) not in wall_set and (nx, ny) not in item_walls):
            return {"bot": bot_id, "action": act}
    return {"bot": bot_id, "action": "wait"}


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def visualize(state, assignments, stuck_bots, order_needed, zones, quota_ctr=None, avail_count=0):
    w = state["grid"]["width"]
    h = state["grid"]["height"]
    grid = [["." for _ in range(w)] for _ in range(h)]
    for wall in state["grid"]["walls"]:
        grid[wall[1]][wall[0]] = "#"
    for item in state["items"]:
        grid[item["position"][1]][item["position"][0]] = "I"
    for dz in zones:
        grid[dz[1]][dz[0]] = "D"
    for bot in state["bots"]:
        bx, by = bot["position"]
        grid[by][bx] = str(bot["id"] % 10)

    print(f"\n--- Round {state['round']} | Score: {state['score']} ---")
    for row in grid:
        print(" ".join(row))

    active  = next((o for o in state["orders"] if o["status"] == "active"), None)
    preview = next((o for o in state["orders"] if o["status"] == "preview"), None)
    if active:
        print(f"Active needed: {order_needed}")
    if preview:
        print(f"Preview: {get_needed(preview)}")

    n_del  = sum(1 for b in state["bots"] if any(t in order_needed for t in b["inventory"]))
    n_act  = sum(1 for a in assignments.values() if not a["for_preview"])
    n_prev = sum(1 for a in assignments.values() if a["for_preview"])
    n_idle = len(state["bots"]) - n_del - len(assignments)
    print(f"Delivering={n_del} Collecting={n_act} PreFetch={n_prev} "
          f"Idle={max(0,n_idle)} Stuck={len(stuck_bots)}")
    # Show each bot's inventory for debugging
    for b in state["bots"]:
        inv = b["inventory"]
        stuck = "STUCK" if b["id"] in stuck_bots else ""
        if inv or stuck:
            print(f"  Bot {b['id']} @ {b['position']} inv={inv} {stuck}")
    if quota_ctr is not None:
        remaining = {k: v for k, v in quota_ctr.items() if v > 0}
        print(f"  Quota remaining: {remaining}  Available on floor: {avail_count}")


# ---------------------------------------------------------------------------
# Game loop
# ---------------------------------------------------------------------------

async def play():
    global _bot_target, _prev_pos, _prev_prev_pos, _stuck_count
    global _prev_item_ids, _active_req_key

    async with websockets.connect(WS_URL) as ws:
        path_cache = PathCache()
        _reset_game()

        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") == "game_over":
                print(f"\nGame over! Final score: {msg['score']}")
                break

            state  = msg
            width  = state["grid"]["width"]
            height = state["grid"]["height"]
            walls_base = state["grid"]["walls"]
            wall_set   = frozenset(map(tuple, walls_base))
            zones      = all_zones(state)
            zone_set   = set(zones)

            # Items are impassable — add them to the wall set for all A* calls
            item_walls  = frozenset(tuple(it["position"]) for it in state["items"])
            all_walls_set = wall_set | item_walls

            active  = next((o for o in state["orders"] if o["status"] == "active"), None)
            preview = next((o for o in state["orders"] if o["status"] == "preview"), None)
            order_needed = get_needed(active) if active else []

            # Invalidate cached paths for bots whose target item disappeared
            cur_item_ids = {it["id"] for it in state["items"]}
            gone_ids = _prev_item_ids - cur_item_ids
            for bid, iid in list(_bot_target.items()):
                if iid in gone_ids:
                    path_cache.invalidate(bid)
            _prev_item_ids = cur_item_ids

            # Reset assignments only on a NEW order
            req_key = tuple(sorted(active["items_required"])) if active else ()
            if req_key != _active_req_key:
                _bot_target.clear()
                path_cache.clear()
                _active_req_key = req_key

            # Stuck detection: stationary 3+ rounds OR A→B→A oscillation
            stuck_bots = set()
            for b in state["bots"]:
                bid  = b["id"]
                cur  = (b["position"][0], b["position"][1])
                prev = _prev_pos.get(bid)
                pp   = _prev_prev_pos.get(bid)
                if prev == cur:
                    _stuck_count[bid] = _stuck_count.get(bid, 0) + 1
                elif pp == cur and prev != cur:
                    # A→B→A oscillation — flag immediately
                    _stuck_count[bid] = max(_stuck_count.get(bid, 0), 3)
                else:
                    _stuck_count[bid] = 0
                if _stuck_count.get(bid, 0) >= 3:
                    stuck_bots.add(bid)
            _prev_prev_pos = dict(_prev_pos)
            _prev_pos = {b["id"]: (b["position"][0], b["position"][1]) for b in state["bots"]}

            assignments, quota_ctr, avail_count = assign_round(
                state, active, preview, wall_set, all_walls_set, width, height, stuck_bots
            )

            items_by_id = {it["id"]: it for it in state["items"]}
            all_bot_pos = {(b["position"][0], b["position"][1]) for b in state["bots"]}

            # Open rows: rows with no interior walls (horizontal corridors).
            # Stuck bots navigate to these to escape narrow aisles.
            open_rows = [r for r in range(height)
                         if not any((wx, r) in wall_set for wx in range(1, width - 1))]

            ctx = {
                "order_needed":  order_needed,
                "wall_set":      wall_set,
                "item_walls":    item_walls,
                "all_walls_set": all_walls_set,
                "zones":         zones,
                "zone_set":      zone_set,
                "assignments":   assignments,
                "items_by_id":   items_by_id,
                "stuck_bots":    stuck_bots,
                "other_pos":     all_bot_pos,
                "open_rows":     open_rows,
                "quota_ctr":     quota_ctr,
            }

            def priority(bot):
                return 1 if any(t in order_needed for t in bot["inventory"]) else 0

            bot_actions    = {}
            reserved_cells = set()
            ACTION_DELTAS  = {
                "move_up": (0, -1), "move_down": (0, 1),
                "move_left": (-1, 0), "move_right": (1, 0),
            }

            for bot in sorted(state["bots"], key=lambda b: -priority(b)):
                bpos = (bot["position"][0], bot["position"][1])
                ctx["other_pos"] = {p for p in all_bot_pos if p != bpos} | reserved_cells
                action = decide(bot, state, ctx, path_cache)
                bot_actions[bot["id"]] = action
                act_name = action.get("action", "wait")
                if act_name in ACTION_DELTAS:
                    dx, dy = ACTION_DELTAS[act_name]
                    reserved_cells.add((bpos[0] + dx, bpos[1] + dy))

            visualize(state, assignments, stuck_bots, order_needed, zones, quota_ctr, avail_count)

            actions = [bot_actions[b["id"]] for b in sorted(state["bots"], key=lambda b: b["id"])]
            await ws.send(json.dumps({"actions": actions}))


asyncio.run(play())
