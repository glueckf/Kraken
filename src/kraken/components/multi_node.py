"""Multi-node placement: one projection evaluated by several instances.

A single-node placement needs one host that every sender of every input
reaches. A multi-node placement splits one input X over several instances:

- every instance receives all senders of every other input (the complete
  inputs), and
- each sender of X sends to exactly one instance.

Every combination of one sender per input then meets at exactly one
instance, so no match is lost and none is produced twice. Only one input can
be split: with two split inputs, a B event at instance 1 would never meet a
C event at instance 2.

A sender is a node that delivers an input with some rate: for a primitive
event a node producing it, for a placed subquery the node of one of its
instances (its output rate).

As in INEv, placement takes two steps:

1. ``splittable_inputs``: is a multi-node placement possible at all? Input X
   can be split if some candidate hosts are reached by every sender of the
   complete inputs and each sender of X reaches at least one of them.
2. ``choose_instances``: which of those hosts run an instance and which X
   senders each one receives, an uncapacitated facility location problem
   solved greedily.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence, Tuple

Sender = Tuple[int, float]  # (node, rate)
Assignment = Tuple[Tuple[int, Tuple[int, ...]], ...]  # ((host, split senders), ...)


@dataclass(frozen=True)
class MultiNodeOption:
    """A multi-node placement of one projection.

    split_input: the dependency whose senders are split over the instances.
    assignment: one (host, nodes of the split input's senders it receives)
        pair per instance, sorted by host; every split sender appears once.
    """

    split_input: Any
    assignment: Assignment

    @property
    def hosts(self) -> Tuple[int, ...]:
        return tuple(host for host, _ in self.assignment)


def splittable_inputs(
    senders: Dict[Any, List[Sender]],
    hosts: Sequence[int],
    reaches: Callable[[int, int], bool],
) -> Dict[Any, List[int]]:
    """Step 1: the inputs a multi-node placement can split.

    Args:
        senders: Senders of each input of the projection.
        hosts: Nodes allowed to host an instance.
        reaches: reaches(sender, host) is True if the sender's events can
            flow to the host.

    Returns:
        For each splittable input, the hosts every sender of the other inputs
        reaches (sorted). An input with fewer than two senders cannot be split.
    """
    if len(senders) < 2:
        return {}
    splittable = {}
    for split, split_senders in senders.items():
        if len(split_senders) < 2:
            continue
        complete = {node for dep, lst in senders.items() if dep != split for node, _ in lst}
        valid = sorted(h for h in hosts if all(reaches(c, h) for c in complete))
        if valid and all(any(reaches(u, h) for h in valid) for u, _ in split_senders):
            splittable[split] = valid
    return splittable


def choose_instances(
    split_senders: List[Sender],
    complete_senders: List[Sender],
    hosts: Sequence[int],
    reaches: Callable[[int, int], bool],
    distances: Any,
    output_per_split_rate: float = 0.0,
    sink_distance: Callable[[int], float] = lambda host: 0.0,
) -> List[Assignment]:
    """Step 2: pick the instances among the hosts of a splittable input.

    All-push costs (rate x hops, as in CostCalculator):
    - an instance on host h costs sum(rate x hops(c -> h)) over all complete
      senders c (every instance receives them all);
    - sending split sender u to h costs rate(u) x hops(u -> h), plus the hops
      from h to the sink(s) for u's share of the output,
      output_per_split_rate x rate(u) (sink_distance(h) is 0 if the output
      needs no sink).

    Returns up to two assignments with at least two instances:
    - the widest split: each split sender at its cheapest host (shortest
      paths, like INEv's multi-sink placement at the sources);
    - a local optimum: starting from the widest split, close or open one
      host at a time while the total cost drops.
    A result with a single instance is a single-node placement, which the
    single-node candidates already cover, so it is left out.
    """
    units = sorted(node for node, _ in split_senders)
    rate = dict(split_senders)
    feasible = {u: [h for h in hosts if reaches(u, h)] for u in units}

    instance_cost = {
        h: sum(r * distances[c][h] for c, r in complete_senders) for h in hosts
    }
    unit_cost = {
        u: {
            h: rate[u] * (distances[u][h] + output_per_split_rate * sink_distance(h))
            for h in feasible[u]
        }
        for u in units
    }

    def assign(open_hosts):
        assignment = {}
        for u in units:
            options = [h for h in feasible[u] if h in open_hosts]
            if not options:
                return None
            assignment[u] = min(options, key=lambda h: (unit_cost[u][h], h))
        return assignment

    def total(assignment):
        used = set(assignment.values())
        return sum(instance_cost[h] for h in used) + sum(
            unit_cost[u][h] for u, h in assignment.items()
        )

    widest = assign(set(hosts))
    if widest is None:
        return []

    best, best_cost = widest, total(widest)
    for _ in range(2 * len(hosts) + 1):  # each accepted move strictly improves
        used = set(best.values())
        moves = [used - {h} for h in sorted(used)]  # close one instance
        moves += [used | {h} for h in hosts if h not in used]  # open one
        improved = None
        for open_hosts in moves:
            candidate = assign(open_hosts)
            if candidate is None:
                continue
            cost = total(candidate)
            if cost < best_cost - 1e-9 and (improved is None or cost < improved[1]):
                improved = (candidate, cost)
        if improved is None:
            break
        best, best_cost = improved

    options = []
    for assignment in (widest, best):
        grouped: Dict[int, List[int]] = {}
        for u, h in assignment.items():
            grouped.setdefault(h, []).append(u)
        option = tuple((h, tuple(sorted(us))) for h, us in sorted(grouped.items()))
        if len(option) >= 2 and option not in options:
            options.append(option)
    return options
