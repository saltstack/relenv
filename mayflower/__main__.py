import argparse

from . import build, create, fetch, toolchain


class ArgParser(argparse.ArgumentParser):
    """
    Wrap default ArgParser implementation adding the ability to suppress
    a positional argument from the example command output by the
    print_help method.
    """

    def __init__(self, *args, **kwargs):
        # if "formatter_class" not in kwargs:
        #     kwargs["formatter_class"] = RawTextHelpFormatter
        super(ArgParser, self).__init__(*args, **kwargs)
        self._errors = []

    def error(self, err):
        self._errors.append(err)


# Build the argparser with its subparsers
argparser = ArgParser(
    description="Mayflower",
)
subparsers = argparser.add_subparsers()

modules_to_setup = [build, toolchain, create, fetch]
for mod in modules_to_setup:
    mod.setup_parser(subparsers)


def main():
    mayflower_args, argv = argparser.parse_known_args()
    mayflower_args.func(mayflower_args)


if __name__ == "__main__":
    main()
