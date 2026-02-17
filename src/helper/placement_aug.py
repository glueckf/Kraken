#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Aug 10 13:16:11 2021

@author: samira
"""

# from helper.processCombination_aug import *
from helper.filter import getMaximalFilter, getDecomposedTotal
from helper.structures import getNodes, NumETBsByKey, setEventNodes, SiSManageETBs
from projections import returnPartitioning
from allPairs import find_shortest_path_or_ancestor
from EvaluationPlan import Instance, Projection
import numpy as np
from helper.filter import getKeySingleSelect
import networkx as nx
from helper.structures import MSManageETBs, getETBs


class PlacementDecision:
    """
    Represents a placement decision for a projection at a specific node.
    """

    def __init__(
        self,
        node,
        costs,
        strategy,
        all_push_costs,
        push_pull_costs=None,
        has_sufficient_resources=False,
        subgraph_info=None,
        plan_details=None,
    ):
        self.node = node
        self.costs = costs
        self.strategy = strategy  # 'all_push' or 'push_pull'
        self.all_push_costs = all_push_costs
        self.push_pull_costs = push_pull_costs
        self.has_sufficient_resources = has_sufficient_resources
        self.subgraph_info = subgraph_info or {}
        self.plan_details = plan_details or {}
        self.savings = all_push_costs - costs if costs < all_push_costs else 0.0

    def __str__(self):
        return f"PlacementDecision(node={self.node}, strategy={self.strategy}, costs={self.costs:.2f}, savings={self.savings:.2f})"

    def __repr__(self):
        return self.__str__()

    def to_dict(self):
        """Convert to dictionary for serialization or logging."""
        return {
            "node": self.node,
            "costs": self.costs,
            "strategy": self.strategy,
            "all_push_costs": self.all_push_costs,
            "push_pull_costs": self.push_pull_costs,
            "has_sufficient_resources": self.has_sufficient_resources,
            "subgraph_info": self.subgraph_info,
            "plan_details": self.plan_details,
            "savings": self.savings,
        }


class PlacementDecisionTracker:
    """
    Tracks and manages placement decisions for a projection across multiple nodes.
    """

    def __init__(self, projection):
        self.projection = projection
        self.decisions = []  # List of PlacementDecision objects
        self.best_decision = None

    def add_decision(self, decision):
        """Add a new placement decision."""
        self.decisions.append(decision)

        # Update best decision if this is better
        if self.best_decision is None or decision.costs < self.best_decision.costs:
            self.best_decision = decision

    def get_best_decision(self):
        """Get the best (lowest cost) placement decision."""
        return self.best_decision

    def get_decisions_by_strategy(self, strategy):
        """Get all decisions using a specific strategy."""
        return [d for d in self.decisions if d.strategy == strategy]

    def get_resource_constrained_decisions(self):
        """Get decisions where resources were insufficient for push-pull."""
        return [d for d in self.decisions if not d.has_sufficient_resources]

    def summarize(self):
        """Generate a summary of all placement decisions."""
        if not self.decisions:
            return "No placement decisions recorded."

        summary = []
        summary.append(f"Placement Analysis for {self.projection}:")
        summary.append(f"  Total candidates evaluated: {len(self.decisions)}")

        push_pull_decisions = self.get_decisions_by_strategy("push_pull")
        all_push_decisions = self.get_decisions_by_strategy("all_push")
        resource_constrained = self.get_resource_constrained_decisions()

        summary.append(f"  Push-pull viable: {len(push_pull_decisions)}")
        summary.append(f"  All-push only: {len(all_push_decisions)}")
        summary.append(f"  Resource constrained: {len(resource_constrained)}")

        if self.best_decision:
            summary.append(f"  Best placement: Node {self.best_decision.node}")
            summary.append(f"  Best strategy: {self.best_decision.strategy}")
            summary.append(f"  Best cost: {self.best_decision.costs:.2f}")
            summary.append(f"  Savings vs all-push: {self.best_decision.savings:.2f}")

        return "\n".join(summary)

    def export_decisions(self):
        """Export all decisions as a list of dictionaries."""
        return [decision.to_dict() for decision in self.decisions]


def getFilters(self, projection, partType):  # move to filter file eventually
    IndexEventNodes = self.h_IndexEventNodes
    projrates = self.h_projrates
    eventNodes = self.h_eventNodes
    totalETBs = 0
    for etb in IndexEventNodes[partType]:  # for each multi-sink
        numETBs = 1
        node = getNodes(etb, eventNodes, IndexEventNodes)[0]
        myETBs = getETBs(node, eventNodes, IndexEventNodes)
        if not set(
            IndexEventNodes[projection]
        ).issubset(
            set(getETBs(node, eventNodes, IndexEventNodes))
        ):  # it is  checked if the node already received all etbs of the projection, if this is the case its not necessary to reduce something here
            # jedes etb eines leaftypes von projection, aufsummieren, wenn von jedem mindestens 1 dann aufmultiplizieren und somit etbs ausrechnen und dann rate der etbs aufsummieren pro knoten
            for primEvent in projection.leafs():
                numETBs *= len(list(set(myETBs) & set(IndexEventNodes[primEvent])))

            totalETBs += numETBs
    #  print("AUTO FILTERS: " + str(totalETBs * projrates[projection][1]))    # if the projection is also input to another projection in the combination, it may also be the case that the nodes of the parttypes already received all instances of the projections, hence filters can't help anymore...
    return totalETBs * projrates[projection][1]


def computeMSplacementCosts(
    self, projection, combination, partType, sharedDict, noFilter, G
):
    # from allPairs import find_shortest_path_or_ancestor
    # import networkx as nx

    projFilterDict = self.h_projFilterDict
    IndexEventNodes = self.h_IndexEventNodes
    nodes = self.h_nodes
    eventNodes = self.h_eventNodes

    projrates = self.h_projrates
    mycombi = self.h_mycombi
    singleSelectivities = self.single_selectivity
    rates = self.h_rates_data
    if not hasattr(self, "assigned_queries_per_node"):
        self.assigned_queries_per_node = {}

    costs = 0
    Filters = []

    ##### FILTERS, append maximal filters
    intercombi = []

    automaticFilters = 0
    for proj in combination:
        if (
            len(proj) > 1 and len(IndexEventNodes[proj]) == 1
        ):  # here a node can only have already ALL events if the node is a sink for the projection, this case is however already covered in normal placement cost calculation
            automaticFilters += getFilters(proj, partType[0])  # TODO first version

        intercombi.append(proj)
        if (
            len(proj) > 1 and len(getMaximalFilter(projFilterDict, proj, noFilter)) > 0
        ):  # those are the extra events that need to be sent around due to filters
            Filters.append((proj, getMaximalFilter(projFilterDict, proj, noFilter)))
            # print("Using Filter: " + str(getMaximalFilter(projFilterDict, proj)) + ": " + str(projFilterDict[proj][getMaximalFilter(projFilterDict, proj)][0]) + " instead of " + str(projrates[proj])  )
            for etype in getMaximalFilter(projFilterDict, proj, noFilter):
                intercombi.append(etype)
    combination = list(set(intercombi))
    myPathLength = 0

    totalInstances = []  #!
    myNodes = []

    # for eventtype in mycombi.get(projection, []):
    #     if eventtype not in IndexEventNodes:
    #         continue
    #     for etb in IndexEventNodes[eventtype]:
    #         candidates = getNodes(etb, eventNodes, IndexEventNodes)
    #         for node in candidates:
    #             if self.network[node].computational_power >= projection.computing_requirements:
    #                 myNodes.append(node)

    # # Remove duplicates
    # myNodes = list(set(myNodes))

    # # Fallback if no valid nodes found
    # if not myNodes:
    #     print(f"[Warning] No valid nodes found for projection {projection}, using fallback node 0")
    #     myNodes = [0]
    # sinkNodes = []

    myProjection = Projection(projection, {}, [], [], Filters)  #!
    for myInput in combination:
        if not partType[0] == myInput:
            if myInput in sharedDict.keys():
                # result = NEWcomputeMSplacementCosts_Path(projection, [myInput], sharedDict[myInput], noFilter)
                result = NEWcomputeMSplacementCosts(
                    self, projection, [myInput], sharedDict[myInput], noFilter, G
                )
                costs += result[0]  # fix SharedDict with Filter Inputs

            else:
                # result = NEWcomputeMSplacementCosts_Path(projection, [myInput],  partType[0], noFilter)
                result = NEWcomputeMSplacementCosts(
                    self, projection, [myInput], partType[0], noFilter, G
                )

                costs += result[0]
            if result[1] > myPathLength:
                myPathLength = result[1]

            myProjection.addInstances(myInput, result[2])  #!
            totalInstances += result[2]  #!
        else:
            myInstances = [Instance(partType[0], partType[0], nodes[partType[0]], {})]
            myProjection.addInstances(partType[0], myInstances)

    # here generate an instance of etbs per parttype and add one line per instance
    MSManageETBs(self, projection, partType[0])

    spawnedInstances = IndexEventNodes[projection]
    myProjection.addSpawned(spawnedInstances)
    for sink in result[3].sinks:
        myProjection.addSinks(sink)
    # for sink in myNodes:
    #     if self.network[sink].computational_power >= projection.computing_requirements:
    #         myProjection.sinks.append(sink)
    #         #self.network[sink].computational_power -= projection.computing_requirements

    #         # if G is not None and G.has_node(sink):
    #         #     G.nodes[sink]['relevant'] = True
    #         print(f"[Placement] Projection {projection} assigned to Node {sink}, remaining power: {self.network[sink].computational_power}")

    costs -= automaticFilters

    return costs, myPathLength, myProjection, totalInstances, Filters


def NEWcomputeMSplacementCosts(
    self, projection, sourcetypes, destinationtypes, noFilter, G
):
    from allPairs import create_routing_dict

    routingDict = create_routing_dict(G)
    routingAlgo = dict(nx.all_pairs_shortest_path(G))
    allPairs = self.allPairs
    node = []
    costs = 0
    longestPath = 0
    newInstances = []
    projFilterDict = self.h_projFilterDict
    IndexEventNodes = self.h_IndexEventNodes
    projrates = self.h_projrates
    singleSelectivities = self.single_selectivity
    mycombi = self.h_mycombi
    rates = self.h_rates_data
    placementTreeDict = self.h_placementTreeDict
    eventNodes = self.h_eventNodes
    routingInfo = []
    dest = 0
    costs_per_sink = {}

    # Check filter
    etype = sourcetypes[0]
    with open("msFilter.txt", "w") as f:
        if etype in projFilterDict and getMaximalFilter(
            projFilterDict, etype, noFilter
        ):
            f.write("VAR=true")
        else:
            f.write("VAR=false")

    myProjection = Projection(projection, {}, [], [], noFilter)  #!
    # search valid sinks
    destinationtypes = [
        node
        for node, neighbors in self.h_network_data.items()
        if not neighbors
        and self.network[node].computational_power >= projection.computing_requirements
    ]
    # Ensure hashable type for later usage in placementTreeDict
    destinationtypes_hashed = tuple(destinationtypes)
    # Filters all valid destinationNodes
    destinationNodes = []
    for destination in destinationtypes:
        skip = False  # Flag to determine if we should skip this destination
        for etype in mycombi.get(projection, []):
            # if eventtype not in IndexEventNodes:
            #     continue
            for etb in IndexEventNodes.get(etype, []):
                possibleSources = getNodes(etb, eventNodes, IndexEventNodes)
                for source in possibleSources:
                    # Use the routing_dict to get the common ancesto
                    common_ancestor = routingDict[destination][source][
                        "common_ancestor"
                    ]
                    if common_ancestor != destination:
                        skip = True
                        break
                if skip:
                    break  # Break out of the etb loop
            if skip:
                break  # Break out of the eventtype loop
        if skip:
            continue
        destinationNodes.append(destination)

        mycosts = 0
        # Main logic: for all event types that belong to the projection
    for etype in mycombi.get(projection, []):
        # if etype not in IndexEventNodes:  # Out of calculation if not relevant
        #     continue
        for etb in IndexEventNodes.get(etype, []):
            newInstance = False
            currentSources = getNodes(etb, eventNodes, IndexEventNodes)
            MydestinationNodes = list(set(destinationNodes) - set(currentSources))
            if MydestinationNodes:
                for dest in MydestinationNodes:
                    if dest not in getNodes(etb, eventNodes, IndexEventNodes):
                        # node.append(destinationNodes)
                        mySource = currentSources[0]
                        for source in currentSources:
                            if allPairs[dest][source] < allPairs[dest][mySource]:
                                mySource = source
                        # node = findBestSource(self,mySource,dest)
                        # shortestPath = find_shortest_path_or_ancestor(routingAlgo, mySource, dest)
                        # if not shortestPath or not isinstance(shortestPath, list):
                        #     print(f"[Warning] No edge from {mySource} to {dest} for etb {etb}")
                        #     continue
                        # edges = list(zip(shortestPath[:-1], shortestPath[1:]))

                        # print(f"[Tracking] send {etb} from {mySource} to {dest} over {shortestPath}")
                        # Cost calculation
                        if etype in projFilterDict.keys() and getMaximalFilter(
                            projFilterDict, etype, noFilter
                        ):  # case input projection has filter
                            mycosts = allPairs[dest][mySource] * getDecomposedTotal(
                                getMaximalFilter(projFilterDict, etype, noFilter), type
                            )
                            if (
                                len(IndexEventNodes[etype]) > 1
                            ):  # filtered projection has ms placement
                                partType = returnPartitioning(etype, mycombi[etype])[0]
                                mycosts -= (
                                    allPairs[dest][mySource]
                                    * rates[partType]
                                    * singleSelectivities[
                                        getKeySingleSelect(partType, etype)
                                    ]
                                    * len(IndexEventNodes[etype])
                                )
                                mycosts += (
                                    allPairs[dest][mySource]
                                    * rates[partType]
                                    * singleSelectivities[
                                        getKeySingleSelect(partType, etype)
                                    ]
                                )
                        elif len(etype) == 1:
                            mycosts = allPairs[dest][mySource] * rates[etype]
                        else:
                            num = NumETBsByKey(etb, etype, IndexEventNodes)
                            mycosts = (
                                allPairs[dest][mySource] * projrates[etype][1] * num
                            )  # FILTER
                            # pathlength and costs
                            # print(mycosts)
        # costs += mycosts
        if MydestinationNodes:
            costs += mycosts
    # print(mycosts)
    # if mycosts < costs and mycosts != 0:
    #     costs = mycosts
    # print(mycosts)
    # if mycosts != 0:
    #     costs += mycosts
    # costs += mycosts
    # desti = dest
    for de in destinationNodes:
        node.append(de)
    for n in node:
        myProjection.addSinks(n)

    # print(f"[MS] Using sink {node} for projection {projection}")

    for etype in mycombi.get(projection, []):
        curInstances = []  #!
        for etb in IndexEventNodes[etype]:
            # MydestinationNodes = list(set(destinationNodes) - set(currentSources))
            # if MydestinationNodes:
            #         for dest in MydestinationNodes:
            #             if not dest in getNodes(etb, eventNodes, IndexEventNodes):
            #                  continue
            possibleSources = getNodes(etb, eventNodes, IndexEventNodes)
            mySource = possibleSources[0]  # ??
            for source in possibleSources:
                if allPairs[destination][source] < allPairs[destination][mySource]:
                    mySource = source
            shortestPath = find_shortest_path_or_ancestor(
                routingAlgo, mySource, destination
            )

            if len(shortestPath) - 1 > longestPath:
                longestPath = len(shortestPath) - 1
            newInstance = Instance(
                etype, etb, [mySource], {projection: shortestPath}
            )  #!
            curInstances.append(newInstance)  #!
            hashable_etb = tuple(sorted(etb.items())) if isinstance(etb, dict) else etb
            placementTreeDict[(destinationtypes_hashed, hashable_etb)] = [
                mySource,
                destination,
                shortestPath,
            ]

            for stop in shortestPath:
                if stop not in getNodes(etb, eventNodes, IndexEventNodes):
                    setEventNodes(stop, etb, eventNodes, IndexEventNodes)

        newInstances += curInstances  #!
        myProjection.addInstances(
            etype, curInstances
        )  #!                      # newInstance = True
        # if newInstance:
        #     myInstance = Instance(etype, etb, [mySource], {projection: routingInfo}) #! #append routing tree information for instance/etb
        #     newInstances.append(myInstance) #!
    if destinationNodes:
        sink_node = destinationNodes[0]
        # MSManageETBs(self, projection, partType[0])
        # Hop-Costs
        # hops = len(find_shortest_path_or_ancestor(routingAlgo, 0, sink_node)) - 1
        hops = (
            len(find_shortest_path_or_ancestor(routingAlgo, 0, sink_node)) - 1
            if len(find_shortest_path_or_ancestor(routingAlgo, 0, sink_node)) > 1
            else 0
        )
        # myProjection.addSpawned([IndexEventNodes[projection][0]]) #!
        costs += max(hops, 0)
    return costs, longestPath, newInstances, myProjection


def NEWcomputeMSplacementCosts_Path(
    self, projection, sourcetypes, destinationtypes, noFilter, G
):  # for PathVariant - fix generate EvalPlan
    costs = 0
    destinationNodes = []
    IndexEventNodes = self.h_IndexEventNodes
    projrates = self.h_projrates
    projFilterDict = self.h_projFilterDict
    mycombi = self.h_mycombi
    singleSelectivities = self.single_selectivity
    rates = self.h_rates_data

    for etype in destinationtypes:
        for etb in IndexEventNodes[etype]:
            destinationNodes += getNodes(etb)

    newInstances = []  #!
    longestPath = 0
    etype = sourcetypes[0]
    routingInfo = []

    for etb in IndexEventNodes[etype]:  # parallelize
        newInstance = False
        MydestinationNodes = list(
            set(destinationNodes).difference(set(getNodes(etb)))
        )  # only consider nodes that do not already hold etb
        if MydestinationNodes:
            for dest in MydestinationNodes:
                if dest not in getNodes(etb):
                    # are there ms nodes which did not receive etb before
                    node = findBestSource(
                        self, getNodes(etb), [dest]
                    )  # best source is node closest to a node of destinationNodes

                    shortestPath = nx.shortest_path(G, dest, node, method="dijkstra")
                    if len(shortestPath) > longestPath:
                        longestPath = len(shortestPath)

                    if etype in projFilterDict.keys() and getMaximalFilter(
                        projFilterDict, etype, noFilter
                    ):  # case input projection has filter
                        mycosts = len(shortestPath) * getDecomposedTotal(
                            getMaximalFilter(projFilterDict, etype, noFilter), etype
                        )
                        if (
                            len(IndexEventNodes[etype]) > 1
                        ):  # filtered projection has ms placement
                            partType = returnPartitioning(etype, mycombi[etype])[0]
                            mycosts -= (
                                len(shortestPath)
                                * rates[partType]
                                * singleSelectivities[
                                    getKeySingleSelect(partType, etype)
                                ]
                                * len(IndexEventNodes[etype])
                            )
                            mycosts += (
                                len(shortestPath)
                                * rates[partType]
                                * singleSelectivities[
                                    getKeySingleSelect(partType, etype)
                                ]
                            )
                    elif len(etype) == 1:
                        mycosts = len(shortestPath) * rates[etype]
                    else:
                        num = NumETBsByKey(etb, etype)
                        mycosts = len(shortestPath) * projrates[etype][1] * num
                    costs += mycosts

                    routingInfo.append(
                        shortestPath
                    )  # destinations have different sources

                    for routingNode in shortestPath:
                        if routingNode not in getNodes(etb):
                            setEventNodes(routingNode, etb)
                    newInstance = True
        if newInstance:
            myInstance = Instance(
                etype, etb, [node], {projection: routingInfo}
            )  #! #append routing tree information for instance/etb
            newInstances.append(myInstance)  #!
    return costs, longestPath, newInstances


# def NEWcomputeMSplacementCosts(projection, sourcetypes, destinationtypes, noFilter): #we need tuples, (C, [E,A]) C should be sent to all e and a nodes ([D,E], [A]) d and e should be sent to all a nodes etc
#     #print(projection, sourcetypes)


#     costs = 0
#     destinationNodes = []

#     for etype in destinationtypes:
#         for etb in IndexEventNodes[etype]:
#             destinationNodes += getNodes(etb)


#     newInstances = [] #!
#     pathLength = 0
#     etype = sourcetypes[0]

#     f = open("msFilter.txt", "w")
#     if etype in projFilterDict.keys() and getMaximalFilter(projFilterDict, etype, noFilter):
#         print("hasFilter")
#         f.write("VAR=true")
#     else:
#         f.write("VAR=false")
#     f.close()


#     for etb in IndexEventNodes[etype]: #parallelize


#             MydestinationNodes = list(set(destinationNodes).difference(set(getNodes(etb)))) #only consider nodes that do not already hold etb
#             if MydestinationNodes: #are there ms nodes which did not receive etb before
#                     node = findBestSource(getNodes(etb), MydestinationNodes) #best source is node closest to a node of destinationNodes
#                     treenodes = copy.deepcopy(MydestinationNodes)
#                     treenodes.append(node)
#                     from networkx.algorithms.approximation import steiner_tree
#                     mytree = steiner_tree(G, treenodes)

#                     myInstance = Instance(etype, etb, [node], {projection: list(mytree.edges)}) #! #append routing tree information for instance/etb
#                     newInstances.append(myInstance) #!


#                     myPathLength = max([len(nx.shortest_path(mytree, x, node, method='dijkstra')) for x in MydestinationNodes]) - 1


#                     if etype in projFilterDict.keys() and  getMaximalFilter(projFilterDict, etype, noFilter): #case input projection has filter
#                         mycosts =  len(mytree.edges()) * getDecomposedTotal(getMaximalFilter(projFilterDict, etype, noFilter), etype)
#                         if len(IndexEventNodes[etype]) > 1 : # filtered projection has ms placement
#                              partType = returnPartitioning(etype, mycombi[etype])[0]
#                              mycosts -= len(mytree.edges())  * rates[partType] * singleSelectivities[getKeySingleSelect(partType, etype)] * len(IndexEventNodes[etype])
#                              mycosts += len(mytree.edges())  * rates[partType] * singleSelectivities[getKeySingleSelect(partType, etype)]
#                     elif len(etype) == 1:
#                         mycosts = len(mytree.edges()) * rates[etype]
#                     else:
#                         num = NumETBsByKey(etb, etype)
#                         mycosts = len(mytree.edges()) *  projrates[etype][1] * num     # FILTER

#                     placementTreeDict[(tuple(destinationtypes),etb)] = [node, MydestinationNodes, mytree] #only kept for updating in the next step
#                     costs +=  mycosts

#                     pathLength = max([pathLength, myPathLength])

#                     # update events sent over network
#                     for routingNode in mytree.nodes():
#                         if not routingNode in getNodes(etb):
#                             setEventNodes(routingNode, etb)


#   # print(list(map(lambda x: str(x), sourcetypes)), costs)
#     return costs, pathLength, newInstances


def findBestSource(
    self, sources, actualDestNodes
):  # this is only a heuristic, as the closest node can still be shit with respect to a good steiner tree ?+
    allPairs = self.allPairs
    curmin = np.inf
    for node in sources:
        if min([allPairs[node][x] for x in actualDestNodes]) < curmin:
            curmin = min([allPairs[node][x] for x in actualDestNodes])
            bestSource = node
    return bestSource


def ComputeSingleSinkPlacement(
    projection,
    combination,
    noFilter,
    projFilterDict,
    EventNodes,
    IndexEventNodes,
    network_data,
    allPairs,
    mycombi,
    rates,
    singleSelectivities,
    projrates,
    Graph,
    network,
    self=None,
):
    from allPairs import create_routing_dict

    routingDict = create_routing_dict(Graph)
    costs = np.inf
    node = 0
    Filters = []
    # routingDict = dict(nx.all_pairs_shortest_path(Graph))
    # print(routingDict)
    routingAlgo = dict(nx.all_pairs_shortest_path(Graph))

    # Calculate the processing latency
    output_rate = projrates[projection][1]
    baseline_input_events = self.sum_of_input_rates_per_query.get(projection)
    if baseline_input_events is None:
        baseline_input_events = self.sum_of_input_rates_per_query.get(
            str(projection), 0.0
        )
    best_actual_input_costs = 0.0

    original_input_objects = set(combination)
    original_input_keys = {str(item) for item in combination}
    filter_input_objects = set()
    filter_input_keys = set()

    """
    NOTE: From Finn Glück on 02.12.2025
    Including an array of sinks, can be extended to multiple sinks later
    """
    sinks = [0]

    # add filters of projections to eventtpes in combi, if filters added, use costs of filter -> compute costs for single etbs of projrates
    intercombi = []
    ##### FILTERS
    for proj in combination:
        intercombi.append(proj)
        # print(list(map(lambda x: str(x), list(projFilterDict.keys()))))
        proj_len = len(proj)
        # Check if proj exists in projFilterDict before calling getMaximalFilter
        if proj in projFilterDict:
            maximal_filter = getMaximalFilter(projFilterDict, proj, noFilter)
            maximal_filter_len = len(maximal_filter)
            if proj_len > 1 and maximal_filter_len > 0:
                Filters.append((proj, maximal_filter))
                if isinstance(maximal_filter, (list, tuple, set)):
                    iterable_filter = list(maximal_filter)
                elif maximal_filter:
                    iterable_filter = [maximal_filter]
                else:
                    iterable_filter = []

                for etype in iterable_filter:
                    intercombi.append(etype)
                    etype_str = str(etype)
                    if (
                        etype not in original_input_objects
                        and etype_str not in original_input_keys
                    ):
                        filter_input_objects.add(etype)
                        filter_input_keys.add(etype_str)
    intercombi_set = set(intercombi)
    combination = list(intercombi_set)

    myProjection = Projection(projection, {}, [], [], Filters)

    non_leaf = [
        node
        for node, neighbors in network_data.items()
        if not neighbors
        and network[node].computational_power >= projection.computing_requirements
    ]

    for destination in non_leaf:
        skip_destination = False  # Flag to determine if we should skip this destination
        for eventtype in combination:
            for etb in IndexEventNodes[eventtype]:
                possibleSources = getNodes(etb, EventNodes, IndexEventNodes)
                for source in possibleSources:
                    # Use the routing_dict to get the common ancestor
                    common_ancestor = routingDict[destination][source][
                        "common_ancestor"
                    ]
                    if common_ancestor != destination:
                        skip_destination = True
                        break
                if skip_destination:
                    break  # Break out of the etb loop
            if skip_destination:
                break  # Break out of the eventtype loop
        if skip_destination:
            continue  # Move on to the next destination without computing costs

        mycosts = 0
        eventtype_costs = {}
        actual_input_costs_candidate = 0.0

        """
        Problem: Placement does not consider the ouput rate of the projection that is placed
        Only Calculates the costs of sending the inputs to the possible placement node 

        The solution would be: 
        input_costs = mycosts 
        output_costs = query_output_rate * hops_to_cloud
        total_costs = input_costs + output_costs
        """
        for eventtype in combination:
            eventtype_cost = 0
            eventtype_str = str(eventtype)
            is_original_input = (
                eventtype in original_input_objects
                or eventtype_str in original_input_keys
            )
            is_filter_input = (
                eventtype in filter_input_objects or eventtype_str in filter_input_keys
            )
            for etb_idx, etb in enumerate(IndexEventNodes[eventtype]):
                possibleSources = getNodes(etb, EventNodes, IndexEventNodes)
                mySource = possibleSources[0]
                for source in possibleSources:
                    if allPairs[destination][source] < allPairs[destination][mySource]:
                        mySource = source

                etb_cost = 0
                if eventtype in projFilterDict.keys() and getMaximalFilter(
                    projFilterDict, eventtype, noFilter
                ):  # case filter
                    maximal_filter = getMaximalFilter(
                        projFilterDict, eventtype, noFilter
                    )
                    decomposed_total = getDecomposedTotal(maximal_filter, eventtype)
                    base_cost = allPairs[destination][mySource] * decomposed_total
                    etb_cost += base_cost

                    if (
                        len(IndexEventNodes[eventtype]) > 1
                    ):  # filtered projection has ms placement
                        partType = returnPartitioning(eventtype, mycombi[eventtype])[0]
                        key_single_select = getKeySingleSelect(partType, eventtype)
                        ms_reduction = (
                            allPairs[destination][mySource]
                            * rates[partType]
                            * singleSelectivities[key_single_select]
                            * len(IndexEventNodes[eventtype])
                        )
                        ms_addition = (
                            allPairs[destination][mySource]
                            * rates[partType]
                            * singleSelectivities[key_single_select]
                        )

                        etb_cost -= ms_reduction
                        etb_cost += ms_addition

                elif eventtype in rates.keys():  # case primitive event
                    rate = rates[eventtype]
                    distance = allPairs[destination][mySource]
                    etb_cost = rate * distance

                else:  # case projection
                    num = NumETBsByKey(etb, eventtype, IndexEventNodes)
                    proj_rate = projrates[eventtype][1]
                    distance = allPairs[destination][mySource]
                    etb_cost = proj_rate * distance * num

                eventtype_cost += etb_cost

            eventtype_costs[eventtype] = eventtype_cost
            mycosts += eventtype_cost

            """
            NOTE: Finn Glück on 02.12.2025
            
            Adjusting the placement mismatch for INEv and INES with the fanouts, by including the output rate for 
            final projections in the workload into the cost calculation.
            """
            # Add costs for sending to cloud if projection is a final query in workload
            if projection in self.query_workload:
                # Projection is a final query in workload
                output_rate = projrates[projection][1]
                for sink in sinks:
                    distance_to_sink = allPairs[destination][sink]
                    output_rate = projrates[projection][1]
                    output_cost = output_rate * distance_to_sink
                    mycosts += output_cost

            if is_original_input and not is_filter_input:
                actual_input_costs_candidate += eventtype_cost

        if mycosts < costs:
            costs = mycosts
            node = destination
            best_actual_input_costs = actual_input_costs_candidate

    myProjection.addSinks(node)  #!

    print("\n[COST_DEBUG] === FINAL PLACEMENT RESULTS ===")
    print(f"[COST_DEBUG] Best destination node: {node}")
    print(f"[COST_DEBUG] Best total cost: {costs}")

    # Remove computational power of sink for next iteration
    # if network[node].computational_power >= projection.computing_requirements:
    #     network[node].computational_power -= projection.computing_requirements

    newInstances = []  #!
    longestPath = 0

    for eventtype in combination:
        curInstances = []  #!

        for etb in IndexEventNodes[eventtype]:
            possibleSources = getNodes(etb, EventNodes, IndexEventNodes)
            mySource = possibleSources[0]  # ??
            for source in possibleSources:
                if allPairs[node][source] < allPairs[node][mySource]:
                    mySource = source

            shortestPath = find_shortest_path_or_ancestor(routingAlgo, mySource, node)

            if len(shortestPath) - 1 > longestPath:
                longestPath = len(shortestPath) - 1
            newInstance = Instance(
                eventtype, etb, [mySource], {projection: shortestPath}
            )  #!
            curInstances.append(newInstance)  #!

            for stop in shortestPath:
                if stop not in getNodes(etb, EventNodes, IndexEventNodes):
                    setEventNodes(stop, etb, EventNodes, IndexEventNodes)

        newInstances += curInstances  #!
        myProjection.addInstances(eventtype, curInstances)  #!

    SiSManageETBs(projection, node, IndexEventNodes, EventNodes, network_data)

    # Add output path to longestPath if projection is a final query in workload
    if projection in self.query_workload:
        max_hops_to_sink = 0
        for sink in sinks:
            path_to_sink = find_shortest_path_or_ancestor(routingAlgo, node, sink)
            hops_to_sink = len(path_to_sink) - 1 if len(path_to_sink) > 1 else 0
            # Track the maximum distance to any sink
            max_hops_to_sink = max(max_hops_to_sink, hops_to_sink)
        # Add only the longest path to sink (representing worst-case end-to-end latency)
        longestPath += max_hops_to_sink

    hops = (
        len(find_shortest_path_or_ancestor(routingAlgo, 0, node)) - 1
        if len(find_shortest_path_or_ancestor(routingAlgo, 0, node)) > 1
        else 0
    )
    myProjection.addSpawned([IndexEventNodes[projection][0]])  #!

    # Calculate the processing latency
    if baseline_input_events > 0:
        processing_latency = output_rate * (
            best_actual_input_costs / baseline_input_events
        )
    else:
        processing_latency = 0.0

    return (
        costs,
        node,
        longestPath,
        myProjection,
        newInstances,
        Filters,
        processing_latency,
    )


def NEWcomputeCentralCosts(workload, IndexEventNodes, allPairs, rates, EventNodes, G):
    # Adding all Eventtypes (simple events) to the list
    import networkx as nx

    eventtypes = []
    for i in workload:
        myevents = i.leafs()
        for e in myevents:
            if e not in eventtypes:
                eventtypes.append(e)
    costs = np.inf
    node = 0
    destination = 0
    mycosts = 0
    for eventtype in eventtypes:
        oldcosts = mycosts
        for etb in IndexEventNodes[eventtype]:
            possibleSources = getNodes(etb, EventNodes, IndexEventNodes)
            mySource = possibleSources[0]
            for source in possibleSources:
                if allPairs[destination][source] <= allPairs[destination][mySource]:
                    mySource = source
            mycosts += rates[eventtype] * allPairs[destination][mySource]
    if mycosts < costs:
        costs = mycosts
        node = destination
    longestPath = max(allPairs[node])

    routingDict = {}  # for evaluation plan
    for e in eventtypes:
        routingDict[e] = {}
        for etb in IndexEventNodes[e]:
            possibleSources = getNodes(etb, EventNodes, IndexEventNodes)
            mySource = possibleSources[0]
            shortestPath = nx.shortest_path(G, mySource, node, method="dijkstra")
            routingDict[e][etb] = shortestPath

    for eventtype in eventtypes:
        thiscosts = 0
        for etb in IndexEventNodes[eventtype]:
            mySource = getNodes(etb, EventNodes, IndexEventNodes)[0]
            thiscosts += rates[eventtype] * allPairs[node][mySource]
    return costs, node, longestPath, routingDict
