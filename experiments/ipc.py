#! /usr/bin/env python

"""Count the actions of the STRIPS domains of the IPCs (satisficing tracks).

Set DOWNWARD_BENCHMARKS to a checkout of
https://github.com/aibasel/downward-benchmarks. The suite includes both
encodings of organic-synthesis (IPC 2018), which we compare in the paper.
"""

import os
import sys

from common import build_experiment

BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
sys.path.insert(0, BENCHMARKS_DIR)
import suites as benchmark_suites  # noqa: E402

SUITE = benchmark_suites.suite_satisficing_strips()
LOCAL_SUITE = ["gripper:prob01.pddl", "organic-synthesis-split-sat18-strips:p01.pddl"]

experiment = build_experiment(BENCHMARKS_DIR, SUITE, LOCAL_SUITE)
experiment.run_steps()
