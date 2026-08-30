import re

def clean_relation(relation):

    relation = relation.upper()

    relation = re.sub(
        r'[^A-Z0-9_]',
        '_',
        relation
    )

    return relation