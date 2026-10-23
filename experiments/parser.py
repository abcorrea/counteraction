"""Parser for the output of counter-action.py."""

import re

from lab.parser import Parser


def parse_count(content, props):
    matches = re.findall(r"# of actions: (\d+)(\+?)$", content, re.MULTILINE)
    if matches:
        count, plus = matches[-1]
        props["counter_actions"] = int(count)
        props["count_exact"] = plus == ""


def make_parser():
    parser = Parser()
    parser.add_pattern("atoms", r"Number of atoms \(not actions\): (\d+)", type=int)
    parser.add_pattern("model_time", r"Total time \(in seconds\): (.+)s", type=float)
    # Lab measures the wall-clock time only to the second, so we use the time
    # that CounterAction reports.
    parser.add_pattern("total_time", r"Overall time \(in seconds\): (.+)s", type=float)
    parser.add_pattern(
        "wall_clock_time", r"counter wall-clock time: (.+)s", file="driver.log", type=float
    )
    parser.add_function(parse_count)
    return parser
