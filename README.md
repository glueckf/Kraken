# Kraken -- Greedy Operator Placement Engine for Distributed CEP

## Overview

Kraken is a novel greedy placement engine for distributed Complex Event Processing (CEP) that jointly optimizes operator placement and push-pull communication strategy selection in a single optimization pass. Unlike prior approaches that treat operator placement and communication optimization as separate, sequential steps, Kraken formulates the combined problem as a state-space search and solves it incrementally using pluggable search strategies (greedy or k-beam).

The repository ships with a full simulation environment for evaluating Kraken against four comparison baselines:

- **All-Push** -- All operators placed at the cloud; all events pushed upstream.
- **INEv** -- Distributes operators across fog nodes to reduce transmission cost.
- **INES** -- Applies PrePP push-pull optimization on top of INEv's operator placement.
- **PrePP** -- Push-pull optimization only, with all operators at the cloud.

All strategies are evaluated on randomly generated hierarchical fog-cloud network topologies with configurable depth, connectivity, event distributions, and query workloads.

---

## Prerequisites and Installation

**Requirements.** Python 3.8+. Linux is recommended for large-scale experiments; macOS works for development.

```bash
# Clone and set up a virtual environment
git clone <repository-url>
cd INES
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Verify the installation
cd src
python -c "from simulation_environment import Simulation, SimulationConfig; print('Import OK')"
```

| Package            | Purpose                                        |
|--------------------|------------------------------------------------|
| `networkx ~= 3.5`  | Graph representation and shortest-path routing |
| `numpy ~= 2.3`     | Numerical operations and event rate generation |
| `pandas == 2.2.3`   | DataFrame operations for result aggregation    |
| `pyarrow == 19.0.1` | Parquet file I/O for result storage            |
| `matplotlib ~= 3.10` | Plotting (optional, for analysis)             |

---

## Kraken Architecture

Kraken formulates operator placement as a **state-space search problem**. It processes projections (query sub-expressions) in topological dependency order and, for each one, evaluates candidate placement nodes and communication strategies (all-push vs. push-pull), building up a solution incrementally. The key insight is that by jointly deciding *where* to place an operator and *how* to acquire its inputs in one step, Kraken avoids the suboptimality of sequential two-phase approaches.

### Module Structure

```
kraken/
|-- run.py                          # Orchestrator: problem setup, strategy execution, result aggregation
|-- problem.py                      # PlacementProblem: state-space definition, expand(), goal test, pruning
|-- data/
|   |-- state.py                    # SolutionCandidate (partial/complete solution), PlacementInfo (single decision)
|   `-- acquisition_step.py         # AcquisitionStep, AcquisitionSet (data acquisition plan per placement)
|-- search/
|   |-- base.py                     # SearchStrategy abstract interface
|   |-- greedy.py                   # GreedySearch: always picks lowest-cost successor, O(n * m) time
|   `-- beam.py                     # BeamSearch(k): maintains k best partial solutions, O(n * k * m) time
|-- components/
|   |-- cost_calculator.py          # Computes all-push and push-pull costs for a placement
|   |-- optimizer.py                # Candidate node selection (feasibility filtering)
|   |-- sorter.py                   # Node ordering heuristic (prioritize nodes with events already available)
|   `-- event_stack_manager.py      # Tracks event availability per node across placements
`-- utils/
    `-- results_logger.py           # Parquet result writing
```

### Key Abstractions

**PlacementProblem** models the search space as a tree. The root is an empty solution (no projections placed). A goal state is a solution where all projections have been placed. The `expand(state)` method generates all valid successor states by placing the next projection in the processing order on each feasible node with each viable communication strategy. Successors are scored using a normalized weighted sum of cost and latency, then returned in sorted order.

**SolutionCandidate** is an immutable record of a partial or complete solution. It carries the set of placement decisions made so far, cumulative cost, cumulative processing latency, and the event stack (which events are available at which nodes). The critical-path latency is computed on demand by traversing the dependency chain.

**PlacementInfo** records a single placement decision: the projection, the chosen node, the communication strategy (`all_push` or `push_pull`), cost breakdown, latency components, and the acquisition steps describing how each input is obtained.

**SearchStrategy** is a pluggable interface with two implementations:
- `GreedySearch` performs depth-first search, always expanding the lowest-cost successor. Time complexity is O(n * m) where n is the number of projections and m is the average number of candidate nodes.
- `BeamSearch(k)` maintains the k best partial solutions at each level, exploring a wider search frontier. Time complexity is O(n * k * m).

**CostCalculator** is the most complex component. For each candidate placement, it computes the all-push cost directly (summing rate * distance for each input event from each source node), then invokes PrePP internally to compute the push-pull alternative. It adjusts for events already available at the candidate node (tracked via the event stack), adds sink transmission costs for workload root queries, and returns both strategies when they differ.

---

## Comparison Baselines

| Strategy     | Description |
|--------------|-------------|
| **All-Push** | Baseline: all operators at the cloud (node 0). Every primitive event is pushed to the cloud for processing. Establishes the upper bound on transmission cost. |
| **INEv**     | Operator placement algorithm that distributes operators across fog nodes to minimize transmission cost, using a centralized cost model and multi-sink filtering. |
| **INES**     | Two-phase approach: first applies INEv operator placement, then runs PrePP push-pull optimization on the resulting placement. |
| **PrePP**    | Push-pull optimization with all operators remaining at the cloud. Selects between push and pull for each event acquisition step, but does not move operators. |
| **Kraken**   | Joint optimization of operator placement and communication strategy in a single incremental pass. Supports greedy and k-beam search strategies. |

---

## Project Structure

```
INES/
|-- README.md                          # This file
|-- requirements.txt                   # Python dependencies
|-- .gitignore
|-- src/
|   |-- start_simulation.py            # Main entry point for running experiments
|   |-- simulation_environment.py      # Simulation orchestrator and configuration
|   |-- core/                          # Network topology, graph utilities, workload generation
|   |   |-- network.py                 # Random tree generation, event rate distribution
|   |   |-- graph.py                   # NetworkX fog-cloud graph construction
|   |   |-- all_pairs.py              # All-pairs shortest path computation
|   |   |-- query_workload.py         # Random CEP query workload generation
|   |   |-- node.py                   # Node data structure
|   |   |-- structures.py            # Event node matrices and utility structures
|   |   |-- write_config.py          # Configuration buffer generation for PrePP
|   |   `-- ...
|   |-- ines/                          # INES-specific logic (projections, selectivities)
|   |   |-- operator_placement.py     # INEv-based operator placement
|   |   |-- projections.py           # Projection generation from query workload
|   |   |-- selectivity.py           # Pairwise selectivity initialization
|   |   |-- combigen.py              # Combination generation for shared projections
|   |   `-- ...
|   |-- inev/                          # INEv placement augmentation and filtering
|   |   |-- placement_aug.py         # Cost computation for centralized placement
|   |   |-- filter.py                # Multi-sink filter logic
|   |   `-- process_combination.py   # Dependency computation for projections
|   |-- prepp/                         # PrePP push-pull plan generation
|   |   |-- prepp.py                  # Main PrePP solver
|   |   |-- generate_eval_plan.py    # Evaluation plan generation from INEv results
|   |   `-- push_pull_plan_generator.py  # Push-pull strategy enumeration
|   |-- kraken/                        # Kraken placement engine (novel contribution)
|   |   |-- run.py                    # Kraken entry point and orchestrator
|   |   |-- problem.py               # PlacementProblem definition
|   |   |-- search/                   # Search strategies (greedy, beam search)
|   |   |-- components/              # Cost calculator, optimizer, sorter
|   |   |-- data/                    # Data structures (state, acquisition steps)
|   |   `-- utils/                   # Result logging utilities
|   `-- result/                        # Output directory for Parquet result files
`-- .gitignore
```

---

## Running the Simulation

### Entry Point

All simulations are launched from the `src/` directory.

```bash
cd src
python start_simulation.py
```

This executes the experiment defined in the `main()` function of `start_simulation.py`. Parameters are configured directly in the Python source code -- there are no external configuration files.

### Simulation Parameters

| Parameter              | Type           | Default | Description |
|------------------------|----------------|---------|-------------|
| `network_sizes`        | `List[int]`    | `[100]` | Number of nodes in the network topology. |
| `workload_sizes`       | `List[int]`    | `[5]`   | Number of queries in each workload. |
| `query_lengths`        | `List[int]`    | `[5]`   | Average number of primitive events per query. |
| `parent_factors`       | `List[float]`  | `[1.8]` | Controls maximum parents per node: `max_parents = parent_factor * ceil(log2(network_size))`. |
| `node_event_ratios`    | `List[float]`  | `[0.7]` | Probability that a leaf node generates a given event type. |
| `num_event_types`      | `List[int]`    | `[6]`   | Number of distinct primitive event types (A, B, C, ...). |
| `event_skews`          | `List[float]`  | `[2.0]` | Zipf exponent controlling event rate distribution skewness. |
| `runs_per_combination` | `int`          | `50`    | Number of independent simulation runs per parameter combination. |
| `xi`                   | `float`        | `0.0`   | Weighting factor for processing latency in the objective function. |
| `latency_threshold`    | `float`        | `None`  | If set, multiplied by All-Push latency to constrain placement latency. |
| `cost_weight`          | `float`        | `1`     | Weight for cost in the cost-latency trade-off (latency weight = 1 - cost_weight). |

### Simulation Modes

| Mode                  | Enum Value         | Description |
|-----------------------|--------------------|-------------|
| `RANDOM`              | `"random"`         | All components (topology, workload, selectivities) are randomly generated each run. |
| `FIXED_TOPOLOGY`      | `"fixed_topology"` | Network topology is hardcoded; workload and selectivities are random. |
| `FIXED_WORKLOAD`      | `"fixed_workload"` | Topology and workload are hardcoded; selectivities are random. |
| `FULLY_DETERMINISTIC` | `"deterministic"`  | All components are hardcoded for full reproducibility. |

### Execution Parameters

| Parameter              | Type    | Default   | Description |
|------------------------|---------|-----------|-------------|
| `enable_parallel`      | `bool`  | `True`    | Enable parallel execution of simulation runs. |
| `max_workers`          | `int`   | CPU count | Number of parallel worker processes. |
| `output_dataset_name`  | `str`   | `None`    | Custom name for the output Parquet dataset directory. Defaults to `"unified_results"`. |

### Parameter Study

A parameter study generates the Cartesian product of all parameter lists and runs `runs_per_combination` independent simulations for each combination. Combinations are sorted by a complexity score so that simpler experiments run first, providing early feedback.

```python
def main() -> None:
    run_parameter_study(
        network_sizes=[20, 50, 100],
        workload_sizes=[3, 5, 10],
        parent_factors=[1.0, 1.8],
        query_lengths=[5, 10, 15],
        runs_per_combination=50,
        node_event_ratios=[0.5, 0.7],
        num_event_types=[6],
        event_skews=[2.0],
        mode=SimulationMode.RANDOM,
        enable_parallel=True,
        max_workers=14,
        output_dataset_name="my_experiment",
    )
```

### Single Configuration

For a single configuration with multiple runs:

```python
def main() -> None:
    run_single_simulation(
        network_size=100,
        workload_size=5,
        query_length=15,
        max_parents=6,
        num_runs=50,
        mode=SimulationMode.RANDOM,
        enable_parallel=True,
        max_workers=8,
    )
```

### Execution Pipeline

Each simulation run executes the following pipeline automatically:

1. **Setup** -- Network topology generation, query workload creation, selectivity initialization, projection computation, and dependency analysis.
2. **All-Push Baseline** -- Computes the cost of placing all operators at the cloud, establishing the baseline transmission cost and latency.
3. **INEv** -- Runs the INEv operator placement algorithm to distribute operators across fog nodes.
4. **INES** -- Applies PrePP push-pull optimization on top of INEv's operator placement.
5. **PrePP from Cloud** -- Runs PrePP with all operators placed at the cloud.
6. **Kraken** -- Runs the Kraken solver, jointly optimizing placement and communication strategy.
7. **Result Writing** -- All strategy results are written to a single Parquet row.

---

## Output

Results are stored as Apache Parquet datasets in the `src/result/` directory. Each simulation run appends a new Parquet file to the dataset directory.

```
src/result/
|-- unified_results.parquet/          # Default output for standard experiments
|   |-- <uuid>-0.parquet              # One file per simulation run
|   `-- ...
|-- run_results.parquet/              # Kraken-specific per-strategy results
|-- kraken_comparison.parquet/        # Wide-format Kraken strategy comparisons
`-- detailed_run_log.parquet/         # Optional per-placement decision logs
```

The dataset name can be customized via the `output_dataset_name` parameter.

### Result Schema

Each row in the unified results dataset represents one complete simulation run.

**Per-strategy metrics** (prefixed with `all_push_`, `inev_`, `ines_`, `prepp_`, `kraken_greedy_`):

| Column                          | Type    | Description |
|---------------------------------|---------|-------------|
| `<prefix>_status`               | string  | `"success"` or `"failed"`. |
| `<prefix>_cost`                 | float64 | Total transmission cost (sum of rate * distance for all events). |
| `<prefix>_transmission_latency` | float64 | Maximum end-to-end transmission latency (critical path in hops). |
| `<prefix>_processing_latency`   | float64 | Cumulative processing latency across all placements. |
| `<prefix>_computing_time`       | float64 | Wall-clock time for the strategy computation (seconds). |

**Kraken-specific extended metrics** (prefixed with `kraken_greedy_`):

| Column                                    | Type    | Description |
|-------------------------------------------|---------|-------------|
| `kraken_greedy_workload_cost`             | float64 | Cost attributed only to root query placements. |
| `kraken_greedy_num_placements`            | float64 | Total number of placement decisions. |
| `kraken_greedy_placements_at_cloud`       | float64 | Number of projections placed at the cloud. |
| `kraken_greedy_average_cost_per_placement`| float64 | Mean cost per individual placement. |

**Configuration columns** (recorded for reproducibility):

| Column              | Type    | Description |
|---------------------|---------|-------------|
| `network_size`      | float64 | Number of nodes in the network. |
| `event_skew`        | float64 | Zipf exponent for event rates. |
| `node_event_ratio`  | float64 | Event generation probability at leaf nodes. |
| `max_parents`       | float64 | Maximum parent nodes per node. |
| `parent_factor`     | float64 | Parent factor used to compute max_parents. |
| `num_event_types`   | float64 | Number of primitive event types. |
| `query_size`        | float64 | Number of queries in the workload. |
| `query_length`      | float64 | Average query length. |
| `xi`                | float64 | Processing latency weight. |
| `mode`              | string  | Simulation mode. |
| `graph_density`     | float64 | NetworkX graph density of the generated topology. |
| `setup_time`        | float64 | Time spent in simulation setup (seconds). |
| `average_selectivity` | float64 | Mean pairwise selectivity across all event type pairs. |

### Loading Results

```python
import pandas as pd

df = pd.read_parquet("src/result/unified_results.parquet")

# Compute transmission ratio (Kraken cost / All-Push cost)
df["kraken_ratio"] = df["kraken_greedy_cost"] / df["all_push_cost"]
print(df["kraken_ratio"].describe())
```

---

## Configuration Reference

| Mode                  | Value            | Topology | Workload | Selectivities |
|-----------------------|------------------|----------|----------|---------------|
| `RANDOM`              | `"random"`       | Random   | Random   | Random        |
| `FIXED_TOPOLOGY`      | `"fixed_topology"` | Fixed  | Random   | Random        |
| `FIXED_WORKLOAD`      | `"fixed_workload"` | Fixed  | Fixed    | Random        |
| `FULLY_DETERMINISTIC` | `"deterministic"` | Fixed   | Fixed    | Fixed         |

| Algorithm          | Value            | Description |
|--------------------|------------------|-------------|
| `GREEDY`           | `"greedy"`       | Greedy search (default). Always picks the lowest-cost successor. |
| `BACKTRACKING`     | `"backtracking"` | Backtracking with latency constraints (not yet implemented). |
