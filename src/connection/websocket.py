import asyncio
import json
import time
from typing import Dict, Any, List, Callable, Optional

import websockets

from ..core.state import GameState, get_needed_items
from ..core.actions import get_next_pos
from ..agents import (
    global_assign,
    compute_all_priorities,
    detect_stuck_bots,
    decision_impl,
    DecisionContext,
)


async def play(
    ws_url: str,
    visualize_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
    deliver_action: str = "submit",
) -> None:
    """
    Main game loop connecting to WebSocket server.

    Args:
        ws_url: WebSocket URL with token
        visualize_fn: Optional function to visualize game state
        deliver_action: Action name to use when delivering ("submit" or "drop_off")
    """
    async with websockets.connect(ws_url) as ws:
        prev_positions: Dict[int, tuple] = {}
        prev_prev_positions: Dict[int, tuple] = {}

        # Statistics tracking
        stats = {
            "wait_count": 0,
            "deliver_count": 0,
            "pickup_count": 0,
            "move_count": 0,
            "items_at_delivery": [],       # items in inventory when delivering
            "idle_bots_per_round": [],     # bots with empty inventory
            "zone_deliveries": {},         # zone -> delivery count
        }

        max_item_count = 0
        min_item_count = 9999
        slow_rounds = 0
        prev_score = 0

        while True:
            t0 = time.monotonic()
            msg = json.loads(await ws.recv())

            if msg["type"] == "game_over":
                print(f"\nGame over! Final score: {msg['score']}")
                total = 500 * 20
                avg_idle = sum(stats["idle_bots_per_round"]) / max(len(stats["idle_bots_per_round"]), 1)
                avg_items = sum(stats["items_at_delivery"]) / max(len(stats["items_at_delivery"]), 1)
                print(f"\n=== BOT STATISTICS ===")
                print(f"Actions: wait={stats['wait_count']} move={stats['move_count']} pickup={stats['pickup_count']} deliver={stats['deliver_count']}")
                print(f"Wait rate:    {stats['wait_count']/total*100:.1f}%")
                print(f"Move rate:    {stats['move_count']/total*100:.1f}%")
                print(f"Pickup rate:  {stats['pickup_count']/total*100:.1f}%")
                print(f"Deliver rate: {stats['deliver_count']/total*100:.1f}%")
                print(f"Avg idle bots/round: {avg_idle:.1f} / 20")
                print(f"Avg items per delivery: {avg_items:.2f} / 3")
                print(f"Total deliveries: {stats['deliver_count']}")
                print(f"Zone deliveries: { {str(k): v for k,v in stats['zone_deliveries'].items()} }")
                print(f"Item count: max={max_item_count} min={min_item_count} (respawn={'YES' if max_item_count > min_item_count + 5 else 'NO/unclear'})")
                print(f"Slow rounds (>150ms): {slow_rounds}")
                break

            state = GameState.from_dict(msg)
            if visualize_fn:
                visualize_fn(msg)

            # Score change detection
            if state.score != prev_score:
                delta = state.score - prev_score
                active_orders = [o for o in state.orders if o["status"] == "active"]
                completed = [o for o in state.orders if o["status"] == "completed"]
                print(f"[SCORE r{state.round}] +{delta} -> {state.score} | active={len(active_orders)} completed={len(completed)}")
                for o in active_orders:
                    needed = get_needed_items(o)
                    print(f"[SCORE r{state.round}]   active: required={o['items_required']} needed={needed}")
                prev_score = state.score

            # Round-0 diagnostics: item distribution and map info
            if state.round == 0:
                xs = [i["position"][0] for i in state.items]
                ys = [i["position"][1] for i in state.items]
                right_side = sum(1 for x in xs if x >= 20)
                mid = sum(1 for x in xs if 10 <= x < 20)
                left_side = sum(1 for x in xs if x < 10)
                print(f"[DIAG r0] items={len(state.items)} | x<10:{left_side} x10-20:{mid} x>=20:{right_side}")
                print(f"[DIAG r0] x range [{min(xs)},{max(xs)}] y range [{min(ys)},{max(ys)}]")
                types = {}
                for i in state.items:
                    types[i["type"]] = types.get(i["type"], 0) + 1
                print(f"[DIAG r0] item types: {types}")
                print(f"[DIAG r0] orders count={len(state.orders)}")
                for o in state.orders:
                    print(f"[DIAG r0]   order status={o['status']} required={o['items_required']} delivered={o['items_delivered']}")

            # Log order status every 10 rounds to track changes
            if state.round % 50 == 0:
                active_orders = [o for o in state.orders if o["status"] == "active"]
                print(f"[DIAG r{state.round}] score={state.score} active_orders={len(active_orders)} total_orders={len(state.orders)}")
                for o in state.orders:
                    if o["status"] in ("active", "preview"):
                        needed = get_needed_items(o)
                        print(f"[DIAG r{state.round}]   {o['status']}: required={o['items_required']} needed={needed} delivered={o['items_delivered']}")

            # Precompute walls + items once per round (used by decision_impl × 20 bots)
            full_walls = state.walls + [i["position"] for i in state.items]
            full_wall_set = set(map(tuple, full_walls))

            # Global remaining: what the order still needs minus all inventories
            active = state.get_active_order()
            order_needed = get_needed_items(active) if active else []
            all_inv = [t for b in state.bots for t in b["inventory"]]
            all_inv_flat = all_inv  # alias for clarity
            global_remaining = list(order_needed)
            for t in all_inv:
                if t in global_remaining:
                    global_remaining.remove(t)

            # Priority scores
            priorities = compute_all_priorities(state.bots, order_needed, global_remaining)

            # Stuck detection
            stuck_bots = detect_stuck_bots(state.bots, prev_positions, prev_prev_positions)

            # Update position history
            prev_prev_positions = dict(prev_positions)
            prev_positions = {b["id"]: tuple(b["position"]) for b in state.bots}

            # Drop-off zones (needed for both assignment and delivery balancing)
            zones = state.drop_off_zones or [state.drop_off]

            # Bots holding preview items are "reserved" — excluded from active collection
            # so they don't accidentally mix in active items and discard their preview items.
            preview = state.get_preview_order()
            preview_needed = get_needed_items(preview) if preview else []

            # Global assignment — pass base walls only (items handled internally)
            collecting_bots = [
                b for b in state.bots
                if not any(t in order_needed for t in b["inventory"])
                and not any(t in preview_needed for t in b["inventory"])
                and len(b["inventory"]) < 3
            ]
            assignments = global_assign(
                collecting_bots,
                list(global_remaining),
                state.items,
                state.walls,
                state.width,
                state.height,
                zones=zones,
            )


            # Each delivering bot goes to its nearest drop-off zone (no load balancing).
            # Load balancing caused spawn-area bots to travel far instead of using [27,16].
            zone_assignments: Dict[int, list] = {}
            delivering_bots = [
                b for b in state.bots
                if any(t in order_needed for t in b["inventory"])
            ]
            for bot in delivering_bots:
                bx, by = bot["position"]
                zone_assignments[bot["id"]] = min(
                    zones,
                    key=lambda z: abs(z[0] - bx) + abs(z[1] - by),
                )

            # Types already claimed by assigned bots — unassigned bots skip these
            assigned_types = {item["type"] for route in assignments.values() for item, _ in route}

            # will_be_at: cell -> bot_id that will occupy it next round
            will_be_at = {tuple(b["position"]): b["id"] for b in state.bots}

            # Process bots in priority order (highest first)
            claimed: set = set()
            covered_types: List[str] = []
            preview_covered: List[str] = []
            bot_actions: Dict[int, Dict[str, Any]] = {}

            for bot in sorted(state.bots, key=lambda b: -priorities[b["id"]]):
                ctx = DecisionContext(
                    global_remaining=global_remaining,
                    claimed=claimed,
                    covered_types=covered_types,
                    priorities=priorities,
                    will_be_at=will_be_at,
                    stuck_bots=stuck_bots,
                    preview_covered=preview_covered,
                    assignment=assignments.get(bot["id"]),
                    deliver_action=deliver_action,
                    zone_assignment=zone_assignments.get(bot["id"]),
                    rounds_remaining=500 - state.round,
                    full_walls=full_walls,
                    wall_set=full_wall_set,
                    assigned_types=assigned_types,
                    all_inv_flat=all_inv_flat,
                )
                action = decision_impl(bot, state, ctx)
                bot_actions[bot["id"]] = action

                # Update will_be_at
                curr = tuple(bot["position"])
                nxt = get_next_pos(bot["position"], action["action"])
                if will_be_at.get(curr) == bot["id"]:
                    del will_be_at[curr]
                will_be_at[nxt] = bot["id"]

            # Collect statistics
            idle = sum(1 for b in state.bots if not b["inventory"])
            stats["idle_bots_per_round"].append(idle)
            for bot in state.bots:
                a = bot_actions[bot["id"]]["action"]
                if a == "wait":
                    stats["wait_count"] += 1
                elif a == deliver_action:
                    stats["deliver_count"] += 1
                    stats["items_at_delivery"].append(len(bot["inventory"]))
                    zone = tuple(zone_assignments.get(bot["id"], state.drop_off))
                    stats["zone_deliveries"][zone] = stats["zone_deliveries"].get(zone, 0) + 1
                elif a == "pick_up":
                    stats["pickup_count"] += 1
                else:
                    stats["move_count"] += 1

            # Track item count for respawn detection
            ic = len(state.items)
            max_item_count = max(max_item_count, ic)
            min_item_count = min(min_item_count, ic)

            # Timing: warn if round computation exceeds 150ms
            elapsed = (time.monotonic() - t0) * 1000
            if elapsed > 150:
                slow_rounds += 1

            # Send actions in ascending bot-ID order (server requirement)
            actions = [bot_actions[b["id"]] for b in state.bots]
            await ws.send(json.dumps({"actions": actions}))
