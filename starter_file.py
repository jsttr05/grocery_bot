import asyncio
import json
import websockets
import heapq

WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIyMjYzOWIzOS00YWU1LTQxNjYtOTMyMy1mZGZjYzc3OGIyMTciLCJ0ZWFtX2lkIjoiMmMxMGRjOTEtNTU0NC00MWMzLTkxNDctMDk1NjE2MmE0MDdkIiwibWFwX2lkIjoiYzg5ZGEyZWMtM2NhNy00MGM5LWEzYjEtODAzNmZjYTNkMGI3IiwibWFwX3NlZWQiOjcwMDEsImRpZmZpY3VsdHkiOiJlYXN5IiwiZXhwIjoxNzczMjQ4NzQ1fQ.Myh200JIqHp-jxrrGyejhdbQvEgciegBYyaBPVtVtEI"


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


def decide(bot, state):
    x, y = bot["position"]
    pos = [x, y]
    walls = state["grid"]["walls"]
    width = state["grid"]["width"]
    height = state["grid"]["height"]
    drop_off = state["drop_off"]
    inventory = bot["inventory"]

    # If standing on drop-off and has items, deliver
    if inventory and [x, y] == drop_off:
        return {"bot": bot["id"], "action": "drop_off"}

    # If inventory full, head to drop-off
    if len(inventory) >= 3:
        return next_action_toward(bot["id"], pos, drop_off, walls, width, height)

    # Find active order
    active = next((o for o in state["orders"] if o["status"] == "active"), None)
    if not active:
        return {"bot": bot["id"], "action": "wait"}

    # Items still needed from server, minus what we already carry
    needed = get_needed_items(active)
    remaining_needed = needed[:]
    for item in inventory:
        if item in remaining_needed:
            remaining_needed.remove(item)

    # Pre-fetch preview order items if space allows
    preview = next((o for o in state["orders"] if o["status"] == "preview"), None)
    preview_needed = get_needed_items(preview) if preview else []

    want = remaining_needed[:]
    for item_type in preview_needed:
        if item_type not in inventory and len(want) + len(inventory) < 3:
            want.append(item_type)

    # Check if adjacent to a wanted item — pick it up
    for item in state["items"]:
        if item["type"] in want:
            ix, iy = item["position"]
            if abs(ix - x) + abs(iy - y) == 1:
                return {"bot": bot["id"], "action": "pick_up", "item_id": item["id"]}

    # If we have all remaining needed items, go deliver
    if not remaining_needed and inventory:
        return next_action_toward(bot["id"], pos, drop_off, walls, width, height)

    # Move toward nearest still-needed item
    best_item = None
    best_dist = float('inf')
    for item in state["items"]:
        if item["type"] in remaining_needed:
            dist = abs(item["position"][0] - x) + abs(item["position"][1] - y)
            if dist < best_dist:
                best_dist = dist
                best_item = item

    if best_item:
        return next_action_toward(bot["id"], pos, best_item["position"], walls, width, height)

    # Nothing left to fetch, go deliver what we have
    if inventory:
        return next_action_toward(bot["id"], pos, drop_off, walls, width, height)

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
        while True:
            msg = json.loads(await ws.recv())

            if msg["type"] == "game_over":
                print(f"\nGame over! Final score: {msg['score']}")
                break

            state = msg
            visualize(state)

            actions = []
            for bot in state["bots"]:
                action = decide(bot, state)
                actions.append(action)

            await ws.send(json.dumps({"actions": actions}))


asyncio.run(play())