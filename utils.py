import argparse
import os


def find_domain_filename(task_filename):
    """Find the domain file of a task using the usual naming conventions."""
    dirname, basename = os.path.split(task_filename)

    domain_basenames = [
        "domain.pddl",
        basename[:3] + "-domain.pddl",
        "domain_" + basename,
        "domain-" + basename,
    ]

    for domain_basename in domain_basenames:
        domain_filename = os.path.join(dirname, domain_basename)
        if os.path.exists(domain_filename):
            return domain_filename
    return None


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Count the number of actions of a full grounding without computing it."
    )
    parser.add_argument("-i", "--instance", required=True, help="Path to the PDDL problem file.")
    parser.add_argument(
        "--domain",
        default=None,
        help="Path to the PDDL domain file. If omitted, the domain file is "
        "deduced from the problem file name.",
    )
    parser.add_argument("-m", "--model-output", default="output.model", help="Model output file.")
    parser.add_argument(
        "-t", "--theory-output", default="output.theory", help="Theory output file."
    )
    parser.add_argument(
        "--theory-with-actions-output",
        default="output-with-actions.theory",
        help="Output file for the theory with action predicates.",
    )
    parser.add_argument(
        "-r", "--remove-files", action="store_true", help="Remove model and theory files."
    )
    parser.add_argument(
        "--inequality-rules",
        action="store_true",
        help="Use inequality preconditions when counting actions.",
    )
    parser.add_argument(
        "-c",
        "--choices",
        action="store_true",
        help="Deprecated. Has no effect: the counting programs always use choice rules.",
    )
    parser.add_argument(
        "-o",
        "--output",
        action="store_true",
        help="Print the counted actions (only without --greedy).",
    )
    parser.add_argument(
        "-b",
        "--bound",
        type=int,
        default=0,
        help="Stop counting the actions of an action schema after this many "
        "actions. A bound of 0 counts all actions.",
    )
    parser.add_argument(
        "--greedy",
        action="store_true",
        help="Count with the model counter d4. Faster on some tasks, but "
        "returns no count for schemas it cannot finish. Requires bound 0.",
    )
    parser.add_argument(
        "--lpopt",
        action="store_true",
        help="Split the rules of the Datalog program with lpopt (as in the experiments "
        "of 2024) instead of the size-aware decomposition.",
    )
    parser.add_argument(
        "--elimination",
        action="store_true",
        help="Count exactly by variable elimination over the relaxed reachable "
        "atoms, without enumerating actions. Requires bound 0.",
    )

    args = parser.parse_args(argv)
    if args.bound < 0:
        parser.error("The bound must be non-negative.")
    if args.greedy and args.bound != 0:
        parser.error("Flag '--greedy' only works with bound 0 (i.e., no bound).")
    if args.elimination and (args.greedy or args.bound != 0 or args.output):
        parser.error("Flag '--elimination' does not work with --greedy, --bound, or --output.")
    if args.greedy and args.output:
        parser.error("Flag '--output' does not work with '--greedy'.")
    if args.domain is None:
        args.domain = find_domain_filename(args.instance)
        if args.domain is None:
            parser.error(f'Could not find a domain file for problem file "{args.instance}".')
    return args
