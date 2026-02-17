#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Aug 19 11:45:00 2021

@author: samira
"""

from core.util import column1s, column
import numpy as np


def init_event_nodes(
    nodes, network
):  # matrice: comlumn indices are node ids, row indices correspond to etbs, for a given etb use IndexEventNodes to get row ID for given ETB
    # Storign all nodes producing a given event type with a 1 in the corresponding list
    # Node generating event type A would have: [1,0,0,0,...]
    myEventNodes = []
    # Storing a dictionary with the event type and node id as key and the index in the myEventNodes type for the list.
    myIndexEventNodes = {}
    offset = 0
    index = 0
    # For each primitve event
    for etype in nodes.keys():
        myetbs = []
        # each node producting the event type
        for node in nodes[etype]:
            # creating a list of zeros with the length of the network
            mylist = [0 for x in range(len(network.keys()))]
            # Adding a 1 at the position of the node producing the event
            mylist[node] = 1
            myEventNodes.append(mylist)
            myIndexEventNodes[etype + str(node)] = index
            index += 1
            myetbs.append(etype + str(node))
        myIndexEventNodes[etype] = myetbs
        # offset = index
    return (myEventNodes, myIndexEventNodes)


def get_etbs(node, EventNodes, IndexEventNodes):
    mylist = column1s(column(EventNodes, node))
    return [
        list(IndexEventNodes.keys())[list(IndexEventNodes.values()).index(x)]
        for x in mylist
    ]  # index from row id <-> etb


def get_nodes(etb, EventNodes, IndexEventNodes):
    return column1s(EventNodes[IndexEventNodes[etb]])


def set_event_nodes(node, etb, EventNodes, IndexEventNodes):
    EventNodes[IndexEventNodes[etb]][node] = 1


def unset_event_nodes(node, etb, EventNodes, IndexEventNodes):
    EventNodes[IndexEventNodes[etb]][node] = 0


def add_etb(etb, etype, EventNodes, IndexEventNodes, network):
    mylist = [0 for x in range(len(network.keys()))]
    EventNodes.append(mylist)
    index = len(EventNodes) - 1
    IndexEventNodes[etb] = index
    if etype not in IndexEventNodes:
        IndexEventNodes[etype] = [etb]
    else:
        IndexEventNodes[etype].append(etb)


def sis_manage_etbs(projection, node, IndexEventNodes, EventNodes, network):
    etbID = generic_etb("", projection, node)[0]
    add_etb(etbID, projection, EventNodes, IndexEventNodes, network)
    set_event_nodes(node, etbID, EventNodes, IndexEventNodes)


def ms_manage_etbs(self, projection, parttype):
    nodes = self.h_nodes
    network = self.h_network_data
    eventNodes = self.h_eventNodes
    IndexEventNodes = self.h_IndexEventNodes
    etbIDs = generic_etb(parttype, projection, nodes)
    for projectionETB in etbIDs:
        add_etb(projectionETB, projection, eventNodes, IndexEventNodes, network)
    for i in range(len(nodes[parttype])):
        set_event_nodes(nodes[parttype][i], etbIDs[i], eventNodes, IndexEventNodes)


def generic_etb(partType, projection, nodes):
    ETBs = []
    if len(partType) == 0 or partType not in projection.leafs():
        myID = ""
        for etype in projection.leafs():
            myID += etype
        ETBs.append(myID)
    else:
        for node in nodes[partType]:
            myID = ""
            for etype in projection.leafs():
                myID += etype
                if etype == partType:
                    myID += str(node)
            ETBs.append(myID)
    return ETBs


def get_num_etbs(projection, IndexEventNodes):
    num = 1
    for etype in projection.leafs():
        num *= len(IndexEventNodes[etype])
    return num


def num_etbs_by_key(etb, projection, IndexEventNodes):
    instancedEvents = []
    index = 0
    if len(projection) == 1:
        return 1
    for i in range(1, len(etb)):
        if (
            etb[i] not in projection.leafs()
            and etb[index] in projection.leafs()
            and etb[index] not in instancedEvents
        ):
            instancedEvents.append(etb[index])
        elif etb[i] in projection.leafs():
            index = i

    num = get_num_etbs(projection, IndexEventNodes)
    for etype in instancedEvents:
        num = num / len(IndexEventNodes[etype])
    return num


def get_longest(allPairs):
    avs = []
    for i in allPairs:
        avs.append(np.average(i))
    return np.median(avs)
