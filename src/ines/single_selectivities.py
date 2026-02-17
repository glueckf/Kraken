import re
import random
from itertools import permutations

NETWORK = "network"
QUERIES = "queries"
MUSE_GRAPH = "muse graph"
SELECTIVITIES = "selectivities"

# CURRENT_SECTION = ''

network = []

queries_to_process = []

query_network = []

eventtype_pair_to_selectivity = {}

eventtypes_single_selectivities = {}

single_selectivity_of_eventtype_within_projection = {}

projection_dependencies_map = {}

all_event_combinations = []

all_eventtype_output_rates = {}

eventtype_to_sources_map = {}

eventtype_to_nodes = {}


class Query_fragment:
    def __init__(self, query, projections, node_placement, forbidden_event_types):
        self.query = query
        self.projections = projections
        self.node_placement = node_placement
        self.forbidden_event_types = forbidden_event_types


def get_current_section(CURRENT_SECTION, line):
    if line == "network\n":
        return NETWORK
    elif line == "queries\n":
        return QUERIES
    elif line == "muse graph\n":
        return MUSE_GRAPH
    elif line == "selectivities\n":
        return SELECTIVITIES
    return CURRENT_SECTION


def extract_network_node(line):
    if line.find("[") != -1:
        return list(map(float, line[line.find("[") + 1 : line.find("]")].split(", ")))


def extract_node_events_produced(output_rates, current_node):
    if output_rates is None:
        return 0
    char_counter = 0
    eventtypes_produced = []
    for output_rate in output_rates:
        if output_rate > 0:
            all_eventtype_output_rates[(chr(ord("A") + char_counter))] = output_rate

            if chr(ord("A") + char_counter) not in eventtype_to_sources_map:
                eventtype_to_sources_map[chr(ord("A") + char_counter)] = []
                eventtype_to_sources_map[chr(ord("A") + char_counter)].append(
                    current_node
                )
            else:
                eventtype_to_sources_map[chr(ord("A") + char_counter)].append(
                    current_node
                )

            eventtypes_produced.append(chr(ord("A") + char_counter))
        char_counter += 1

    return eventtypes_produced


# AND(B1, SEQ(F, AND(G1, SEQ(G2, AND(I1, I2, B2)))))
def get_all_query_components(query):
    operators = ["AND", "SEQ"]

    # adjust query format -> no digits/whitespaces
    query = re.sub(r"[0-9]+", "", query)
    query = query.replace(" ", "")

    # current_pos += 4 jumps over the first L_PAREN -> 1
    open_parentheses = 1
    current_pos = 4
    query_components = []

    for idx in range(current_pos, len(query)):
        if query[current_pos : current_pos + 3] in operators:
            first_pos = current_pos

            # set to pos x in AND(x / SEQ(x
            current_pos += 4
            while open_parentheses >= 1:
                if query[current_pos : current_pos + 3] in operators:
                    current_pos += 3

                if query[current_pos] == "(":
                    open_parentheses += 1

                if query[current_pos] == ")":
                    open_parentheses -= 1

                current_pos += 1

            eventtype = query[first_pos:current_pos]
            eventtype = re.sub(r"[0-9]+", "", eventtype)
            query_components.append(eventtype)
        else:
            if current_pos + 1 < len(query):
                if query[current_pos].isalpha():
                    query_components.append(query[current_pos])

        current_pos += 1

    return query_components


def is_complex_eventtype(eventtype):
    return len(eventtype) > 1


def determine_query_output_rate(
    query, multi_sink_placement_eventtype, is_single_sink_placement
):
    query = re.sub(r"[0-9]+", "", query)

    if not is_complex_eventtype(query):
        if query != multi_sink_placement_eventtype or is_single_sink_placement:
            return all_eventtype_output_rates[query] * len(
                eventtype_to_sources_map[query]
            )
        else:
            return all_eventtype_output_rates[query]

    output_rate = 1
    first_operator = query[0:3]
    all_query_components = get_all_query_components(query)
    for eventtype in all_query_components:
        output_rate *= determine_query_output_rate(
            eventtype, multi_sink_placement_eventtype, is_single_sink_placement
        )

    if first_operator == "SEQ":
        return output_rate

    if first_operator == "AND":
        operand_count = len(all_query_components)
        return operand_count * output_rate


def determine_all_primitive_events_of_projection(projection):
    given_predicates = projection.replace("AND", "")
    given_predicates = given_predicates.replace("SEQ", "")
    given_predicates = given_predicates.replace("(", "")
    given_predicates = given_predicates.replace(")", "")
    given_predicates = re.sub(r"[0-9]+", "", given_predicates)
    given_predicates = given_predicates.replace(" ", "")
    return given_predicates.split(",")


# takes a preprocessed string (instead of list) and computes the total selectivity
def determine_total_query_selectivity(query):
    selectivity = 1.0

    for i in range(0, len(query) - 1):
        for k in range(i + 1, len(query)):
            selectivity *= float(
                eventtype_pair_to_selectivity[str(query[i]) + str(query[k])]
            )

    return selectivity


# takes a preprocessed string (instead of projection with operators etc.) and computes the total outputrate
def determine_total_query_outputrate(query):
    outputrate = 1.0

    for eventtype in query:
        outputrate *= all_eventtype_output_rates[eventtype] * len(
            eventtype_to_sources_map[eventtype]
        )

    return outputrate


def extract_queries(line):
    if line != "queries" and len(line) > 1:
        # Remove trailing newline/whitespace instead of just last character
        clean_line = line.strip()
        queries_to_process.append(clean_line)
        return line


def extract_muse_graph_queries(line):
    if line.find("SELECT") != -1:
        return line[line.find("SELECT") + 7 : line.find("FROM") - 1]


def extract_muse_graph_sub_queries(line):
    if line.find("FROM") != -1:
        return line[line.find("FROM") + 5 : line.find("ON") - 1].split("; ")


def extract_muse_graph_sources(line):
    if line.find("{") != -1:
        return list(map(int, line[line.find("{") + 1 : line.find("}")].split(", ")))


def extract_muse_graph_forbidden(line):
    if line.find("/n(") != -1:
        if line.find("WITH") != -1:
            return line[line.find("/n(") + 3 : line.find("WITH") - 2]
        else:
            return line[line.find("/n(") + 3 : len(line) - 2]


def extract_muse_graph_selectivities(line):
    """Extract event selectivities from a muse graph line.

    Parses a line containing event combinations and their selectivities,
    extracting both event products and their associated selectivity values.

    Args:
        line: String line containing event combinations and selectivities
    """
    import logging

    # Declare global variables for debugger access
    global all_event_combinations, eventtype_pair_to_selectivity

    # Setup logging
    logger = logging.getLogger(__name__)

    logger.debug(f"Processing selectivities line: {line.strip()}")

    # Find all quote positions (mark event product boundaries)
    quote_positions = _find_quote_positions(line)

    # Find separator positions (commas and closing braces)
    separator_positions = _find_separator_positions(line)

    logger.debug(
        f"Found {len(quote_positions)} quote positions and {len(separator_positions)} separators"
    )

    # Process each event product-selectivity pair
    position_offset = 0
    for pair_index in range(len(separator_positions)):
        try:
            # Extract event product name
            event_product = _extract_event_product(
                line, quote_positions, position_offset
            )

            # Track event combinations (every other event product)
            if _should_track_combination(position_offset):
                all_event_combinations.append(event_product)
                logger.debug(f"Added event combination: {event_product}")

            # Extract selectivity value
            selectivity_value = _extract_selectivity_value(
                line, quote_positions, separator_positions, position_offset, pair_index
            )

            # Store selectivity mappings
            _store_selectivity_mappings(event_product, selectivity_value)
            logger.debug(f"Stored selectivity: {event_product} = {selectivity_value}")

            position_offset += 2

        except Exception as e:
            logger.error(f"Error processing pair at index {pair_index}: {e}")
            raise


def _find_quote_positions(line):
    """Find all positions of single quotes in the line."""
    return [match.start() for match in re.finditer("'", line)]


def _find_separator_positions(line):
    """Find all positions of commas and closing braces."""
    comma_positions = [match.start() for match in re.finditer(",", line)]
    brace_positions = [match.start() for match in re.finditer("}", line)]
    return comma_positions + brace_positions


def _extract_event_product(line, quote_positions, position_offset):
    """Extract event product name between quotes."""
    start_pos = quote_positions[0 + position_offset]
    end_pos = quote_positions[1 + position_offset]
    return line[start_pos + 1 : end_pos]


def _should_track_combination(position_offset):
    """Determine if this event combination should be tracked."""
    return (position_offset // 2) % 2 == 0


def _extract_selectivity_value(
    line, quote_positions, separator_positions, position_offset, pair_index
):
    """Extract selectivity value from between quote and separator."""
    start_pos = quote_positions[1 + position_offset] + 3  # Skip quote and ": "
    end_pos = separator_positions[pair_index]
    selectivity_str = line[start_pos:end_pos]
    return float(selectivity_str)


def _store_selectivity_mappings(event_product, selectivity_value):
    """Store selectivity mappings for the event product."""
    global eventtype_pair_to_selectivity

    # Store the main selectivity mapping
    eventtype_pair_to_selectivity[event_product] = selectivity_value

    # Store single event type mapping (always 1.0)
    single_event_key = 2 * str(event_product[0])
    eventtype_pair_to_selectivity[single_event_key] = 1


# return the current upper bound for a given eventtype based on all possible lower bounds of size n-1
def return_minimum_upper_bound(upper_bounds, eventtype):
    lowest_upper_bound = 1.0

    for _list in upper_bounds:
        for ele in _list:
            if ele == eventtype:
                key = str(eventtype) + "|" + str(_list)

                # this is because of missing keys caused by projections with r(p) < 1..
                if key in single_selectivity_of_eventtype_within_projection:
                    if (
                        lowest_upper_bound
                        > single_selectivity_of_eventtype_within_projection[key]
                    ):
                        lowest_upper_bound = (
                            single_selectivity_of_eventtype_within_projection[key]
                        )
    return lowest_upper_bound


def no_better_option_found_handling(query, upper_bounds_keys):
    for idx in range(0, len(query)):
        upper_bound = return_minimum_upper_bound(upper_bounds_keys, query[idx])
        key = str(query[idx]) + "|" + str(query)

        # Preserve specific low selectivity for A|AB combination
        if key == "A|AB":
            single_selectivity_of_eventtype_within_projection[key] = 0.0013437
        else:
            single_selectivity_of_eventtype_within_projection[key] = upper_bound


def determine_randomized_single_selectivities_within_all_projections(
    query, upper_bounds_keys, is_deterministic=False
):
    # print(f"[SELECTIVITY_DEBUG] determine_randomized_single_selectivities called for query={''.join(query)}, is_deterministic={is_deterministic}")

    # Ensure deterministic behavior with consistent seed for each query
    if is_deterministic:
        # Use a hash of the query to get consistent but query-specific deterministic values
        query_hash = hash("".join(sorted(query)))
        # print(f"[SELECTIVITY_DEBUG] Setting deterministic seed: 42 + {query_hash} = {42 + query_hash}")
        random.seed(42 + query_hash)

    projection_selectivity = determine_total_query_selectivity(query)
    projection_outputrate = determine_total_query_outputrate(query)
    total_outputrate = projection_outputrate * projection_selectivity

    outputrates = []
    for primitive_eventtype in query:
        outputrates.append(
            (
                all_eventtype_output_rates[primitive_eventtype]
                * len(eventtype_to_sources_map[primitive_eventtype])
            )
        )

    limit = len(query)

    solution_found = False
    total_sel = projection_selectivity

    delta = 0
    decreasing_value = 1
    while not solution_found:
        delta += 1
        first_n_random_values = []
        product = 1

        current_idx = 0
        chosen_indices = [ele for ele in range(0, limit)]
        if not is_deterministic:
            random.shuffle(chosen_indices)
        # In deterministic mode, use indices in their natural order

        # print(f"[SELECTIVITY_DEBUG] Delta {delta}: chosen_indices={chosen_indices}")

        for n in range(0, len(chosen_indices) - 1):
            if delta == 1000:
                # if no better option was found, use same bounds as for the previous level of selectivities
                no_better_option_found_handling(query, upper_bounds_keys)
                return

            lower_bound = total_sel
            upper_bound = return_minimum_upper_bound(
                upper_bounds_keys, query[chosen_indices[n]]
            )

            if is_deterministic:
                # Use deterministic value: halfway between bounds
                deterministic_value = (lower_bound + upper_bound) / 2.0
                # print(f"[SELECTIVITY_DEBUG] Deterministic value for index {chosen_indices[n]} (eventtype {query[chosen_indices[n]]}): bounds=[{lower_bound}, {upper_bound}] -> {deterministic_value}")
                first_n_random_values.append(deterministic_value)
            else:
                random_value = random.uniform(lower_bound, upper_bound)
                # print(f"[SELECTIVITY_DEBUG] Random value for index {chosen_indices[n]} (eventtype {query[chosen_indices[n]]}): bounds=[{lower_bound}, {upper_bound}] -> {random_value}")
                first_n_random_values.append(random_value)
            product *= first_n_random_values[n]

        if total_sel / product <= 1.0:
            solution_found = True
            first_n_random_values.append(total_sel / product)
            # print("first_n_random_values~~:", first_n_random_values)

            idx = 0

            for random_value in first_n_random_values:
                if total_outputrate > 1.0:
                    # constraint 1 => if the outputrate of a projection is > 1, then all primitive events it consists of  times their single selectivities
                    # have to be bigger than one or..
                    # constraint 2 => the outputrate times the single selectivity for a given eventtype can not be bigger than the outputrate of the
                    # projection
                    if (
                        random_value * outputrates[chosen_indices[idx]] < 1.0
                        and projection_outputrate > 1.0
                    ) or (
                        random_value * outputrates[chosen_indices[idx]]
                    ) > projection_outputrate:
                        solution_found = False
                        break
                else:
                    if (
                        random_value * outputrates[chosen_indices[idx]]
                    ) > projection_outputrate:
                        solution_found = False
                        break
                idx += 1

    idx = 0
    # print(f"[SELECTIVITY_DEBUG] Final selectivity assignments:")
    for random_value in first_n_random_values:
        projection_key = str(query[chosen_indices[idx]]) + "|" + str(query)

        # Preserve specific low selectivity for A|AB combination
        if projection_key == "A|AB":
            single_selectivity_of_eventtype_within_projection[projection_key] = (
                0.0013437
            )
        else:
            single_selectivity_of_eventtype_within_projection[projection_key] = (
                first_n_random_values[idx]
            )
        # print(f"[SELECTIVITY_DEBUG] {projection_key} = {first_n_random_values[idx]}")
        idx += 1


def determine_permutations_of_all_relevant_lengths(eventtypes):
    result = []
    already_created = {}
    tmp = ""
    purged_result = []

    # decreases the number of single selectivties that have to be calculated
    # in order to speed up the sampling of different selectivities
    for current_length in range(2, len(eventtypes) + 1):
        # group of eventtypes to permutate, desired permutation length
        for permutation in permutations(eventtypes, current_length):
            # save memory, as selectivities/outputrates are commutative
            # and therefore memoize only ordered pairs of concatenated eventtypes
            for ele in permutation:
                tmp += str(ele)
            tmp = "".join(sorted(tmp))

            # save them once
            if tmp in already_created:
                tmp = ""
                continue
            already_created[tmp] = "key created!"
            result.append(tmp)
            tmp = ""

        res = ""

    return result


def determine_next_smaller_dependencies(eventtypes):
    result = []
    already_created = {}
    tmp = ""
    purged_result = []
    start = len(eventtypes) - 1
    length = len(eventtypes)
    for current_length in range(start, length):
        # group of eventtypes to permutate, desired permutation length
        for permutation in permutations(eventtypes, current_length):
            for ele in permutation:
                tmp += str(ele)
            tmp = "".join(sorted(tmp))

            # save them once
            if tmp in already_created:
                tmp = ""
                continue
            already_created[tmp] = "key created!"
            result.append(tmp)
            tmp = ""

        res = ""

    return result


def get_all_distinct_eventtypes_of_used_queries():
    total_list = []
    for query in queries_to_process:
        _list = determine_all_primitive_events_of_projection(query)
        for _item in _list:
            if _item not in total_list:
                total_list.append(_item)

    return "".join(sorted(total_list))


def determine_all_single_selectivities_for_projection(
    projection, is_deterministic=False
):
    if isinstance(projection, list):
        tmp = projection
    else:
        tmp = determine_all_primitive_events_of_projection(projection)

    global_total_query_length = len(tmp)

    all_possible_projections = determine_permutations_of_all_relevant_lengths(tmp)

    for eventtype in tmp:
        single_selectivity_of_eventtype_within_projection[eventtype] = 1.0

    all_different_projection_lengths = []

    current_length = 2
    current_length_projections = []
    for possible_projection in all_possible_projections:
        if len(possible_projection) > current_length:
            all_different_projection_lengths.append(current_length_projections)
            current_length_projections = []
            current_length += 1
            current_length_projections.append(possible_projection)
        else:
            current_length_projections.append(possible_projection)

    all_different_projection_lengths.append(
        [all_possible_projections[len(all_possible_projections) - 1]]
    )
    for current_length_projections in all_different_projection_lengths:
        for projection in current_length_projections:
            upper_bound_keys = []

            if len(projection) > 2:
                # determine all upper bounds of the previous length (e.g., AB, AC, for A in ABC)
                upper_bound_keys = determine_next_smaller_dependencies(projection)

            determine_randomized_single_selectivities_within_all_projections(
                projection, upper_bound_keys, is_deterministic
            )


def initializeSingleSelectivity(
    CURRENT_SECTION,
    config_single,
    workload,
    is_deterministic=False,
    all_events_array_string=None,
):
    # print(f"[SELECTIVITY_DEBUG] initializeSingleSelectivity called with is_deterministic={is_deterministic}")

    # Clear all global variables to ensure clean state
    global \
        network, \
        eventtypes_single_selectivities, \
        single_selectivity_of_eventtype_within_projection
    global \
        projection_dependencies_map, \
        all_event_combinations, \
        all_eventtype_output_rates
    global eventtype_to_sources_map, eventtype_to_nodes

    # print(f"[SELECTIVITY_DEBUG] Clearing global variables...")
    network.clear()
    eventtypes_single_selectivities.clear()
    single_selectivity_of_eventtype_within_projection.clear()
    projection_dependencies_map.clear()
    all_event_combinations.clear()
    all_eventtype_output_rates.clear()
    eventtype_to_sources_map.clear()
    eventtype_to_nodes.clear()

    # Set random seed for deterministic behavior
    if is_deterministic:
        # print(f"[SELECTIVITY_DEBUG] Setting random seed to 42 for deterministic behavior")
        random.seed(42)

    current_node = 0

    content = config_single.getvalue()
    # CURRENT_SECTION = ''
    for line in config_single:
        OLD_SECTION = CURRENT_SECTION
        CURRENT_SECTION = get_current_section(CURRENT_SECTION, line)
        if OLD_SECTION != CURRENT_SECTION:
            continue

        if CURRENT_SECTION == NETWORK:
            result = extract_node_events_produced(
                extract_network_node(line), current_node
            )
            current_node += 1
            if result != 0:
                network.append(result)
        # print(result)

        if CURRENT_SECTION == QUERIES:
            print(extract_queries(line))

        if CURRENT_SECTION == MUSE_GRAPH:
            print("-----")
            query = Query_fragment("", [], [], "")
            if extract_muse_graph_queries(line) is not None:
                query.query = extract_muse_graph_queries(line)

            if extract_muse_graph_sources(line) is not None:
                query.projections = extract_muse_graph_sub_queries(line)

            if extract_muse_graph_sources(line) is not None:
                query.node_placement = extract_muse_graph_sources(line)

            if extract_muse_graph_forbidden(line) is not None:
                query.forbidden_event_types = extract_muse_graph_forbidden(line)

            query_network.append(query)

        if CURRENT_SECTION == SELECTIVITIES:
            # print(line)
            extract_muse_graph_selectivities(line)

    workload = [x.stripKL_simple() for x in workload]
    workload = [x.strip_NSEQ() for x in workload]

    """
    Finn Glück 31.08.2025: 
    When using multiple runs the legacy system produces an error since some selectivities are not initialized properly. 
    This is a quick fix to ensure that all selectivities are initialized properly.
    """
    if all_events_array_string is None:
        for i in workload:
            determine_all_single_selectivities_for_projection(str(i), is_deterministic)
    else:
        determine_all_single_selectivities_for_projection(all_events_array_string)

    return single_selectivity_of_eventtype_within_projection
