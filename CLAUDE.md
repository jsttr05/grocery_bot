# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a competitive game bot for the NM i AI grocery bot challenge. The bot connects to a WebSocket game server at `game.ainm.no`, controlling one or more bots on a 2D grid to collect grocery items and deliver them to a drop-off point, maximizing score.

## Running the Bot

```bash
python bot.py
```

The bot connects immediately via WebSocket and plays until `game_over` is received. The `WS_URL` at the top of each file contains a JWT token — replace it with a fresh token from the competition platform when expired.

## Files

- `bot.py` — Main bot (active development). Uses `"submit"` as the delivery action.
- `starter_file.py` — Original scaffold provided by organizers. Uses `"drop_off"` as the delivery action. Keep as reference.

## Game State Structure

Each WebSocket message is a JSON state object:

```
state["grid"]          — width, height, walls (list of [x,y])
state["bots"]          — list of {id, position: [x,y], inventory: [item_type, ...]}
state["items"]         — list of {id, type, position: [x,y]} (items on the floor)
state["orders"]        — list of {status, items_required, items_delivered}
state["drop_off"]      — [x, y] delivery zone
state["round"]         — current round number
state["score"]         — current score
```

Order statuses: `"active"` (current order), `"preview"` (next order visible in advance).

## Bot Actions

Each turn, send: `{"actions": [{"bot": bot_id, "action": ACTION, ...}, ...]}`

| Action | Extra field |
|--------|------------|
| `move_up/down/left/right` | — |
| `pick_up` | `"item_id": id` |
| `submit` | — (deliver inventory at drop-off) |
| `wait` | — |

## Architecture

The `decide(bot, state)` function is the core decision loop — it runs once per bot per round and returns a single action dict. Logic priority in `bot.py`:

1. If at drop-off with inventory → submit
2. If inventory has active-order items or is ≥3 full → head to drop-off
3. If adjacent to a wanted item → pick it up
4. Move toward the nearest needed item (A* pathfinding)
5. If nothing needed, wait

`astar(start, goal, walls, width, height)` returns the full path as a list of `(x, y)` tuples. `next_action_toward` takes the first step of that path and converts it to a directional action.

Preview-order pre-fetching: if inventory space allows, the bot also picks up items for the upcoming `"preview"` order.

## Environment

Uses conda (configured in `.vscode/settings.json`). Required packages: `websockets`.
