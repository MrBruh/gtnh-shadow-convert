"""``gtnh-shadow-convert``: the command line.

::

    gtnh-shadow-convert PLAN.gtnh --data DATA.bin [-o OUT.json] [--pack-version V]
    gtnh-shadow-convert fetch-data [--url URL --sha256 HEX] [--cache DIR]

The first writes the converted plan as JSON (to stdout, or to ``-o``); the second downloads the
calculator's ``data.bin`` into the user cache and prints where it put it. Warnings go to stderr. A
plan that does not convert exits 2 with the reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .emit import convert, version
from .errors import ConversionError
from .fetch import DEFAULT_SHA256, fetch_data

_EXIT_FAILED = 2


def _convert_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gtnh-shadow-convert",
        description=(
            "Convert a ShadowTheAge GT:NH calculator plan (.gtnh) into gtnh-factory-flow plan JSON. "
            "Run 'gtnh-shadow-convert fetch-data' first to download the recipe data it needs."
        ),
    )
    parser.add_argument("plan", type=Path, help="the .gtnh file the calculator saved")
    parser.add_argument(
        "--data", type=Path, required=True, help="the calculator's data.bin (see fetch-data)"
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="write the plan JSON here instead of to stdout"
    )
    parser.add_argument(
        "--pack-version",
        help="the GTNH pack the data.bin came from, needed only for a file the converter does not know",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version()}")
    return parser


def _fetch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gtnh-shadow-convert fetch-data",
        description="Download the calculator's data.bin into the user cache and print its path.",
    )
    parser.add_argument("--url", help="download from here instead of the pinned gtnh-data commit")
    parser.add_argument(
        "--sha256",
        default=None,
        help=(
            "the file's expected sha256: by default the pinned file's, or no check with --url; "
            "'none' skips the check"
        ),
    )
    parser.add_argument("--cache", type=Path, help="cache directory (default: the user cache)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args[:1] == ["fetch-data"]:
            return _fetch(_fetch_parser().parse_args(args[1:]))
        return _convert(_convert_parser().parse_args(args))
    except ConversionError as error:
        print(f"gtnh-shadow-convert: {error}", file=sys.stderr)
        return _EXIT_FAILED
    except OSError as error:
        print(f"gtnh-shadow-convert: {error}", file=sys.stderr)
        return _EXIT_FAILED


def _convert(args: argparse.Namespace) -> int:
    plan = convert(args.plan, args.data, pack_version=args.pack_version)
    text = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


def _fetch(args: argparse.Namespace) -> int:
    if args.sha256 is None:
        sha256: str | None = None if args.url else DEFAULT_SHA256
    else:
        sha256 = None if args.sha256.lower() == "none" else args.sha256
    print(fetch_data(url=args.url, sha256=sha256, cache=args.cache))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
