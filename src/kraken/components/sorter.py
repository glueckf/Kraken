"""Event placement sorter for optimized candidate ordering."""

from typing import Any, Dict, List


class EventPlacementSorter:
    """
    Component responsible for sorting candidate nodes to optimize
    the search process with pruning opportunities.
    """

    def sort_candidate_nodes_optimized(
        self,
        candidate_nodes: List[int],
        projection: Any,
        event_stack: Dict[int, Dict[str, Any]],
    ) -> List[int]:
        """Sort candidate nodes for optimal search with pruning.

        Strategy:
        1. Prioritize nodes that already have required events
        2. Sort by network depth (leaf nodes first, then fog, then cloud)

        Args:
            candidate_nodes: List of viable node IDs
            projection: Projection being placed
            event_stack: Current event availability per node

        Returns:
            Sorted list of node IDs
        """
        # Extract events needed for projection
        needed_events = self._get_needed_events(projection)

        # Score each node
        scored_nodes = []
        for node_id in candidate_nodes:
            # Check how many needed events are already at this node
            available_events = set(event_stack.get(node_id, {}).keys())
            overlap = len(needed_events & available_events)

            # Create score tuple: (num_available_events, -node_id)
            # Higher overlap = better, higher node_id = deeper in network = better
            score = (overlap, node_id)
            scored_nodes.append((score, node_id))

        # Sort by score (descending) and extract node IDs
        scored_nodes.sort(reverse=True, key=lambda x: x[0])
        return [node_id for _, node_id in scored_nodes]

    def _get_needed_events(self, projection: Any) -> set:
        """Extract primitive events needed for projection.

        Args:
            projection: Projection object

        Returns:
            Set of event names
        """
        if hasattr(projection, "leafs") and callable(projection.leafs):
            return set(projection.leafs())

        # Fallback: parse from string
        import re

        proj_str = str(projection)
        proj_str = proj_str.replace("AND", "").replace("SEQ", "")
        proj_str = proj_str.replace("(", "").replace(")", "")
        proj_str = re.sub(r"[0-9]+", "", proj_str).replace(" ", "")

        if "," in proj_str:
            return set(proj_str.split(","))
        else:
            return set(list(proj_str))
