import argparse

from . import build, create, fetch, toolchain


class ArgParser(argparse.ArgumentParser):
    """
    Wrap default ArgParser implementation adding the ability to suppress
    a positional argument from the example command output by the
    print_help method.
    """

    def __init__(self, *args, **kwargs):
        super(ArgParser, self).__init__(*args, **kwargs)
        self._errors = []

    def error(self, err):
        self._errors.append(err)


def setup_cli():
    """
    Build the argparser with its subparsers
    """
    argparser = ArgParser(
        description="Mayflower",
    )
    subparsers = argparser.add_subparsers()

    modules_to_setup = [build, toolchain, create, fetch]
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
