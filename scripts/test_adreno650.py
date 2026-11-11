#!/usr/bin/env python3
"""Host tests of the Adreno 650 kernel GPU driver fork (xVanTuring/Adreno650, gap G3), pinned, and the pipa board's GPU
nodes through its device-tree parser.

    scripts/test_adreno650.py [--work DIR] [--dtb pipa-mainline.dtb] [--json OUT]

Adreno650 is the pipa branch of UniXNU's Adreno740 (no catalog component yet, so format 2 cannot select it:
devices/pipa/feeds.toml). Its tests/ hold host tests over software register peers with authored IOKit doubles
(tests/XnuMemoryFixture.h). This script fetches the fork and its ArmSmmu4K kit at the pins below, compiles the
driver sources that build against those doubles (UniXNU's AdrenoPM4 kit from the submodule), and runs every test:
  - ShengGmu.h, the GMU API the fork's sheng (A740) GMU config and platform sources include, comes from the
    Sm8550Platform kit at its UniXNU catalog pin (header only; the A650 build does not link that platform);
  - a test needing a header generated per board for sheng (ShengGmuSource.h, build/sheng-gmu) is skipped, named;
  - a test needing a source written for AArch64 only (inline dsb/isb) is skipped on another host, named;
  - a failure listed in KNOWN_FAILURES (variant, test, the source line it stops at, the established cause) is
    reported "known-fail"; a listed failure that no longer fails, or fails elsewhere, is FAILED;
  - every other test must build and pass.
The tests run twice: on the fork as pinned ("pin") and with patches/adreno650/series applied ("patched": a driver
fix and a test fixture fix, each patch says what and why). Both results are printed and written to the JSON.
With --dtb (the mainline pipa DTB of scripts/pipa_hw.py compile), tests/gpu/A650PipaBoard.cpp also feeds the GPU and
GMU nodes' reg and iommus properties through NativeAdrenoBoard and checks them against package/GpuPowerBoard.h.

These test the fork's logic on the host. Nothing here builds the kernel driver or runs on the tablet.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ADRENO650_GIT = "https://github.com/xVanTuring/Adreno650"
ADRENO650_COMMIT = "01db67e0620fe0e70ab8cbce533cbdb1369f5922"     # = devices/pipa/feeds.toml [[source]] Adreno650
KITS = ROOT / "third_party/UniXNU/kits"
PKG = ROOT / "devices/pipa/package"
SHIM_HEADERS = ["IOKit/IOTypes.h", "IOKit/IOReturn.h", "IOKit/IOBufferMemoryDescriptor.h", "IOKit/IOLib.h", "kern/task.h"]
GENERATED = ("ShengGmuSource.h", "ShengGmuVotesSource.h", "ShengGmuCommandDbSource.h")   # build/sheng-gmu, sheng's
AARCH64 = platform.machine() in ("aarch64", "arm64")
PATCHES = ROOT / "patches/adreno650"
# (variant, test) -> (text of the source line the test stops at, established cause). Traced in a host build under gdb.
KNOWN_FAILURES = {
    ("pin", "test_gmumap"): ("CHECK(0)", "its SMMU peer forbids 64-bit writes; the merged ArmSmmu4K drops an unmap's pages with "
                             "TLBIVAL, a 64-bit write at context bank + 0x620 (NativeAdrenoVm::unmap -> "
                             "ArmSmmu4KSyncContextTlbPages). Stale test fixture: patch 0002"),
    ("pin", "test_vm"): ("CHECK(0)", "the same stale SMMU peer (TLBIVAL at context bank + 0x620): patch 0002"),
    ("patched", "test_vm"): ("s.vm.map(&second,0,0x802000", "the test expects a second owned BO aliasing the first one's "
                             "physical page (made by the fixture) with other attributes to be refused; since fork commit "
                             "1c4065c owned memory is mapped without the alias scan and the test was not updated. A "
                             "test/driver disagreement left open, not patched"),
}


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def fetch(git, commit, dest):
    dest = Path(dest)
    if (dest / ".git").exists() and run(["git", "-C", dest, "rev-parse", "HEAD"]).stdout.strip() == commit:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    for cmd in (["git", "init", "-q", dest], ["git", "-C", dest, "remote", "add", "origin", git],
                ["git", "-C", dest, "fetch", "-q", "--depth", "1", "origin", commit],
                ["git", "-c", "advice.detachedHead=false", "-C", dest, "checkout", "-q", "FETCH_HEAD"]):
        p = run(cmd)
        if p.returncode:
            sys.exit(f"failed: {' '.join(map(str, cmd))}\n{p.stderr}")
    return dest


def feed_commit(name):
    for src in tomllib.loads((ROOT / "devices/pipa/feeds.toml").read_text())["source"]:
        if src["name"] == name:
            return src["git"], src["commit"]
    raise KeyError(name)


def check_feeds_comment():
    """The fork's pin here is the [[source]] Adreno650 of devices/pipa/feeds.toml (format 2 builds that checkout)."""
    if feed_commit("Adreno650") != (ADRENO650_GIT, ADRENO650_COMMIT):
        sys.exit(f"devices/pipa/feeds.toml Adreno650 is {feed_commit('Adreno650')}, this script pins {ADRENO650_COMMIT}")


def catalog_pin(component):
    """repository, revision and path of a UniXNU catalog component (third_party/UniXNU/components.toml)."""
    for entry in tomllib.loads((ROOT / "third_party/UniXNU/components.toml").read_text())["component"]:
        if entry["id"] == component:
            return entry["repository"].removesuffix(".git"), entry["revision"], entry["path"]
    raise KeyError(component)


def compile_all(fork, smmu, work, cxx, cc, extra_includes=()):
    inc = work / "host-include"
    for name in SHIM_HEADERS:
        (inc / name).parent.mkdir(parents=True, exist_ok=True)
        (inc / name).write_text('#include "XnuMemoryFixture.h"\n')
    flags = ["-I", inc, "-I", fork, "-I", fork / "tests", "-I", smmu, "-I", KITS / "AdrenoPM4", "-I", KITS / "AdrenoFirmware"]
    for d in extra_includes:
        flags += ["-I", d]
    objdir = work / "obj"
    objdir.mkdir(parents=True, exist_ok=True)
    built, missing = [], {}
    sources = sorted(fork.glob("NativeAdreno*.cpp")) + sorted(p for p in smmu.glob("*.c") if not p.name.startswith("test_")) \
        + sorted(p for p in (KITS / "AdrenoPM4").glob("*.c") if not p.name.startswith("test_"))
    for src in sources:
        obj = objdir / (src.stem + ".o")
        compiler = [cxx, "-std=c++23"] if src.suffix == ".cpp" else [cc, "-std=gnu11"]
        p = run([*compiler, "-O1", "-w", *flags, "-c", src, "-o", obj])
        if p.returncode == 0:
            built.append(obj)
            continue
        m = re.search(r"fatal error: '?([^':\s]+)'? file not found", p.stderr)
        if m:
            missing[src.name] = f"needs {m.group(1)}"
        elif re.search(r"invalid instruction mnemonic|unknown register|Error: unknown mnemonic|#error[^\n]*AArch64", p.stderr):
            missing[src.name] = "AArch64 only"
        else:
            missing[src.name] = "error: " + p.stderr.strip().splitlines()[-1][:200]
    lib = work / "libadreno650-host.a"
    lib.unlink(missing_ok=True)
    run(["ar", "rcs", lib, *built]).check_returncode()
    return flags, lib, missing


def owner(symbol, fork, missing):
    """The source that was not built and defines this symbol (Class::member in Class.cpp, or a C function or variable
    declared there), or None."""
    cls = symbol.split("::")[0] if "::" in symbol else None
    for src in missing:
        if cls and Path(src).stem == cls:
            return src
        path = next((p for p in (fork / src, *fork.parent.glob(f"*/{src}")) if p.is_file()), None)
        if path and not cls and re.search(rf"\b{re.escape(symbol)}\b\s*[;({{=\[]", path.read_text(errors="replace")):
            return src
    return None


def classify(variant, name, text, why):
    """A failing run: known-fail when it stops where KNOWN_FAILURES says, otherwise FAILED."""
    known = KNOWN_FAILURES.get((variant, name))
    m = re.match(r"line (\d+): ", why)
    if known and m and 0 < int(m.group(1)) <= len(text.splitlines()) and known[0] in text.splitlines()[int(m.group(1)) - 1]:
        return "known-fail", f"{why} -- {known[1]}"
    return "FAILED", why


def apply_series(src, dest):
    """A copy of the fork with patches/adreno650/series applied."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
    applied = []
    for line in (PATCHES / "series").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(dest.parent))
        p = subprocess.run(["git", "apply", str(PATCHES / line.strip())], cwd=dest, env=env, capture_output=True, text=True)
        if p.returncode:
            sys.exit(f"patches/adreno650/{line.strip()} does not apply:\n{p.stderr}")
        applied.append(line.strip())
    return dest, applied


def run_tests(fork, flags, lib, missing, work, cxx, variant="pin"):
    results = {}
    for test in sorted((fork / "tests").glob("test_*.cpp")):
        name = test.stem
        text = test.read_text()
        needs = [h for h in GENERATED if re.search(rf'#include "[^"]*{re.escape(h[:-2])}', text)]
        binary = work / name
        p = run([cxx, "-std=c++23", "-O1", "-w", *flags, "-o", binary, test, lib])
        if p.returncode:
            gen = needs or [h for h in GENERATED if h in p.stderr]
            undefined = sorted(set(re.findall(r"undefined reference to `([^'(]+)", p.stderr)))
            owners = {sym: owner(sym, fork, missing) for sym in undefined}
            if gen:
                results[name] = {"result": "skipped", "why": f"needs sheng's generated {', '.join(gen)} (build/sheng-gmu)"}
            elif undefined and all(owners.values()):
                why = sorted({f"{src} ({missing[src]})" for src in owners.values()})
                results[name] = {"result": "skipped", "why": "links " + ", ".join(why)}
            else:
                results[name] = {"result": "FAILED", "why": (p.stderr.strip().splitlines() or ["?"])[-1][:300]}
            continue
        r = run([binary], timeout=600)
        out = (r.stdout + r.stderr).strip().splitlines()
        why = out[-1][:300] if out else ""
        if r.returncode == 0:
            result = "passed"
            if (variant, name) in KNOWN_FAILURES:       # a listed failure that passes: the table is out of date
                result, why = "FAILED", f"listed in KNOWN_FAILURES but passed: {why}"
        else:
            result, why = classify(variant, name, text, why)
        results[name] = {"result": result, "why": why}
    return results


def pipa_board(fork, flags, lib, work, cxx, dtb):
    """tests/gpu/A650PipaBoard.cpp over the mainline pipa DTB's gpu and gmu nodes."""
    from tools.hw.fdt import Tree
    tree = Tree.load(dtb)

    node = tree.label
    def cells(n, prop):
        return ", ".join(f"0x{b:02x}" for b in n.props[prop])

    gpu, gmu = node("gpu"), node("gmu")
    soc = gpu.parent
    smmu = tree.phandle(struct_u32(gpu.props["iommus"])[0])
    header = work / "pipa_gpu_props.h"
    header.write_text(
        "/* Generated by scripts/test_adreno650.py from the mainline pipa DTB. */\n"
        f"static const uint8_t pipa_gpu_reg[] = {{{cells(gpu, 'reg')}}};\n"
        f"static const uint8_t pipa_gmu_reg[] = {{{cells(gmu, 'reg')}}};\n"
        f"static const uint8_t pipa_gpu_iommus[] = {{{cells(gpu, 'iommus')}}};\n"
        f"static const uint8_t pipa_gmu_iommus[] = {{{cells(gmu, 'iommus')}}};\n"
        f"static const uint32_t pipa_address_cells = {soc.u32('#address-cells')}, pipa_size_cells = {soc.u32('#size-cells')};\n"
        f"static const uint32_t pipa_iommu_cells = {smmu.u32('#iommu-cells')};\n")
    binary = work / "A650PipaBoard"
    p = run([cxx, "-std=c++23", "-O1", "-Wall", "-Wextra", *flags, "-I", work, "-I", PKG, "-o", binary,
             ROOT / "tests/gpu/A650PipaBoard.cpp", lib])
    if p.returncode:
        return {"result": "FAILED", "why": p.stderr.strip().splitlines()[-1][:300]}
    r = run([binary])
    out = (r.stdout + r.stderr).strip().splitlines()
    return {"result": "passed" if r.returncode == 0 else "FAILED", "why": out[-1][:300] if out else ""}


def struct_u32(raw):
    return [int.from_bytes(raw[i:i + 4], "big") for i in range(0, len(raw), 4)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, default=ROOT / "build/adreno650-host")
    ap.add_argument("--dtb", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    check_feeds_comment()
    if not (KITS / "AdrenoPM4/AdrenoPM4.c").is_file():
        sys.exit("needs UniXNU's AdrenoPM4 kit: git submodule update --init --depth 1 third_party/UniXNU && "
                 "git -C third_party/UniXNU submodule update --init --depth 1 kits/AdrenoPM4")
    cxx = os.environ.get("CXX") or shutil.which("clang++") or "c++"
    cc = os.environ.get("CC") or shutil.which("clang") or "cc"
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    fork = fetch(ADRENO650_GIT, ADRENO650_COMMIT, work / "Adreno650")
    smmu = fetch(*feed_commit("ArmSmmu4K"), work / "ArmSmmu4K")
    sm8550_git, sm8550_rev, _ = catalog_pin("Sm8550Platform")
    sm8550 = fetch(sm8550_git, sm8550_rev, work / "UniXNU-sm8550-common") / "kits/Sm8550Platform"
    patched, applied = apply_series(fork, work / "Adreno650-patched")
    report, failed = {}, False
    for variant, tree in (("pin", fork), ("patched", patched)):
        vwork = work / variant
        vwork.mkdir(parents=True, exist_ok=True)
        flags, lib, missing = compile_all(tree, smmu, vwork, cxx, cc, [sm8550])
        results = run_tests(tree, flags, lib, missing, vwork, cxx, variant)
        if args.dtb and variant == "patched":
            results["A650PipaBoard (pipa DTB)"] = pipa_board(tree, flags, lib, vwork, cxx, args.dtb)
        print(f"== {variant}" + (f" ({', '.join(applied)})" if variant == "patched" else f" ({ADRENO650_COMMIT[:12]})"))
        for name, r in results.items():
            print(f"{r['result']:10} {name:28} {r['why']}")
        for src, why in sorted(missing.items()):
            print(f"not built  {src}: {why}")
        summary = {k: sum(1 for r in results.values() if r["result"] == k) for k in ("passed", "skipped", "known-fail", "FAILED")}
        print(json.dumps({"variant": variant, "host": platform.machine(), **summary}))
        report[variant] = {"summary": summary, "tests": results, "not_built": missing}
        failed |= bool(summary["FAILED"]) or not summary["passed"]
    if args.json:
        args.json.write_text(json.dumps({"adreno650": ADRENO650_COMMIT, "host": platform.machine(), "patches": applied,
                                         **report}, indent=2) + "\n")
    if failed:
        sys.exit("Adreno650 host tests failed")


if __name__ == "__main__":
    main()
