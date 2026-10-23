"""Count the groundings of an action schema by variable elimination.

The groundings of a schema are the answers of a full conjunctive query: each
precondition is an atom of the query, and every variable is an output variable.
We count the answers with sum-product variable elimination over the relations
of the relaxed reachable atoms, without enumerating them. The running time is
polynomial in the size of the relations and exponential only in the width of
the elimination order.
"""

import itertools
import time
from collections import Counter, defaultdict
from operator import itemgetter

from counting import Atom, is_variable

# Check the deadline after this many steps of a join.
CHECK_INTERVAL = 1 << 16


class TooExpensive(Exception):
    """An intermediate factor exceeds the size limit, or the time is up."""


def load_relations(model_file, predicates):
    """Read the facts of the given predicates from a model file.

    Each line of the file is a fact such as "p(a,b)." or "q.".
    """
    relations = {predicate: set() for predicate in predicates}
    with open(model_file) as f:
        for line in f:
            predicate, parenthesis, args = line.partition("(")
            if parenthesis:
                relation = relations.get(predicate)
                if relation is not None:
                    relation.add(tuple(args.rstrip().removesuffix(").").split(",")))
            else:
                relation = relations.get(line.rstrip().removesuffix("."))
                if relation is not None:
                    relation.add(())
    return relations


class Factor:
    """A function from assignments of the variables to positive counts."""

    __slots__ = ("variables", "table", "unit")

    def __init__(self, variables, table, unit=False):
        self.variables = variables
        self.table = table
        # True if every count is 1, as in the factors of atoms.
        self.unit = unit

    def __len__(self):
        return len(self.table)


def atom_factor(predicate, args, relation):
    """Return the factor of an atom: its satisfying assignments, each with count 1."""
    variables = tuple(dict.fromkeys(arg for arg in args if is_variable(arg)))
    if len(variables) == len(args):
        # Fast path: distinct variables and no constants.
        return Factor(variables, dict.fromkeys(relation, 1), unit=True)
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
    return Factor(variables, table, unit=True)


def project(factor, keep):
    """Return the table of the factor with all variables but those at *keep* summed out."""
    table = factor.table
    if not keep:
        return {(): sum(table.values())}
    if factor.unit:
        # Count with C loops: every assignment contributes 1.
        if len(keep) == 1:
            counts = Counter(map(itemgetter(keep[0]), table))
            return {(value,): count for value, count in counts.items()}
        return dict(Counter(map(itemgetter(*keep), table)))
    result = defaultdict(int)
    for assignment, count in table.items():
        result[tuple(assignment[i] for i in keep)] += count
    return dict(result)


class Eliminator:
    def __init__(self, deadline, max_factor_size):
        self.deadline = deadline
        self.max_factor_size = max_factor_size
        self.steps = 0
        # Induced width: largest number of variables in a bucket, minus one.
        self.width = 0

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            raise TooExpensive("time limit")

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
        keep = [i for i, v in enumerate(factor.variables) if v != variable]
        table = project(factor, keep)
        self.check_deadline()
        return Factor(tuple(factor.variables[i] for i in keep), table)

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
            factors = self.project_private_variables(factors)
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

    def project_private_variables(self, factors):
        """Sum out, in one pass per factor, the variables that occur in no other factor."""
        occurrences = defaultdict(int)
        for factor in factors:
            for variable in factor.variables:
                occurrences[variable] += 1
        result = []
        for factor in factors:
            keep = [i for i, v in enumerate(factor.variables) if occurrences[v] > 1]
            if len(keep) == len(factor.variables):
                result.append(factor)
                continue
            self.width = max(self.width, len(factor.variables) - 1)
            table = project(factor, keep)
            self.check_deadline()
            result.append(Factor(tuple(factor.variables[i] for i in keep), table))
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


class ColumnCache:
    """Cache the set of values in each column of each relation."""

    def __init__(self, relations):
        self.relations = relations
        self.columns = {}

    def column(self, predicate, position):
        key = (predicate, position)
        values = self.columns.get(key)
        if values is None:
            values = set(map(itemgetter(position), self.relations[predicate]))
            self.columns[key] = values
        return values


def drop_implied_unary_atoms(atoms, cache):
    """Remove unary atoms p(X) that hold for every value of X in another atom.

    For example, a type atom is implied if X occurs in an atom whose relation
    only contains objects of this type at the position of X. Such atoms do not
    change the count, but they would make every variable occur in two factors.
    """
    result = []
    for atom in atoms:
        if len(atom.args) == 1 and atom.variables:
            (variable,) = atom.variables
            values = cache.column(atom.predicate, 0)
            implied = any(
                cache.column(other.predicate, position) <= values
                for other in atoms
                if len(other.args) > 1
                for position, arg in enumerate(other.args)
                if arg == variable
            )
            if implied:
                continue
        result.append(atom)
    return result


def count_groundings(schema, relations, deadline, max_factor_size, cache=None):
    """Count the groundings of a schema whose preconditions hold in the relations.

    Returns the count and the induced width of the elimination orders.

    Inequalities are handled by inclusion-exclusion: we count with each subset
    of the inequalities turned into equalities.
    """
    cache = cache or ColumnCache(relations)
    positive = [atom for atom in schema.preconditions if not atom.inequality]
    inequalities = [atom.args for atom in schema.preconditions if atom.inequality]
    total = 0
    width = 0
    for size in range(len(inequalities) + 1):
        for subset in itertools.combinations(inequalities, size):
            mapping = _merge(subset)
            if mapping is None:
                continue  # Two different constants must be equal.
            atoms = [Atom(atom.predicate, substitute(atom.args, mapping)) for atom in positive]
            factors = [
                atom_factor(atom.predicate, atom.args, relations[atom.predicate])
                for atom in drop_implied_unary_atoms(atoms, cache)
            ]
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
