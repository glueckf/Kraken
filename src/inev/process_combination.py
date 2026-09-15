#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Aug 16 11:47:10 2021

@author: samira
"""

from simulator.projections import return_partitioning
from inev.filter import get_maximal_filter


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
            for event in combiDict[proj] + list(
                get_maximal_filter(myProjFilters, proj)
            ):
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
