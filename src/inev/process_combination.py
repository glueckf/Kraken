#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Aug 16 11:47:10 2021

@author: samira
"""

from ines.projections import return_partitioning, set_to_proj, total_rate
import copy
from inev.filter import (
    get_maximal_filter,
    get_decomposed,
)
import string
from core.tree import Tree
from core.structures import get_num_etbs
import numpy as np


def compute_dependencies(
    self, combiDict, criticalMSTypes
):  # has as input a final combination
    """outputs a dictionary which has as keys the projections of a final combination and as corresponding key the level of the projection in the muse graph, for sis and ms projections having the same level, level for msp is increased as placements can be exploited here"""
    levels = {}
    for proj in combiDict.keys():
        if len(proj.leafs()) == 2 or set(combiDict[proj]) == set(proj.leafs()):
            levels[proj] = 0

    for proj in sorted(
        [x for x in combiDict.keys() if x not in levels.keys()],
        key=lambda z: len(z.leafs()),
    ):  # mit vorsicht zu genießen
        mymax = max(
            list(
                map(
                    lambda x: levels[x],
                    [x for x in combiDict[proj] if x in combiDict.keys()],
                )
            )
        )
        levels[proj] = mymax + 1

    # increase level  of projections having msp
    for proj in levels.keys():
        levels[proj] = levels[proj] * 2
    for proj in levels.keys():
        if not return_partitioning(
            self, proj, combiDict[proj], self.h_projrates, criticalMSTypes
        ):
            levels[proj] = levels[proj] + 1

    return levels


def copy_allAncestors(projection, mycombi):
    ancestors = []
    if len(projection.leafs()) == 2:  # has no complex ancestors
        return ancestors
    else:
        for i in mycombi[projection]:
            if len(i) > 1:  # is a complex event
                ancestors.append(i)
                if i in mycombi.keys():  # is something which has a combination
                    ancestors += copy_allAncestors(i, mycombi)
    return list(set(ancestors))


def pre_pone(mylist, index1, index2):
    toPop = mylist[index2]
    return (
        [mylist[x] for x in range(len(mylist)) if x < index1]
        + [mylist[index2]]
        + [mylist[index1]]
        + [x for x in mylist[index1 + 1 :] if not x == toPop]
    )


def compute_dependencies_simple(combiDict):  # has as input a final combination
    """outputs a dictionary which has as keys the projections of a final combination and as corresponding key the level of the projection in the muse graph, for sis and ms projections having the same level, level for msp is increased as placements can be exploited here"""
    levels = {}
    for proj in combiDict.keys():
        if len(proj.leafs()) == 2 or set(combiDict[proj]) == set(proj.leafs()):
            levels[proj] = 0

    for proj in sorted(
        [x for x in combiDict.keys() if x not in levels.keys()],
        key=lambda z: len(z.leafs()),
    ):  # mit vorsicht zu genießen
        mymax = max(
            list(
                map(
                    lambda x: levels[x],
                    [x for x in combiDict[proj] if x in combiDict.keys()],
                )
            )
        )
        levels[proj] = mymax + 1

    return levels


def get_shared_ms_input(self, combiDict, myProjFilters):
    """for each ms projection in final combination, check if there is an input in the current combination, that is shared with another ms projection, output is shared dict, which is used for MS placements"""
    sharedInput = {}
    criticalMSTypes = self.h_criticalMSTypes
    projrates = self.h_projrates
    for proj in combiDict.keys():
        part = return_partitioning(
            self, proj, combiDict[proj], projrates, criticalMSTypes
        )
        if part:  # only MS projections
            # for event in combiDict[proj]:
            for event in combiDict[proj] + list(get_maximal_filter(myProjFilters, proj)):
                if event not in sharedInput and not part[0] == event:
                    sharedInput[event] = [part[0]]
                elif not part[0] == event:
                    sharedInput[event].append(part[0])
    return sharedInput


def make_unredundant(combi):
    toRemove = []
    for i in combi:
        myset = set([x if len(x) == 1 else x.leafs() for x in [i]][0])
        for k in [x for x in combi if x != i]:
            outSet = set([x if len(x) == 1 else x.leafs() for x in [k]][0])
            if myset.issubset(outSet):
                toRemove.append(i)
    return [x for x in combi if x not in toRemove]


def remove_layer(combiDict, layer):  # make sure, that no query is removed from
    levels = compute_dependencies_simple(combiDict)
    # levels = compute_dependencies(combiDict)
    projections = [x for x in levels.keys() if levels[x] in layer and x not in wl]
    myCombination = copy.deepcopy(combiDict)
    for l in sorted(layer):
        newCombination = {}
        for i in sorted(
            [x for x in myCombination.keys() if not levels[x] == l],
            key=lambda y: len(y.leafs()),
        ):  # change only for projs with layer
            newCombination[i] = sum(
                [
                    [x]
                    if not (x in levels.keys() and levels[x] == l)
                    else myCombination[x]
                    for x in myCombination[i]
                ],
                [],
            )
        myCombination = copy.deepcopy(newCombination)
    newCombination = {
        x: make_unredundant(list(set(newCombination[x])))
        for x in list(newCombination.keys())
    }
    return newCombination


def remove_projection(combiDict, projection):
    combi = mycombi[projection]
    myCombination = copy.deepcopy(combiDict)
    newCombination = {}
    for i in [x for x in combiDict.keys() if not x == projection]:
        newCombination[i] = sum(
            [[x] if not (x == projection) else combi for x in myCombination[i]], []
        )
    return {
        x: make_unredundant(list(set(newCombination[x])))
        for x in list(newCombination.keys())
    }


def has_ms_parent(projection):  # checks for a projection if it is input to a MS placement
    for i in mycombi.keys():
        if projection in mycombi[i]:
            if originalDict[i][1] and i not in criticalMSProjections:
                return True
    else:
        return False


def remove_sis_chains():
    levels = compute_dependencies_simple(mycombi)
    newlevels = {}
    toRemove = []
    for x in levels.values():
        newlevels[x] = []
        for k in levels.keys():
            if x == levels[k]:
                newlevels[x].append(k)

    for i in [x for x in newlevels.keys() if not x == max(newlevels.keys())]:
        count = 0
        for proj in [x for x in newlevels[i] if x not in wl]:
            if originalDict[proj][1] or has_ms_parent(proj):  # has multisink placement
                break
            elif proj in criticalMSProjections:
                count += 1
            else:
                count += 1
        if count == len(newlevels[i]):
            toRemove.append(i)
    newcombi = copy.deepcopy(mycombi)
    if toRemove:
        newcombi = remove_layer(mycombi, toRemove)
    newcombi = remove_sis_families(newcombi)
    return newcombi


def remove_sis_families(combi):
    toRemove = []
    for i in [x for x in combi.keys() if x not in wl]:
        if not originalDict[i][1] and not has_ms_parent(i):
            toRemove.append(i)
        elif i in criticalMSProjections:
            toRemove.append(i)
    newcombi = combi
    for i in toRemove:
        newcombi = remove_projection(newcombi, i)
    return newcombi


def str_to_proj(subProj, projection):
    if isinstance(subProj, Tree):
        return subProj
    elif len(subProj) == 1:
        return subProj
    else:
        evlist = []
        for i in range(len(subProj)):
            if not (i == 0 or i == len(subProj) - 1):
                if subProj[i - 1] not in list(string.ascii_uppercase) and subProj[
                    i + 1
                ] not in list(string.ascii_uppercase):
                    evlist.append(subProj[i])
        return set_to_proj(evlist, projection)


def get_div(i, partType):
    if len(i) == 1:
        if i == partType:
            return instances[partType]
        return 1
    elif partType in i.leafs():
        return instances[partType]
    return 1


def get_filtered_rate(projection, diamond, filtered):
    if len(diamond) == 1:
        if diamond in filtered:
            return singleSelectivities[
                get_key_single_select(diamond, projection)
            ] * total_rate(diamond)
        return total_rate(diamond)

    lst = [
        x for x in diamond.leafs() if x in filtered
    ]  # return list of filtered events contained in projection
    filter_lst = [x for x in diamond.leafs() if x not in lst]
    lst = list(
        map(lambda x: singleSelectivities[get_key_single_select(x, projection)], lst)
    )
    filter_lst = list(
        map(lambda x: singleSelectivities[get_key_single_select(x, diamond)], filter_lst)
    )
    prod = 1
    for i in lst + filter_lst:
        prod *= i
    return diamond.evaluate() * get_num_etbs(diamond) * prod


def diamond_costs_filtered(projection, diamonds, filtered):
    costs = 0
    for diamond in diamonds:
        diamond1 = get_filtered_rate(projection, diamond[0], filtered)
        diamond2 = get_filtered_rate(projection, diamond[1], filtered)
        costs += diamond1 + diamond2 + diamond1 * diamond2
    return costs


def diamond_costs(projection, diamonds, partType):
    costs = 0
    div = False
    for i in diamonds:
        div0 = get_div(i[0], partType)
        div1 = get_div(i[1], partType)
        costs += (
            total_rate(i[0]) / div0
            + total_rate(i[1]) / div1
            + total_rate(i[0]) / div0 * total_rate(i[1]) / div1
        )
    return costs


def get_mini_diamonds(
    projection, partType, combination, *args
):  # args is list of filtered events
    samplingSize = (
        1  # len(combination) * 25 # TODO adjust to length/number of possibilities
    )
    costs = np.inf
    outDiamonds = []
    diamonds = []

    if args:
        filteredEvents = args[0]
        if len(args) > 1:
            samplingSize = args[1]
    else:
        filteredEvents = ""

    for i in range(samplingSize):
        originalDiamonds = copy.deepcopy(diamonds)
        mycosts = 0
        myDiamonds = get_mini_diamonds_rec(
            projection, partType, combination, originalDiamonds
        )
        if filteredEvents:
            mycosts = diamond_costs_filtered(projection, myDiamonds, filteredEvents)
        else:
            mycosts = diamond_costs(projection, myDiamonds, partType)
        if mycosts < costs:
            outDiamonds = myDiamonds
            costs = mycosts
    return outDiamonds


def get_mini_diamonds_rec(projection, partType, combination, diamonds):
    combination = list(map(lambda x: str_to_proj(x, projection), combination))
    if len(combination) == 2:
        diamondTuple = combination
        diamonds.append(diamondTuple)
        return diamonds
    else:
        curMax = int(np.random.uniform(0, len(combination)))
        curMin = int(np.random.uniform(0, len(combination)))
        if curMax == curMin:
            if curMax < len(combination) - 1:
                curMax += 1
            else:
                curMax -= 1
        diamondTuple = [combination[curMax], combination[curMin]]
        diamonds.append(diamondTuple)
        combination = [x for x in combination if x not in diamondTuple]
        # print([x.leafs() if len(x)> 1 else [x] for x in diamondTuple])
        combination.append(
            set_to_proj(
                sum([x.leafs() if len(x) > 1 else [x] for x in diamondTuple], []),
                projection,
            )
        )

        return get_mini_diamonds_rec(projection, partType, combination, diamonds)


def get_ms_inputs():
    out = []
    for proj in mycombi.keys():
        part = originalDict[proj][1]
        if part:
            myInputs = [
                x
                for x in mycombi[proj]
                if not x == part[0] and len(x) == 1 and part[0] not in criticalMSTypes
            ]
            out.append(myInputs)
    return sum(out, [])


def augment_proj_filters(old, additional, mylist):
    for proj in mycombi.keys():
        additionalFilters = []
        for event in mylist:
            if event in additional[proj].keys():
                additionalFilters.append(event)
        oldFilter = get_maximal_filter(old, proj, 0)
        additionalFilters = [x for x in additionalFilters if x not in oldFilter]
        newFilter = "".join(additionalFilters)
        old[proj][newFilter] = get_decomposed(additionalFilters, proj)
    return old
