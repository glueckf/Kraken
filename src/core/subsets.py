def combination_util(arr, n, r, index, data, i, blub):
    if index == r:
        bla = ""

        for j in range(r):
            bla = bla + data[j]
        blub.append(bla)
        return

    if i >= n:
        return

    data[index] = arr[i]
    combination_util(arr, n, r, index + 1, data, i + 1, blub)

    combination_util(arr, n, r, index, data, i + 1, blub)


def printcombination(arr, i):
    r = i
    n = len(arr)
    data = list(range(r))
    blub = []
    combination_util(arr, n, r, 0, data, 0, blub)
    return blub


def combination_util2(arr, n, r, index, data, i, blub):
    if index == r:
        bla = []

        for j in range(r):
            bla.append(data[j])
        blub.append(bla)
        return

    if i >= n:
        return

    data[index] = arr[i]
    combination_util2(arr, n, r, index + 1, data, i + 1, blub)

    combination_util2(arr, n, r, index, data, i + 1, blub)


def printcombination2(arr, i):
    r = i
    n = len(arr)
    data = list(range(r))
    blub = []
    combination_util2(arr, n, r, 0, data, 0, blub)
    return blub


def combination(arr, n, r, index, data, i, blub):
    if index == r:
        bla = ""
        for j in range(r):
            if not bla:
                bla = bla + data[j]
            else:
                bla = bla + "," + data[j]
        blub.append(bla)
        return

    if i >= n:
        return

    data[index] = arr[i]
    combination(arr, n, r, index + 1, data, i + 1, blub)

    combination(arr, n, r, index, data, i + 1, blub)


def boah(arr, i):
    r = i
    n = len(arr)
    data = list(range(r))
    blub = []

    combination(arr, n, r, 0, data, 0, blub)
    return blub
