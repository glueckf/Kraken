import multiprocessing
import networkx as nx


# G = None


def find_shortest_path_or_ancestor(routingDict, me, j):
    """Find the shortest path between nodes `me` and `j`.
    If no direct path exists, calculate the combined distance via common ancestors or fallback to node 0.
    Returns the list of nodes representing the path.
    """

    try:
        # Attempt to find the direct shortest path and return the path (list of nodes)
        return routingDict[me][j]  # nx.shortest_path(G, me, j, method='dijkstra')
    except KeyError:
        # If no direct path exists, find the shortest combined path via an intermediate node
        try:
            # Get all shortest path lengths from me and j to all other nodes (including the cloud)
            me_shortest_paths = routingDict[me]
            j_shortest_paths = routingDict[j]

            # Find the common nodes (ancestors) reachable from both me and j
            common_ancestors = set(me_shortest_paths.keys()) & set(
                j_shortest_paths.keys()
            )

            if common_ancestors:
                # Calculate the combined path length for all common ancestors
                shortest_combined_path = None
                min_distance = float("inf")
                # Check which common ancestor offers the shortest combined path
                for ancestor in common_ancestors:
                    path_me_to_ancestor = routingDict[me][
                        ancestor
                    ]  # nx.shortest_path(G, me, ancestor, method='dijkstra')
                    path_j_to_ancestor = routingDict[j][
                        ancestor
                    ]  # nx.shortest_path(G, j, ancestor, method='dijkstra')
                    combined_distance = (
                        len(path_me_to_ancestor) + len(path_j_to_ancestor) - 2
                    )  # Subtract 2 to exclude double-counting ancestor

                    if combined_distance < min_distance:
                        min_distance = combined_distance
                        # Combine the paths without duplicating the ancestor
                        shortest_combined_path = (
                            path_me_to_ancestor + path_j_to_ancestor[::-1][1:]
                        )

                return shortest_combined_path

            else:
                # Fallback to the cloud (node 0) if no other common ancestors exist
                path_me_to_cloud = routingDict[me][0]
                path_j_to_cloud = routingDict[j][
                    0
                ]  # nx.shortest_path(G, j, 0, method='dijkstra')
                # Combine the paths via the cloud (node 0) and return
                return path_me_to_cloud + path_j_to_cloud[::-1][1:]

        except nx.NetworkXNoPath:
            # If there's no path to the cloud or any other intermediary, return an empty path
            return []


def get_common_ancestor_and_steps(G, source, destination):
    """Find the common ancestor between source and destination and calculate the steps from each."""
    if source == destination:
        return source, 0  # The common ancestor is the node itself

    # Attempt to find a direct path
    if nx.has_path(G, source, destination):
        # Direct path exists
        path = nx.shortest_path(G, source, destination, method="dijkstra")
        common_ancestor = destination
        steps_from_source = len(path) - 1
        steps_from_destination = 0
    else:
        # No direct path; find common ancestors
        source_paths = nx.single_source_dijkstra_path_length(G, source)
        dest_paths = nx.single_source_dijkstra_path_length(G, destination)

        # Find common ancestors
        common_ancestors = set(source_paths.keys()) & set(dest_paths.keys())

        if common_ancestors:
            # Find the common ancestor with the minimal combined distance
            min_combined_distance = float("inf")
            best_ancestor = None
            for ancestor in common_ancestors:
                total_distance = source_paths[ancestor] + dest_paths[ancestor]
                if total_distance < min_combined_distance:
                    min_combined_distance = total_distance
                    best_ancestor = ancestor
            common_ancestor = best_ancestor
            steps_from_source = source_paths[best_ancestor]
            steps_from_destination = dest_paths[best_ancestor]
        else:
            # Fallback to the cloud (node 0)
            try:
                source_to_cloud = nx.shortest_path_length(
                    G, source, 0, method="dijkstra"
                )
                dest_to_cloud = nx.shortest_path_length(
                    G, destination, 0, method="dijkstra"
                )
                common_ancestor = 0
                steps_from_source = source_to_cloud
                steps_from_destination = dest_to_cloud
            except nx.NetworkXNoPath:
                # No path exists
                common_ancestor = None
                steps_from_source = None
                steps_from_destination = None
    hops = steps_from_source + steps_from_destination
    return common_ancestor, hops


def create_routing_dict(graph):
    """Create the routing dictionary for the graph."""

    routing_dict = {}
    for destination in graph.nodes():
        routing_dict[destination] = {}
        for source in graph.nodes():
            common_ancestor, hops = get_common_ancestor_and_steps(
                graph, source, destination
            )
            routing_dict[destination][source] = {
                "common_ancestor": common_ancestor,
                "hops": hops,
            }
    return routing_dict


def create_myDistances(routingDict, G, me):
    """Create the myDistances array for a given node `me`."""
    myDistances = []
    for j in range(len(G.nodes)):
        # Call the function to find the shortest path or compute it via common ancestors/cloud
        # print(f"Calculating distance from {me} to {j}")
        myDistances.append(
            len(find_shortest_path_or_ancestor(routingDict, me, j)) - 1
        )  ## -1
    return (me, myDistances)


# New helper function to replace the lambda in pool.map
def compute_distances_for_node(routingDict, G, node):
    return create_myDistances(routingDict, G, node)


def populate_allPairs(graph: nx.digraph):
    # "TODO No globals"
    # global routingDict
    # global G
    G = graph
    routingDict = dict(nx.all_pairs_shortest_path(graph))

    myNodes = list(graph.nodes)
    allPairs = [[] for x in myNodes]

    args = [(routingDict, G, node) for node in myNodes]

    if __name__ == "__main__":
        pool = multiprocessing.Pool()
        result = pool.starmap(compute_distances_for_node, args)
        for i in result:
            allPairs[i[0]] = i[1]
    else:
        # Run sequentially when imported as module to avoid multiprocessing issues
        for routingDict_arg, G_arg, node in args:
            result = compute_distances_for_node(routingDict_arg, G_arg, node)
            allPairs[result[0]] = result[1]

    return allPairs
