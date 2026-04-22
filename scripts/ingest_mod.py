#!/usr/bin/env python3
"""Ingest a mod's `config.cpp` into the classname index."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arma3_builder.rag import get_store
from arma3_builder.rag.ingest_classnames import ingest_config_cpp


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path, help="Path to config.cpp")
    p.add_argument("--tenant", required=True, help="Mod identifier (e.g. 'rhsusf_main')")
    args = p.parse_args()

    n = ingest_config_cpp(get_store(), args.path, tenant=args.tenant)
    print(f"Indexed {n} classnames from tenant={args.tenant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
