"""Command line: `python -m scripts.fake_bom serve|apply|list`."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import scenarios
from .server import FakeBom

DEFAULT_ROOT = Path("config/fake-bom")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.fake_bom", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list scenario names")
    for name, help_text in (
        ("serve", "reset to a scenario and serve it until Ctrl-C"),
        ("apply", "reset the directory to a scenario while a server is running"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("scenario", choices=scenarios.names())
        command.add_argument("--root", type=Path, default=DEFAULT_ROOT)
        command.add_argument(
            "--spatial-dir", type=Path, help="directory of IDM000NN.zip files to serve"
        )
        if name == "serve":
            command.add_argument("--port", type=int, default=2121)
    args = parser.parse_args(argv)

    if args.command == "list":
        print("\n".join(scenarios.names()))
        return 0

    scenarios.apply(args.scenario, args.root, args.spatial_dir)
    if args.command == "apply":
        print(f"{args.root}: {args.scenario}")
        return 0
    if not scenarios.listens(args.scenario):
        print(f"{args.scenario}: not listening on port {args.port}; Ctrl-C does nothing here")
        return 0
    server = FakeBom(args.root, args.port)
    print(f"{args.scenario}: serving {args.root} on {server.address}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
