from core.tree import PrimEvent, SEQ, AND, NSEQ, KL
from core.proj_string import filter_numbers
import string
import random as rd

# Private global variables
# _Prim = None
# _PrimitiveEvents = None


# Function to initialize Prim and PrimitiveEvents
def initialize_prim_and_primitive_events(primitive_events_data):
    "TODO No global variables"
    # _Prim = self.prim,
    # _PrimitiveEvents = self.primitiveEvents

    # Create PrimitiveEvents list
    primitiveEvents = list(string.ascii_uppercase[: len(primitive_events_data)])

    # Populate the Prim dictionary
    prim = {i: primitiveEvents[i] for i in range(len(primitiveEvents))}
    return primitiveEvents, prim


# Getter for PrimitiveEvents
def get_primitive_events(primitive_events_data):
    primitiveEvents, _ = initialize_prim_and_primitive_events(primitive_events_data)
    return primitiveEvents


# Getter for Prim
def get_prim_variable(primitive_events_data):
    _, prim = initialize_prim_and_primitive_events(primitive_events_data)
    return prim


def get_prim(PrimitiveEvents, Prim):
    x = rd.uniform(0, len(PrimitiveEvents))
    x = int(x)
    return PrimEvent(Prim[x])


def generate_workload(size, maxlength, primitive_events_data):  # count, lenthh
    qwl = []
    initialize_prim_and_primitive_events(primitive_events_data)
    primitiveEvents, prim = initialize_prim_and_primitive_events(primitive_events_data)
    # for i in range(size):          # changed
    while len(qwl) != size:
        mylength = int(rd.uniform(maxlength / 2, maxlength + 1))
        while mylength <= 2:
            mylength = int(rd.uniform(2, maxlength + 1))
        nesting_depth = rd.uniform(1, mylength - 1)
        x = rd.uniform(0, 1)
        if x <= 0.5:
            query = SEQ()
        else:
            query = AND()
        query.children = generate_q(
            query, int(nesting_depth), mylength, primitiveEvents, prim
        )

        query = number_children(query)
        if not hasdoubles(query):  # changed
            qwl.append(query)

    return qwl


def generate_balanced_workload(size, maxlength):  # count, lenthh
    qwl = []
    kleene = []
    negation = []
    none = []
    # for i in range(size):          # changed
    while len(qwl) != size:
        mylength = int(rd.uniform(maxlength / 2, maxlength + 1))
        while mylength == 2:
            mylength = int(rd.uniform(2, maxlength + 1))
        nesting_depth = rd.uniform(1, mylength - 1)
        x = rd.uniform(0, 1)
        if x <= 0.5:
            query = SEQ()
        else:
            query = AND()
        # query.children = generate_q(query, int(nesting_depth), mylength)

        query.children = generate_q_kl(query, int(nesting_depth), mylength, False, False)
        query = number_children(query)
        if not hasdoubles(query):  # changed
            qwl.append(query)
    for i in qwl:
        if i.has_kleene():
            kleene.append(i)
        if i.has_negation():
            negation.append(i)
        if i not in negation and i not in kleene:
            none.append(i)

    if len(kleene) < int(size / 3):
        while len(kleene) < int(size / 3):
            mylength = int(rd.uniform(maxlength / 2, maxlength + 1))
            while mylength == 2:
                mylength = int(rd.uniform(2, maxlength + 1))
            nesting_depth = rd.uniform(1, mylength - 1)
            x = rd.uniform(0, 1)
            if x <= 0.5:
                query = SEQ()
            else:
                query = AND()
            query.children = get_kleene_query(query, int(nesting_depth), maxlength, False)
            if not hasdoubles(query):
                kleene.append(query)
                if none:
                    none.pop(0)

    if len(negation) < int(size / 3):
        while len(negation) < int(size / 3):
            mylength = int(rd.uniform(maxlength / 2, maxlength + 1))
            while mylength == 2:
                mylength = int(rd.uniform(2, maxlength + 1))
            nesting_depth = rd.uniform(1, mylength - 1)
            x = rd.uniform(0, 1)
            if x <= 0.5:
                query = SEQ()
            else:
                query = AND()
            query.children = get_nseq_query(query, int(nesting_depth), maxlength, False)
            if not hasdoubles(query):  # changed
                negation.append(query)
                if none:
                    none.pop(0)
    qwl = none + kleene + negation
    return list(set(qwl))


def hasdoubles(query):
    prims = map(lambda x: str(x), query.leafs())
    prims = list(map(lambda x: filter_numbers(x), prims))
    if len(prims) > len(list(set(prims))):
        return True
    else:
        return False


def number_children(query):
    mychildren = query.leafs()
    children = query.get_leafs()
    types = list(set(mychildren))
    for i in types:
        mycount = mychildren.count(i)
        if mycount > 1:
            c = 0
            for k in children:
                if str(k) == i:
                    newName = str(i) + str(c + 1)
                    c += 1
                    k.rename(newName)

    return query


def generate_q(query, nestingdepth, maxlength, PrimitiveEvent, Prim):
    count = 0
    children = []
    remainingPrims = maxlength - 1 - nestingdepth
    if nestingdepth == 1:
        for i in range(maxlength):
            newchild = get_prim(PrimitiveEvent, Prim)

            children.append(newchild)
        return children

    else:
        x = rd.uniform(0, remainingPrims)

        for i in range(int(x) + 1):
            newchild = get_prim(PrimitiveEvent, Prim)

            children.append(newchild)
            count += 1

        if isinstance(query, AND):
            myquery = SEQ()
        elif isinstance(query, SEQ):
            myquery = AND()
        myquery.children = generate_q(
            myquery, nestingdepth - 1, maxlength - count, PrimitiveEvent, Prim
        )
        children.append(myquery)

        return children


def generate_q_kl(query, nestingdepth, maxlength, negation, kleene):
    count = 0
    children = []
    remainingPrims = maxlength - 1 - nestingdepth
    if nestingdepth == 1:
        for i in range(maxlength):
            newchild = get_prim()

            children.append(newchild)
        return children

    else:
        x = rd.uniform(0, remainingPrims)
        negKL = rd.uniform(0, 1)
        for i in range(int(x) + 1):
            newchild = get_prim()

            children.append(newchild)
            count += 1

        if not kleene:
            if negKL < 1 and maxlength - count - 1 >= remainingPrims:  # Kleene
                newchild = get_prim()
                children.append(KL(newchild))
                count += 1
                kleene = True
        if not negation:
            if negKL < 1 and maxlength - count - 3 >= remainingPrims:  # negation
                myq = NSEQ()
                myq.children = [get_prim(), get_prim(), get_prim()]
                children.append(myq)
                count += 3
                negation = True
        if isinstance(query, AND):
            myquery = SEQ()
        elif isinstance(query, SEQ):
            myquery = AND()
        nestingdepth = min(nestingdepth, maxlength - count - 1)
        if nestingdepth < 2:
            nestingdepth = 2
        myquery.children = generate_q_kl(
            myquery, nestingdepth - 1, maxlength - count, negation, kleene
        )
        children.append(myquery)

        return children


def get_kleene_query(query, nestingdepth, maxlength, kleene):
    count = 0
    children = []
    remainingPrims = maxlength - 1 - nestingdepth
    if nestingdepth == 1:
        if not kleene:
            newchild = get_prim()
            children.append(KL(newchild))
            count += 1
            kleene = True
        for i in range(maxlength - count):
            newchild = get_prim()

            children.append(newchild)
        return children
    else:
        if not kleene:
            newchild = get_prim()
            children.append(KL(newchild))
            count += 1
            kleene = True
        if isinstance(query, AND):
            myquery = SEQ()
        elif isinstance(query, SEQ):
            myquery = AND()
        nestingdepth = min(nestingdepth, maxlength - count - 1)
        if nestingdepth < 2:
            nestingdepth = 2
        myquery.children = get_kleene_query(
            myquery, nestingdepth - 1, maxlength - count, kleene
        )
        children.append(myquery)

        return children


def get_nseq_query(query, nestingdepth, maxlength, negation):
    count = 0
    children = []
    if nestingdepth == 1:
        if not negation:
            myq = NSEQ()
            myq.children = [get_prim(), get_prim(), get_prim()]
            children.append(myq)
            negation = True
            count += 3

        for i in range(maxlength - count):
            newchild = get_prim()

            children.append(newchild)
        return children
    else:
        if not negation:
            myq = NSEQ()
            myq.children = [get_prim(), get_prim(), get_prim()]
            children.append(myq)
            count += 3
            negation = True

        if isinstance(query, AND):
            myquery = SEQ()
        elif isinstance(query, SEQ):
            myquery = AND()

        nestingdepth = min(nestingdepth, maxlength - count - 1)

        if nestingdepth < 2:
            nestingdepth = 2
        myquery.children = get_nseq_query(
            myquery, nestingdepth - 1, maxlength - count, negation
        )
        children.append(myquery)

        return children


def make_long(count, length):
    wl = generate_workload(count, length)
    while True:
        for i in wl:
            if len(i.leafs()) == length:
                return wl
        wl = generate_workload(count, length)


def make_long_balanced(count, length):
    wl = generate_balanced_workload(count, length)
    return wl


# def parse_arguments():
#     # Initialize the parser
#     parser = argparse.ArgumentParser(description="Process length, count, and negated values.")

#     # Add the parameters with default values
#     parser.add_argument('--length', type=int, default=5, help="Length value (default: 5)")
#     parser.add_argument('--count', type=int, default=3, help="Count value (default: 3)")
#     parser.add_argument('--negated', type=int, default=3, help="Negated value (default: 3)")

#     # Parse the arguments and return the results
#     return parser.parse_args()

# def main():
#     # Parse arguments using the function
#     args = parse_arguments()

#     # Access the arguments
#     length = args.length
#     count = args.count
#     negated = args.negated


#     # generate workload without kleene and nseq
#     wl = generate_workload(count, length)


#     if negated==1:
#           wl = [AND(PrimEvent('D'),SEQ(PrimEvent('B'), KL(PrimEvent('A')), PrimEvent('C')),PrimEvent('E'))]
#     elif negated == 0:
#           wl = [AND(PrimEvent('D'),SEQ(PrimEvent('B'),  PrimEvent('A'), PrimEvent('C')),PrimEvent('E'))]
#     elif negated==2:
#           wl = [AND(PrimEvent('D'),NSEQ(PrimEvent('B'),  PrimEvent('A'), PrimEvent('C')),PrimEvent('E'))]


#     with open('current_wl', 'wb') as wl_file:
#         pickle.dump(wl, wl_file)

#     print("QUERY WORKLOAD")
#     print("---------------")
#     for i in (list(map(lambda x: str(x), wl))):
#         print(i)
#     print("\n")

# if __name__ == "__main__":
#     main()
