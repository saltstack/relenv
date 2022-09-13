import sys
import argparse
from argparse import RawTextHelpFormatter
from . import build
from . import toolchain
from . import create
from . import fetch


class ArgParser(argparse.ArgumentParser):
    """
    Wrap default ArgParser implementation adding the ability to supress
    a positional argument from the example cammand output by the
    print_help method.
    """

    def __init__(self, *args, **kwargs):
        if 'formatter_class' not in kwargs:
            kwargs['formatter_class'] = RawTextHelpFormatter
        super(ArgParser, self).__init__(*args, **kwargs)
        self._errors = []

    def error(self, err):
        self._errors.append(err)

    def supress_positional(self, dest):
        for i in self._positionals._group_actions:
            if i.dest == dest:
                i.help = argparse.SUPPRESS


argparser = ArgParser(
    description='Mayflower',
    add_help=False,
)


def list_commands(argparser=argparser, show_help=False):
    argparser.descrption = 'List available auth commands'
    ns, argv = argparser.parse_known_args()
    if ns.help:
        argparser.print_help()
        sys.exit(0)
    print("Available commands are:")
    for i in COMMANDS:
        print("  " + i)

COMMANDS = {
  "list": list_commands,
  "build" : build.main,
  "toolchain" : toolchain.main,
  "create" : create.main,
  "fetch" : fetch.main,
}

def main():
    argparser.add_argument('command', help='Run this command')
    argparser.add_argument('--help', '-h', action='store_true')
    argparser.epilog = "Run `mayflower list` to see a list of available commands."
    ns, argv = argparser.parse_known_args()
    if ns.command and ns.command in COMMANDS:
        argparser.supress_positional('command')
        argparser.prog = '{} {}'.format(argparser.prog, ns.command)
        argparser.epilog = ''
        argparser.description = ''
        nextmain = COMMANDS[ns.command]
        nextmain(argparser)
    else:
        argparser.print_help()
        sys.exit(0)

if __name__ == "__main__":
   main()

