"""
Initialize selectivities for given tuple of primitive event types (projlist) within interval [x,y].
"""

import random as rd
import numpy as np
from core.proj_string import generate_twosets, change_order
from core.query_workload import get_primitive_events


def initialize_selectivities(primEvents, x=0.2, y=0.05):
    """Calculate selectivities for all projections in projlist within interval [x,y]."""

    """"
    Note from Finn Glück 27.08.2024:

    Changed x from 0.1 to 0.2 and y from 0.01 to 0.05 to make selectivities generally higher.
    Added max_rate to scale selectivities based on the highest event rate.
    This hopefully prevents extremely high output rates for projections with high-rate inputs.

    Changed random_float range from 0.0 - 0.3 to 0.0 - 0.4 and adjusted conditions from >0.2 to >0.3
    This decreases the chance of a selectivity being set to 1, making high selectivities less freuquent.
    """

    primitive_events_rates = primEvents
    primEvents = get_primitive_events(primEvents)

    projlist = generate_twosets(primEvents)
    projlist = list(set(projlist))
    selectivities = {}
    selectivity = 0

    # Make selectivities smaller based on the biggest rate
    max_rate = float(np.max(primitive_events_rates))

    for i in projlist:
        # if len(filter_numbers(i)) >1 :
        random_float = rd.uniform(0.0, 0.4)
        if random_float > 0.3:
            selectivity = 1
            selectivities[str(i)] = selectivity
            selectivities[str(change_order(i))] = selectivity
        if random_float <= 0.3:
            selectivity = float(rd.uniform(x, y) / max_rate)
            selectivities[str(i)] = selectivity
            selectivities[str(change_order(i))] = selectivity
    selectivitiesExperimentData = [x, float(np.median(list(selectivities.values())))]
    return selectivities, selectivitiesExperimentData


def increase_selectivities(
    percentage, selectivities
):  # multiply x percent of selectivities with factor ? -> 10 for starters
    number = int(len(list(selectivities.keys())) / 100) * percentage
    mylist = list(selectivities.keys())
    rd.shuffle(mylist)
    projs = mylist[0:number]
    for proj in projs:
        selectivities[proj] = selectivities[proj] * 10
    return selectivities
