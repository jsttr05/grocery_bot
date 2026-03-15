from typing import Dict, Any, List

from .base import BaseAgent


class PriorityAgent(BaseAgent):
    """Agent for computing bot priorities (right-of-way)."""

    def decide(
        self, bot: Dict[str, Any], state: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        # Priority is computed globally
        return {"bot": bot["id"], "action": "wait"}


def compute_priority(
    bot: Dict[str, Any], order_needed: List[str], global_remaining: List[str]
) -> int:
    """
    Higher score = higher right-of-way.
    Delivering bots beat collecting bots.

    Returns:
        0 = empty, collecting
        1 = has items (useless for current order)
        2 = delivering something useful
        3 = delivering the last needed items (most critical)
    """
    has_useful = any(t in order_needed for t in bot["inventory"])
    if has_useful and not global_remaining:
        return 3
    if has_useful:
        return 2
    if bot["inventory"]:
        return 1
    return 0


def compute_all_priorities(
    bots: List[Dict[str, Any]], order_needed: List[str], global_remaining: List[str]
) -> Dict[int, int]:
    """Compute priorities for all bots."""
    return {b["id"]: compute_priority(b, order_needed, global_remaining) for b in bots}
