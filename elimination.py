"""Count the groundings of an action schema by variable elimination.

The groundings of a schema are the answers of a full conjunctive query: each
precondition is an atom of the query, and every variable is an output variable.
We count the answers with sum-product variable elimination over the relations
of the relaxed reachable atoms, without enumerating them. The running time is
polynomial in the size of the relations and exponential only in the width of
the elimination order.
"""

import itertools
import re
import time
from collections import defaultdict

from counting import is_variable

FACT_PATTERN = re.compile(r"(\w+)(?:\(([^)]*)\))?\.")

# Check the deadline after this many steps of a join.
CHECK_INTERVAL = 1 << 16


class TooExpensive(Exception):
    """An intermediate factor exceeds the size limit, or the time is up."""


def load_relations(model_file, predicates):
    """Read the facts of the given predicates from a model file."""
    relations = {predicate: set() for predicate in predicates}
    with open(model_file) as f:
        for line in f:
            match = FACT_PATTERN.match(line)
            if match is None:
                continue
            predicate, args = match.groups()
            relation = relations.get(predicate)
            if relation is not None:
                relation.add(tuple(args.split(",")) if args else ())
    return relations


class Factor:
    """A function from assignments of the variables to positive counts."""

    __slots__ = ("variables", "table")

    def __init__(self, variables, table):
        self.variables = variables
        self.table = table

    def __len__(self):
        return len(self.table)


def atom_factor(predicate, args, relation):
    """Return the factor of an atom: its satisfying assignments, each with count 1."""
    variables = tuple(dict.fromkeys(arg for arg in args if is_variable(arg)))
    if len(variables) == len(args):
        # Fast path: distinct variables and no constants.
        return Factor(variables, dict.fromkeys(relation, 1))
    positions = [variables.index(arg) if is_variable(arg) else None for arg in args]
    table = {}
    for values in relation:
        assignment = [None] * len(variables)
        for arg, value, position in zip(args, values, positions, strict=True):
            if position is None:
                if value != arg:
                    break
            elif assignment[position] is None:
                assignment[position] = value
            elif assignment[position] != value:
                break
        else:
            table[tuple(assignment)] = 1
    return Factor(variables, table)


class Eliminator:
    def __init__(self, deadline, max_factor_size):
        self.deadline = deadline
        self.max_factor_size = max_factor_size
        self.steps = 0
        # Induced width: largest number of variables in a bucket, minus one.
        self.width = 0

    def tick(self):
        self.steps += 1
        if self.steps % CHECK_INTERVAL == 0 and time.monotonic() > self.deadline:
            raise TooExpensive("time limit")

    def join(self, left, right, drop=None):
        """Return the product of two factors, summing out the variable *drop*."""
        if len(left) > len(right):
            left, right = right, left
        shared = [v for v in left.variables if v in right.variables]
        left_key = [left.variables.index(v) for v in shared]
        right_key = [right.variables.index(v) for v in shared]
        extra = [i for i, v in enumerate(right.variables) if v not in left.variables]
        variables = left.variables + tuple(right.variables[i] for i in extra)
        keep = [i for i, v in enumerate(variables) if v != drop]

        index = defaultdict(list)
        for assignment, count in left.table.items():
            index[tuple(assignment[i] for i in left_key)].append((assignment, count))
        table = defaultdict(int)
        for assignment, count in right.table.items():
            matches = index.get(tuple(assignment[i] for i in right_key))
            if not matches:
                continue
            suffix = tuple(assignment[i] for i in extra)
            for left_assignment, left_count in matches:
                self.tick()
                joined = left_assignment + suffix
                if drop is not None:
                    joined = tuple(joined[i] for i in keep)
                table[joined] += left_count * count
            if len(table) > self.max_factor_size:
                raise TooExpensive("factor size")
        return Factor(tuple(variables[i] for i in keep), dict(table))

    def sum_out(self, factor, variable):
        position = factor.variables.index(variable)
        variables = factor.variables[:position] + factor.variables[position + 1 :]
        table = defaultdict(int)
        for assignment, count in factor.table.items():
            self.tick()
            table[assignment[:position] + assignment[position + 1 :]] += count
        return Factor(variables, dict(table))

    def eliminate(self, factors, variable):
        """Multiply the factors that contain the variable and sum it out."""
        factors = sorted(factors, key=len)
        if len(factors) == 1:
            return self.sum_out(factors[0], variable)
        product = factors[0]
        for factor in factors[1:-1]:
            product = self.join(product, factor)
            if not product.table:
                return Factor((), {})
        return self.join(product, factors[-1], drop=variable)

    def count(self, factors):
        """Return the sum over all assignments of the product of the factors."""
        result = 1
        factors = list(factors)
        while True:
            for factor in factors:
                if not factor.table:
                    return 0
            remaining = {v for factor in factors for v in factor.variables}
            if not remaining:
                break
            variable = self.choose_variable(factors, remaining)
            bucket = [f for f in factors if variable in f.variables]
            scope = set().union(*(f.variables for f in bucket))
            self.width = max(self.width, len(scope) - 1)
            factors = [f for f in factors if variable not in f.variables]
            factors.append(self.eliminate(bucket, variable))
        for factor in factors:
            result *= factor.table.get((), 0)
        return result

    @staticmethod
    def choose_variable(factors, remaining):
        """Prefer variables whose bucket fits in one factor, then small buckets."""

        def score(variable):
            bucket = [f for f in factors if variable in f.variables]
            scope = set().union(*(f.variables for f in bucket))
            fits = any(scope <= set(f.variables) for f in bucket)
            size = max(len(f) for f in bucket) if fits else _product(len(f) for f in bucket)
            return (not fits, len(scope), size, variable)

        return min(remaining, key=score)


def _product(numbers):
    result = 1
    for number in numbers:
        result *= max(number, 1)
    return result


def substitute(args, mapping):
    return tuple(mapping.get(arg, arg) for arg in args)


def count_groundings(schema, relations, deadline, max_factor_size):
    """Count the groundings of a schema whose preconditions hold in the relations.

    Returns the count and the induced width of the elimination orders.

    Inequalities are handled by inclusion-exclusion: we count with each subset
    of the inequalities turned into equalities.
    """
    positive = [atom for atom in schema.preconditions if not atom.inequality]
    inequalities = [atom.args for atom in schema.preconditions if atom.inequality]
    total = 0
    width = 0
    for size in range(len(inequalities) + 1):
        for subset in itertools.combinations(inequalities, size):
            mapping = _merge(subset)
            if mapping is None:
                continue  # Two different constants must be equal.
            factors = []
            for atom in positive:
                args = substitute(atom.args, mapping)
                factors.append(atom_factor(atom.predicate, args, relations[atom.predicate]))
            eliminator = Eliminator(deadline, max_factor_size)
            count = eliminator.count(factors)
            width = max(width, eliminator.width)
            total += -count if size % 2 else count
    return total, width


def _merge(equalities):
    """Map each term to a representative of its equivalence class."""
    parent = {}

    def find(term):
        while parent.get(term, term) != term:
            term = parent[term]
        return term

    for lhs, rhs in equalities:
        lhs, rhs = find(lhs), find(rhs)
        if lhs == rhs:
            continue
        if not is_variable(lhs) and not is_variable(rhs):
            return None
        # Keep constants as representatives.
        if is_variable(lhs):
            parent[lhs] = rhs
        else:
            parent[rhs] = lhs
    return {term: find(term) for term in parent}
