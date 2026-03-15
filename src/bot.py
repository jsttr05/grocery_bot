import asyncio
import argparse

from .config import (
    WS_URL,
    DEFAULT_STRATEGY,
    STRATEGY_EASY,
    STRATEGY_MEDIUM,
    STRATEGY_HARD,
    STRATEGY_NIGHTMARE,
    DELIVER_ACTIONS,
)
from .connection import play
from .visualization import visualize


def main() -> None:
    parser = argparse.ArgumentParser(description="Grocery Bot AI")
    parser.add_argument(
        "--strategy",
        choices=[STRATEGY_EASY, STRATEGY_MEDIUM, STRATEGY_HARD, STRATEGY_NIGHTMARE],
        default=DEFAULT_STRATEGY,
        help="Game difficulty strategy",
    )
    parser.add_argument("--url", default=WS_URL, help="WebSocket URL")
    parser.add_argument(
        "--no-viz", action="store_true", help="Disable terminal visualization"
    )
    args = parser.parse_args()

    viz_fn = None if args.no_viz else visualize
    deliver_action = DELIVER_ACTIONS[args.strategy]

    print(f"Starting bot with strategy: {args.strategy}")
    asyncio.run(play(args.url, viz_fn, deliver_action=deliver_action))


if __name__ == "__main__":
    main()
