import logging

from core.structures import get_num_etbs


logger = logging.getLogger(__name__)


def compute_promising_type(self, projection):
    projrates = self.h_projrates
    longestPath = self.h_longestPath
    rates = self.h_rates_data
    IndexEventNodes = self.h_IndexEventNodes
    promisingEvent = "X"
    currentSave = 0
    for primEvent in projection.leafs():
        decomposedSum = get_decomposed_total(
            [primEvent], projection, self.single_selectivity, rates, self.h_instances
        )
        rateSaved = (
            projrates[projection][1] * num_etbs("", projection, self.h_IndexEventNodes)
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
            get_decomposed(
                [promisingEvent], projection, self.single_selectivity, rates
            ),
        )
    else:
        return (
            promisingEvent,
            get_decomposed(
                [promisingEvent], projection, self.single_selectivity, rates
            ),
        )


def num_etbs(primEvents, projection, IndexEventNodes):
    count = 1
    for event in projection.leafs():
        if event not in primEvents:
            count *= len(IndexEventNodes[event])
    return count


def get_decomposed(primEvents, projection, singleSelectivities, rates):
    mysum = 0
    for event in projection.leafs():
        if event not in primEvents:
            myKey = get_key_single_select(event, projection)
            mysum += singleSelectivities[myKey] * rates[event]
    return mysum


def get_decomposed_total(primEvents, projection, singleSelectivities, rates, instances):
    mysum = 0
    for event in [
        x for x in projection.leafs() if x not in primEvents
    ]:  # implement for list of primEvents, to use during placement
        myKey = get_key_single_select(event, projection)
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


def get_key_single_select(primEvent, projection):
    myString = primEvent + "|" + "".join(sorted(projection.leafs()))
    return myString


""" def additionalFilters(projection, promisingEvent):
    additionalFiltersList = []
    for event in projection.leafs():
        if not event  == promisingEvent:
            myKey = get_key_single_select(event, projection)
            #commonETBS = len(IndexEventNodes[promisingEvent]) * num_etbs([event, promisingEvent],projection)
            commonETBS = num_etbs([event, promisingEvent],projection)
            additionalSavings = commonETBS *  singleSelectivities[myKey] * rates[event]
            additionalSavings -= rates[event] * longestPath        
            if additionalSavings > 0 :
                additionalSavings += rates[event] * longestPath # do not substract by upper bound of sending filters, as actual costs can be computed during placement
                additionalSavings *= len(IndexEventNodes[event])
                additionalFiltersList.append((event, additionalSavings))
    return additionalFiltersList 
 """


def return_proj_filter_dict(self, projection):
    """return for a projection with different subsets of primitive events that can be used as filters and the resulting rate of the projection"""
    ProjFilterDict = {}
    projrates = self.h_projrates
    # total_rate = num_etbs("", projection) * projrates[projection][1]
    total_rate = projrates[projection][1]  # singleRate
    ProjFilterDict[projection] = {}
    ProjFilterDict[projection][""] = (total_rate, 0)
    promising = compute_promising_type(self, projection)

    if promising[0] != "X":
        currentKey = promising[0]
        currentRate = promising[1]
        ProjFilterDict[projection][currentKey] = (currentRate, 0)

    return ProjFilterDict


def get_maximal_filter(filterdict, proj, *args):
    if args:
        if args[0] == 1:
            return sorted(filterdict[proj].keys(), key=len)[
                0
            ]  # USED TO SUPRESS FILTER!!!
    return sorted(filterdict[proj].keys(), key=len, reverse=True)[0]


def get_pms(projection, myfilter):
    return 0


def return_additional_filter_dict(self):
    projrates = self.h_projrates
    additional = {}
    for i in projrates.keys():
        additional[i] = {}
        myrate = projrates[i][1] * get_num_etbs(i)
        for k in i.leafs():
            if (
                get_decomposed_total(
                    [k], i, self.single_selectivity, self.h_rates_data, self.h_instances
                )
                < myrate
            ):
                additional[i][k] = (
                    get_decomposed([k], i),
                    self.single_selectivity,
                    self.h_rates_data,
                )
    return additional
