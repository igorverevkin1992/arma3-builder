#!/usr/bin/env python3
"""Ingest a directory of Biki markdown into the configured RAG store."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arma3_builder.rag import get_store
from arma3_builder.rag.ingest_biki import ingest_directory, ingest_jsonl


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path, help="Directory of .md files OR a .jsonl dump")
    p.add_argument("--source", default="biki")
    args = p.parse_args()

    store = get_store()
    if args.path.is_dir():
        n = ingest_directory(store, args.path, source=args.source)
    else:
        n = ingest_jsonl(store, args.path, source=args.source)
    print(f"Indexed {n} documents into the {args.source} namespace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
