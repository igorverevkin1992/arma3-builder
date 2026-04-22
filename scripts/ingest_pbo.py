#!/usr/bin/env python3
"""Ingest a mod PBO archive into the classname index.

Requires `armake2` (recommended) or Mikero's `extractpbo` on PATH.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arma3_builder.rag import get_store
from arma3_builder.rag.ingest_pbo import UnpackerNotFound, ingest_pbo


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pbo", type=Path)
    p.add_argument("--tenant", required=True)
    args = p.parse_args()

    try:
        n = ingest_pbo(get_store(), args.pbo, tenant=args.tenant)
    except UnpackerNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"Indexed {n} classnames from {args.pbo} (tenant={args.tenant})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
