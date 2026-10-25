# CounterAction

CounterAction counts the actions of the propositional task that a grounder would
produce from a PDDL task, without grounding it. Like Fast Downward's grounder,
it counts the actions that are reachable in the delete relaxation of the task.
If counting takes too long, it reports a lower bound.

CounterAction works in two phases. First, it computes the relaxed reachable
atoms with a Datalog program that has no action predicates: it splits long
rules with a size-aware decomposition and grounds the program with `gringo`. Second, for each action schema, it counts the groundings that are
applicable in these atoms: by enumerating them with `clingo`, with the model
counter `d4`, or by variable elimination (`--elimination`).

## Installation

CounterAction needs Linux on x86-64 and [uv](https://docs.astral.sh/uv/). All
other binaries (`clingo`, `gringo`, `lpopt`, `d4`, ...) are in `bin/`, and the
Python code has no third-party dependencies.

```bash
uv sync
```

## Usage

```bash
uv run counter-action.py -i /path/to/problem.pddl
```

The domain file is found automatically if it follows the usual naming
conventions (e.g., `domain.pddl` in the same directory); otherwise, pass it
with `--domain`. You can also run the tool from another directory with
`uv run --project /path/to/counteraction /path/to/counteraction/counter-action.py ...`.

The tool prints the count of each action schema and the total:

```
[12:00:00.000] INFO ::: # of actions: 36
```

A trailing `+` (e.g., `# of actions: 1000000+`) means that the number is a
lower bound. In this case, the exit code is 10.

### Options

- `--domain`: PDDL domain file (otherwise, the domain file is inferred).
- `-b`, `--bound`: stop counting the actions of a schema after this many
  actions. A bound of 0 (default) counts all actions.
- `--greedy`: count with the model counter `d4` instead of enumerating. This
  is much faster on some domains, but gives no count for a schema that `d4`
  cannot finish. Requires bound 0.
- `--elimination`: count exactly by variable elimination over the relaxed
  reachable atoms. The groundings of a schema are the answers of a conjunctive
  query, which we count without enumerating them; the time is exponential only
  in the width of the precondition hypergraph. Requires bound 0.
- `--lpopt`: split the rules with `lpopt` instead of the size-aware
  decomposition (as in the experiments of 2024).
- `--inequality-rules`: use inequality preconditions such as
  `(not (= ?x ?y))` when counting.
- `-o`, `--output`: print the counted actions (not with `--greedy`).
- `-m`, `--model-output`, `-t`, `--theory-output`,
  `--theory-with-actions-output`: names of the intermediate files.
- `-r`, `--remove-files`: remove the intermediate files at the end.
- `-c`, `--choices`: deprecated; has no effect.

Counting a single action schema is limited to 6 minutes and 4 GiB (see
`SCHEMA_TIME_LIMIT` and `SCHEMA_MEMORY_LIMIT` in `counting.py`). If a schema
reaches a limit, CounterAction moves on to the next one and reports a lower
bound.

## Development

```bash
uv sync                      # installs ruff, pytest, pre-commit, and Lab
uv run pre-commit install    # runs ruff on every commit
uv run pytest                # runs the tests
uv run ruff check . && uv run ruff format --check .
```

The directory `src/translate` contains the PDDL parser and the Datalog encoding,
adapted from the translator of [Fast Downward](https://www.fast-downward.org).

## Experiments

See [experiments/README.md](experiments/README.md).
