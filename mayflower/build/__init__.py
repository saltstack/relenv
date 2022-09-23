import sys


def main(argparse):
    if sys.platform == "darwin":
        from .darwin import main
        main(argparse)
    elif sys.platform == "linux":
        from .linux import main
        main(argparse)
    else:
        print("Unsupported platform")
        sys.exit(1)
