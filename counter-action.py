#!/usr/bin/env python3
"""Count the delete-relaxed reachable actions of a PDDL task without grounding it.

The tool works in two phases. First, it computes the relaxed reachable atoms
with a Datalog program that has no action predicates. Second, it counts the
groundings of each action schema that are applicable in these atoms.
"""

import logging
import os
import signal
import subprocess
import sys
import tempfile
import time

from counting import (
    BIN_DIR,
    PROCESSES,
    ROOT,
    ClingoCounter,
    D4Counter,
    count_actions,
    format_count,
    parse_action_schemas,
    remove_silently,
)
from utils import parse_arguments

TRANSLATOR = ROOT / "src" / "translate" / "pddl_to_prolog.py"

# Exit code if the number of actions is only a lower bound.
LOWER_BOUND_EXIT_CODE = 10

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="[%(asctime)s.%(msecs)03d] %(levelname)s ::: %(message)s",
    datefmt="%H:%M:%S",
)


def run_to_file(command, output_file, description):
    with open(output_file, "w") as output:
        process = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, text=True)
    # Log the messages of the tool, so that our stderr only contains errors.
    for line in process.stderr.splitlines():
        logging.info(line)
    returncode = process.returncode
    if returncode != 0:
        logging.error(f"{description} failed with exit code {returncode}.")
        sys.exit(1)


def translate(domain_file, instance_file, output_file, extra_options):
    command = [sys.executable, str(TRANSLATOR), domain_file, instance_file, *extra_options]
    run_to_file(command, output_file, "Translating the task")


def rewrite_with_lpopt(theory_file):
    """Rewrite the rules of the theory in place to make grounding cheaper."""
    directory = os.path.dirname(os.path.abspath(theory_file))
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
        temporary_file = temporary.name
    try:
        command = [str(BIN_DIR / "lpopt"), "-f", theory_file]
        run_to_file(command, temporary_file, "Rewriting the theory with lpopt")
        os.replace(temporary_file, theory_file)
    finally:
        remove_silently(temporary_file)


def compute_reachable_atoms(theory_file, model_file):
    start_time = time.time()
    with open(model_file, "w") as output:
        command = [str(BIN_DIR / "gringo"), theory_file, "--output", "text"]
        returncode = subprocess.run(command, stdout=output, stderr=subprocess.DEVNULL).returncode
    if returncode != 0:
        logging.error(f"Something went wrong with gringo! Gringo's exit code: {returncode}.")
        logging.info("Gringo finished correctly: 0")
        sys.exit(1)
    logging.info("Gringo finished correctly: 1")
    logging.info(f"Total time (in seconds): {time.time() - start_time:0.5f}s")
    with open(model_file) as f:
        num_atoms = sum(1 for _ in f)
    logging.info(f"Number of atoms (not actions): {num_atoms}")


def stop_on_signal(signum, frame):
    PROCESSES.terminate_all()
    sys.exit(128 + signum)


def main():
    start_time = time.time()
    args = parse_arguments()
    for filename in (args.domain, args.instance):
        if not os.path.isfile(filename):
            sys.exit(f"Error: File {filename} does not exist.")

    signal.signal(signal.SIGTERM, stop_on_signal)
    signal.signal(signal.SIGINT, stop_on_signal)

    output_files = [args.model_output, args.theory_output, args.theory_with_actions_output]
    try:
        translate(args.domain, args.instance, args.theory_output, ["--remove-action-predicates"])
        logging.info(f"ASP model being copied to {args.theory_output}")

        options = ["--inequality-rules"] if args.inequality_rules else []
        translate(args.domain, args.instance, args.theory_with_actions_output, options)
        logging.info(f"ASP model *with actions* being copied to {args.theory_with_actions_output}")

        rewrite_with_lpopt(args.theory_output)
        compute_reachable_atoms(args.theory_output, args.model_output)

        with open(args.theory_with_actions_output) as f:
            schemas = parse_action_schemas(f)
        if args.greedy:
            counter = D4Counter()
        else:
            counter = ClingoCounter(bound=args.bound, show_actions=args.output)
        total, exact = count_actions(args.model_output, schemas, counter)
        logging.info(f"# of actions: {format_count(total, exact)}")
    finally:
        if args.remove_files:
            logging.info("Removing intermediate files.")
            for filename in output_files:
                remove_silently(filename)

    logging.info(f"Overall time (in seconds): {time.time() - start_time:0.5f}s")
    logging.info("Done!")
    if not exact:
        sys.exit(LOWER_BOUND_EXIT_CODE)


if __name__ == "__main__":
    main()
