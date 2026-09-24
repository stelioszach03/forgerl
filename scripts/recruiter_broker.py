#!/usr/bin/env python3
"""Run the optional private broker on a Unix socket only; disabled by default."""

import argparse
import os
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("FORGERL_RECRUITER_WORKER_ENABLED", "0") != "1":
        parser.error(
            "Private live broker is disabled; operator review is required before enabling"
        )
    if (
        not args.socket.is_absolute()
        or args.socket.exists()
        or args.socket.is_symlink()
    ):
        parser.error(
            "A new absolute Unix socket path is required; existing listeners are never replaced"
        )
    args.socket.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(args.socket))
        args.socket.chmod(0o660)
        listener.listen(32)
        import uvicorn

        uvicorn.run(
            "forgerl.recruiter.broker:app",
            fd=listener.fileno(),
            proxy_headers=False,
            workers=1,
            access_log=False,
            limit_concurrency=24,
            timeout_keep_alive=3,
        )
    finally:
        listener.close()
        if args.socket.is_socket():
            args.socket.unlink()


if __name__ == "__main__":
    main()
