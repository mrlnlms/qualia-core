"""Distância lexical entre transcrições; a referência não é verdade do áudio."""
import re


def tokens(text):
    return re.findall(r"\w+", text.casefold())


def align_words(reference, generated):
    """Levenshtein exato por palavra, com traceback de memória compacta.

    Empates priorizam substituição, depois exclusão, depois inserção. A soma
    mínima é estável; a decomposição pode variar em alinhamentos equivalentes.
    """
    n, m = len(reference), len(generated)
    directions = [bytearray(m+1) for _ in range(n+1)]
    directions[0] = bytearray([2])*(m+1)
    previous = list(range(m+1))
    for i, word in enumerate(reference, 1):
        current = [i] + [0]*m
        direction = directions[i]
        direction[0] = 1
        for j, other in enumerate(generated, 1):
            if word == other:
                current[j] = previous[j-1]
                continue
            substitute = previous[j-1]+1
            delete = previous[j]+1
            insert = current[j-1]+1
            if substitute <= delete and substitute <= insert:
                current[j] = substitute
            elif delete <= insert:
                current[j] = delete
                direction[j] = 1
            else:
                current[j] = insert
                direction[j] = 2
        previous = current
    i, j = n, m
    operations = []
    while i or j:
        direction = directions[i][j]
        if direction == 0:
            i -= 1; j -= 1
            operations.append(('equal' if reference[i] == generated[j] else 'substitute', i, j))
        elif direction == 1:
            i -= 1
            operations.append(('delete', i, j))
        else:
            j -= 1
            operations.append(('insert', i, j))
    operations.reverse()
    counts = {key: sum(op[0] == key for op in operations) for key in ['equal','substitute','delete','insert']}
    return {'reference_words': n, 'generated_words': m, **counts,
            'distance': previous[-1], 'wer': previous[-1]/n if n else None,
            'operations': operations}
