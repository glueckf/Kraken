import time
from inev.filter import getMaximalFilter, getDecomposedTotal, returnProjFilterDict
from core.structures import getNumETBs
from core.tree import PrimEvent
from ines.projections import totalRate, returnPartitioning
import numpy as np


numberCombis = 0


def populate_projFilterDict(self):
    projFilterDict = {}
    projlist = self.h_projlist
    for proj in projlist:
        projFilterDict.update(returnProjFilterDict(self, proj))
    return projFilterDict


def optimisticTotalRate(
    self, projection, *noFilterParam
):  # USE FILTERED RATE FOR ESTIMATION
    noFilter = 0
    projlist = self.h_projlist
    projFilterDict = self.h_projFilterDict
    rates = self.h_rates_data
    nodes = self.h_nodes
    IndexEventNodes = self.h_IndexEventNodes

    singleSelectivities = self.single_selectivity
    instances = self.h_instances

    if noFilterParam:
        noFilter = noFilter[0]
    if projection in projlist:  # is complex event
        for i in projFilterDict.keys():
            if i == projection:
                myproj = i

                if getMaximalFilter(projFilterDict, myproj):
                    return getDecomposedTotal(
                        getMaximalFilter(projFilterDict, myproj, noFilter),
                        myproj,
                        singleSelectivities,
                        rates,
                        instances,
                    )
                else:
                    # return projrates[myproj][1]
                    return projFilterDict[myproj][
                        getMaximalFilter(projFilterDict, myproj, noFilter)
                    ][0] * getNumETBs(myproj, IndexEventNodes)  # TODO change
    else:
        return rates[projection.leafs()[0]] * len(nodes[projection.leafs()[0]])


def removeFilters(self):
    projFilterDict = self.h_projFilterDict
    for i in projFilterDict.keys():
        toRemove = [x for x in projFilterDict[i].keys() if not x == ""]
        for x in toRemove:
            del projFilterDict[i][x]
    return projFilterDict


def cheapRest(
    self, upstreamprojection, projection, partEvent, restRate
):  # this is not correct -> all partitionings of cheap rest must be investigated! also remaining events muss in teillisten aufgeteilt werden etc.
    """checks if the rest of primitve events that must be provided to match upstream projection with projection and a multisink placement of partEvent allows the multi-sink placement at partEvent"""
    remainingEvents = list(
        set(upstreamprojection.leafs()).difference(
            set(projection.leafs() + [partEvent])
        )
    )
    remainingEventsQ = [PrimEvent(x) for x in remainingEvents]
    for event in remainingEvents:  # problem -> primitive events
        # print(list(map(lambda x: str(x), [x for x in (projlist + remainingEventsQ) if event in x.leafs() and len(x.leafs()) < len(upstreamprojection.leafs()) and set(x.leafs()).issubset(set(upstreamprojection.leafs()))]))) # and set(x.leafs()).issubset(set(upstreamprojection.leafs()))])
        # TODO: next line is highly critical...
        # cheapestProj =  sorted([x for x in (projlist + remainingEventsQ) if partEvent not in x.leafs() and not set(projection.leafs()).issubset(set(x.leafs())) and event in x.leafs() and len(x.leafs()) < len(upstreamprojection.leafs()) and set(x.leafs()).issubset(set(upstreamprojection.leafs()))], key = lambda x: optimisticTotalRate(x))[0]
        cheapestProj = PrimEvent(
            event[0]
        )  # only MS combinations with exactly one complex event as input investigates
        remainingEvents = list(
            set(remainingEventsQ).difference(
                set(remainingEventsQ).intersection(set(cheapestProj.leafs()))
            )
        )
        restRate -= optimisticTotalRate(self, cheapestProj)
    if restRate > 0:
        return True
    else:
        return False


def promisingChainProjection(self, projection):
    """outputs for a projection a dictionary having potential partitioning event types as keys and the potential multisink projections in which projection is part of the combination"""
    optimisticRate = optimisticTotalRate(self, projection)
    combinationdict = {}
    projFilterDict = self.h_projFilterDict
    rates = self.h_rates_data
    projlist = self.h_projlist
    query = self.query_workload[-1]

    singleSelectivities = self.single_selectivity
    instances = self.h_instances

    cheapRests = {}
    for eventtype in query.leafs():
        if eventtype not in projection.leafs():
            for i in projFilterDict.keys():
                if i == projection:
                    myproj = i
                    filters = projFilterDict[
                        myproj
                    ].keys()  # here totalRate should also investigate "filtered rates"
                    break
            usingfilter = []
            for myfilter in filters:
                if (
                    getDecomposedTotal(
                        myfilter, projection, singleSelectivities, rates, instances
                    )
                    < rates[eventtype]
                ):
                    usingfilter.append(myfilter)
            if usingfilter:  # always true...
                events = [x for x in projection.leafs()]
                events.append(eventtype)

                curprojlist = [
                    x
                    for x in projlist
                    if len(x.leafs()) >= len(events) and set(events).issubset(x.leafs())
                ]  # get possible upstream projs

                curprojlist = [
                    x
                    for x in curprojlist
                    if cheapRest(
                        self,
                        x,
                        projection,
                        eventtype,
                        rates[eventtype] - optimisticRate,
                    )
                ]  # OLD and SLOW
                if curprojlist:
                    combinationdict[eventtype] = curprojlist + usingfilter
                # else:
                # print("an cheap rest gescheitert "  + str(eventtype))

    return combinationdict


def extractMsOptions(self, query):
    """returns all possible event types which can be partitioning input of a multisink projection"""
    projsPerQuery = self.h_projsPerQuery
    MsOptions = []
    # per query
    myprojlist = [x for x in projsPerQuery[query]]
    for projection in myprojlist:
        dictionary = promisingChainProjection(self, projection)
        if dictionary.keys():
            for x in dictionary.keys():
                if x not in MsOptions:
                    MsOptions += x
    return MsOptions


def MSoptionsPerEvent(self, query):
    projlist = self.h_projlist
    events = extractMsOptions(self, query)
    MSOptionsDict = {}
    for event in events:
        MSOptionsDict[event] = []
        for proj in projlist:
            d = promisingChainProjection(self, proj)
            if event in d.keys():
                for upProj in [x for x in d[event] if len(x) > 1]:
                    MSOptionsDict[event].append((proj, upProj))
    return MSOptionsDict


# combiDict = {}
# globalPartitioninInputTypes = {}
# globalSiSInputTypes = {}


def getSavings(
    self, partType, combination, projection, DistMatrices, MSTrees
):  # OPTIMISTIC TOTAL RATE
    longestPath = self.h_longestPath
    wl = self.query_workload

    # # Debug partType
    # print(f"[SAVINGS] Calculating savings for partType: {partType}")
    #
    # # Debug MSTrees lookup
    # if partType not in MSTrees:
    #     print(f"[ERROR] PartType '{partType}' not found in MSTrees. Available: {list(MSTrees.keys())}")
    # else:
    #     print(f"[DEBUG] PartType '{partType}' found in MSTrees")
    #
    # # Debug DistMatrices lookup
    # if partType in MSTrees and MSTrees[partType] not in DistMatrices:
    #     print(f"[ERROR] MSTrees[{partType}] -> '{MSTrees[partType]}' not found in DistMatrices. Available: {list(DistMatrices.keys())}")
    # else:
    #     print(f"[DEBUG] MSTrees[{partType}] found in DistMatrices")

    # Debug projection.get_original(wl)
    proj_original = projection.get_original(wl)
    # if proj_original not in wl:
    #     print(f"[WARNING] Projection '{proj_original}' not found in workload")

    # Debug totalRate calls
    try:
        rate = totalRate(self, partType, self.h_projrates)
    except KeyError as e:
        print(f"[ERROR] KeyError in totalRate: {e}")
        print(f"[DEBUG] Available projrates keys: {list(self.h_projrates.keys())}")

    try:
        opt_rate = optimisticTotalRate(self, projection)
    except KeyError as e:
        print(f"[ERROR] KeyError in optimisticTotalRate: {e}")

    # TODO: it is not totalRate but only local Rate that we save for PartType
    if projection.get_original(wl) not in wl:  # some intermediate projection
        #  return totalRate(partType) - (len(MSTrees[partType].edges())*  ((sum(list(map(lambda x: totalRate(x), [y for y in combination if not y == partType])))) + optimisticTotalRate(projection)))
        return longestPath * totalRate(self, partType, self.h_projrates) - (
            len(MSTrees[partType].edges())
            * (
                sum(
                    list(
                        map(
                            lambda x: totalRate(self, x, self.h_projrates),
                            [y for y in combination if not y == partType],
                        )
                    )
                )
            )
            + longestPath * optimisticTotalRate(self, projection)
        )

    elif projection.get_original(wl) in wl and partType not in list(
        map(lambda x: str(x), projection.get_original(wl).kleene_components())
    ):  # sink projection
        return longestPath * totalRate(self, partType, self.h_projrates) - (
            len(MSTrees[partType].edges())
            * sum(
                list(
                    map(
                        lambda x: totalRate(self, partType, self.h_projrates),
                        [y for y in combination if not y == partType],
                    )
                )
            )
        )

    elif projection.get_original(wl) in wl and partType in list(
        map(lambda x: str(x), projection.get_original(wl).kleene_components())
    ):  # ms sink query at kleene type
        return longestPath * totalRate(self, partType, self.h_projrates) - (
            len(MSTrees[partType].edges())
            * (
                sum(
                    list(
                        map(
                            lambda x: totalRate(self, partType, self.h_projrates),
                            [y for y in combination if not y == partType],
                        )
                    )
                )
            )
            + longestPath * optimisticTotalRate(self, projection)
        )


def getBestChainCombis(self, query, shared, criticalMSTypes, noFilter):
    combiDict = self.h_combiDict
    projsPerQuery = self.h_projsPerQuery
    longestPath = self.h_longestPath
    myMSDict = MSoptionsPerEvent(self, query)
    myprojlist = [
        x for x in projsPerQuery[query]
    ]  # HERE WE NEED TO RESPECT OPERATOR SEMANTIC -> new function

    for projection in [
        x for x in myprojlist
    ]:  # trivial combination and ms placement for projections containing two prim events only
        partType, MSTrees, DistMatrices = returnPartitioning(
            self, projection, projection.leafs(), self.h_projrates, criticalMSTypes
        )
        if partType:
            rest = [x for x in projection.leafs() if x not in partType]
            costs = getSavings(
                self,
                partType[0],
                [partType[0]] + rest,
                projection,
                DistMatrices,
                MSTrees,
            )
            combiDict[projection] = (projection.leafs(), partType, costs)
        else:
            costs = (
                sum(
                    list(
                        map(
                            lambda x: totalRate(self, x, self.h_projrates),
                            projection.leafs(),
                        )
                    )
                )
                * longestPath
            )
            combiDict[projection] = (projection.leafs(), [], 0 - costs)
    for projection in sorted(
        [x for x in myprojlist if len(x.leafs()) > 2], key=lambda x: len(x.leafs())
    ):  # returns combination, that has only one input projection, the rest are primitive event types
        mycosts = 0
        for eventtype in myMSDict.keys():
            for mytuple in myMSDict[eventtype]:
                if projection == mytuple[1]:
                    remainingEvents = list(
                        set(mytuple[1].leafs()).difference(set(mytuple[0].leafs()))
                    )
                    mycombination = [mytuple[0]] + remainingEvents
                    res, MSTrees, DistMatrices = returnPartitioning(
                        self,
                        projection,
                        mycombination,
                        self.h_projrates,
                        criticalMSTypes,
                    )
                    curMSTypes = [eventtype]
                    if res:
                        curcosts = getSavings(
                            self,
                            eventtype,
                            mycombination,
                            projection,
                            DistMatrices,
                            MSTrees,
                        )
                        if (
                            mytuple[0] in combiDict.keys()
                        ):  # upstream projection also has a ms placement such that we already saved something here
                            curcosts += combiDict[mytuple[0]][2]
                        if curcosts > mycosts:  # update with new best chain combination
                            if projection not in combiDict.keys():
                                combiDict[projection] = []
                            mycosts = curcosts
                            combiDict[projection] = (
                                mycombination,
                                [eventtype],
                                mycosts,
                            )
                            # if a component of the combination is not in combidict, this means that it has no ms placement, however, we need to add it to combidict, to exclude bad combinations later
                            if mytuple[0] not in combiDict.keys():
                                combiDict[mytuple[0]] = (mytuple[0].leafs(), [], 0)

        mylist = [
            x
            for x in myprojlist
            if len(x.leafs()) < len(projection.leafs())
            and set(x.leafs()).issubset(projection.leafs())
        ]
        getBestTreeCombiRec(
            self,
            longestPath,
            query,
            projection,
            mylist,
            [],
            0,
            shared,
            criticalMSTypes,
            DistMatrices,
            MSTrees,
        )

    return combiDict


def getBestTreeCombiRec(
    self,
    longestPath,
    query,
    projection,
    mylist,
    mycombi,
    mycosts,
    shared,
    criticalMSTypes,
    DistMatrices,
    MSTrees,
):  # atm combinations are generated redundantly and also performance could be improved with a hashtable [ -> the projections with which ABC could be combined in a combination for ABCDE are a subset of the projections AB can be combined...]
    combiDict = self.h_combiDict
    if mylist:
        for i in range(len(sorted(mylist, key=lambda x: len(x.leafs())))):
            proj = mylist[i]
            subProjections = sorted(mylist, key=lambda x: len(x.leafs()))[
                i:
            ]  # problematic

            combiBefore = [x for x in mycombi]
            mycombi.append(proj)

            ##### fill each intermediate combination with primitive events to generate new combination
            _missingEvents = list(
                set(projection.leafs()).difference(
                    set("".join(map(lambda x: "".join(x.leafs()), mycombi)))
                )
            )
            _missingEvents += mycombi
            getBestTreeCombiRec(
                self,
                longestPath,
                query,
                projection,
                [],
                _missingEvents,
                mycosts,
                shared,
                criticalMSTypes,
                DistMatrices,
                MSTrees,
            )

            # exclude redundant combinations
            mycombiEvents = "".join(map(lambda x: "".join(x.leafs()), mycombi))
            subProjections = [
                x
                for x in subProjections
                if not set(x.leafs()).issubset(set(list(mycombiEvents)))
                and not set(list(mycombiEvents)).issubset(set(x.leafs()))
            ]

            # exclude the projections of the list in which the partitioning input type of proj is element of the leafs
            if proj in combiDict.keys() and combiDict[proj][1]:
                partProj = combiDict[proj][1][0]
                subProjections = [
                    x for x in subProjections if partProj not in x.leafs()
                ]
                # exclude case in which part proj of other projection in the list is part of projs leafs
                subProjections = [
                    x
                    for x in subProjections
                    if not (
                        x in combiDict.keys()
                        and combiDict[x][1]
                        and combiDict[x][1][0] in proj.leafs()
                    )
                ]

            # TODO -> Check on Paper and check Implementation carefully
            # exclude subprojections in which the events covered by multi-sink placement are a subset of those events covered by the projections in the combination so far
            myMSTypes = sum(
                [allMSTypes(self, x) for x in mycombi if x in combiDict.keys()], []
            )
            subProjections = [
                x
                for x in subProjections
                if not (
                    x in combiDict.keys()
                    and set(allMSTypes(self, x)).issubset(set(myMSTypes))
                )
            ]

            # exclude the projection in which one of the partProjs of the combination so far is used as input of a single sink placement of an ancestor
            allSiSTypes = sum(
                [allSiSEvents(self, x) for x in mycombi if x in combiDict.keys()], []
            )  # get SIS events, i e those that are covered by combi but not in MS types and remove all projections having ms events that intersect
            subProjections = [
                x
                for x in subProjections
                if not (
                    x in combiDict.keys()
                    and set(allMSTypes(self, x)).intersection(set(allSiSTypes))
                )
            ]
            subProjections = [
                x
                for x in subProjections
                if not (
                    x in combiDict.keys()
                    and set(allSiSEvents(self, x)).intersection(set(myMSTypes))
                )
            ]

            # NEW: exlude combinations with subprojections whichs parttypes would cause to exceed a parttype threshold, here it would be nice to keep a set of good candidates for each projection
            subProjections = [
                x
                for x in subProjections
                if not globalPartitioningOK(
                    self, query, mycombi + [x], longestPath, MSTrees
                )
            ]

            getBestTreeCombiRec(
                self,
                longestPath,
                query,
                projection,
                subProjections,
                mycombi,
                mycosts,
                shared,
                criticalMSTypes,
                DistMatrices,
                MSTrees,
            )
            mycombi = combiBefore

    else:
        if not mycombi or set(
            sum([[x] if len(x) == 1 else x.leafs() for x in mycombi], [])
        ) != set(
            projection.leafs()
        ):  # not even one ms placeable subprojection exists ?
            return

        else:  # only correct combination which match the projection
            (mycosts, partEvent) = costsOfCombination(
                self,
                projection,
                mycombi,
                shared,
                criticalMSTypes,
                DistMatrices,
                MSTrees,
            )

            if (
                projection not in combiDict.keys()
            ):  # projection has only sis placement and thus was not in combidict before
                combiDict[projection] = (mycombi, partEvent, mycosts)
            if mycosts > combiDict[projection][2]:
                combiDict[projection] = (mycombi, partEvent, mycosts)


def costsOfCombination(
    self, projection, mycombi, shared, criticalMSTypes, DistMatrices, MSTrees
):  # here is a good spot to check the combinations that are actually enumerated during our algorithm
    combiDict = self.h_combiDict
    longestPath = self.h_longestPath
    mycosts = 0

    for proj in [
        x for x in mycombi if x in combiDict.keys()
    ]:  # add savings per input of combination
        mycosts += combiDict[proj][2]

    # check if it has a multi-sink placement and add costs/savings
    partEvent, DistMatrices, MSTrees = returnPartitioning(
        self, projection, mycombi, self.h_projrates, criticalMSTypes
    )

    if partEvent and not isinstance(partEvent, list):
        mycosts += getSavings(
            self, partEvent[0], mycombi, projection, DistMatrices, MSTrees
        )

    else:  # projection has a single sink placement, such that we need to send th total rates of all inputs of the combination average path length at least once
        mycosts -= (
            sum(
                list(
                    map(
                        lambda x: totalRate(self, x, self.h_projrates),
                        [
                            y
                            for y in mycombi
                            if y in combiDict.keys() and not combiDict[y][1]
                        ],
                    )
                )
            )
        ) * longestPath

    # reduce by primitive events and shared subprojection
    mycosts -= sharedAncestorsCost(
        self, projection, mycombi, partEvent, DistMatrices, MSTrees
    )

    # if multiple projections share the same input, add a little bit of that inputs rate to simulate later sharing oportunities -> extend myMSTypes to dictionary
    mycosts += eventSharing(
        self, projection, mycombi, mycosts, shared
    )  # rates of event types input to multiple multi-sink placement in the combination are shared, which should be accounted for here

    # TODO: this might be stupid in the case of multiquery
    MSChildren = sum([combiDict[x][1] if len(x) > 1 else [x] for x in mycombi], [])
    if len(MSChildren) != len(mycombi) and not partEvent:
        mycosts = -np.inf

    return (mycosts, partEvent)


def eventSharing(self, projection, mycombi, mycosts, shared):
    combiDict = self.h_combiDict
    longestPath = self.h_longestPath
    wl = self.query_workload
    # output costs of inputs of multi-sink placements that are shared between multiple projections of the combination
    costs = 0
    # get for the sub-graph representing the combination of each projection in mycombi the ms placed sub-projections
    myInputsMSProjs = {}
    for proj in [x for x in mycombi if len(x) > 1] + [
        y for y in wl if y in combiDict.keys()
    ]:  # check sharing with already processed other queries
        myInputsMSProjs[proj] = [
            x for x in allAncestors(self, proj, combiDict[proj][0]) if combiDict[x][1]
        ]  # list of ms ancestors
        myInputsMSProjs[proj] = list(
            set(
                sum(
                    [
                        [y for y in combiDict[x][0] if not y == combiDict[x][1][0]]
                        for x in myInputsMSProjs[proj]
                    ],
                    [],
                )
            )
        )
    myInputs = set(sum(list(myInputsMSProjs.values()), []))
    totalInputs = sum(list(myInputsMSProjs.values()), [])
    for event in myInputs:
        costs += (
            totalRate(self, event, self.h_projrates)
            * longestPath
            * totalInputs.count(event)
        )
    return costs


def sharedAncestorsCost(
    self, projection, mycombi, partEvent, DistMatrices, MSTrees
):  # for each partitioning event type covered in the combi, we can only reduce its total rate once from the total savings provided by the combi
    combiDict = self.h_combiDict
    costs = 0
    longestPath = self.h_longestPath
    if partEvent:
        partEvent = [partEvent[0]]

    partTypes = sum(
        [allMSTypes(self, x) for x in mycombi if len(str(x)) > 1] + [partEvent], []
    )

    partTypeDict = {x: partTypes.count(x) for x in set(partTypes)}

    ancestorProjs = sum(
        [
            allAncestors(self, x, combiDict[x][0])
            for x in mycombi
            if x in combiDict.keys()
        ],
        [],
    )
    ancestorProjs += [x for x in mycombi if x in combiDict.keys()]
    ancestorDict = {x: ancestorProjs.count(x) for x in set(ancestorProjs)}

    # this has two parts, first for shared subprojections, we reduce by the costs/savings of the shared projection (which is less than the rate of the primevents)
    for anc in ancestorDict.keys():
        if ancestorDict[anc] > 1:
            costs += (ancestorDict[anc] - 1) * combiDict[anc][2]
            if combiDict[anc][1]:  # ms ancestor
                partTypeDict[combiDict[anc][1][0]] -= ancestorDict[anc] - 1

    # then , we reduce by the savings for all partitioning primitive event types that are part of multiple different projections
    for partProj in partTypeDict.keys():
        # myAllPairs = DistMatrices[MSTrees[partProj]]
        # bestNodeValue = min([sum(x) for x in myAllPairs if x])
        costs += (
            (partTypeDict[partProj] - 1)
            * totalRate(self, partProj, self.h_projrates)
            * longestPath
        )

    return costs


def allSiSEvents(self, projection):
    MSTypes = allMSTypes(self, projection)
    # return list(set(list(''.join(map(lambda x: ''.join(x.leafs()),  projections)))).difference(set(MSTypes)))
    return list(set(projection.leafs()).difference(set(MSTypes)))


def allMSTypes(self, projection):
    combiDict = self.h_combiDict
    if projection in combiDict.keys():
        MSTypes = [
            combiDict[x][1][0]
            for x in allAncestors(self, projection, combiDict[projection][0])
            + [projection]
            if x in combiDict.keys() and combiDict[x][1]
        ]

        return [
            x for x in list(set(MSTypes)) if len(str(x)) == 1
        ]  # quatsch, trees müssen aus output von partproj raus
    else:
        return []


def allAncestors(self, projection, mycombi):
    combiDict = self.h_combiDict
    ancestors = []
    if len(projection.leafs()) == 2:  # has no complex ancestors
        return ancestors
    else:
        for i in mycombi:
            if len(i) > 1:  # is a complex event
                ancestors.append(i)
                if i in combiDict.keys():  # is something which has a combination
                    ancestors += allAncestors(self, i, combiDict[i][0])
    return list(set(ancestors))


def globalPartitioningOK(
    self, projection, combination, longestPath, MSTrees
):  # TODO: current version oversees the sharing potential with other projections with which the costs of those inputs are shared
    combiDict = self.h_combiDict
    additionalCriticals = []
    myMSDict = {}
    ancestors = allAncestors(self, projection, combination)

    myMSTypes = sum([allMSTypes(self, x) for x in combination], [])
    myMSTypes = set(
        [x for x in myMSTypes if myMSTypes.count(x) > 1]
    )  # only partprojs used multiple times can be problematic
    for etype in set(myMSTypes):
        myMSDict[etype] = [
            x for x in ancestors if combiDict[x][1] and etype in combiDict[x][1]
        ]
        myInputs = [
            x
            for x in list(set(sum([combiDict[y][0] for y in myMSDict[etype]], [])))
            if not x == etype
        ]
        mycosts = sum(
            map(lambda x: totalRate(self, x, self.h_projrates), myInputs)
        ) * len(MSTrees[etype].edges())

        if longestPath * totalRate(self, etype, self.h_projrates) < mycosts:
            additionalCriticals.append(etype)

    return additionalCriticals


def getExpensiveProjs(self, criticals):  # only on criticalTypes
    combiDict = self.h_combiDict
    wl = self.query_workload
    allProjs = sum(
        [
            allAncestors(self, x.stripKL_simple(), combiDict[x.stripKL_simple()][0])
            for x in wl
        ],
        [],
    )
    allMSProjs = [
        x for x in allProjs if combiDict[x][1] and combiDict[x][1][0] in criticals
    ]

    # only if projection is input to single sink (or multisink?)
    myMSProjs = [
        x
        for x in combiDict.keys()
        if set(allMSProjs).intersection(set(combiDict[x][0])).issubset(set(allMSProjs))
        and combiDict[x][1]
    ]
    # the inputs are already part of other multi-sink placements (or if at least some of the inputs are already disseminated)
    for proj in allMSProjs:
        print(str(proj) + " : " + str(totalRate(self, proj, self.h_projrates)))
    print(list(map(lambda x: str(x), myMSProjs)))

    #
    # allExpensiveMSProjs = [outRateHigh(x) for x in allMSProjs]
    return  # [combiDict[x][1][0] for x in allExpemensiveMSProjs if x in criticalTypes]


def outRateHigh(self, projection):
    combiDict = self.h_combiDict
    combi = combiDict[projection][0]
    partType = returnPartitioning(projection, combiDict[projection][0])
    outRate = totalRate(self, projection, self.h_projrates)
    return []


def unfold_combi(
    self, query, combination
):  # unfolds a combination, however in the new version we will have only one combination which is provided in the same format as the unfolded dict
    # print(f"[UNFOLD_COMBI] Processing query: {query}")
    # print(f"[UNFOLD_COMBI] Initial combination: {combination}")
    unfoldedDict = {}
    unfoldedDict[query] = combination
    # print(f"[UNFOLD_COMBI] Added to unfoldedDict: {query} -> {combination}")
    unfoldedDict.update(unfold_combiRec(self, combination, unfoldedDict))
    # print(f"[UNFOLD_COMBI] Final unfoldedDict: {unfoldedDict}")
    return unfoldedDict


def unfold_combiRec(self, combination, unfoldedDict):
    # print(f"[UNFOLD_REC] Processing combination: {combination}")
    combiDict = self.h_combiDict
    for proj in combination:
        # print(f"[UNFOLD_REC] Processing proj: {proj}, len(proj): {len(proj) if hasattr(proj, '__len__') else 'no len'}")
        if len(proj) > 1:
            # print(f"[UNFOLD_REC] Complex projection detected: {proj}")
            if proj in combiDict.keys():
                mycombination = combiDict[proj][0]
                # print(f"[UNFOLD_REC] Found in combiDict: {proj} -> {mycombination}")
            else:
                # Keep complex projections as subqueries instead of decomposing to primitives
                mycombination = [
                    proj
                ]  # this is the case if proj is a single sink projection, and we have to decide how to match it later
                # print(f"[UNFOLD_REC] Not in combiDict, keeping as subquery: {proj} -> {mycombination}")
            unfoldedDict[proj] = mycombination
            # print(f"[UNFOLD_REC] Added to unfoldedDict: {proj} -> {mycombination}")
            # print(f"[UNFOLD_REC] Recursively processing: {mycombination}")
            unfoldedDict.update(unfold_combiRec(self, mycombination, unfoldedDict))
        # else:
        # print(f"[UNFOLD_REC] Primitive event (len <= 1): {proj}")
    return unfoldedDict


def extract_primitive_events_for_projection(projection):
    """Extract all primitive events for a given projection, flattening complex subqueries.

    Args:
        projection: A projection object with leafs() method that returns primitive events

    Returns:
        List of primitive event strings
    """
    if hasattr(projection, "leafs"):
        return projection.leafs()
    else:
        # Handle string representations or simple event types
        return [str(projection)]


def generate_primitive_events_dict(mycombi):
    """Generate a dictionary mapping projections to their primitive events.

    This function takes the combination dictionary and creates a new dictionary
    where each projection maps to a list of its primitive events, with all
    complex subqueries flattened to their primitive components.

    Args:
        mycombi: Dictionary mapping projections to their combinations

    Returns:
        Dictionary mapping projection strings to lists of primitive event strings
    """
    primitive_events_dict = {}

    for projection, combination in mycombi.items():
        # Get primitive events from the projection itself
        primitive_events = []

        # Use the projection's leafs() method to get all primitive events
        if hasattr(projection, "leafs"):
            primitive_events = projection.leafs()
        else:
            # Fallback for simple projections
            primitive_events = [str(projection)]

        # Convert to strings and store in dictionary with projection string as key
        projection_str = str(projection)
        primitive_events_dict[projection_str] = [
            str(event) for event in primitive_events
        ]

    return primitive_events_dict


def generate_combigen(self):
    # TODO: Check for processingOrder
    combiDict = self.h_combiDict
    criticalMSTypes = []
    noFilter = 0
    shared = 1

    wl = self.query_workload
    projsPerQuery = self.h_projsPerQuery

    start_time = time.time()
    # random.shuffle(wl)
    for query in sorted(
        wl, key=(lambda x: len(projsPerQuery[x.stripKL_simple()])), reverse=True
    ):
        query = query.stripKL_simple()
        getBestChainCombis(self, query, shared, criticalMSTypes, noFilter)
        criticalMSTypes += allSiSEvents(self, query)
    end_time = time.time()

    combigenTime = round(end_time - start_time, 2)

    globalMSTypes = set(sum([allMSTypes(self, x.stripKL_simple()) for x in wl], []))
    # print("potentialMSTypes:  "  + str(globalMSTypes))
    globalSiSTypes = set(sum([allSiSEvents(self, x.stripKL_simple()) for x in wl], []))
    # print("globalSiSTypes:  "  + str(globalSiSTypes))
    criticalMSTypes = list(set(globalMSTypes).intersection(set(globalSiSTypes)))

    curcombi = {}

    for i in range(len(wl)):
        query = wl[i].stripKL_simple()
        # print(f"[GENERATE_COMBIGEN] Processing query {i}: {query}")
        # print(f"[GENERATE_COMBIGEN] Query in combiDict: {query in combiDict.keys()}")
        if query in combiDict.keys():
            # print(f"[GENERATE_COMBIGEN] combiDict[{query}]: {combiDict[query]}")
            # print(f"[GENERATE_COMBIGEN] combiDict[{query}][0]: {combiDict[query][0]}")
            curcombi.update(unfold_combi(self, query, combiDict[query][0]))

    mycombi = curcombi
    # print(f"[GENERATE_COMBIGEN] Final mycombi keys: {list(mycombi.keys())}")
    # print(f"[GENERATE_COMBIGEN] Final mycombi contents:")
    # for key, value in mycombi.items():
    #     print(f"  {key} -> {value}")

    # Check if SEQ(A, B) is referenced but missing
    referenced_projs = set()
    for key, value in mycombi.items():
        for item in value:
            if hasattr(item, "__str__") and len(str(item)) > 1:
                referenced_projs.add(str(item))

    mycombi_keys_str = {str(k) for k in mycombi.keys()}
    missing_projections = []
    for proj in referenced_projs:
        if proj not in mycombi_keys_str:
            missing_projections.append(proj)

    # Process missing projections that exist in combiDict
    for missing_proj_str in missing_projections:
        # Find the actual projection object in combiDict
        for combi_key in combiDict.keys():
            if str(combi_key) == missing_proj_str:
                curcombi.update(unfold_combi(self, combi_key, combiDict[combi_key][0]))
                break

    # Update mycombi with the newly processed projections
    mycombi = curcombi

    criticalMSProjs = [
        x
        for x in mycombi.keys()
        if combiDict[x][1] and combiDict[x][1][0] in criticalMSTypes
    ]

    # for pro in curcombi.keys():
    #     print(str(pro) + " " + str(list(map(lambda x: str(x), curcombi[pro]))))
    # print("time: " + str(end_time - start_time))
    # print(numberCombis)

    projlist = self.h_projlist

    # getExpensiveProjs(criticalMSTypes)
    # export number of queries, computation time combination, maximal query length,
    # TODO: maximal depth combination tree, portion of rates saved by multi-sink eventtypes
    combiExperimentData = [
        len(wl),
        combigenTime,
        max(len(x) for x in wl),
        len(projlist),
    ]

    # Generate primitive events dictionary
    primitive_events = generate_primitive_events_dict(mycombi)

    return (
        mycombi,
        combiDict,
        [criticalMSTypes, criticalMSProjs],
        combiExperimentData,
        primitive_events,
    )
