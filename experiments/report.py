#! /usr/bin/env python

"""Compute the tables and numbers of the paper from experiment results.

Usage:
    report.py PROPERTIES [PROPERTIES ...]

Each PROPERTIES file is a "properties" file of a Lab experiment (plain JSON, or
compressed with xz). The 2024 results in results/2024-htg-properties.json.xz
contain the baseline CHH+ and the counters before the bug fixes. Results of
newer runs override older results of the same algorithm and task.
"""

import argparse
import collections
import json
import lzma
import math
import statistics

TIME_LIMIT = 1800

# Algorithm names of the 2024 experiments.
OLD_NAMES = {
    "baseline": "CHH+",
    "baseline-LPCNT_OPT_BIN_PATH": "any",
    "baseline-LPCNT_1M_BIN_PATH": "bound-1M",
    "baseline-LPCNT_500K_BIN_PATH": "bound-500K",
    "baseline-LPCNT_BIN_PATH": "greedy",
}
ALGORITHMS = ["CHH+", "any", "bound-1M", "bound-500K", "greedy"]
COUNTERS = ALGORITHMS[1:]

# Domains of the HTG benchmark grouped as in the paper.
FAMILIES = [
    ("blocksworld", "blocksworld-large"),
    ("childsnack", "childsnacks-large"),
    ("genome-edit-distance", "genome-edit-dist."),
    ("logistics", "logistics-large"),
    ("organic-synthesis", "organic-synthesis"),
    ("pipesworld", "pipesworld-tankage"),
    ("rovers", "rovers-large"),
    ("visitall", "visitall-multidim."),
]


def family(domain):
    for prefix, name in FAMILIES:
        if domain.startswith(prefix):
            return name
    return domain


def load_properties(filename):
    opener = lzma.open if filename.endswith(".xz") else open
    with opener(filename, "rt") as f:
        return json.load(f)


def parse_count(value):
    """Return the count of a run, or None if it is missing or a lower bound of a baseline."""
    if isinstance(value, str):
        return int(value) if value.isdigit() else None
    return value


def run_time(props):
    if "total_time" in props and "newground_time" not in props:
        return props["total_time"]
    # 2024 experiments: grounding and counting were separate commands.
    grounding, counting = props.get("gringo_time"), props.get("newground_time")
    if grounding is None or counting is None:
        return None
    return grounding + counting


def load_runs(filenames):
    """Map (domain, problem) to {algorithm: (count, time)} for solved runs."""
    runs = collections.defaultdict(dict)
    for filename in filenames:
        for props in load_properties(filename).values():
            algorithm = OLD_NAMES.get(props["algorithm"], props["algorithm"])
            if algorithm not in ALGORITHMS:
                continue
            count = parse_count(props.get("counter_actions"))
            time = run_time(props)
            solved = count is not None and time is not None and time <= TIME_LIMIT
            key = (props["domain"], props["problem"])
            runs[key][algorithm] = (count, time) if solved else (None, None)
    return runs


def geometric_mean(values):
    return math.exp(statistics.fmean(math.log(max(value, 0.01)) for value in values))


def coverage(runs):
    print("Table 1: solved tasks")
    for algorithm in ALGORITHMS:
        solved = sum(1 for task in runs.values() if task.get(algorithm, (None,))[0] is not None)
        print(f"  {algorithm:12} {solved}")


def time_per_domain(runs):
    algorithms = ["CHH+", "any", "bound-1M", "greedy"]
    common = {
        key: task
        for key, task in runs.items()
        if all(task.get(algorithm, (None, None))[1] is not None for algorithm in algorithms)
    }
    print("\nTable 2: geometric mean of the time over tasks solved by all methods")
    by_family = collections.defaultdict(list)
    for (domain, _), task in common.items():
        by_family[family(domain)].append(task)
    domain_means = collections.defaultdict(list)
    for name, tasks in sorted(by_family.items()):
        means = [geometric_mean([task[a][1] for task in tasks]) for a in algorithms]
        for algorithm, mean in zip(algorithms, means, strict=True):
            domain_means[algorithm].append(mean)
        print(f"  {name:20} ({len(tasks):3}) {' '.join(f'{mean:7.1f}' for mean in means)}")
    # As in the paper, the last row is the geometric mean of the domain means.
    means = [geometric_mean(domain_means[algorithm]) for algorithm in algorithms]
    print(f"  {'geometric mean':20} ({len(common):3}) {' '.join(f'{mean:7.1f}' for mean in means)}")


def anytime(runs):
    print("\nTable 3: solved tasks within the time limit")
    limits = [10, 60, 300, 1800]
    for algorithm in ALGORITHMS:
        times = [task[algorithm][1] for task in runs.values() if algorithm in task]
        solved = [time for time in times if time is not None]
        counts = [sum(1 for time in solved if time <= limit) for limit in limits]
        print(f"  {algorithm:12} {counts}")


def accuracy(runs):
    print("\nAccuracy on the tasks that CHH+ solves")
    reference = {
        key: task for key, task in runs.items() if task.get("CHH+", (None,))[0] is not None
    }
    for algorithm in COUNTERS:
        exact = higher = 0
        inexact_counts = []
        for task in reference.values():
            count = task.get(algorithm, (None,))[0]
            if count is None:
                continue
            true_count = task["CHH+"][0]
            if count == true_count:
                exact += 1
            else:
                inexact_counts.append(true_count)
                higher += count > true_count
        smallest = min(inexact_counts) if inexact_counts else None
        print(
            f"  {algorithm:12} exact {exact}/{len(reference)}, above the exact count "
            f"{higher}, smallest exact count among inexact tasks {smallest}"
        )


def bounds_per_family(runs):
    print("\nTasks per domain where bound-500K counts fewer actions than bound-1M")
    by_family = collections.Counter()
    for (domain, _), task in runs.items():
        small, large = task.get("bound-500K", (None,))[0], task.get("bound-1M", (None,))[0]
        if small is not None and large is not None and small < large:
            by_family[family(domain)] += 1
    for name, number in sorted(by_family.items()):
        print(f"  {name:20} {number}")


def compare_encodings(runs, original, split):
    pairs = []
    for (domain, problem), task in runs.items():
        if domain == original:
            other = runs.get((split, problem), {})
            count, split_count = task.get("any", (None,))[0], other.get("any", (None,))[0]
            if count and split_count:
                pairs.append(count / split_count)
    if pairs:
        print(
            f"\n{original} vs. {split}: {len(pairs)} pairs, split smaller in "
            f"{sum(1 for ratio in pairs if ratio > 1)}, ratio min {min(pairs):.1f}, "
            f"median {statistics.median(pairs):.1f}, max {max(pairs):.1f}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("properties", nargs="+", help="properties files of Lab experiments")
    args = parser.parse_args()
    runs = load_runs(args.properties)
    coverage(runs)
    time_per_domain(runs)
    anytime(runs)
    accuracy(runs)
    bounds_per_family(runs)
    compare_encodings(runs, "genome-edit-distance", "genome-edit-distance-split")
    compare_encodings(
        runs, "organic-synthesis-sat18-strips", "organic-synthesis-split-sat18-strips"
    )


if __name__ == "__main__":
    main()
