import re
import subprocess
import sys
from pathlib import Path

import pytest

import counting
from counting import Atom, counting_program, parse_action_schemas, parse_atoms

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data"
TASKS = ["gripper", "constants", "inequality", "conditional"]


def test_parse_atoms():
    atoms = parse_atoms("p(Var_x,c),handempty,Var_x!=Var_y,q(Var_y)")
    assert atoms == [
        Atom("p", ("Var_x", "c")),
        Atom("handempty", ()),
        Atom("!=", ("Var_x", "Var_y"), inequality=True),
        Atom("q", ("Var_y",)),
    ]


def test_parse_action_schemas():
    theory = [
        "at(a).\n",
        "action_go(Var_x) :- pddl_type_t(Var_x),at(Var_x),ready.\n",
        "at(Var_x) :- action_go(Var_x).\n",
        "action_start :- go.\n",
        "action_reset.\n",
    ]
    go, start, reset = parse_action_schemas(theory)
    assert go.name == "action_go"
    assert go.parameters == ("Var_x",)
    assert [str(atom) for atom in go.preconditions] == ["pddl_type_t(Var_x)", "at(Var_x)", "ready"]
    assert start.name == "action_start"
    assert start.parameters == ()
    assert reset.name == "action_reset"
    assert reset.preconditions == []


def test_counting_program_checks_constants_and_ground_atoms():
    (schema,) = parse_action_schemas(
        [
            "action_a(Var_x,Var_y) :- pddl_type_t(Var_x),pddl_type_t(Var_y),"
            "link(Var_x,Var_y,depot),at(pkg,depot),ready,Var_x!=Var_y.\n"
        ]
    )
    program = counting_program(schema)
    assert ":- not link(Var_x,Var_y,depot), g_Var_x(Var_x), g_Var_y(Var_y)." in program
    assert ":- not at(pkg,depot)." in program
    assert ":- not ready." in program
    assert ":- Var_x=Var_y, g_Var_x(Var_x), g_Var_y(Var_y)." in program
    assert "g_depot" not in program


def run_translator(task, *options):
    command = [
        sys.executable,
        str(ROOT / "src" / "translate" / "pddl_to_prolog.py"),
        str(DATA / task / "domain.pddl"),
        str(DATA / task / "problem.pddl"),
        *options,
    ]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def reference_count(task, tmp_path, inequality_rules=False):
    """Count the actions in the canonical model of the program with action predicates."""
    theory = tmp_path / "reference.lp"
    theory.write_text(run_translator(task, *(["--inequality-rules"] if inequality_rules else [])))
    command = [str(ROOT / "bin" / "gringo"), "--output", "text", str(theory)]
    model = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    return len({line for line in model.splitlines() if line.startswith("action_")})


def run_counter(task, tmp_path, *options):
    command = [
        sys.executable,
        str(ROOT / "counter-action.py"),
        "-i",
        str(DATA / task / "problem.pddl"),
        "-m",
        str(tmp_path / "output.model"),
        "-t",
        str(tmp_path / "output.theory"),
        "--theory-with-actions-output",
        str(tmp_path / "output-with-actions.theory"),
        *options,
    ]
    result = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path)
    match = re.search(r"# of actions: (\d+)(\+?)$", result.stdout, re.MULTILINE)
    assert match, result.stdout + result.stderr
    return int(match.group(1)), match.group(2) != "+", result


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("options", [[], ["--bound", "1000"], ["--greedy"], ["--elimination"]])
def test_count_matches_reference(task, options, tmp_path):
    count, exact, result = run_counter(task, tmp_path, *options)
    assert exact
    assert result.returncode == 0
    assert count == reference_count(task, tmp_path)


@pytest.mark.parametrize("options", [[], ["--greedy"], ["--elimination"]])
def test_inequality_rules(options, tmp_path):
    count, exact, _ = run_counter("inequality", tmp_path, "--inequality-rules", *options)
    assert exact
    assert count == reference_count("inequality", tmp_path, inequality_rules=True)


def test_known_counts(tmp_path):
    assert reference_count("gripper", tmp_path) == 36
    # move: 2, load: 0, unload: 0, start: 1
    assert reference_count("constants", tmp_path) == 3
    # step: 3, self: 3
    assert reference_count("inequality", tmp_path) == 6
    # mark: 2, use: 2
    assert reference_count("conditional", tmp_path) == 4


def test_bound_gives_lower_bound(tmp_path):
    count, exact, result = run_counter("gripper", tmp_path, "--bound", "1")
    assert not exact
    assert result.returncode == 10
    assert count == 3  # One action per schema.


def test_output_prints_actions(tmp_path):
    _, _, result = run_counter("constants", tmp_path, "--output")
    assert "action_move(l1,l2)" in result.stdout
    assert "action_move(l2,l1)" in result.stdout


def test_remove_files(tmp_path):
    run_counter("gripper", tmp_path, "--remove-files")
    assert not list(tmp_path.iterdir())


def test_time_limit_gives_lower_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(counting, "SCHEMA_TIME_LIMIT", 1)
    model = tmp_path / "model.lp"
    model.write_text("".join(f"d({i}).\n" for i in range(30)))
    variables = [f"Var_{i}" for i in range(6)]
    body = ",".join(f"d({v})" for v in variables)
    (schema,) = parse_action_schemas([f"action_a({','.join(variables)}) :- {body}.\n"])
    result = counting.ClingoCounter().count(model, schema, counting_program(schema))
    assert not result.exact
    assert 0 < result.count < 30**6


def test_decomposition_avoids_large_auxiliary_atoms():
    from decompose import decompose

    program = [
        "truck(t1).\n",
        "city(c1).\n",
        *[f"location(l{i}).\n" for i in range(10)],
        "at(Var_t,Var_to) :- truck(Var_t),location(Var_to),at(Var_t,Var_from),"
        "location(Var_from),in_city(Var_from,Var_c),in_city(Var_to,Var_c),city(Var_c).\n",
    ]
    rules = [line for line in decompose(program) if ":-" in line]
    # Eliminate Var_from first: an atom over (Var_c, Var_t), not over pairs of locations.
    assert rules[0].startswith("aux__0(Var_c,Var_t) :- ")
    # No atom that copies the head.
    assert len(rules) == 2


def test_lpopt_option(tmp_path):
    count, exact, _ = run_counter("gripper", tmp_path, "--lpopt")
    assert exact
    assert count == 36
