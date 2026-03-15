from abc import ABC, abstractmethod
from typing import Dict, Any, List, Set, Tuple, Optional


class BaseAgent(ABC):
    """Abstract base class for all game agents."""

    @abstractmethod
    def decide(
        self, bot: Dict[str, Any], state: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Decide what action the bot should take.

        Args:
            bot: The bot dictionary with id, position, inventory
            state: Full game state
            context: Additional context (global_remaining, claimed, etc.)

        Returns:
            Action dict with 'bot', 'action', and optional 'item_id'
        """
        pass


class DecisionContext:
    """Context passed to agents with precomputed data."""

    def __init__(
        self,
        global_remaining: List[str],
        claimed: set,
        covered_types: List[str],
        priorities: Dict[int, int],
        will_be_at: Dict[tuple, int],
        stuck_bots: set,
        preview_covered: List[str],
        assignment: Any = None,
        deliver_action: str = "submit",
        zone_assignment: Any = None,
        rounds_remaining: int = 500,
        full_walls: Optional[List[List[int]]] = None,
        wall_set: Optional[Set[Tuple[int, int]]] = None,
        assigned_types: Optional[Set[str]] = None,
        all_inv_flat: Optional[List[str]] = None,
    ):
        self.global_remaining = global_remaining
        self.claimed = claimed
        self.covered_types = covered_types
        self.priorities = priorities
        self.will_be_at = will_be_at
        self.stuck_bots = stuck_bots
        self.preview_covered = preview_covered
        self.assignment = assignment
        self.deliver_action = deliver_action
        self.zone_assignment = zone_assignment  # pre-assigned drop-off zone for this bot
        self.rounds_remaining = rounds_remaining
        self.full_walls = full_walls  # walls + item positions, precomputed per round
        self.wall_set = wall_set      # frozenset version, for O(1) lookup
        self.assigned_types = assigned_types or set()  # types claimed by assigned bots
        self.all_inv_flat = all_inv_flat or []  # flat list of all bot inventories
