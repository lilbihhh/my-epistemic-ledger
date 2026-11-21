#!/usr/bin/env python3
"""Compatibility entry point.

Prefer ``python -m epistemic_ledger``. This module forwards to the same CLI
so ``python main.py ask "..."`` still works.
"""

from epistemic_ledger.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
