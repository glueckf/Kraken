class Node:
    id = 0
    computational_power = 0
    memory = 0
    eventrates = []

    def __init__(self, id: int, compute_power: int, memory: int):
        self.id = id
        self.computational_power = compute_power
        self.memory = memory
        self.eventrates = []
        self.Parent = []
        self.Child = []
        self.Sibling = []

    def __str__(self):
        parent_ids = [parent.id for parent in self.Parent] if self.Parent else None
        child_ids = [child.id for child in self.Child] if self.Child else None
        sibling_ids = [sibling.id for sibling in self.Sibling] if self.Sibling else None

        # Convert numpy types to Python types to avoid 'np.int64(...)' in strings
        eventrates_clean = self._convert_numpy_to_python(self.eventrates)

        return (
            f"Node {self.id}\n"
            f"Computational Power: {self.computational_power}\n"
            f"Memory: {self.memory}\n"
            f"Eventrates: {eventrates_clean}\n"
            f"Parents: {parent_ids}\n"
            f"Child: {child_ids}\n"
            f"Siblings: {sibling_ids}\n"
        )

    @staticmethod
    def _convert_numpy_to_python(obj):
        """Convert numpy types to Python native types for clean string representation."""
        try:
            import numpy as np

            if isinstance(obj, np.ndarray):
                return [Node._convert_numpy_to_python(item) for item in obj.tolist()]
            elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, list):
                return [Node._convert_numpy_to_python(item) for item in obj]
            elif hasattr(obj, "item"):
                # Catch any other numpy scalar type
                return obj.item()
            else:
                return obj
        except ImportError:
            # numpy not available, return as-is
            return obj
