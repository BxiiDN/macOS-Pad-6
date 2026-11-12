#!/usr/bin/env python3
"""Apply UniXNU's XNU patch chain plus this repository's patches to a copy of XNU.

    scripts/check_patch_chain.py --xnu XNU --unixnu UNIXNU --profile tahoe-26.5 [--json OUT]

Profiles:
  macos-27.3   UniXNU's arm64e arch series + its macos-27.3-26C5035r OS series, as published
  tahoe-26.5   the series devices/pipa/board.toml names for macos-26.5-25F71, in its order:
               UniXNU's arm64e arch series, devices/pipa/patches/xnu-12377/soc (the arm64e SM8250
               layer), the OS series of profiles/macos-26.5/unixnu/macos-26.5-25F71 (UniXNU's macOS
               series without the patches that add Darwin 26 system calls and KPIs, which
               xnu-12377.121.6, the macOS 26.5 kernel source, must not get), then
               devices/pipa/patches/xnu-12377/series (the ARMv8.2 layer)

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


PIPA = ROOT / "devices/pipa/patches/xnu-12377"
PROFILE_26 = ROOT / "profiles/macos-26.5/unixnu/macos-26.5-25F71"


def resolve_series(series, roots, virtual_dir=None):
    """Lines of a UniXNU series: "arch:" and "os:" select a profile root, other lines are relative to
    the series' directory (virtual_dir when the series is read from outside the UniXNU checkout)."""
    out = []
    for line in series.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        prefix, sep, rest = line.partition(":")
        if sep and prefix in roots:
            out.append((roots[prefix] / rest).resolve())
        else:
            out.append(((virtual_dir or series.parent) / line).resolve())
    return out


def chain(unixnu, profile, soc=None, soc_dir=None):
    """The ordered patch list. soc is a UniXNU-<soc>-common checkout whose patches/xnu-12377
    series replaces the default SoC layer; soc_dir a directory holding a series directly."""
    arch_dir = unixnu / "profiles/arch/arm64e"
    arch = read_series(arch_dir / "patches/xnu/series", arch_dir / "patches/xnu", arch_dir / "patches/xnu")
    if soc is not None:
        soc_dir = soc / "patches/xnu-12377"
    if profile == "macos-27.3":
        os_dir = unixnu / MACOS27 / "patches/xnu"
        ospatches = read_series(os_dir / "series", arch_dir, os_dir)
        socp = [("soc", p) for p in read_series(soc_dir / "series", soc_dir, soc_dir)] if soc_dir else []
        return [("unixnu-arch", p) for p in arch] + socp + [("unixnu-os", p) for p in ospatches]
    if profile == "tahoe-26.5":
        soc_dir = soc_dir or PIPA / "soc"
        socp = resolve_series(soc_dir / "series", {})
        # The profile is installed as profiles/os/macos-26.5-25F71 of the UniXNU checkout; its series
        # names UniXNU's macOS patches relative to that place.
        installed = unixnu / "profiles/os" / PROFILE_26.name / "patches/xnu"
        ospatches = resolve_series(PROFILE_26 / "patches/xnu/series", {"arch": arch_dir, "os": installed.parent.parent},
                                   virtual_dir=installed)
        device = resolve_series(PIPA / "series", {})
        return ([("unixnu-arch", p) for p in arch] + [("soc", p) for p in socp] +
                [("unixnu-os", p) for p in ospatches] + [("pipa", p) for p in device])
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
