import logging

from core.structures import getNumETBs


logger = logging.getLogger(__name__)


def computePromisingType(self, projection):
    projrates = self.h_projrates
    longestPath = self.h_longestPath
    rates = self.h_rates_data
    IndexEventNodes = self.h_IndexEventNodes
    promisingEvent = "X"
    currentSave = 0
    for primEvent in projection.leafs():
        decomposedSum = getDecomposedTotal(
            [primEvent], projection, self.single_selectivity, rates, self.h_instances
        )
        rateSaved = (
            projrates[projection][1] * numETBs("", projection, self.h_IndexEventNodes)
        ) - (
            (longestPath * rates[primEvent] * len(IndexEventNodes[primEvent]))
            + decomposedSum
        )
        if (
            rateSaved > currentSave and rateSaved > 0
        ):  # saved rate must include costs for routing promising event to dest, prob not necessary
            currentSave = rateSaved
            promisingEvent = primEvent
    if promisingEvent != "X":
        return (
            promisingEvent,
            getDecomposed([promisingEvent], projection, self.single_selectivity, rates),
        )
    else:
        return (
            promisingEvent,
            getDecomposed([promisingEvent], projection, self.single_selectivity, rates),
        )


def numETBs(primEvents, projection, IndexEventNodes):
    count = 1
    for event in projection.leafs():
        if event not in primEvents:
            count *= len(IndexEventNodes[event])
    return count


def getDecomposed(primEvents, projection, singleSelectivities, rates):
    mysum = 0
    for event in projection.leafs():
        if event not in primEvents:
            myKey = getKeySingleSelect(event, projection)
            mysum += singleSelectivities[myKey] * rates[event]
    return mysum


def getDecomposedTotal(primEvents, projection, singleSelectivities, rates, instances):
    mysum = 0
    for event in [
        x for x in projection.leafs() if x not in primEvents
    ]:  # implement for list of primEvents, to use during placement
        myKey = getKeySingleSelect(event, projection)
        selectivity = singleSelectivities.get(myKey)
        if selectivity is None:
            logger.debug(
                "Missing single selectivity entry for key '%s'; defaulting to 0",
                myKey,
            )
            continue
        rate_value = rates.get(event)
        instance_value = instances.get(event)
        if rate_value is None or instance_value is None:
            logger.debug(
                "Missing rate/instance for event '%s' (rate=%s, instance=%s); skipping contribution",
                event,
                rate_value,
                instance_value,
            )
            continue
        mysum += selectivity * rate_value * instance_value
    return mysum


def getKeySingleSelect(primEvent, projection):
    myString = primEvent + "|" + "".join(sorted(projection.leafs()))
    return myString


""" def additionalFilters(projection, promisingEvent):
    additionalFiltersList = []
    for event in projection.leafs():
        if not event  == promisingEvent:
            myKey = getKeySingleSelect(event, projection)
            #commonETBS = len(IndexEventNodes[promisingEvent]) * numETBs([event, promisingEvent],projection)
            commonETBS = numETBs([event, promisingEvent],projection)
            additionalSavings = commonETBS *  singleSelectivities[myKey] * rates[event]
            additionalSavings -= rates[event] * longestPath        
            if additionalSavings > 0 :
                additionalSavings += rates[event] * longestPath # do not substract by upper bound of sending filters, as actual costs can be computed during placement
                additionalSavings *= len(IndexEventNodes[event])
                additionalFiltersList.append((event, additionalSavings))
    return additionalFiltersList 
 """


def returnProjFilterDict(self, projection):
    """return for a projection with different subsets of primitive events that can be used as filters and the resulting rate of the projection"""
    ProjFilterDict = {}
    projrates = self.h_projrates
    # totalRate = numETBs("", projection) * projrates[projection][1]
    totalRate = projrates[projection][1]  # singleRate
    ProjFilterDict[projection] = {}
    ProjFilterDict[projection][""] = (totalRate, 0)
    promising = computePromisingType(self, projection)

    if promising[0] != "X":
        currentKey = promising[0]
        currentRate = promising[1]
        ProjFilterDict[projection][currentKey] = (currentRate, 0)

    return ProjFilterDict


def getMaximalFilter(filterdict, proj, *args):
    if args:
        if args[0] == 1:
            return sorted(filterdict[proj].keys(), key=len)[
                0
            ]  # USED TO SUPRESS FILTER!!!
    return sorted(filterdict[proj].keys(), key=len, reverse=True)[0]


def getPMs(projection, myfilter):
    totalETBs = numETBs("", projection)
    return 0


def returnAdditionalFilterDict(self):
    projrates = self.h_projrates
    additional = {}
    for i in projrates.keys():
        additional[i] = {}
        myrate = projrates[i][1] * getNumETBs(i)
        for k in i.leafs():
            if (
                getDecomposedTotal(
                    [k], i, self.single_selectivity, self.h_rates_data, self.h_instances
                )
                < myrate
            ):
                additional[i][k] = (
                    getDecomposed([k], i),
                    self.single_selectivity,
                    self.h_rates_data,
                )
    return additional
