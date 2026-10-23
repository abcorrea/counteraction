# Experiments

The experiments use [Downward Lab](https://lab.readthedocs.io). Install it with

```bash
uv sync --group experiments
```

## Running

The scripts run the configurations of the paper (`any`, `bound-1M`,
`bound-500K`, `greedy`) with a limit of 30 minutes and 3872 MiB per task. On
the Basel cluster (sciCORE), they submit the runs to the `infai_1` partition,
like the experiments in the paper. On any other machine, they run a small test
suite locally.

```bash
# Hard-to-ground benchmark (Lauer et al. 2021); one subdirectory per domain.
export HTG_BENCHMARKS_FLATTENED=/path/to/htg-domains-flattened
uv run --group experiments experiments/htg.py

# STRIPS domains of the IPC satisficing tracks, including both encodings of
# organic-synthesis. Needs https://github.com/aibasel/downward-benchmarks.
export DOWNWARD_BENCHMARKS=/path/to/downward-benchmarks
uv run --group experiments experiments/ipc.py
```

The scripts accept the usual Lab arguments, e.g., `htg.py build`, `htg.py
start`, `htg.py parse fetch`. The results end up in
`experiments/data/<script>-eval/properties`.

## Tables of the paper

```bash
uv run python experiments/report.py \
    experiments/results/2024-htg-properties.json.xz \
    experiments/data/htg-eval/properties
```

`results/2024-htg-properties.json.xz` holds the results of 2024: the baseline
CHH+ (Corrêa et al. 2023) and the counters before the bug fixes of 2026. Later
files override earlier ones, so the command above combines the CHH+ baseline
with the new counter results. The baseline FD (C++ reimplementation of Fast
Downward's grounder) is not part of these results.
