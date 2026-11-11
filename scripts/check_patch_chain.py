#!/usr/bin/env python3
"""Apply UniXNU's XNU patch chain plus this repository's patches to a copy of XNU.

    scripts/check_patch_chain.py --xnu XNU --unixnu UNIXNU --profile tahoe-26.5 [--json OUT]

Profiles:
  macos-27.3   UniXNU's arm64e arch series + its macos-27.3-26C5035r OS series, as published
  tahoe-26.5   UniXNU's arm64e arch series, this repository's SM8250 SoC series
               (profiles/macos-26.5/soc-sm8250, or --soc), UniXNU's macOS OS series minus the
               patches that add Darwin 26 (macOS 27) system calls and KPIs, which
               xnu-12377.121.6 (the macOS 26.5 kernel source) must not get, then
               profiles/macos-26.5/patches/series

Each patch is applied with `git apply` in order to a throw-away clone; the
report lists every patch with ok/FAIL. Nothing is built.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XNU_REVISION = "ac9718fb1af618d5ce8678d0dc6e8a58f252216f"
MACOS27 = "profiles/os/macos-27.3-26C5035r"

# macOS 27 (Darwin 26) additions: Tahoe 26.x runs Darwin 25, which is what
# xnu-12377 already is. Determined from the patch names and their headers;
# docs/tahoe-26-report.md lists the evidence.
DARWIN26_ONLY = {
    "darwin26-syscalls.patch",
    "darwin26-kpi.patch",
    "darwin26-shared-region.patch",
    "macos-darwin26-kpi.patch",
}


def read_series(series, base_arch, base_os):
    out = []
    for line in series.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("arch:"):
            out.append((base_arch / line[5:]).resolve())
        else:
            out.append((base_os / line).resolve())
    return out


def chain(unixnu, profile, soc=None, soc_dir=None):
    """The ordered patch list. soc is a UniXNU-<soc>-common checkout; soc_dir a
    directory holding a SoC series directly. tahoe-26.5 defaults to this
    repository's SM8250 series (pipa)."""
    arch_dir = unixnu / "profiles/arch/arm64e"
    arch = read_series(arch_dir / "patches/xnu/series", arch_dir / "patches/xnu", arch_dir / "patches/xnu")
    os_dir = unixnu / MACOS27 / "patches/xnu"
    ospatches = read_series(os_dir / "series", arch_dir, os_dir)
    if soc is not None:
        soc_dir = soc / "patches/xnu-12377"
    elif soc_dir is None and profile == "tahoe-26.5":
        soc_dir = ROOT / "profiles/macos-26.5/soc-sm8250"
    socp = [("soc", p) for p in read_series(soc_dir / "series", soc_dir, soc_dir)] if soc_dir else []
    if profile == "macos-27.3":
        return [("unixnu-arch", p) for p in arch] + socp + [("unixnu-os", p) for p in ospatches]
    if profile == "tahoe-26.5":
        mine_dir = ROOT / "profiles/macos-26.5/patches"
        mine = read_series(mine_dir / "series", mine_dir, mine_dir)
        return ([("unixnu-arch", p) for p in arch] + socp +
                [("unixnu-os", p) for p in ospatches if p.name not in DARWIN26_ONLY] +
                [("macos-pad-6", p) for p in mine])
    raise SystemExit(f"unknown profile {profile}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xnu", type=Path, required=True)
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--profile", required=True, choices=["macos-27.3", "tahoe-26.5"])
    ap.add_argument("--soc", type=Path, help="a UniXNU-<soc>-common checkout (its series goes between arch and OS)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    head = subprocess.run(["git", "-C", str(args.xnu), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    if head != XNU_REVISION:
        sys.exit(f"XNU is at {head}, expected {XNU_REVISION}")
    unixnu_rev = subprocess.run(["git", "-C", str(args.unixnu), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "xnu"
        subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "-q", "--shared", str(args.xnu), str(work)], check=True)
        subprocess.run(["git", "-c", "advice.detachedHead=false", "-C", str(work), "checkout", "-q",
                        XNU_REVISION], check=True)
        for origin, patch in chain(args.unixnu.resolve(), args.profile,
                                   args.soc.resolve() if args.soc else None):
            if not patch.exists():
                results.append({"origin": origin, "patch": patch.name, "ok": False, "error": "missing"})
                continue
            p = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=work,
                               capture_output=True, text=True)
            results.append({"origin": origin, "patch": patch.name, "ok": p.returncode == 0,
                            "error": p.stderr.strip().splitlines()[:2]})
    ok = sum(r["ok"] for r in results)
    for r in results:
        print(f"{'ok  ' if r['ok'] else 'FAIL'} {r['origin']:12} {r['patch']}"
              + ("" if r["ok"] else f"  {r['error']}"))
    print(f"{args.profile}: {ok}/{len(results)} patches apply (xnu {XNU_REVISION[:12]}, UniXNU {unixnu_rev[:12]})")
    if args.json:
        args.json.write_text(json.dumps({"profile": args.profile, "xnu": XNU_REVISION,
                                         "unixnu": unixnu_rev, "skipped_darwin26": sorted(DARWIN26_ONLY),
                                         "results": results}, indent=2) + "\n")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
