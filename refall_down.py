#!/usr/bin/env python3
"""Convenience wrapper for `python3 -m ref_all_executor.cli down`."""

import sys

from ref_all_executor.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["down", *sys.argv[1:]]))
