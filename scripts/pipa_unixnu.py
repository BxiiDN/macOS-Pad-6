#!/usr/bin/env python3
"""Run UniXNU on devices/pipa, the format 2 board of the Xiaomi Pad 6.

    scripts/pipa_unixnu.py prepare [--unixnu DIR] [--work DIR] [--in-place]
    scripts/pipa_unixnu.py run [--work DIR] -- COMMAND [ARGS...]     e.g. -- status --os macos-26.5-25F71
    scripts/pipa_unixnu.py check [--unixnu DIR] [--work DIR] [--in-place] [--xnu XNU] [--adt] [--json OUT]

prepare  copies the pinned UniXNU checkout (third_party/UniXNU, with its driver and kit
         submodules) to WORK/UniXNU, installs profiles/macos-26.5/unixnu/macos-26.5-25F71 as
         profiles/os/macos-26.5-25F71 there, and clones every [[source]] of
         devices/pipa/feeds.toml at its pinned commit into WORK/feeds (default WORK: build/pipa-unixnu).
         --in-place installs the profile into --unixnu itself instead; that must be a Git
         checkout of its own (the kernel build workflow uses a fresh clone), because
         "unixnu fetch" updates the submodules of the checkout it runs in.
run      starts ./unixnu in WORK/UniXNU with "-D devices/pipa" and one --local-module per feed
         source. UniXNU resolves a module of its own checkout before a git feed of the device
         (docs/reference/configuration.md, "Module resolution"), so without these overrides the
         board would get UniXNU/ArmCpu instead of the pipa branch feeds.toml pins.
check    prepare, then "unixnu status --json" for both OS profiles of the board, and asserts:
         - macos-26.5-25F71 is the default: IPSW 26.5 (25F71), the profile's kernelcache pin, no
           Darwin 26 patch, and the patch order equal to scripts/check_patch_chain.py's tahoe-26.5
           chain (the chain CI applies to xnu-12377.121.6);
         - ipados-17.7.11-21H461 (UniXNU-pipa's port, kept as an override) still resolves;
         - the SoC layer and every selected component that feeds.toml pins come from that pin.
         --xnu also applies the board's patch order to XNU (git apply, as check_patch_chain.py).
         --adt compiles dts/pipa.dts with dtc and runs UniXNU's ADT generator on it (needs dtc).

Nothing here builds a kernel, touches a device or downloads Apple software.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "devices/pipa"
PROFILE = ROOT / "profiles/macos-26.5/unixnu/macos-26.5-25F71"
UNIXNU_PATCHES = ROOT / "patches/unixnu"
DEFAULT_OS = "macos-26.5-25F71"
OVERRIDE_OS = "ipados-17.7.11-21H461"
DEFAULT_WORK = ROOT / "build/pipa-unixnu"
DARWIN26 = ("darwin26",)

sys.path.insert(0, str(ROOT / "scripts"))
import check_patch_chain as cpc  # noqa: E402


def sh(*cmd, cwd=None, capture=False):
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, text=True,
                       capture_output=capture, check=False)
    if p.returncode:
        err = (p.stderr or "")[-3000:] if capture else ""
        sys.exit(f"failed ({p.returncode}): {' '.join(map(str, cmd))}\n{err}")
    return p.stdout if capture else ""


def feed_sources():
    out = []
    for src in tomllib.loads((BOARD / "feeds.toml").read_text()).get("source", []):
        if not (src.get("git") and src.get("commit") and len(src["commit"]) == 40):
            sys.exit(f"devices/pipa/feeds.toml: {src.get('name')} needs git and a 40-digit commit")
        out.append(src)
    return out


def fetch(src, cache):
    """A checkout of src["git"] at src["commit"], cached under cache/NAME-COMMIT12."""
    path = cache / f"{src['name']}-{src['commit'][:12]}"
    if (path / ".git").exists():
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
        if head.stdout.strip() == src["commit"]:
            return path
        shutil.rmtree(path)
    path.mkdir(parents=True)
    sh("git", "init", "-q", path)
    sh("git", "-C", path, "remote", "add", "origin", src["git"])
    sh("git", "-C", path, "fetch", "-q", "--depth", "1", "origin", src["commit"])
    sh("git", "-c", "advice.detachedHead=false", "-C", path, "checkout", "-q", "FETCH_HEAD")
    for sub in src.get("submodules", []):
        sh("git", "-C", path, "submodule", "update", "--init", "--depth", "1", "--", sub)
    return path


def prepare(unixnu, work, in_place=False):
    """A UniXNU checkout with the 26.5 profile and the feed sources. By default a copy under WORK (the submodule stays
    clean). --in-place installs the profile into UNIXNU itself, which must then be a Git checkout of its own (a fresh
    clone, as the kernel build workflow makes): "unixnu fetch" updates the submodules of the checkout it runs in."""
    unixnu = unixnu.resolve()
    empty = [p for p in ("drivers/ArmCpu", "drivers/ArmDTPlatform", "kits/XnuPrelink")
             if not any((unixnu / p).iterdir())] if (unixnu / "drivers").is_dir() else ["drivers"]
    if empty:
        sys.exit(f"{unixnu}: submodules not checked out ({', '.join(empty)}); run\n"
                 f"  git -C {unixnu} submodule update --init --depth 1")
    work.mkdir(parents=True, exist_ok=True)
    if in_place:
        if not (unixnu / ".git").exists():
            sys.exit(f"--in-place: {unixnu} is not a Git checkout")
        ux = unixnu
    else:
        ux = work / "UniXNU"
        if ux.exists():
            for name in ("out", ".cache"):     # keep build output and fetched sources between runs
                if (ux / name).exists():
                    shutil.move(str(ux / name), str(work / f".keep-{name}"))
            shutil.rmtree(ux)
        # No .git and no .gitmodules: the copy sits inside this repository, and Git commands that unixnu runs in it
        # must not reach this repository's submodules. The copy's submodules are already checked out.
        shutil.copytree(unixnu, ux, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", ".gitmodules", "out", ".cache"))
        for name in ("out", ".cache"):
            if (work / f".keep-{name}").exists():
                shutil.move(str(work / f".keep-{name}"), str(ux / name))
    apply_unixnu_patches(ux)
    target = ux / "profiles/os" / PROFILE.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(PROFILE, target)
    modules = {}
    for src in feed_sources():
        modules[(src["kind"], src["name"])] = fetch(src, work / "feeds")
    (work / "modules.json").write_text(json.dumps(
        {"unixnu": str(ux), "source": str(unixnu),
         "modules": {f"{k}:{n}": str(p) for (k, n), p in modules.items()}}, indent=2) + "\n")
    return ux, modules


def unixnu_patches():
    series = UNIXNU_PATCHES / "series"
    if not series.is_file():
        return []
    return [UNIXNU_PATCHES / line.strip() for line in series.read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def git_apply(ux, *args):
    """git apply in UX as a tree of its own: the copy sits inside this repository, where git apply would resolve
    paths against this repository's top level and skip every file (exit 0, nothing changed)."""
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(Path(ux).resolve().parent))
    return subprocess.run(["git", "apply", *map(str, args)], cwd=ux, env=env, capture_output=True, text=True)


def apply_unixnu_patches(ux):
    """patches/unixnu/series on the UniXNU copy (or the --in-place checkout): each patch is applied unless it is
    already there (its reverse applies), so preparing twice is harmless. Returns {patch: "applied" | "present"}."""
    done = {}
    for patch in unixnu_patches():
        check = git_apply(ux, "--check", patch)
        if check.returncode == 0:
            if git_apply(ux, patch).returncode:
                sys.exit(f"{patch.name}: git apply failed in {ux}")
            done[patch.name] = "applied"
            continue
        back = git_apply(ux, "--check", "--reverse", patch)
        if back.returncode != 0:
            sys.exit(f"{patch.name} does not apply to {ux}:\n{check.stderr[-2000:]}")
        done[patch.name] = "present"
    return done


def ufs_probe_compatible(native_ufs, defines, cc=None):
    """The controller compatible string NativeUfs.cpp's probe() looks for under these -D flags: the #if block that
    defines `compatible`, cut out of the source and run through the C preprocessor."""
    import re
    import tempfile
    text = Path(native_ufs).read_text()
    blocks = [m for m in re.finditer(r"^[ \t]*#if defined\(NATIVE_UFS_[^\n]*\n(?:[^\n]*\n)*?[ \t]*#endif[^\n]*\n", text, re.M)
              if "const char *compatible" in m.group(0)]
    if len(blocks) != 1:
        raise LookupError(f"{native_ufs}: {len(blocks)} NATIVE_UFS_<SoC> blocks define the compatible string, expected 1")
    m = blocks[0]
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "probe.c"
        src.write_text(m.group(0))
        out = subprocess.run([cc or os.environ.get("CC") or "cc", "-E", "-P", *defines, str(src)],
                             capture_output=True, text=True, check=True).stdout
    found = re.findall(r'const char \*compatible = "([^"]+)"', out)
    if len(found) != 1:
        raise LookupError(f"{native_ufs}: the preprocessed block gives {found}")
    return found[0]


def load_state(work):
    f = work / "modules.json"
    if not f.is_file():
        sys.exit(f"{work}: run 'scripts/pipa_unixnu.py prepare' first")
    state = json.loads(f.read_text())
    ux = Path(state["unixnu"])
    if not (ux / "unixnu").is_file():
        sys.exit(f"{ux}: no UniXNU checkout; run 'scripts/pipa_unixnu.py prepare' again")
    return ux, {tuple(k.split(":", 1)): Path(v) for k, v in state["modules"].items()}


def unixnu_args(modules):
    args = ["-D", str(BOARD)]
    for (kind, name), path in sorted(modules.items()):
        args += ["--local-module", f"{kind}:{name}={path}"]
    return args


BUILD_COMMANDS = ("build", "kernel", "prelink", "payload", "package", "release")
# What the kernel is built from in this repository. The pinned build date is the time of the last commit that changed
# one of these, so a commit that only touches documentation, CI or tooling builds the same kernel bit for bit.
KERNEL_INPUTS = ("devices/pipa", "profiles", "kernel", "third_party", ".gitmodules", "patches")


def reproducible_env(env=None):
    """Environment for a reproducible kernel step. XNU's config/newvers.pl stamps `date` into the kernel version
    string unless KERNEL_BUILD_DATE is set; it is set here from SOURCE_DATE_EPOCH, or else from the time of the last
    commit that changed a kernel input (KERNEL_INPUTS), so two builds of the same inputs carry the same string (it was
    the only difference between two builds: docs/kernel-build.md). ZERO_AR_DATE (archive member and debug-map times)
    is set by UniXNU's kernel step already; it is repeated for the archive builders."""
    import time
    env = dict(os.environ if env is None else env)
    epoch = env.get("SOURCE_DATE_EPOCH")
    if not epoch:
        shallow = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],
                                 capture_output=True, text=True).stdout.strip() == "true"
        if shallow:
            # In a shallow clone the oldest commit looks like it changed every path, so the date is that commit's and
            # two commits with the same kernel inputs build different kernels. Not fatal: within one checkout the
            # build stays reproducible.
            print("pipa_unixnu: warning: shallow clone; the build date follows HEAD, not the last kernel-input change "
                  "(git fetch --unshallow, or set SOURCE_DATE_EPOCH)", file=sys.stderr)
        epoch = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct", "--", *KERNEL_INPUTS],
                               capture_output=True, text=True).stdout.strip() or "0"
        env["SOURCE_DATE_EPOCH"] = epoch
    env.setdefault("KERNEL_BUILD_DATE", time.strftime("%a %b %d %H:%M:%S UTC %Y", time.gmtime(int(epoch))))
    env.setdefault("ZERO_AR_DATE", "1")
    return env


def run(work, command):
    ux, modules = load_state(work)
    if not command:
        sys.exit("run: give a unixnu command after --")
    env = reproducible_env() if command[0] in BUILD_COMMANDS else None
    if env:
        print(f"pipa_unixnu: KERNEL_BUILD_DATE={env['KERNEL_BUILD_DATE']} (SOURCE_DATE_EPOCH={env['SOURCE_DATE_EPOCH']})",
              file=sys.stderr)
    p = subprocess.run(["./unixnu", *command, *unixnu_args(modules)], cwd=ux, env=env)
    sys.exit(p.returncode)


def status(ux, modules, os_name):
    p = subprocess.run(["./unixnu", "status", "--json", "--os", os_name, *unixnu_args(modules)],
                       cwd=ux, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"unixnu status --os {os_name} failed:\n{p.stderr[-3000:]}")
    return json.loads(p.stdout[p.stdout.index("{"):])


def module_rows(st, unixnu, ux):
    """kind, name -> origin, checked-out revision, catalog pin. A module of a UniXNU copy is read at its
    place in the original checkout (the copy has no .git, so Git would answer for the enclosing repository)."""
    rows = {}
    copy = ux.resolve()
    for m in st["modules"]:
        rev, path = None, Path(m["path"]) if m.get("path") else None
        if path is not None:
            if path.resolve().is_relative_to(copy):
                path = unixnu.resolve() / path.resolve().relative_to(copy)
            top = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True).stdout.strip()
            if path.is_dir() and top and Path(top).resolve() == path.resolve():
                rev = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip() or None
        rows[(m["kind"], m["name"])] = {"origin": m["origin"], "revision": rev, "catalog_pin": m.get("pin"),
                                        "path": m["path"]}
    return rows


def parse_adt(blob):
    """Apple device tree -> {path: {property: bytes}} (node: property and child counts; property: 32-byte name,
    length with the placeholder bit, value padded to 4 bytes)."""
    import struct
    nodes = {}

    def walk(offset, parent):
        nprops, nchildren = struct.unpack_from("<II", blob, offset)
        offset += 8
        props = {}
        for _ in range(nprops):
            name = blob[offset:offset + 32].split(b"\0")[0].decode()
            length = struct.unpack_from("<I", blob, offset + 32)[0] & 0x7fffffff
            props[name] = blob[offset + 36:offset + 36 + length]
            offset += 36 + ((length + 3) & ~3)
        path = f"{parent}/{props.get('name', b'').rstrip(bytes(1)).decode()}".replace("//", "/")
        nodes[path] = props
        for _ in range(nchildren):
            offset = walk(offset, path)
        return offset

    walk(0, "")
    return nodes


def check_adt(ux, modules):
    """Compile dts/pipa.dts and run UniXNU's ADT generator on it in-process, as 'build payload' does, then compare
    the result with board.toml and the hardware facts of the DTS."""
    import struct
    if not shutil.which("dtc"):
        sys.exit("--adt needs dtc (apt install device-tree-compiler / brew install dtc)")
    sys.path.insert(0, str(ux / "scripts"))
    cwd = os.getcwd()
    os.chdir(ux)
    try:
        from unixnu.cli import parser
        from unixnu.config import Context
        from unixnu.devicetree import compile_hardware, generate
        ctx = Context(parser().parse_args(["status", "--os", DEFAULT_OS, *unixnu_args(modules)]))
        dtb = Path(compile_hardware(ctx)).resolve()
        adt = generate(dtb, ctx.board, unique_chip_id="0123456789abcdef")
    finally:
        os.chdir(cwd)
    # G2: the controller NativeUfs.cpp's probe() looks for, with the define the (patched) UFS recipes derive from
    # [board] soc, must be one the hardware tree's enabled UFS host carries.
    sys.path.insert(0, str(ROOT))
    from tools.hw.fdt import Tree
    import ufs_soc
    tree = Tree.load(dtb)
    ufs_compat = sorted({c for n in tree.nodes if tree.effectively_enabled(n)
                         for c in n.strings("compatible") if c.endswith("-ufshc")})
    soc = tomllib.loads((BOARD / "board.toml").read_text())["board"]["soc"]
    ufs_defines = ufs_soc.defines(soc)
    probe = ufs_probe_compatible(Path(modules[("driver", "ShengUfs")]) / "NativeUfs.cpp", ufs_defines)
    nodes = parse_adt(adt)
    board = tomllib.loads((BOARD / "board.toml").read_text())
    pay = board["payload"]

    def u32(path, name):
        v = nodes.get(path, {}).get(name)
        return struct.unpack("<I", v[:4])[0] if v and len(v) >= 4 else None

    def u64(path, name):
        v = nodes.get(path, {}).get(name)
        return struct.unpack("<Q", v[:8])[0] if v and len(v) >= 8 else None

    cpus = sorted(p for p in nodes if p.startswith("/device-tree/cpus/cpu"))
    found = {
        "dram-base": u64("/device-tree/chosen", "dram-base"),
        "dram-size": u64("/device-tree/chosen", "dram-size"),
        "darwinboot-memory-size": u64("/device-tree/chosen", "darwinboot-memory-size"),
        # The excluded-range table DarwinBoot fills (G6): its capacity in (base, size) pairs, 0 when absent.
        "darwinboot-memory-excluded": len(nodes.get("/device-tree/chosen", {}).get("darwinboot-memory-excluded", b"")) // 16,
        "chip-id": u32("/device-tree/chosen", "chip-id"),
        "kernel-ctrr-to-be-enabled": u32("/device-tree/chosen", "kernel-ctrr-to-be-enabled"),
        "vmm-present": u32("/device-tree/defaults", "vmm-present"),
        "sleep-disabled": u32("/device-tree/defaults", "sleep-disabled"),
        "cpus": [(nodes[p]["cluster-type"].rstrip(bytes(1)).decode(), u32(p, "reg"), u32(p, "timebase-frequency"))
                 for p in cpus],
        "intc": nodes.get("/device-tree/arm-io/intc", {}).get("compatible", b"").split(bytes(1))[0].decode(),
        "root_compatible": nodes["/device-tree"]["compatible"].split(bytes(1))[0].decode(),
        "ufs": {"defines": ufs_defines, "probe_compatible": probe, "dts_compatible": ufs_compat,
                "matches": probe in ufs_compat},
    }
    want = {
        "dram-base": 0x80000000,
        "dram-size": int(pay["dram_size"], 0),
        "darwinboot-memory-size": int(pay["adt"]["owned_memory_size"], 0),
        "darwinboot-memory-excluded": int(pay["adt"].get("owned_memory_excluded_ranges") or 0),
        "chip-id": int(pay["adt"]["chip_id"], 16),
        "kernel-ctrr-to-be-enabled": 0,
        "vmm-present": 1,
        "sleep-disabled": 1,
        # Four Cortex-A55 (E) then four Cortex-A77 (P), MPIDR 0x000..0x700 (Affinity1), the 19.2 MHz generic timer.
        "cpus": [("E", i << 8, 19200000) for i in range(4)] + [("P", i << 8, 19200000) for i in range(4, 8)],
        "intc": "arm,gic-v3",
        "ufs": {"defines": ["-DNATIVE_UFS_SM8250=1"], "probe_compatible": "qcom,sm8250-ufshc",
                "dts_compatible": ["qcom,sm8250-ufshc"], "matches": True},
    }
    wrong = {k: {"adt": found[k], "expected": v} for k, v in want.items() if found[k] != v}
    return {"dtb_bytes": Path(dtb).stat().st_size, "adt_bytes": len(adt), "nodes": len(nodes),
            "values": {k: (hex(v) if isinstance(v, int) and v > 0xffff else v) for k, v in found.items()},
            "wrong": wrong}


def check(args):
    ux, modules = prepare(args.unixnu, args.work, args.in_place)
    feeds = {(s["kind"], s["name"]): s["commit"] for s in feed_sources()}
    board = tomllib.loads((BOARD / "board.toml").read_text())
    prof = tomllib.loads((PROFILE / "profile.toml").read_text())
    errors = []
    if board["board"]["os_profile"] != DEFAULT_OS:
        errors.append(f"board.toml os_profile is {board['board']['os_profile']}, expected {DEFAULT_OS}")

    new = status(ux, modules, DEFAULT_OS)
    old = status(ux, modules, OVERRIDE_OS)
    b = new["board"]
    order = [Path(p).name for p in new["patch_order"]]
    expected = [p.name for _, p in cpc.chain(args.unixnu.resolve(), "tahoe-26.5")]
    rows = module_rows(new, args.unixnu, ux)
    res = {
        "profile": Path(new["profiles"].get("os", "")).name,
        "ipsw": [b["ipsw"]["product"], b["ipsw"]["version"], b["ipsw"]["build"]],
        "kernelcache_sha256": b["kernel"]["prelink"]["kernelcache_sha256"],
        "defconfig": b["kernel"].get("defconfig"),
        "patches": len(order),
        "patch_order_matches_check_patch_chain": order == expected,
        "darwin26_patches": [p for p in order if any(d in p for d in DARWIN26)],
        "components": sorted(c["id"] for c in new["components"]),
        "modules": {f"{k}:{n}": r for (k, n), r in sorted(rows.items())
                    if k in ("soc", "driver", "kit")},
        # patches/unixnu, as prepare() left them in the copy: reverse-applicable means present.
        "unixnu_patches": {pt.name: git_apply(ux, "--check", "--reverse", pt).returncode == 0 for pt in unixnu_patches()},
        "override": {
            "profile": Path(old["profiles"].get("os", "")).name,
            "ipsw": [old["board"]["ipsw"]["version"], old["board"]["ipsw"]["build"]],
            "patches": len(old["patch_order"]),
            "components": sorted(c["id"] for c in old["components"]),
            # The iPadOS 17 kernel does not read the excluded-range table, so its payload must not carry one.
            "owned_memory": {k: old["board"].get("payload", {}).get("adt", {}).get(k)
                             for k in ("owned_memory_size", "owned_memory_excluded_ranges")},
        },
    }
    if res["profile"] != DEFAULT_OS:
        errors.append(f"default profile resolved to {res['profile']}")
    if res["ipsw"][1:] != [prof["ipsw"]["version"], prof["ipsw"]["build"]]:
        errors.append(f"IPSW {res['ipsw']} is not the profile's")
    if res["kernelcache_sha256"] != prof["kernel"]["prelink"]["kernelcache_sha256"]:
        errors.append("kernelcache pin differs from profile.toml")
    if res["defconfig"] != "pipa_macos26_defconfig":
        errors.append(f"defconfig {res['defconfig']}")
    if res["darwin26_patches"]:
        errors.append(f"Darwin 26 patches in the 26.5 chain: {res['darwin26_patches']}")
    if not res["patch_order_matches_check_patch_chain"]:
        diff = [(i, a, e) for i, (a, e) in enumerate(zip(order, expected)) if a != e][:5]
        errors.append(f"patch order differs from check_patch_chain ({len(order)} vs {len(expected)}): {diff}")
    if res["override"]["profile"] != OVERRIDE_OS or res["override"]["ipsw"] != ["17.7.11", "21H461"]:
        errors.append(f"override resolved as {res['override']}")
    if not all(res["unixnu_patches"].values()):
        errors.append(f"UniXNU patches not in the copy: {res['unixnu_patches']}")
    if res["override"]["owned_memory"]["owned_memory_excluded_ranges"]:
        errors.append("the iPadOS override carries owned_memory_excluded_ranges, which its kernel does not read")
    # Every pinned source the default profile selects must come from its pin, not UniXNU's checkout.
    for key, commit in feeds.items():
        row = rows.get(key)
        if row is None:
            if key[0] == "soc":
                errors.append(f"SoC source {key[1]} not resolved")
            continue
        if row["revision"] != commit:
            errors.append(f"{key[0]}:{key[1]} resolved to {row['origin']} {row['revision']}, feeds.toml pins {commit}")
    for os_name, st in ((DEFAULT_OS, new), (OVERRIDE_OS, old)):
        rows_os = module_rows(st, args.unixnu, ux)
        for key, commit in feeds.items():
            if key in rows_os and rows_os[key]["revision"] != commit:
                errors.append(f"{os_name}: {key} at {rows_os[key]['revision']}, pinned {commit}")
    if args.xnu:
        res["xnu_apply"] = apply_order(args.xnu, new["patch_order"])
        if res["xnu_apply"]["failed"]:
            errors.append(f"patches failing on XNU: {res['xnu_apply']['failed']}")
    if args.adt:
        res["adt"] = check_adt(ux, modules)
        if res["adt"]["wrong"]:
            errors.append(f"ADT differs from board.toml / the DTS: {res['adt']['wrong']}")
    res["errors"] = errors
    print(json.dumps(res, indent=2))
    if args.json:
        args.json.write_text(json.dumps(res, indent=2) + "\n")
    if errors:
        sys.exit("devices/pipa did not resolve as expected:\n  " + "\n  ".join(errors))
    print(f"devices/pipa resolves: {DEFAULT_OS} with {res['patches']} patches, {OVERRIDE_OS} as override")


def apply_order(xnu, patch_order):
    import tempfile
    head = sh("git", "-C", xnu, "rev-parse", "HEAD", capture=True).strip()
    if head != cpc.XNU_REVISION:
        sys.exit(f"XNU is at {head}, expected {cpc.XNU_REVISION}")
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "xnu"
        sh("git", "clone", "-q", "--shared", xnu, work)
        for patch in patch_order:
            p = subprocess.run(["git", "-C", str(work), "apply", "--whitespace=nowarn", str(patch)],
                               capture_output=True, text=True)
            if p.returncode:
                failed.append(Path(patch).name)
                break
    return {"applied": len(patch_order) - len(failed), "total": len(patch_order), "failed": failed}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "check"):
        p = sub.add_parser(name)
        p.add_argument("--unixnu", type=Path, default=ROOT / "third_party/UniXNU")
        p.add_argument("--work", type=Path, default=DEFAULT_WORK)
        p.add_argument("--in-place", action="store_true",
                       help="install the profile into --unixnu itself (a Git checkout of its own) instead of a copy")
        if name == "check":
            p.add_argument("--xnu", type=Path)
            p.add_argument("--adt", action="store_true")
            p.add_argument("--json", type=Path)
    p = sub.add_parser("run")
    p.add_argument("--work", type=Path, default=DEFAULT_WORK)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    if args.cmd == "prepare":
        ux, modules = prepare(args.unixnu, args.work.resolve(), args.in_place)
        print(f"UniXNU with {DEFAULT_OS}: {ux}")
        for (k, n), path in sorted(modules.items()):
            print(f"  {k}:{n} -> {path}")
    elif args.cmd == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        run(args.work.resolve(), command)
    else:
        args.work = args.work.resolve()
        check(args)


if __name__ == "__main__":
    main()
