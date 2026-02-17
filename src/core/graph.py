import networkx as nx
from core.node import Node


def create_fog_graph(nodes_list: list[Node]):
    graph = nx.DiGraph()
    # Add all nodes with their attributes
    graph.add_nodes_from(
        (
            node.id,
            {
                "label": str(node.id),
                "computational_power": node.computational_power,
                "memory": node.memory,
                "eventrates": node.eventrates,
            },
        )
        for node in nodes_list
    )

    # Collect all edges (from child to parent)
    edges = set()

    for node in nodes_list:
        # Add edges from child to parents
        if node.Parent:
            for parent_node in node.Parent:
                edges.add((node.id, parent_node.id))

    # Add edges to the graph in bulk
    graph.add_edges_from(edges)

    return graph


def draw_graph(graph: nx.digraph):
    import random

    p = nx.drawing.nx_pydot.to_pydot(graph)
    p.set_rankdir("BT")  # Set the layout direction from top to bottom

    # Remove node labels by setting them to an empty string
    for node in p.get_nodes():
        node.set_label("")  # This removes the label from the node

    # Alternatively, you can completely remove the label attribute
    # for node in p.get_nodes():
    #     node.del_label()
    # Remove node labels and set background color
    for node in p.get_nodes():
        node.set_label("")  # Remove the label from the node
        node.set_style(
            "filled"
        )  # Set the node style to 'filled' to apply the fill color
        node.set_fillcolor(
            "#647687"
        )  # Set the fill color (background color) using a hex color code

    randomNumber = random.randint(1000, 9999)
    p.write_png(f"graph_{randomNumber}.png")
