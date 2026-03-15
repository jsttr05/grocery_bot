from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class GameState:
    """Wrapper for game state with typed accessors."""

    grid: Dict[str, Any]
    bots: List[Dict[str, Any]]
    items: List[Dict[str, Any]]
    orders: List[Dict[str, Any]]
    drop_off: List[int]
    round: int
    score: int
    drop_off_zones: Optional[List[List[int]]] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "GameState":
        return GameState(
            grid=data["grid"],
            bots=data["bots"],
            items=data["items"],
            orders=data["orders"],
            drop_off=data["drop_off"],
            round=data["round"],
            score=data["score"],
            drop_off_zones=data.get("drop_off_zones"),
        )

    def get_active_order(self) -> Optional[Dict[str, Any]]:
        """Returns the currently active order."""
        return next((o for o in self.orders if o["status"] == "active"), None)

    def get_preview_order(self) -> Optional[Dict[str, Any]]:
        """Returns the preview order (next order)."""
        return next((o for o in self.orders if o["status"] == "preview"), None)

    @property
    def width(self) -> int:
        return self.grid["width"]

    @property
    def height(self) -> int:
        return self.grid["height"]

    @property
    def walls(self) -> List[List[int]]:
        return self.grid["walls"]


def get_needed_items(order: Dict[str, Any]) -> List[str]:
    """Returns list of item types still needed to fulfill the order."""
    needed = list(order["items_required"])
    for d in order["items_delivered"]:
        if d in needed:
            needed.remove(d)
    return needed


def nearest_drop_off(pos: List[int], state: "GameState") -> List[int]:
    """Returns the nearest drop-off position (x, y)."""
    zones = state.drop_off_zones or [state.drop_off]
    x, y = pos
    return min(zones, key=lambda z: abs(z[0] - x) + abs(z[1] - y))
