"""
Generate network with given size (nwsize), node-event ratio (node_event_ratio),
number of event types (num_eventtypes), event rate skew (eventskew)-
"""

import numpy as np
import random
from core.node import Node
import pandas as pd


def generate_eventrates(eventskew, numb_eventtypes, total_count=5000):
    # Ensure all eventrates are greater than 0
    # Note Finn Glück: 27.08.2025 changed total_count from 10000 to 5000

    # TODO: Find better way to calculate event rates, as they should be really distibuted for good results
    min_value = 1
    max_value = 1000
    # Generate ranks
    k = np.arange(1, numb_eventtypes + 1)

    # Calculate weights based on Zipf's law
    weights = 1 / k**eventskew

    """
    Note from Finn Glück 28.08.2025: 
    Maybe we should introduce a noise value. This should make the events behave in less
    predictable sequences and also give us better edge case distribution of events. 
    Currently events behave in a very predictable way. 
    E.g. for eventskew = 3, r(A) is always 1000, r(B) is 528,6 +- 15 etc. not much variance. 
    """
    # TODO: Discuss this approach with Ariane
    # NOISE_FACTOR = 1.5
    # noise = np.random.lognormal(mean=0, sigma=NOISE_FACTOR, size=numb_eventtypes)
    # weights = weights * noise

    weights /= weights.sum()  # Normalize to sum to 1

    # Sample event rates from multinomial distribution
    eventrates = np.random.multinomial(total_count, weights)

    # Clip event rates to be within min and max values
    eventrates = np.clip(eventrates, min_value, max_value)

    return eventrates


# At one Node show in Array the Events which are generated at each node
# Looping through all Eventrates
def generate_events(eventrates, n_e_r):
    myevents = []
    for i in range(len(eventrates)):
        x = np.random.uniform(0, 1)
        if x < n_e_r:
            myevents.append(int(eventrates[i]))
        else:
            myevents.append(0)
    return myevents


def create_random_tree(nwsize, eventrates, node_event_ratio, max_parents: int = 1):
    if nwsize <= 0:
        return None
    import math

    # Initialize the list to store all nodes
    nw = []

    # Track events along the network nodes
    eList = {}

    levels = math.ceil(math.log2(nwsize))
    print(f"[NETWORK] Network levels: {levels}")
    # Create the root node
    root = Node(
        id=0, compute_power=math.inf, memory=math.inf
    )  # , eventrate=generate_events(eventrates, node_event_ratio))
    nw.append(root)

    # Track nodes by level to manage the structure and prevent imbalance
    level_nodes = {0: [root]}

    # Create remaining nodes and build the tree
    for node_id in range(1, nwsize):
        # Determine the level for the new node
        level = min(levels - 1, node_id // (nwsize // levels) + 1)

        # Compute power and memory decrease as the level increases
        compute_power = levels - level
        memore = levels - level

        # Create the new node
        new_node = Node(id=node_id, compute_power=compute_power, memory=memore)

        # Ensure level-specific nodes exist in the dictionary
        if level not in level_nodes:
            level_nodes[level] = []

        # Randomly choose the number of parents between 1 and max_parents
        num_parents = random.randint(1, max_parents)

        # Randomly choose parents from the previous level
        parent_nodes = random.sample(
            level_nodes[level - 1], min(len(level_nodes[level - 1]), num_parents)
        )

        # Set parents and add the new node to each parent's list of children
        for parent_node in parent_nodes:
            new_node.Parent.append(parent_node)
            parent_node.Child.append(new_node)

        # Add new node to the list and to the level-specific tracking
        nw.append(new_node)
        level_nodes[level].append(new_node)

    # Assign event rates to leaf nodes and initialize non-leaf nodes with empty event rates
    for node in nw:
        if len(node.Child) == 0:
            # get leaf nodes as keys
            eList[node.id] = []

            evtrate = generate_events(eventrates, node_event_ratio)

            # with open('PrimitiveEvents', 'wb') as f:
            #     pickle.dump(evtrate, f)
            node.eventrates = evtrate

            # assign leaf nodes and their parent nodes till cloud to the dictionary.
            # parentNodes = []
            # for i, pNodes in enumerate(evtrate):
            #     if pNodes > 0:
            #         parentNodes.append(i)
            # eList[node.id] = parentNodes

        else:
            node.eventrates = [0] * len(eventrates)

    eventrates_df = pd.DataFrame(
        [node.eventrates for node in nw if len(node.Child) == 0]
    )
    # Check if any column (representing an event) has only 0
    for column in eventrates_df.columns:
        if eventrates_df[column].sum() == 0:
            # Select a random leaf node and assign the eventrate from eventrates array
            # print(f"Assigning eventrate to a random leaf node {column}")
            random_leaf_node = random.choice(
                [node for node in nw if len(node.Child) == 0]
            )
            # print(random_leaf_node)
            random_leaf_node.eventrates[column] = eventrates[column]
    print(f"[NETWORK] Event rates: {eventrates}")
    for column in eventrates_df.columns:
        if eventrates_df[column].sum() == 0:
            print(f"[WARNING] Column {column} still has zero sum")
    # post_order_sum_events(root)

    # assign keys their parent nodes as values till cloud in the dictionary.
    for leaf_id in eList.keys():
        leaf_node = nw[leaf_id]
        # call function get_parents to collect
        all_parents = get_parents(leaf_node)
        eList[leaf_id] = sorted(all_parents)
    # print_network_structure(nw)
    print(f"[NETWORK] Event list structure: {eList}")
    return root, nw, eList


def get_parents(node, assigned=None):
    """
    Recursive function to collect all superior Node-IDs of the leaf nodes.
    """
    if assigned is None:
        assigned = set()

    # iterate and collect parents of leaf nodes
    for parent in node.Parent:
        # assign parent
        assigned.add(parent.id)
        # recurive call as long as not None
        get_parents(parent, assigned)

    return assigned


### Debugging
# def print_network_structure(nw):
#     print("\n[NETWORK STRUCTURE]")
#     for node in nw:
#         children = [child.id for child in node.Child]
#         parents = [parent.id for parent in node.Parent]
#         print(f"Node {node.id} → Children: {children}, Parents: {parents}, Events: {node.eventrates}")


def compressed_graph(G, eList):
    compList = []

    # add relevant nodes into the compressed graph list
    for nodes, etypes in eList.items():
        if len(etypes) > 1:
            compList.append(nodes)

    compressed_nodes = sorted(set(compList))

    # compGraph = G.copy()

    # mark relevant nodes for operator placement
    for n in G.nodes:
        if n in compressed_nodes:
            G.nodes[n]["relevant"] = True
        else:
            G.nodes[n]["relevant"] = False

    # for n in compGraph.nodes:
    #     if n in compressed_nodes:
    #         compGraph.nodes[n]['relevant'] = n in compList
    print(f"[COMPRESSION] Compressed graph list: {compList}")

    print(f"[COMPRESSION] Total nodes in compressed graph: {len(G.nodes)}")
    print(f"[COMPRESSION] Total nodes in original graph: {len(G.nodes)}")

    total_nodes = len(G.nodes)
    relevant_nodes = len(compList)
    compression_ratio = 100 * (1 - relevant_nodes / total_nodes)

    print(
        f"[COMPRESSION] Total: {total_nodes}, Relevant: {relevant_nodes} (including leaf nodes)"
    )
    print(f"[COMPRESSION] Compression ratio: {compression_ratio:.2f}% nodes removed")

    return G


def tree_dict(network_data, eList):
    # dict with nodes as key and their events
    treeAsDict = {}

    for node, events in network_data.items():
        # Iterate over each event associated with the current node
        for etypes in events:
            # add node to dict as key and event to node as value
            if node not in treeAsDict:
                # add nodes into dict
                treeAsDict[node] = set()
            # add their events
            treeAsDict[node].add(etypes)

            # forward events as value to nodes which were in eList as values
            for cNodes in eList.get(node, []):
                # add node to dict as key and event to node as value
                if cNodes not in treeAsDict:
                    # add nodes into dict
                    treeAsDict[cNodes] = set()
                # add their events
                treeAsDict[cNodes].add(etypes)

    print(f"[NETWORK] Tree as dictionary: {treeAsDict}")

    # sort keys & values in new dict
    final_treeDict = {}
    for k, val in sorted(treeAsDict.items()):
        final_treeDict[k] = sorted(list(val))

    return final_treeDict
