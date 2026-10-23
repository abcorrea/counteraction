import argparse
import sys


def parse_args():
    argparser = argparse.ArgumentParser(
        description="Print the Datalog program of the delete relaxation of a PDDL task."
    )
    argparser.add_argument("domain", help="path to domain pddl file")
    argparser.add_argument("task", help="path to task pddl file")
    argparser.add_argument(
        "--remove-action-predicates",
        dest="remove_action_predicates",
        action="store_true",
        help="remove action predicates from logic program",
    )
    argparser.add_argument(
        "--inequality-rules",
        dest="inequality_rules",
        action="store_true",
        help="add inequalities to rules",
    )
    return argparser.parse_args()


def copy_args_to_module(args):
    module_dict = sys.modules[__name__].__dict__
    for key, value in vars(args).items():
        module_dict[key] = value


def setup():
    args = parse_args()
    copy_args_to_module(args)


setup()
