from typing import Dict, Any, List

from ..core.state import get_needed_items


def visualize(state: Dict[str, Any]) -> None:
    """Print a text representation of the game state."""
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
