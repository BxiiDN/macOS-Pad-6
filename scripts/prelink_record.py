#!/usr/bin/env python3
"""Summarize XnuPrelink's record of a prelink (kernel/kernel.json) and its symbol pairing (kernel.map.json).

    scripts/prelink_record.py kernel.json [kernel.map.json] [--json OUT]

Prints every key of the record. Lists longer than --list-max become {"count": N, "first": [...]}; tables
(dicts) longer than --list-max become {"count": N, "total": sum of numeric values or of nested counts}.
For the pairing it prints how many collection targets were paired, by method ("symbol", ...). Nothing in
either file is Apple code: they hold hashes, bundle identifiers, symbol names, addresses and counts.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
from collections import Counter
from pathlib import Path


def total(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return sum(total(v) for v in value.values())
    if isinstance(value, list):
        return len(value)
    return 0


def shorten(value, limit):
    if isinstance(value, list) and len(value) > limit:
        return {"count": len(value), "first": value[:limit]}
    if isinstance(value, dict):
        if len(value) > limit:
            return {"count": len(value), "total": total(value)}
        return {k: shorten(v, limit) for k, v in value.items()}
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record", type=Path)
    ap.add_argument("pairing", type=Path, nargs="?")
    ap.add_argument("--list-max", type=int, default=12)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    record = json.loads(args.record.read_text())
    out = {"record": {k: shorten(v, args.list_max) for k, v in record.items()}}
    if args.pairing and args.pairing.is_file():
        pairing = json.loads(args.pairing.read_text())
        out["pairing"] = {
            "method": pairing.get("method"),
            "functions": len(pairing.get("functions", {})),
            "data": len(pairing.get("data", {})),
            "functions_by_how": dict(Counter(v.get("how") for v in pairing.get("functions", {}).values())),
            "data_by_how": dict(Counter(v.get("how") for v in pairing.get("data", {}).values())),
            "other_keys": sorted(k for k in pairing if k not in ("functions", "data")),
        }
    text = json.dumps(out, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")


if __name__ == "__main__":
    main()
