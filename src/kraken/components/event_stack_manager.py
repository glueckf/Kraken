import re
from typing import Any, Set
from kraken.data.state import PlacementInfo


def update_event_stack(
    stack: dict, node_id: int, query_id: Any, placement_info: PlacementInfo
) -> None:
    """Update the event stack with events made available by a new placement.

    Args:
        stack: The event stack to update (modified in place)
        node_id: The node where the placement occurred
        query_id: The projection/query that was placed
        placement_info: Information about the placement including acquisition steps
    """
    # Extract primitive events from the projection itself
    projection_str = str(query_id)
    primitive_events = _extract_primitive_events(projection_str)

    # Initialize node entry if it doesn't exist
    if node_id not in stack:
        stack[node_id] = {}

    # Add the projection's primitive events to the stack
    for event in primitive_events:
        if event not in stack[node_id]:
            stack[node_id][event] = {
                "query_id": query_id,
                "acquisition_type": placement_info.strategy,
            }


def _extract_primitive_events(projection_str: str) -> Set[str]:
    """Extract primitive event names from a projection string.

    Args:
        projection_str: String representation of projection (e.g., "SEQ(A, B, C)")

    Returns:
        Set of primitive event names
    """
    # Remove operators and special characters
    cleaned = projection_str.replace("AND", "").replace("SEQ", "")
    cleaned = cleaned.replace("(", "").replace(")", "")
    cleaned = re.sub(r"[0-9]+", "", cleaned).replace(" ", "")

    # Split on comma if present, otherwise treat as individual characters
    if "," in cleaned:
        return set(cleaned.split(","))
    else:
        return set(list(cleaned))
