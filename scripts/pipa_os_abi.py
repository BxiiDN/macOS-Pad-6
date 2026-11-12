#!/usr/bin/env python3
"""Which of devices/pipa/package goes into which kernel: the macOS 26.5 one, the iPadOS 17 one, or none (host models).

    scripts/pipa_os_abi.py [--markdown OUT] [--json OUT] [--check]

The board package holds three kinds of code side by side: sources the macOS 26.5 kernel step compiles, sources only
the iPadOS 17 port (UniXNU-pipa, format 1, its tablet runs) compiles, because they bind iPadOS classes or boot flows
(IOMobileFramebufferLegacy, backboardd, the offline display bring-up), and plain models tested on the host that no
kernel compiles yet (the panel link, touch vendor and backlight models). This derives the split from the build
recipes themselves rather than from a list kept by hand:

  macOS   board.toml [kernel] archives: each device script, and per component its recipe (component:ShengUfs runs
          UniXNU's arm64e source storage recipe, component:Adreno650 runs build-adreno650.py)
  iPadOS  the [os_overrides."ipados-17.7.11-21H461".kernel] archives, plus build-boot-progress.py, which
          pipa_defconfig's CONFIG_XNU_BOOT_PROGRESS links

A source belongs to a kernel when a builder names it in its code (string constants; docstrings and comments do not
count), and a header when a source of that kernel includes it (transitively). --check fails when a source the macOS
kernel compiles, or a header it includes, names an iPadOS-only interface in its code (comments do not count).

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "devices/pipa"
PACKAGE = BOARD / "package"
UNIXNU = ROOT / "third_party/UniXNU"
IPADOS = "ipados-17.7.11-21H461"
# Component recipes that compile board package sources, per kernel. The iPadOS (arm64) ShengUfs build is
# build-arm-driver.py on NativeUfs alone; only the arm64e one runs the source storage recipe.
COMPONENT_BUILDERS = {
    "macos": {"ShengUfs": UNIXNU / "scripts/build-sheng-source-storage.py", "Adreno650": BOARD / "scripts/build-adreno650.py"},
    "ipados": {"Adreno650": BOARD / "scripts/build-adreno650.py"},
}
# Interfaces that exist only in the iPadOS port's boot: the original mobile framebuffer classes and their bring-up,
# the iPadOS render server, the offline display boot flags.
IPADOS_ONLY = ("IOMobileFramebuffer", "NativeLegacyDisplay", "IOMobileGraphicsFamily", "OriginalMobileFramebufferABI",
               "backboardd", "SpringBoard", "offline-legacy", "native_legacy_")


def code_strings(path):
    """String constants of a Python script outside docstrings (f-string parts included)."""
    tree = ast.parse(path.read_text())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def c_code(text):
    """C/C++ text without comments and without string-free noise: what the compiler sees, roughly."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def builders():
    board = tomllib.loads((BOARD / "board.toml").read_text())
    plans = {"macos": board["kernel"]["archives"],
             "ipados": board["os_overrides"][IPADOS]["kernel"]["archives"] + ["build-boot-progress.py"]}
    out = {}
    for os_name, entries in plans.items():
        scripts = []
        for entry in entries:
            if entry.startswith("component:"):
                recipe = COMPONENT_BUILDERS[os_name].get(entry.split(":", 1)[1])
                if recipe:
                    scripts.append(recipe)
                continue
            path = BOARD / "scripts" / entry.split()[0]
            if path.is_file():         # UniXNU's own builders (corecrypto, pthread, ...) compile no board source
                scripts.append(path)
        out[os_name] = scripts
    return out


def storage_recipe_sources(script):
    """The board sources UniXNU's source storage recipe always compiles: the device_source(...) calls of its first
    `sources = [...]` list. The ones it appends later depend on the OS major version (27 and later), which the
    macOS 26.5 kernel is not; kernel-build attempt 15's link map lists exactly these five as linked."""
    for node in ast.walk(ast.parse(script.read_text())):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)
                and any(isinstance(t, ast.Name) and t.id == "sources" for t in node.targets)):
            return [c.args[0].value for c in node.value.elts
                    if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "device_source"]
    return []


def sources_of(script, names):
    if script.name == "build-sheng-source-storage.py":
        return set(storage_recipe_sources(script)) & set(names)
    strings = code_strings(script)
    found = set()
    for name in names:
        stem = Path(name).stem
        if any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(stem)}(?![A-Za-z0-9_])", s) for s in strings):
            found.add(name)
    return found


def includes(name, seen=None):
    seen = set() if seen is None else seen
    path = PACKAGE / name
    if name in seen or not path.is_file():
        return seen
    seen.add(name)
    for inc in re.findall(r'#\s*include\s+"([^"]+)"', c_code(path.read_text(errors="replace"))):
        includes(Path(inc).name, seen)
    return seen


def classify():
    files = sorted(p.name for p in PACKAGE.iterdir() if p.suffix in (".c", ".cpp", ".h"))
    compiled = [f for f in files if f.endswith((".c", ".cpp")) and not f.endswith("Tests.c")]
    per_os, by = {}, {}
    for os_name, scripts in builders().items():
        names = set()
        for script in scripts:
            got = sources_of(script, compiled)
            for f in got:
                by.setdefault(f, set()).add(f"{os_name}:{script.name}")
            names |= got
        closure = set()
        for f in names:
            closure |= includes(f)
        per_os[os_name] = closure
    rows = []
    for f in files:
        kernels = [o for o in ("macos", "ipados") if f in per_os[o]]
        if f.endswith("Tests.c"):
            kind = "host test"
        elif kernels == ["macos", "ipados"]:
            kind = "both kernels"
        elif kernels:
            kind = f"{kernels[0]} kernel only"
        else:
            kind = "host model (no kernel compiles it)"
        markers = sorted({m for m in IPADOS_ONLY if m in c_code((PACKAGE / f).read_text(errors="replace"))})
        rows.append({"file": f, "kind": kind, "kernels": kernels, "built_by": sorted(by.get(f, ())),
                     "ipados_only_interfaces": markers})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    rows = classify()
    problems = [f"{r['file']}: compiled into the macOS kernel but names {', '.join(r['ipados_only_interfaces'])}"
                for r in rows if "macos" in r["kernels"] and r["ipados_only_interfaces"]]
    lines = ["| File | Kernel | Built by | iPadOS-only interfaces in code |", "| --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| `{r['file']}` | {r['kind']} | {', '.join(r['built_by']) or '—'} | "
                     f"{', '.join(r['ipados_only_interfaces']) or '—'} |")
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.markdown:
        args.markdown.write_text(text)
    if args.json:
        args.json.write_text(json.dumps({"rows": rows, "problems": problems}, indent=2) + "\n")
    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    print("; ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    if args.check and problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main()
