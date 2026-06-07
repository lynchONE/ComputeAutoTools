from __future__ import annotations

import argparse

from vast_autotools.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Vast.ai auto scanner and instance launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
