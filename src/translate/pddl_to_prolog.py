#! /usr/bin/env python3

"""Print the Datalog program that encodes the delete relaxation of a PDDL task.

The canonical model of the program contains exactly the delete-relaxed
reachable atoms (and, unless --remove-action-predicates is given, actions).
"""

import copy
import sys

import normalize
import options
import pddl


class PrologProgram:
    def __init__(self):
        self.facts = []
        self.rules = []
        self.objects = set()

    def add_fact(self, atom):
        self.facts.append(Fact(atom))
        self.objects |= set(atom.args)

    def add_rule(self, rule):
        self.rules.append(rule)

    def dump_sanitized(self, file=None):
        for fact in self.facts:
            print(fact._sanitize_output(), file=file)
        for rule in self.rules:
            print(rule._sanitize_output(), file=file)

    def normalize(self):
        # Normalized prolog programs have the following properties:
        # 1. Each variable that occurs in the effect of a rule also occurs in its
        #    condition.
        # 2. The variables that appear in each effect or condition are distinct.
        # 3. There are no rules with empty condition.
        self.remove_free_effect_variables()
        self.split_duplicate_arguments()
        self.convert_trivial_rules()

    def remove_free_effect_variables(self):
        """Remove free effect variables like the variable Y in the rule
        p(X, Y) :- q(X). This is done by introducing a new predicate
        @object, setting it true for all objects, and translating the above
        rule to p(X, Y) :- q(X), @object(Y).
        After calling this, no new objects should be introduced!"""

        # Note: This should never be necessary for typed domains.
        # Leaving it in at the moment regardless.
        must_add_predicate = False
        for rule in self.rules:
            eff_vars = get_variables([rule.effect])
            cond_vars = get_variables(rule.conditions)
            if not eff_vars.issubset(cond_vars):
                must_add_predicate = True
                eff_vars -= cond_vars
                for var in sorted(eff_vars):
                    rule.add_condition(pddl.Atom("@object", [var]))
        if must_add_predicate:
            print("Unbound effect variables: Adding @object predicate.", file=sys.stderr)
            self.facts += [Fact(pddl.Atom("@object", [obj])) for obj in self.objects]

    def split_duplicate_arguments(self):
        """Make sure that no variable occurs twice within the same symbolic fact,
        like the variable X does in p(X, Y, X). This is done by renaming the second
        and following occurrences of the variable and adding equality conditions.
        For example p(X, Y, X) is translated to p(X, Y, X@0) with the additional
        condition =(X, X@0); the equality predicate must be appropriately instantiated
        somewhere else."""
        printed_message = False
        for rule in self.rules:
            if rule.rename_duplicate_variables() and not printed_message:
                print("Duplicate arguments: Adding equality conditions.", file=sys.stderr)
                printed_message = True

    def convert_trivial_rules(self):
        """Convert rules with an empty condition into facts.
        This must be called after bounding rule effects, so that rules with an
        empty condition must necessarily have a variable-free effect.
        Variable-free effects are the only ones for which a distinction between
        ground and symbolic atoms is not necessary."""
        must_delete_rules = []
        for i, rule in enumerate(self.rules):
            if not rule.conditions:
                assert not get_variables([rule.effect])
                self.add_fact(pddl.Atom(rule.effect.predicate, rule.effect.args))
                must_delete_rules.append(i)
        if must_delete_rules:
            print("Trivial rules: Converted to facts.", file=sys.stderr)
            for rule_no in must_delete_rules[::-1]:
                del self.rules[rule_no]

    def remove_action_predicates(self):
        """Replace each action atom in a rule body by the body of the action rule.

        For example,

        action_a(?x, ?b) :- p(?x, ?b), r(?x).
        eff_1(?x) :- action_a(?x, ?b).
        eff_2(?b) :- action_a(?x, ?b), q(?b).

        becomes

        eff_1(?x) :- p(?x, ?b), r(?x).
        eff_2(?b) :- p(?x, ?b), r(?x), q(?b).

        This *needs* to be done before renaming variables.
        """
        action_rules = {}
        other_rules = []
        for rule in self.rules:
            head = str(rule.effect)
            if head.startswith("action_"):
                action_rules[head] = rule
            else:
                other_rules.append(rule)

        new_rules = []
        for rule in other_rules:
            conditions = []
            for condition in rule.conditions:
                action_rule = action_rules.get(str(condition))
                if action_rule is None:
                    conditions.append(condition)
                else:
                    conditions.extend(copy.deepcopy(action_rule.conditions))
            new_rules.append(Rule(conditions, rule.effect))
        self.rules = new_rules


def get_variables(symbolic_atoms):
    variables = set()
    for sym_atom in symbolic_atoms:
        variables |= {arg for arg in sym_atom.args if arg[0] == "?"}
    return variables


class Fact:
    def __init__(self, atom):
        self.atom = atom

    def __str__(self):
        return "%s." % self.atom

    def _sanitize_output(self):
        return "%s." % self.atom._sanitize_output()


class Rule:
    def __init__(self, conditions, effect):
        self.conditions = conditions
        self.effect = effect

    def add_condition(self, condition):
        self.conditions.append(condition)

    def get_variables(self):
        return get_variables(self.conditions + [self.effect])

    def _rename_duplicate_variables(self, atom, new_conditions):
        used_variables = set()
        for i, var_name in enumerate(atom.args):
            if var_name[0] == "?":
                if var_name in used_variables:
                    new_var_name = "%s@%d" % (var_name, len(new_conditions))
                    atom = atom.replace_argument(i, new_var_name)
                    new_conditions.append(pddl.Atom("=", [var_name, new_var_name]))
                else:
                    used_variables.add(var_name)
        return atom

    def rename_duplicate_variables(self):
        extra_conditions = []
        self.effect = self._rename_duplicate_variables(self.effect, extra_conditions)
        old_conditions = self.conditions
        self.conditions = []
        for condition in old_conditions:
            self.conditions.append(self._rename_duplicate_variables(condition, extra_conditions))
        self.conditions += extra_conditions
        return bool(extra_conditions)

    def __str__(self):
        cond_str = ", ".join(map(str, self.conditions))
        return "%s :- %s." % (self.effect, cond_str)

    def _sanitize_output(self):
        cond_str = ",".join([x._sanitize_output() for x in self.conditions])
        cond_str = cond_str.replace(" ", "")
        cond_str = cond_str.replace("()", "")
        return "%s :- %s." % (self.effect._sanitize_output(), cond_str)


def translate_typed_object(prog, obj, type_dict):
    supertypes = type_dict[obj.type_name].supertype_names
    for type_name in [obj.type_name] + supertypes:
        prog.add_fact(pddl.TypedObject(obj.name, type_name).get_atom())


def translate_facts(prog, task):
    type_dict = {type.name: type for type in task.types}
    for obj in task.objects:
        translate_typed_object(prog, obj, type_dict)
    for fact in task.init:
        assert isinstance(fact, (pddl.Atom, pddl.Assign))
        if isinstance(fact, pddl.Atom):
            prog.add_fact(fact)


def translate(task):
    # Note: The function requires that the task has been normalized.
    prog = PrologProgram()
    translate_facts(prog, task)
    for conditions, effect in normalize.build_exploration_rules(task):
        prog.add_rule(Rule(conditions, effect))
    prog.normalize()
    if options.remove_action_predicates:
        prog.remove_action_predicates()
    return prog


if __name__ == "__main__":
    import pddl_parser

    task = pddl_parser.open()
    normalize.normalize(task)
    prog = translate(task)
    prog.dump_sanitized()
