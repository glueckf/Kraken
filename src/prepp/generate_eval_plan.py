import core.subsets as sbs


def get_com(mylist):
    return [
        (mylist[i], mylist[i + 1]) for i in range(len(mylist)) if i < len(mylist) - 1
    ]


def traverse_list(source, mylist):
    for i in range(len(mylist)):
        if mylist[i] == source[0]:
            myindex = i
    firstpart = mylist[: myindex + 1]
    firstpart.reverse()
    secondpart = mylist[myindex:]
    mytuples = get_com(firstpart)
    mytuples += get_com(secondpart)
    return mytuples


def traverse_list_tuples(source, mytuples):
    sources = source
    myPairs = []
    while mytuples:
        toRemove = []
        for i in mytuples:
            curSource = list(set(sources).intersection(set(i)))
            if curSource:
                newInd = i.index(curSource[0])
                newInd = not newInd
                pair = (curSource[0], i[int(newInd)])
                myPairs.append(pair)
                sources.append(pair[1])
                toRemove.append(i)
        mytuples = [x for x in mytuples if x not in toRemove]
    return myPairs


def process_instance(instance, forwardingDict):
    routingTuples = []
    instanceDict = forwardingDict[instance.projname][instance.name]

    for path in instance.routingDict.values():
        if type(path[0]) == list:
            for mypath in path:
                routingTuples.append(traverse_list([mypath[len(mypath) - 1]], mypath))
        elif type(path[0]) == int:
            routingTuples.append(traverse_list(instance.sources, path))
        else:
            routingTuples.append(traverse_list_tuples(instance.sources, path))
    for path in routingTuples:
        for mytuple in path:
            if mytuple[0] not in instanceDict.keys():
                instanceDict[mytuple[0]] = []
            instanceDict[mytuple[0]].append(mytuple[1])
    return instanceDict


def get_selection_rate(projection, combination, selectivities):
    subsProj = set(sbs.printcombination(projection.leafs(), 2))
    subsCombi = set(
        sum([sbs.printcombination(x.leafs(), 2) for x in combination if len(x) > 1], [])
    )
    subsProj = subsProj.difference(subsCombi)
    res = 1
    for i in [selectivities[x] for x in subsProj]:
        res *= i
    return res


# filterdict: proj: [filter, remainingproj, resultingcombination]
def new_filter_dict():
    newDict = {}
    for proj in filterDict.keys():
        myfilter = filterDict[proj]
        # subproj = set_to_proj(list(set(proj.leafs()).difference(set(list(myfilter)))), proj)
        subproj = list(
            set(proj.leafs()).difference(set(list(myfilter)))
        )  # atm only single events send for filters
        newDict[str(proj)] = [myfilter, subproj, [subproj] + list(myfilter)]
    return newDict


def sep_numbers(evlist):
    """ "A1B" -> [A1,B]"""
    newevlist = []
    if len(evlist) > len(filter_numbers(evlist)):
        for i in range(len(evlist)):
            if evlist[i] in list(string.ascii_uppercase):
                newevlist.append(evlist[i])
            else:
                newevlist[len(newevlist) - 1] = newevlist[len(newevlist) - 1] + str(
                    evlist[i]
                )
    else:
        newevlist = evlist
    return newevlist


def filter_numbers(in_string):
    x = list(filter(lambda c: not c.isdigit(), in_string))
    return "".join(x)


def filter_literals(in_string):
    x = list(filter(lambda c: c.isdigit(), in_string))
    return "".join(x)


def to_etb(instance):
    text = ""
    parts = sep_numbers(instance)
    for ev in parts:
        mytype = filter_numbers(ev)
        mynode = filter_literals(ev)
        if mynode:
            text += "(" + str(mytype) + ": node" + str(mynode) + ");"
        else:
            text += "(" + str(mytype) + ": ANY);"

    text = text[:-1]
    return text


def nodelist(mylist):
    mylist = list(set(mylist))
    text = "["
    for i in mylist:
        text += "node" + str(i) + ";"
    text = text[:-1]
    text += "]"
    return text


def list_str(mylist):
    text = ""
    for i in mylist:
        text += str(i) + ","
    return text[:-1]


def forwarding_rule(i):
    text = "Forward rules:\n"
    for projection in forwardingDict.keys():
        for instance in forwardingDict[projection].keys():
            post = []
            instanceText = ""
            if str(projection) in filterDict.keys():
                instanceText += (
                    list_str((filterDict[str(projection)][1]))
                    + "|"
                    + str(projection)
                    + " - [ETB:"
                    + to_etb(instance)
                    + " FROM:"
                )
            else:
                instanceText += (
                    str(projection) + " - [ETB:" + to_etb(instance) + " FROM:"
                )
            for node in forwardingDict[projection][instance].values():
                pre = [
                    p
                    for p in forwardingDict[projection][instance].keys()
                    if i in forwardingDict[projection][instance][p]
                ]
                if i in forwardingDict[projection][instance].keys():
                    post = forwardingDict[projection][instance][i]
                else:
                    post = []

            if post:
                if not pre:
                    pre = [i]
                instanceText += nodelist(pre) + " TO:" + nodelist(post) + "] \n"
                text += instanceText
    return text


def forwarding_rule_central(i, myForwardingDict):
    text = "Forward rules:\n"

    for projection in myForwardingDict.keys():
        for instance in myForwardingDict[projection].keys():
            post = []
            instanceText = ""
            instanceText += str(projection) + " - [ETB:" + to_etb(instance) + " FROM:"
            for node in myForwardingDict[projection][instance].values():
                pre = [
                    p
                    for p in myForwardingDict[projection][instance].keys()
                    if i in myForwardingDict[projection][instance][p]
                ]
                if i in myForwardingDict[projection][instance].keys():
                    post = myForwardingDict[projection][instance][i]
                else:
                    post = []
            if post:
                if not pre:
                    pre = [i]
                instanceText += nodelist(pre) + " TO:" + nodelist(post) + "] \n"
                text += instanceText
    return text


def adjust_routing_central(mydict, source):
    outdict = {}
    for proj in mydict.keys():
        outdict[proj] = {}
        for instance in mydict[proj]:
            outdict[proj][instance] = {}
            mysource = int(filter_literals(instance))
            routingTuples = traverse_list([mysource], mydict[proj][instance])
            for mytuple in routingTuples:
                if mytuple[0] not in outdict[proj][instance].keys():
                    outdict[proj][instance][mytuple[0]] = []
                outdict[proj][instance][mytuple[0]].append(mytuple[1])
    return outdict


def processing_text(combinationDict, sinkDict, selectionRate):
    text = "muse graph\n"
    for projection in combinationDict.keys():
        text += "SELECT " + projection + " FROM "
        if combinationDict[projection]:  # Only add FROM section if we have items
            for i in combinationDict[projection]:
                text += i + "; "
            text = text[:-2]  # Remove the last "; "
        else:
            # Remove the " FROM " we just added since there are no items
            text = text[:-6]  # Remove " FROM "
        text += " ON " + str(set(sinkDict[projection][0]))
        if len(sinkDict[projection][0]) > 1:
            text += "/n(" + sinkDict[projection][1] + ")"
        text += " WITH selectionRate= " + str(selectionRate[projection]) + "\n"
    return text


def network_text(nw):
    mystr = "network\n"
    for i in range(len(nw)):
        mystr += "Node " + str(i) + " " + str(nw[i])
        mystr += "\n"
    return mystr


def selectivities_text(selectivities):
    return "selectivities\n" + str(selectivities) + " \n"


def queries_text(wl):
    mystr = "queries\n"
    for i in wl:
        mystr += str(i) + "\n"
    return mystr


def generate_plan(
    network, selectivities, workload, combinationDict, sinkDict, selectionRate
):
    text = ""
    text += network_text(network) + "\n"
    text += selectivities_text(selectivities) + "\n"
    reused_text = text
    text += queries_text(workload) + "\n"
    #    text +="Randomized Rate-Based Primitive Event Generation\n"
    #    text +="-----------\n"
    text += processing_text(combinationDict, sinkDict, selectionRate)
    return text, reused_text


def generate_eval_plan(nw, selectivities, myPlan, centralPlan, workload):
    import io

    ID = "curr"
    MSPlacements = myPlan[2]
    myplan = myPlan[0]

    print(f"Myplan is {myplan}")

    cdict = centralPlan[1]
    csource = centralPlan[0]
    wl = centralPlan[2]
    evaluationDict = {}
    combinationDict = {}
    evaluationDict = {x: [] for x in range(len(nw))}
    forwardingDict = {}
    selectionRate = {}
    filterDict = {}
    sinkDict = {}

    for i in myplan.projections:
        myproj = i.name
        for filterTuple in myproj.Filters:
            filterDict[filterTuple[0]] = filterTuple[1]
        for node in myproj.sinks:
            evaluationDict[node].append(str(myproj.name))
        # Operator as Key and Prim Values as Value
        combinationDict[str(myproj.name)] = list(
            map(lambda x: str(x), myproj.combination.keys())
        )  # remove events used as filters
        selectionRate[str(myproj.name)] = get_selection_rate(
            myproj.name, myproj.combination.keys(), selectivities
        )
        sinkDict[str(myproj.name)] = [myproj.sinks, ""]
        if len(myproj.sinks):
            for proj in myproj.combination.keys():
                for instance in myproj.combination[proj]:
                    if instance.sources == myproj.sinks:
                        sinkDict[str(myproj.name)][1] = instance.projname
        for instancelist in myproj.combination.keys():
            for instance in myproj.combination[instancelist]:
                if instance.projname not in forwardingDict.keys():
                    forwardingDict[instance.projname] = {}
                if (
                    instance.projname in forwardingDict.keys()
                    and instance.name not in forwardingDict[instance.projname].keys()
                ):
                    forwardingDict[instance.projname][instance.name] = {}
                if list(instance.routingDict.keys()):
                    forwardingDict[instance.projname][instance.name] = process_instance(
                        instance, forwardingDict
                    )

    config_buffer = io.StringIO()

    text_buffer, reused_text = generate_plan(
        nw, selectivities, workload, combinationDict, sinkDict, selectionRate
    )

    config_buffer.write(text_buffer)
    config_buffer.seek(0)
    return config_buffer, reused_text
