"""Count the ground actions of each action schema without enumerating them.

For every action schema, we build a small logic program whose answer sets
correspond one-to-one to the delete-relaxed reachable groundings of the schema.
The program guesses one value per schema variable (choice rules) and discards
guesses that violate a precondition (integrity constraints). A model counter
then counts the answer sets of this program together with the relaxed
reachable atoms.
"""

import contextlib
import logging
import os
import re
import resource
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"

# Resource limits for counting a single action schema.
SCHEMA_TIME_LIMIT = 360  # seconds (wall-clock)
SCHEMA_MEMORY_LIMIT = 4096  # MiB

# Equivalence-preserving pmc options recommended for model counting.
PMC_OPTIONS = [
    "-vivification",
    "-eliminateLit",
    "-litImplied",
    "-iterate=10",
    "-equiv",
    "-orGate",
    "-affine",
]

ACTION_PREFIX = "action_"
TYPE_PREFIX = "pddl_type"
VARIABLE_PREFIX = "Var_"

# An atom is either an inequality "X!=Y", or "p(t1,...,tn)", or a nullary "p".
ATOM_PATTERN = re.compile(r"(\w+)!=(\w+)|(\w+)(?:\(([^)]*)\))?")


def is_variable(term):
    return term.startswith(VARIABLE_PREFIX)


@dataclass(frozen=True)
class Atom:
    predicate: str
    args: tuple
    inequality: bool = False

    @property
    def variables(self):
        return [arg for arg in self.args if is_variable(arg)]

    def __str__(self):
        if self.inequality:
            return f"{self.args[0]}!={self.args[1]}"
        if not self.args:
            return self.predicate
        return f"{self.predicate}({','.join(self.args)})"


def parse_atoms(text):
    atoms = []
    for match in ATOM_PATTERN.finditer(text):
        lhs, rhs, predicate, args = match.groups()
        if lhs is not None:
            atoms.append(Atom("!=", (lhs, rhs), inequality=True))
        else:
            terms = tuple(arg.strip() for arg in args.split(",")) if args else ()
            atoms.append(Atom(predicate, terms))
    return atoms


@dataclass
class ActionSchema:
    name: str
    parameters: tuple
    preconditions: list = field(default_factory=list)


def parse_action_schemas(theory_lines):
    """Extract the action applicability rules from a Datalog program."""
    schemas = []
    for line in theory_lines:
        if not line.startswith(ACTION_PREFIX):
            continue
        head, body = line.split(":-", 1)
        (head_atom,) = parse_atoms(head)
        body = body.strip().removesuffix(".")
        schemas.append(ActionSchema(head_atom.predicate, head_atom.args, parse_atoms(body)))
    return schemas


def guess_atom(variable):
    return f"g_{variable}({variable})"


def counting_program(schema):
    """Return a program whose answer sets are the groundings of the schema.

    For each variable X, the choice rule guesses exactly one value among those
    that satisfy every precondition containing X. The integrity constraints
    then check each precondition on the joint assignment.
    """
    positive = [atom for atom in schema.preconditions if not atom.inequality]
    variables = []
    for atom in positive:
        if atom.predicate.startswith(TYPE_PREFIX):
            variables.extend(atom.variables)
    # Variables without a type atom (e.g., copies introduced for repeated
    # arguments) are determined by an equality atom; guess them as well.
    for atom in positive:
        variables.extend(atom.variables)
    variables = list(dict.fromkeys(variables))

    # Hide all atoms except the guesses when clingo prints answer sets.
    lines = ["#show."]
    for variable in variables:
        condition = ",".join(str(atom) for atom in positive if variable in atom.args)
        lines.append(f"1 {{ {guess_atom(variable)} : {condition} }} 1.")
        lines.append(f"#show g_{variable}/1.")
    for atom in schema.preconditions:
        if atom.predicate.startswith(TYPE_PREFIX):
            continue
        if atom.inequality:
            lhs, rhs = atom.args
            literals = [f"{lhs}={rhs}"]
        else:
            literals = [f"not {atom}"]
        literals += [guess_atom(variable) for variable in dict.fromkeys(atom.variables)]
        lines.append(f":- {', '.join(literals)}.")
    return "\n".join(lines) + "\n"


@dataclass
class CountResult:
    count: int | None
    """Number of groundings found, or None if the counter produced no number."""
    exact: bool
    """True if the count is the exact number of groundings."""


def limit_memory():
    """Limit the address space of a child process. Runs before exec."""
    limit = SCHEMA_MEMORY_LIMIT * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))


def stop_process(process):
    """Ask a process to stop, and kill it if it is still running after 5 seconds."""
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


class ProcessRegistry:
    """Start child processes with resource limits and stop them on a signal."""

    def __init__(self):
        self._processes = set()
        self._timers = {}

    def popen(self, *args, time_limit=None, **kwargs):
        """Start a process whose memory is limited to SCHEMA_MEMORY_LIMIT.

        After *time_limit* seconds, the process receives SIGTERM. clingo then
        stops and reports the number of answer sets found so far.
        """
        process = subprocess.Popen(*args, preexec_fn=limit_memory, **kwargs)
        self._processes.add(process)
        if time_limit is not None:
            timer = threading.Timer(time_limit, stop_process, [process])
            timer.daemon = True
            timer.start()
            self._timers[process] = timer
        return process

    def release(self, process):
        self._processes.discard(process)
        timer = self._timers.pop(process, None)
        if timer is not None:
            timer.cancel()

    def terminate_all(self):
        for timer in self._timers.values():
            timer.cancel()
        for process in list(self._processes):
            stop_process(process)
        self._processes.clear()


PROCESSES = ProcessRegistry()


def parse_clingo_models(line):
    # clingo prints "Models       : 42" or "Models       : 42+". The "+" means
    # that clingo stopped before enumerating all answer sets.
    value = line.split(":", 1)[1].strip()
    return int(value.rstrip("+")), not value.endswith("+")


class ClingoCounter:
    """Count groundings by enumerating answer sets with clingo.

    A bound of 0 enumerates all answer sets. If clingo is interrupted, it still
    reports the number of answer sets found so far, which is a lower bound.
    """

    def __init__(self, bound=0, show_actions=False):
        self.bound = bound
        self.show_actions = show_actions

    def count(self, model_file, schema, program):
        command = [str(BIN_DIR / "clingo"), "--warn=none", "-n", str(self.bound)]
        if not self.show_actions:
            command.append("-q")
        command += [str(model_file), "-"]
        process = PROCESSES.popen(
            command,
            time_limit=SCHEMA_TIME_LIMIT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            process.stdin.write(program)
            process.stdin.close()
            result = CountResult(None, False)
            for line in process.stdout:
                if line.startswith("Models"):
                    count, exact = parse_clingo_models(line)
                    result = CountResult(count, exact)
                elif self.show_actions and line.startswith("g_"):
                    log_action(schema, line)
            process.wait()
        finally:
            PROCESSES.release(process)
        return result


class D4Counter:
    """Count groundings with the knowledge compiler d4.

    The program is translated to CNF (lp2normal2, lp2lp2, lp2sat), simplified
    with pmc and counted with d4. The count is exact if d4 finishes; otherwise
    no count is available for the schema.
    """

    def count(self, model_file, schema, program):
        stages = [
            [str(BIN_DIR / "gringo"), "--warn=none", "--output", "smodels", str(model_file), "-"],
            [str(BIN_DIR / "lp2normal2-2.27")],
            [str(BIN_DIR / "lp2lp2-1.23")],
            [str(BIN_DIR / "lp2sat-1.24")],
            [str(BIN_DIR / "pmc-1.0"), *PMC_OPTIONS],
        ]
        with tempfile.NamedTemporaryFile("w+", suffix=".cnf") as cnf:
            self._write_cnf(stages, program, cnf)
            cnf.seek(0)
            if self._refuted_by_pmc(cnf):
                return CountResult(0, True)
            return self._run_d4(cnf.name)

    @staticmethod
    def _refuted_by_pmc(cnf):
        # If pmc refutes the input, it prints only comments and no formula.
        # d4 would then count the single model of the empty formula.
        # The comments come before the header line "p cnf ...".
        for line in cnf:
            if line.startswith("p "):
                return False
            if line.startswith("c UNSATISFIABLE"):
                return True
        return False

    @staticmethod
    def _write_cnf(stages, program, cnf):
        processes = []
        try:
            for index, command in enumerate(stages):
                last = index == len(stages) - 1
                process = PROCESSES.popen(
                    command,
                    stdin=subprocess.PIPE if index == 0 else processes[-1].stdout,
                    stdout=cnf if last else subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                if processes:
                    # Let the previous stage receive SIGPIPE if this one exits.
                    processes[-1].stdout.close()
                processes.append(process)
            processes[0].stdin.write(program)
            processes[0].stdin.close()
            # A failing stage leaves an incomplete formula, for which d4
            # reports no count.
            for process in processes:
                process.wait()
        finally:
            for process in processes:
                PROCESSES.release(process)

    @staticmethod
    def _run_d4(cnf_file):
        command = [str(BIN_DIR / "d4-1.2"), "-mc", cnf_file]
        process = PROCESSES.popen(
            command,
            time_limit=SCHEMA_TIME_LIMIT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            result = CountResult(None, False)
            for line in process.stdout:
                if line.startswith("s "):
                    result = CountResult(int(line[2:]), True)
            process.wait()
        finally:
            PROCESSES.release(process)
        return result


class EliminationCounter:
    """Count groundings exactly by variable elimination (see elimination.py).

    The counter reads the relaxed reachable atoms once and counts every schema
    in this process, without calling a solver.
    """

    # Largest intermediate factor (number of entries) before we give up.
    MAX_FACTOR_SIZE = 5_000_000

    def __init__(self):
        self.relations = None

    def prepare(self, model_file, schemas):
        from elimination import load_relations

        predicates = {atom.predicate for schema in schemas for atom in schema.preconditions}
        self.relations = load_relations(model_file, predicates)

    def count(self, model_file, schema, program):
        from elimination import TooExpensive, count_groundings

        deadline = time.monotonic() + SCHEMA_TIME_LIMIT
        try:
            count, width = count_groundings(schema, self.relations, deadline, self.MAX_FACTOR_SIZE)
        except TooExpensive as error:
            logging.info(f"Variable elimination stopped: {error}")
            return CountResult(None, False)
        logging.info(f"Variable elimination width: {width}")
        return CountResult(count, True)


def log_action(schema, model_line):
    values = {}
    for atom in parse_atoms(model_line):
        values[atom.predicate.removeprefix("g_")] = atom.args[0]
    arguments = ",".join(values.get(parameter, parameter) for parameter in schema.parameters)
    logging.info(f"{schema.name}({arguments})")


def count_actions(model_file, schemas, counter):
    """Count the groundings of all schemas. Returns the total and whether it is exact."""
    total = 0
    exact = True
    with open(model_file) as f:
        num_facts = sum(1 for _ in f)
    if hasattr(counter, "prepare"):
        counter.prepare(model_file, schemas)
    for schema in schemas:
        program = counting_program(schema)
        num_rules = program.count("\n")
        logging.info(f"Counting {schema.name} on {num_facts} facts and {num_rules} rules")
        result = counter.count(model_file, schema, program)
        if result.count is not None:
            total += result.count
        exact = exact and result.exact
        logging.info(f"# of actions (intermediate result): {format_count(total, exact)}")
    return total, exact


def format_count(count, exact):
    return f"{count}{'' if exact else '+'}"


def remove_silently(filename):
    with contextlib.suppress(FileNotFoundError):
        os.remove(filename)
