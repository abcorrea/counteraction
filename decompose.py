"""Split long Datalog rules to make grounding cheaper.

For each rule, we eliminate the variables that occur in the body but not in the
head, one at a time. Eliminating a variable X replaces the atoms that contain X
by a new atom over their other variables, defined by a new rule. We choose the
variable whose new atom has the smallest bound on its number of ground atoms:
the product of the domain sizes of its variables. The domain of a variable is
bounded by the number of facts of each static unary predicate (such as a type)
that applies to it. Unlike structure-only decompositions, this avoids new atoms over large
domains, and the result does not depend on random choices.
"""

import collections

from counting import Atom, parse_atoms

AUXILIARY_PREFIX = "aux__"


def split_rule(head, body, domain_size, new_name):
    """Return the rules (head, body) that replace the rule head :- body."""
    domains = {}
    for atom in body:
        size = domain_size(atom)
        if size is not None:
            (variable,) = atom.variables
            domains[variable] = min(domains.get(variable, float("inf")), size)
    head_variables = set(head.variables)
    body = list(body)
    rules = []
    while True:
        existential = {v for atom in body for v in atom.variables} - head_variables
        candidates = []
        for variable in existential:
            bucket = [atom for atom in body if variable in atom.args]
            if len(bucket) == len(body):
                continue  # A new rule would only rename the body.
            scope = {v for atom in bucket for v in atom.variables} - {variable}
            if scope >= head_variables:
                continue  # The new atom would be a copy of the head.
            size = 1
            for v in scope:
                size *= max(domains.get(v, 1), 1)
            candidates.append((size, len(scope), variable, bucket, sorted(scope)))
        if not candidates:
            break
        _, _, variable, bucket, scope = min(candidates, key=lambda c: c[:3])
        auxiliary = Atom(new_name(), tuple(scope))
        rules.append((auxiliary, bucket))
        body = [atom for atom in body if variable not in atom.args] + [auxiliary]
    rules.append((head, body))
    return rules


def decompose(lines):
    """Rewrite a Datalog program given as lines of text. Facts stay unchanged."""
    # Number of facts of each unary predicate.
    sizes = collections.Counter()
    rules = []
    output = []
    for line in lines:
        if ":-" in line:
            head, body = line.split(":-", 1)
            (head_atom,) = parse_atoms(head)
            rules.append((head_atom, parse_atoms(body.strip().removesuffix("."))))
        elif line.strip():
            output.append(line.rstrip("\n"))
            predicate, parenthesis, args = line.partition("(")
            if parenthesis and "," not in args:
                sizes[predicate] += 1
    derived = {head.predicate for head, _ in rules}
    names = iter(range(1 << 62))

    def domain_size(atom):
        """Bound on the values of the variable of a unary atom, if the atom is static."""
        if len(atom.args) != 1 or not atom.variables or atom.predicate in derived:
            return None
        return sizes.get(atom.predicate, 0)

    def new_name():
        return f"{AUXILIARY_PREFIX}{next(names)}"

    for head, body in rules:
        for new_head, new_body in split_rule(head, body, domain_size, new_name):
            output.append(f"{new_head} :- {','.join(str(atom) for atom in new_body)}.")
    return output
