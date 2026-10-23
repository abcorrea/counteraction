"""Shared setup of the CounterAction experiments with Downward Lab."""

import os
import platform
import sys
from pathlib import Path

from downward import suites
from lab.environments import BaselSlurmEnvironment, LocalEnvironment
from lab.experiment import Experiment
from parser import make_parser

REPO = Path(__file__).resolve().parent.parent
COUNTER = REPO / "counter-action.py"

# Limits of the paper: 30 minutes and 4 GiB per task.
TIME_LIMIT = 1800
MEMORY_LIMIT = 3872

CONFIGS = {
    "any": [],
    "bound-1M": ["--bound", "1000000"],
    "bound-500K": ["--bound", "500000"],
    "greedy": ["--greedy"],
}


def running_on_cluster():
    node = platform.node()
    return node.endswith((".scicore.unibas.ch", ".cluster.bc2.ch"))


def build_experiment(benchmarks_dir, suite, local_suite, configs=CONFIGS):
    """Create an experiment that runs each configuration on each task.

    On the Basel cluster, the experiment uses the full suite on the infai_1
    partition (AMD EPYC 7742), like the experiments of the paper. Elsewhere, it
    runs the small local suite to test the setup.
    """
    if running_on_cluster():
        environment = BaselSlurmEnvironment(
            partition="infai_1", email=os.environ.get("EMAIL"), export=["PATH"]
        )
    else:
        environment = LocalEnvironment(processes=2)
        suite = local_suite

    experiment = Experiment(environment=environment)
    experiment.add_parser(make_parser())
    for config, options in configs.items():
        for task in suites.build_suite(benchmarks_dir, suite):
            run = experiment.add_run()
            run.add_resource("domain", task.domain_file, symlink=True)
            run.add_resource("problem", task.problem_file, symlink=True)
            # sys.executable is the Python of the uv environment that runs
            # this script. CounterAction itself has no dependencies.
            command = [sys.executable, str(COUNTER), "--domain", "{domain}", "-i", "{problem}"]
            run.add_command(
                "counter",
                [*command, "--remove-files", *options],
                time_limit=TIME_LIMIT,
                memory_limit=MEMORY_LIMIT,
            )
            run.set_property("algorithm", config)
            run.set_property("domain", task.domain)
            run.set_property("problem", task.problem)
            run.set_property("id", [config, task.domain, task.problem])

    experiment.add_step("build", experiment.build)
    experiment.add_step("start", experiment.start_runs)
    experiment.add_step("parse", experiment.parse)
    experiment.add_fetcher(name="fetch")
    return experiment
