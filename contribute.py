#!/usr/bin/env python3
"""One-command, opt-in contribution to the community anchor dataset.

    python contribute.py            # preview + (after a one-time token setup) open a PR
    python contribute.py --dry-run  # preview only; upload nothing

Thin wrapper over ``python -m appscope.federation.contribute`` that:
  * guides a one-time Hugging Face token setup the first time (see
    ``appscope/federation/token_bootstrap.py``), then never asks again, and
  * remembers your contributor name (in ``.contributor``) so you never retype it.

Nothing is ever uploaded without your token and an explicit run — no background
sync. Pass ``--contributor NAME`` once to set/replace the remembered name.
"""
from __future__ import annotations

import pathlib
import sys

from appscope.federation.contribute import main

_NAME_FILE = pathlib.Path(__file__).with_name(".contributor")


def _with_remembered_contributor(argv: list[str]) -> list[str]:
    if "--contributor" in argv:
        try:  # persist whatever the user just passed
            _NAME_FILE.write_text(argv[argv.index("--contributor") + 1], encoding="utf-8")
        except (IndexError, OSError):
            pass
        return argv
    if _NAME_FILE.exists():
        name = _NAME_FILE.read_text(encoding="utf-8").strip()
        if name:
            return [*argv, "--contributor", name]
    if sys.stdin.isatty() and "--dry-run" not in argv:
        name = input("Contributor name to credit on the PR (e.g. your HF username): ").strip()
        if name:
            try:
                _NAME_FILE.write_text(name, encoding="utf-8")
            except OSError:
                pass
            return [*argv, "--contributor", name]
    return argv


if __name__ == "__main__":
    raise SystemExit(main(_with_remembered_contributor(sys.argv[1:])))
