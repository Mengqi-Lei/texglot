"""Single-owner local service, shared by GUI and CLI clients."""

import argparse
import os
import socket
import sys
import threading

import uvicorn

from .config import DATA
from .platforms import WINDOWS, configure_stdio, service_lock


def run(port: int, *, parent_pipe: bool = False):
    # Bind before importing JobManager: a losing concurrent launch must not
    # load or alter task state owned by the running service.
    with service_lock(DATA / "service.lock"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            option = socket.SO_EXCLUSIVEADDRUSE if WINDOWS else socket.SO_REUSEADDR
            sock.setsockopt(socket.SOL_SOCKET, option, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(128)
            config = uvicorn.Config(
                "app.main:app",
                log_level="warning",
                timeout_graceful_shutdown=10,
                loop="asyncio",
            )
            server = uvicorn.Server(config)
            if parent_pipe:

                def watch_parent():
                    # Only the owning desktop process holds this pipe open.
                    # EOF also handles an unexpected desktop process exit.
                    try:
                        while sys.stdin.buffer.read(1024):
                            pass
                    finally:
                        server.should_exit = True

                threading.Thread(target=watch_parent, daemon=True).start()
            server.run(sockets=[sock])


def main():
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pipe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--port",
        type=int,
        default=int(
            os.environ.get("TEXGLOT_PORT", os.environ.get("MOYI_PORT", "8765"))
        ),
    )
    args = parser.parse_args()
    run(args.port, parent_pipe=args.parent_pipe)


if __name__ == "__main__":
    main()
