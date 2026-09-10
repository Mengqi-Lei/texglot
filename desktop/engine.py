"""Frozen backend entry point; also exposes the full TeXGlot CLI."""

import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--engine-server":
        del sys.argv[1]
        from app.server import main as serve

        serve()
    else:
        from app.cli import main as cli

        cli()


if __name__ == "__main__":
    main()
