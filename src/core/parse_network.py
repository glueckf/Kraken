import string

# Private global variables
# _network = None
# _rates = None
# _primEvents = None
# _instances = None
# _nodes = None


# Function to initialize global variables
def initialize_globals(network_data):
    network = {}
    rates = {}
    primEvents = []
    instances = {}
    nodes = {}
    etb_rates = {}

    ind = 0
    for node in network_data:
        network[ind] = []
        for eventtype in range(len(node.eventrates)):
            if node.eventrates[eventtype] > 0:
                event = string.ascii_uppercase[eventtype]
                network[ind].append(event)
                if event not in primEvents:
                    primEvents.append(event)
                if event not in rates.keys():
                    rates[event] = 0
                rates[event] += float(node.eventrates[eventtype])
                etb_rates[f"{event}{ind}"] = float(node.eventrates[eventtype])
        ind += 1

    # Populate nodes dictionary
    for i in network.keys():
        for event in network[i]:
            if event not in nodes:
                nodes[event] = [i]
            else:
                nodes[event].append(i)

    # Populate instances dictionary
    for i in primEvents:
        instances[i] = len(nodes[i])

    return network, rates, primEvents, instances, nodes, etb_rates


# Getter functions with lazy initialization
def get_network(network_data):
    network, _, _, _, _ = initialize_globals(network_data)
    return network


def get_rates(network_data):
    _, rates, _, _, _ = initialize_globals(network_data)
    return rates


def get_primEvents(network_data):
    _, _, primEvents, _, _ = initialize_globals(network_data)
    return primEvents


def get_instances(network_data):
    _, _, _, instances, _ = initialize_globals(network_data)
    return instances


def get_nodes(network_data):
    _, _, _, _, nodes = initialize_globals(network_data)
    return nodes


# Utility function for accessing network events
def events(node, network_data):
    network, _, _, _, _ = initialize_globals(network_data)
    return network[node]


# Function to calculate instances from projections
def instances_func(proj, network_data):
    _, _, _, _, nodes = initialize_globals(network_data)

    num = 1
    for i in proj:
        if len(i) == 1:
            num *= len(nodes[i])
        else:
            for j in i:
                num *= len(nodes[j])
    return num
