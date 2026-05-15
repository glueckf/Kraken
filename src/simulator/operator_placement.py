import logging
import uuid

from inev.placement_aug import (
    new_compute_central_costs,
    compute_single_sink_placement,
    compute_ms_placement_costs,
)
from inev.process_combination import compute_dependencies, get_shared_ms_input
import time
from simulator.evaluation_plan import EvaluationPlan
from simulator.projections import return_partitioning, total_rate

logger = logging.getLogger(__name__)


# maxDist = max([max(x) for x in allPairs])


def get_lower_bound(
    query, self
):  # lower bound -> for multiple projections, keep track of events sent as single sink and do not add up
    projsPerQuery = self.h_projsPerQuery
    rates = self.h_rates_data
    longestPath = self.h_longestPath

    MS = []
    for e in query.leafs():
        # myprojs = [p for p in list(set(projsPerQuery[query]).difference(set([query]))) if
        #            total_rate(p) < rates[e] and not e in p.leafs()]

        # Step 1: Get projects for this query
        projects_for_query = projsPerQuery[query]

        # Step 2: Remove duplicates and convert to set
        projects_set = set(projects_for_query)

        # Step 3: Remove the query itself from the projects
        query_set = set([query])
        filtered_projects_set = projects_set.difference(query_set)

        # Step 4: Convert back to list
        filtered_projects_list = list(filtered_projects_set)

        # Step 5: Filter by conditions
        myprojs = []

        for p in filtered_projects_list:
            if total_rate(self, p, self.h_projrates) < rates[e] and e not in p.leafs():
                myprojs.append(p)
        if myprojs:
            MS.append(e)
        for p in [x for x in projsPerQuery[query] if e in x.leafs()]:
            part = return_partitioning(
                self, p, p.leafs(), self.h_projrates, self.h_combiDict
            )

            if e in part:
                MS.append(e)
    nonMS = [e for e in query.leafs() if e not in MS]
    if nonMS:
        minimalRate = (
            sum(
                sorted(
                    [
                        total_rate(self, e, self.h_projrates)
                        for e in query.leafs()
                        if e not in MS
                    ]
                )
            )
            * longestPath
        )
    else:
        minimalRate = (
            min([total_rate(self, e, self.h_projrates) for e in query.leafs()])
            * longestPath
        )
    minimalProjs = sorted(
        [
            total_rate(self, p, self.h_projrates)
            for p in projsPerQuery[query]
            if not p == query
        ]
    )[: len(list(set(MS))) - 1]
    if not len(nonMS) == len(query.leafs()):
        minimalRate += sum(minimalProjs) * longestPath

    return minimalRate  # , nonMS)


def calculate_operator_placement(self, file_path: str, max_parents: int):
    wl = self.query_workload
    allPairs = self.allPairs
    # getNetworkParameters, selectivityParameters, combigenParameters
    networkParams = self.networkParams
    selectivityParams = self.selectivitiesExperimentData
    combigenParams = self.h_combiExperimentData
    longestPath = self.h_longestPath
    projFilterDict = self.h_projFilterDict
    IndexEventNodes = self.h_IndexEventNodes
    allPairs = self.allPairs
    rates = self.h_rates_data
    network = self.network
    mycombi = self.h_mycombi
    singleSelectivities = self.single_selectivity
    projrates = self.h_projrates
    EventNodes = self.h_eventNodes
    G = self.graph

    Filters = []

    filename = "results"
    noFilter = 0  # NO FILTER

    # Access the arguments
    filename = file_path
    number_parents = max_parents

    logger.info(
        "inev: starting placement (workload=%d nodes=%d)",
        len(wl),
        len(network),
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("inev: workload=%s", [str(q) for q in wl])
        logger.debug("inev: file=%s event_nodes=%s", filename, list(IndexEventNodes.keys()))
    ccosts = new_compute_central_costs(
        wl, IndexEventNodes, allPairs, rates, EventNodes, self.graph
    )
    centralHopLatency = max(allPairs[ccosts[1]])
    numberHops = sum(allPairs[ccosts[1]])
    logger.info(
        "inev: central baseline cost=%.2f node=%s hops=%s hop_latency=%.2f",
        ccosts[0],
        ccosts[1],
        numberHops,
        centralHopLatency,
    )
    MSPlacements = {}
    start_time = time.time()

    hopLatency = {}

    # Reduce calls of init_event_nodes
    # init_eventNodes = init_event_nodes()
    EventNodes = self.h_eventNodes
    IndexEventNodes = self.h_IndexEventNodes

    myPlan = EvaluationPlan([], [])

    # transforming indexeventnodes into EvaluationPLan object with all entries as a instance
    # jede instance ist eine node ein event (nodes * events die produziert werden pro node)
    myPlan.init_instances(
        IndexEventNodes
    )  # init with instances for primitive event types

    # mycombi = removeSisChains()
    unfolded = self.h_mycombi
    criticalMSTypes = self.h_criticalMSTypes
    sharedDict = get_shared_ms_input(self, unfolded, projFilterDict)
    dependencies = compute_dependencies(self, unfolded, criticalMSTypes)
    processingOrder = sorted(
        dependencies.keys(), key=lambda x: dependencies[x]
    )  # unfolded enthält kombi
    self.processing_order = processingOrder
    costs = 0

    # Processing Latency
    processing_latency = 0

    central_eval_plan = [ccosts[1], ccosts[3], wl]

    temp_results_dict = {}

    logger.debug(
        "inev: placing %d projections in dependency order (first 5: %s%s)",
        len(processingOrder),
        [str(p) for p in processingOrder[:5]],
        "..." if len(processingOrder) > 5 else "",
    )

    for projection in (
        processingOrder
    ):  # parallelize computation for all projections at the same level
        if set(unfolded[projection]) == set(
            projection.leafs()
        ):  # initialize hop latency with maximum of children
            hopLatency[projection] = 0
        else:
            hopLatency[projection] = max(
                [hopLatency[x] for x in unfolded[projection] if x in hopLatency.keys()]
            )

        # partType = return_partitioning(self,projection, unfolded[projection], self.h_projrates,criticalMSTypes)

        # ComputeMSPlacement
        # TODO: Currntly leave out MS placement for integrated approach, as it is not yet implemented
        # partType,_,_ = return_partitioning(self, projection, unfolded[projection], projrates ,criticalMSTypes)
        partType = False
        if partType:
            MSPlacements[projection] = partType
            result = compute_ms_placement_costs(
                self,
                projection,
                unfolded[projection],
                partType,
                sharedDict,
                noFilter,
                G,
            )
            additional = result[0]

            costs += additional
            hopLatency[projection] += result[1]

            myPlan.add_projection(result[2])  #!

            for newin in result[2].spawnedInstances:  # add new spawned instances
                myPlan.add_instances(projection, newin)

            myPlan.update_instances(result[3])  #! update instances

            Filters += result[4]
            # if partType, and projection in wl and partType kleene component of projection, add sink

            if projection.get_original(wl) in wl and partType[0] in list(
                map(lambda x: str(x), projection.get_original(wl).kleene_components())
            ):
                result = compute_single_sink_placement(
                    projection.get_original(wl), [projection], noFilter
                )
                additional = result[0]
                costs += additional

        else:
            # INFO: compute_single_sink_placement is called for the sequential approach.
            # Implementing a new function for the integrated approach

            result = compute_single_sink_placement(
                projection,
                unfolded[projection],
                noFilter,
                projFilterDict,
                EventNodes,
                IndexEventNodes,
                self.h_network_data,
                allPairs,
                mycombi,
                rates,
                singleSelectivities,
                projrates,
                self.graph,
                self.network,
                self,
            )

            placement_costs = result[0]
            placement_node = result[1]
            temp_results_dict[projection] = {
                "placement_node": placement_node,
                "placement_costs": placement_costs,
            }
            processing_latency += result[6]
            additional = result[0]
            costs += additional
            hopLatency[projection] += result[2]
            myPlan.add_projection(result[3])  #!
            for newin in result[3].spawnedInstances:  # add new spawned instances
                myPlan.add_instances(projection, newin)

            myPlan.update_instances(result[4])  #! update instances
            Filters += result[5]

    # Summarise placement decisions
    if not temp_results_dict:
        logger.warning("inev: no projections were placed")
    elif logger.isEnabledFor(logging.DEBUG):
        placements_by_node = {}
        for projection, result in temp_results_dict.items():
            node = result["placement_node"]
            placements_by_node.setdefault(node, []).append(
                (projection, result["placement_costs"])
            )
        logger.debug(
            "inev: placement distribution across %d node(s):",
            len(placements_by_node),
        )
        for node in sorted(placements_by_node.keys()):
            projections = placements_by_node[node]
            node_total_cost = sum(cost for _, cost in projections)
            logger.debug(
                "  node %s: %d projection(s) cost=%.2f",
                node,
                len(projections),
                node_total_cost,
            )
            for proj, cost in projections:
                logger.debug("    - %s: %.2f", proj, cost)

    mycosts = costs / ccosts[0] if ccosts[0] else 0.0

    if len(wl) > 1 or wl[0].has_kleene() or wl[0].has_negation():
        lowerBound = 0
    else:
        for query in wl:
            lowerBound = get_lower_bound(query, self)

    total_savings = ccosts[0] - costs
    savings_percentage = (total_savings / ccosts[0] * 100) if ccosts[0] > 0 else 0
    totaltime = str(round(time.time() - start_time, 2))
    placed = len(temp_results_dict)
    ttime_f = float(totaltime) if totaltime else 0.0

    logger.info(
        "inev: placed=%d cost=%.2f ratio=%.4f savings=%.2f (%.1f%%) time=%ss",
        placed,
        costs,
        mycosts,
        total_savings,
        savings_percentage,
        totaltime,
    )
    if ccosts[0]:
        logger.debug(
            "inev: lower_bound_efficiency=%.4f throughput=%.2f proj/s avg_cost/proj=%.2f",
            lowerBound / ccosts[0],
            placed / ttime_f if ttime_f > 0 else 0.0,
            (costs / placed) if placed else 0.0,
        )

    ID = uuid.uuid4()

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "inev: processing_order=%s dependency_levels=%d",
            [str(p) for p in processingOrder],
            len(set(dependencies.values())),
        )
    # print(f"  Max Dependency Depth: {max_dependency:.1f}")
    # hoplatency = max([hopLatency[x] for x in hopLatency.keys()])
    if dependencies:
        max_dependency = float(max(list(dependencies.values())) / 2)
    else:
        max_dependency = 0.0  # default value
    # totalLatencyRatio = hoplatency / centralHopLatency
    myResult = [
        ID,
        mycosts,
        ccosts[0],
        costs,
        Filters,
        networkParams[3],
        networkParams[0],
        networkParams[2],
        len(wl),
        combigenParams[3],
        selectivityParams[0],
        selectivityParams[1],
        combigenParams[1],
        longestPath,
        totaltime,
        centralHopLatency,
        max_dependency,
        ccosts[0],
        lowerBound / ccosts[0],
        networkParams[1],
        number_parents,
    ]

    eval_Plan = [myPlan, ID, MSPlacements]
    experiment_result = [ID, costs]

    end_time = time.time()
    logging_result_inev = {
        "cost": costs,
        "transmission_latency": centralHopLatency,
        "processing_latency": processing_latency,
        "computing_time": end_time - start_time,
        "status": "success",
    }
    return (
        eval_Plan,
        central_eval_plan,
        experiment_result,
        myResult,
        logging_result_inev,
    )
