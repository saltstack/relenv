"""
The entrypoint into mayflower
"""

from argparse import ArgumentParser

from . import build, create, fetch, toolchain


def setup_cli():
    """
    Build the argparser with its subparsers.

    The modules with commands to add must specify a setup_parser function
    that takes in the subparsers object from `argparse.add_subparsers()`

    :return: The fully setup argument parser
    :rtype: ``argparse.ArgumentParser``
    """
    argparser = ArgumentParser(
        description="Mayflower",
    )
    subparsers = argparser.add_subparsers()

    modules_to_setup = [
        build,
        toolchain,
        create,
        fetch,
    ]
    for mod in modules_to_setup:
        mod.setup_parser(subparsers)

    return argparser


def main():
    """
    Run the mayflower cli and disbatch to subcommands
    """
    parser = setup_cli()
    args = parser.parse_args()
    try:
        args.func(args)
    except AttributeError:
        parser.exit(1, "No subcommand given...")


if __name__ == "__main__":
    main()
