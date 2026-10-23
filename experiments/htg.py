#! /usr/bin/env python

"""Count the actions of the hard-to-ground (HTG) benchmark (Lauer et al. 2021).

Set HTG_BENCHMARKS_FLATTENED to the directory with one subdirectory per domain.
"""

import os

from common import build_experiment

SUITE = [
    "blocksworld-large-simple",
    *[
        f"childsnack-contents-parsize{size}-cham{cham}"
        for size in range(1, 5)
        for cham in (3, 5, 7)
    ],
    "genome-edit-distance",
    "genome-edit-distance-split",
    "logistics-large-simple",
    "organic-synthesis-alkene",
    "organic-synthesis-MIT",
    "organic-synthesis-original",
    "pipesworld-tankage-nosplit",
    "rovers-large-simple",
    *[
        f"visitall-multidimensional-{dim}-dim-visitall-{dist}-g{goals}"
        for dim in (3, 4, 5)
        for dist in ("CLOSE", "FAR")
        for goals in (1, 2, 3)
    ],
]

LOCAL_SUITE = [
    "genome-edit-distance:d-5-12.pddl",
    "pipesworld-tankage-nosplit:p01-net1-b6-g2-t50.pddl",
]

experiment = build_experiment(os.environ["HTG_BENCHMARKS_FLATTENED"], SUITE, LOCAL_SUITE)
experiment.run_steps()
