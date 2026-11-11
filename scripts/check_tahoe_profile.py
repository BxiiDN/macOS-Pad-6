#!/usr/bin/env python3
"""Resolve profiles/macos-26.5/unixnu with UniXNU's own `unixnu status`.

    scripts/check_tahoe_profile.py --unixnu UNIXNU --board BOARD_DIR --soc NAME=PATH [--json OUT]

UniXNU-pipa is still a format 1 board, which ignores OS profiles, so a format 2
board (UniXNU-sheng) hosts the check. The profile is installed into a copy of
UniXNU, both the 26.5 and 27.3 profiles are resolved, and the result must name
the 26.5 IPSW, its kernelcache pin, and no Darwin 26 patch.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def status(ux, os_name, board, soc):
    p = subprocess.run(["./unixnu", "status", "--json", "--os", os_name, "-D", str(board),
                        "--local-module", f"soc:{soc}"], cwd=ux, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"unixnu status --os {os_name} failed:\n{p.stderr[-2000:]}")
    return json.loads(p.stdout[p.stdout.index("{"):])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--soc", required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    (pdir,) = list((ROOT / "profiles/macos-26.5/unixnu").iterdir())
    prof = tomllib.loads((pdir / "profile.toml").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        ux = Path(tmp) / "UniXNU"
        shutil.copytree(args.unixnu, ux, symlinks=True, ignore=shutil.ignore_patterns(".git", "out", ".cache"))
        shutil.copytree(pdir, ux / "profiles/os" / pdir.name)
        new = status(ux, pdir.name, args.board.resolve(), args.soc)
        old = status(ux, "macos-27.3-26C5035r", args.board.resolve(), args.soc)
    b = new["board"]
    res = {
        "profile": Path(new["profiles"].get("os", "")).name,
        "ipsw": [b["ipsw"]["product"], b["ipsw"]["version"], b["ipsw"]["build"]],
        "kernelcache_sha256": b["kernel"]["prelink"]["kernelcache_sha256"],
        "early_security_init": b["kernel"]["prelink"]["early_security_init"],
        "patches": len(new["patch_order"]),
        "patches_27_3": len(old["patch_order"]),
        "darwin26_patches": [p.split("/")[-1] for p in new["patch_order"] if "darwin26" in p],
        "only_in_27_3": sorted({p.split("/")[-1] for p in old["patch_order"]} -
                               {p.split("/")[-1] for p in new["patch_order"]}),
    }
    print(json.dumps(res, indent=2))
    ok = (res["profile"] == pdir.name and res["ipsw"][1:] == [prof["ipsw"]["version"], prof["ipsw"]["build"]]
          and res["kernelcache_sha256"] == prof["kernel"]["prelink"]["kernelcache_sha256"]
          and not res["darwin26_patches"])
    if args.json:
        args.json.write_text(json.dumps(res, indent=2) + "\n")
    if not ok:
        sys.exit("the 26.5 profile did not resolve as expected")
    print("profile resolves in UniXNU")


if __name__ == "__main__":
    main()
