import io


def _convert_numpy_to_python(obj):
    """Convert numpy types to Python native types for clean string representation."""
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return [_convert_numpy_to_python(item) for item in obj.tolist()]
        elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, list):
            return [_convert_numpy_to_python(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(_convert_numpy_to_python(item) for item in obj)
        elif isinstance(obj, dict):
            return {k: _convert_numpy_to_python(v) for k, v in obj.items()}
        elif hasattr(obj, "item"):
            # Catch any other numpy scalar type
            return obj.item()
        else:
            return obj
    except ImportError:
        # numpy not available, return as-is
        return obj


def generate_config_buffer(network, query_workload, selectivities):
    # Create an in-memory file-like object
    config_buffer = io.StringIO()

    # Write the configuration to the buffer
    config_buffer.write("network\n")
    for i in range(len(network)):
        # Convert numpy types to Python types to avoid 'np.int64(...)' in strings
        network_node = _convert_numpy_to_python(network[i])
        config_buffer.write(f"Node {i} {network_node}\n")

    config_buffer.write("\nqueries\n")
    for query in query_workload:
        query = query.strip_NSEQ()
        config_buffer.write(f"{query.stripKL_simple()}\n")

    config_buffer.write("\nmuse graph\n")
    config_buffer.write(
        "SELECT SEQ(A, B, C, D, E) FROM AND(B, SEQ(A, E, F)); I ON {1, 2, 4, 6, 7, 8, 9}/n(I)\n"
    )

    config_buffer.write("\nselectivities\n")
    # Convert selectivities to avoid numpy type strings
    selectivities_clean = _convert_numpy_to_python(selectivities)
    config_buffer.write(str(selectivities_clean))

    # Reset the buffer's position to the beginning
    config_buffer.seek(0)

    return config_buffer
