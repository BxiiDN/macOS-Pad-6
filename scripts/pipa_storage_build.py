#!/usr/bin/env python3
"""Build pipa's arm64e source storage (G2) in the resolved tree of a finished kernel step, and check the archive.

    scripts/pipa_storage_build.py --unixnu UNIXNU [--tree TREE] [--modules M] [--json OUT]   (macOS runner, after build kernel)
    scripts/pipa_storage_build.py --plan                                            (any host: print the environment)

The archive is built, not linked: the macOS profile does not select ShengUfs, and CONFIG_XNU_NATIVE_UFS is not set, so
the kernel stays the same. What runs is UniXNU's own recipe (build-arm-driver.py ShengUfs -> build-sheng-source-storage.py
under arm64e) with patches/unixnu 0001 and 0003 applied by pipa_unixnu.py, in the tree whose compile records the
kernel step left, with the board's environment:
  UNIXNU_SOC from board.toml [board] soc (0001: -DNATIVE_UFS_SM8250=1),
  UNIXNU_SOURCE_STORAGE_ROOT from [storage] root (0003: no root policies, an all-zero anchor),
  UNIXNU_KIT from [board] kit (0003: the package sources are found under kits/pipa),
  UNIXNU_XNU_ARCH, UNIXNU_IOS_VERSION, UNIXNU_XNU_TARGET, UNIXNU_IPSW_BUILD from the OS profile.
The recipe's IOStorageFamily headers come from apple-oss-distributions/IOStorageFamily at the commit the recipe pins
(public source, cloned on the runner, not committed).

Checks on the archive (nm, strings): the pipa entry points are defined (native_source_storage_start,
native_source_root_policies_load, native_verified_block_root_authorized, boot_log_tick, boot_reset_bootloader,
native_ufs_source_create); NativeUfs was compiled with -DNATIVE_UFS_SM8250=1 (its recorded command line) and holds
no "qcom,sm8550-ufshc"; the root policy bundle is empty. A built archive proves compilation against xnu-12377 headers only, not that it works.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "devices/pipa/board.toml"
PROFILE = ROOT / "profiles/macos-26.5/unixnu/macos-26.5-25F71/profile.toml"
IOSTORAGE_GIT = "https://github.com/apple-oss-distributions/IOStorageFamily"
REQUIRED_SYMBOLS = ["native_source_storage_start", "native_source_storage_parent", "native_source_root_policies_load",
                    "native_verified_block_root_authorized", "native_verified_block_volume_device",
                    "native_verified_block_manifest_sha384", "boot_log_tick", "boot_reset_bootloader", "boot_reset_probe",
                    "native_ufs_source_create", "verified_root_policies", "verified_root_policy_count",
                    "pipa_storage_decision"]


def board_env():
    board = tomllib.loads(BOARD.read_text())
    prof = tomllib.loads(PROFILE.read_text())
    os_ = prof.get("os", {})
    return {
        "UNIXNU_SOC": board["board"]["soc"],
        "UNIXNU_SOURCE_STORAGE_ROOT": board.get("storage", {}).get("root", ""),
        "UNIXNU_KIT": board["board"]["kit"],
        "UNIXNU_XNU_ARCH": os_.get("arch", "arm64e"),
        "UNIXNU_IOS_VERSION": os_["ios_version"],
        "UNIXNU_XNU_TARGET": os_.get("target", "ios"),
        "UNIXNU_IPSW_BUILD": prof["ipsw"]["build"],
    }


def run(cmd, **kw):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if p.returncode:
        sys.exit(f"failed: {' '.join(map(str, cmd))}\n{(p.stdout + p.stderr)[-6000:]}")
    return p.stdout


def find_tree(unixnu):
    kernels = sorted(Path(unixnu, "out").rglob("mach.development.bcm2837.unstripped.noctf"))
    if not kernels:
        sys.exit(f"{unixnu}/out: no kernel step output (run build kernel first)")
    text = str(kernels[0])
    return Path(text[:text.index("/build/xnu/")])


def iostorage(tree):
    recipe = (tree / "scripts/build-sheng-source-storage.py").read_text()
    m = re.search(r"headers\.prepare\(storage, '([0-9a-f]{40})'", recipe)
    if not m:
        sys.exit("build-sheng-source-storage.py: no pinned IOStorageFamily commit")
    commit = m.group(1)
    dest = tree / "refer/IOStorageFamily"
    if dest.is_symlink() or (dest / ".git").exists():
        head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head == commit:
            return dest, commit
    if dest.is_symlink():
        dest.unlink()
    dest = tree / "refer/IOStorageFamily-pipa"
    if not (dest / ".git").exists():
        dest.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q", dest])
        run(["git", "-C", dest, "remote", "add", "origin", IOSTORAGE_GIT])
        run(["git", "-C", dest, "fetch", "-q", "--depth", "1", "origin", commit])
        run(["git", "-c", "advice.detachedHead=false", "-C", dest, "checkout", "-q", "FETCH_HEAD"])
    return dest, commit


# What the recipe reads besides the package: ShengUfs from the device tree (device / drivers/ShengUfs), the others from
# the recipe's own root (the directory above the script it runs). The macOS profile selects none of them, so the
# kernel step's tree may lack them: ShengUfs comes from the feeds.toml pin (pipa_unixnu.py's modules.json), the rest
# from the UniXNU checkout (its submodules).
RECIPE_INPUTS = {"drivers/ShengUfs": ("module", "driver:ShengUfs", "NativeUfs.cpp"),
                 "drivers/RamBlock": ("unixnu", "drivers/RamBlock", "NativeRamBlock.cpp"),
                 "drivers/VirtioMmioBlock": ("unixnu", "drivers/VirtioMmioBlock", None),
                 "kits/VerifiedRoot": ("unixnu", "kits/VerifiedRoot", "src/verified_root.c")}


def ensure_inputs(tree, unixnu, modules_json):
    """Link every RECIPE_INPUTS path the recipe will not find into TREE (and into the recipe's root when that is
    another directory). Returns {path: "present" | source linked}. Exits when a source is missing."""
    modules = json.loads(Path(modules_json).read_text())["modules"] if modules_json and Path(modules_json).is_file() else {}
    roots = {Path(tree).resolve(), (Path(tree) / "scripts/build-sheng-source-storage.py").resolve().parents[1]}
    done = {}
    for rel, (kind, key, probe) in RECIPE_INPUTS.items():
        for root in sorted(roots):
            dest = root / rel
            if dest.exists() and (probe is None or (dest / probe).is_file()) and any(dest.iterdir()):
                done.setdefault(rel, "present")
                continue
            src = Path(modules[key]) if kind == "module" and key in modules else (Path(unixnu) / key if unixnu else None)
            if src is None or not src.is_dir() or (probe and not (src / probe).is_file()):
                sys.exit(f"{rel}: not in {root} and no source for it ({kind} {key})")
            if dest.is_dir() and not dest.is_symlink() and any(dest.iterdir()):
                sys.exit(f"{dest}: exists without {probe}; not replaced")
            if dest.is_symlink() or (dest.is_dir() and not any(dest.iterdir())):
                dest.unlink() if dest.is_symlink() else dest.rmdir()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(src.resolve(), target_is_directory=True)
            done[rel] = str(src)
    return done


def compile_errors(log, context=3, limit=60):
    """The compiler's `error:` lines of LOG, each with the CONTEXT lines after it (the source line and caret)."""
    lines = log.splitlines()
    out = []
    for i, line in enumerate(lines):
        if re.search(r"\berror:", line):
            out += ["ERROR " + line] + lines[i + 1:i + 1 + context]
        if len(out) >= limit * (context + 1):
            break
    return out


def check_archive(tree):
    out = tree / "build/sheng-source-storage"
    archive = out / "libShengSourceStorage.a"
    if not archive.is_file():
        sys.exit(f"{archive}: not built")
    nm = run(["xcrun", "nm", "-gP", archive]).splitlines()
    defined = {line.split()[0].lstrip("_") for line in nm if len(line.split()) > 1 and line.split()[1] in "TSDBC"}
    missing = [s for s in REQUIRED_SYMBOLS if s not in defined]
    ufs = sorted(out.glob("NativeUfs*.o"))
    strings = "".join(run(["strings", "-a", o]) for o in ufs)
    # The SoC switch as the compiler saw it: the recipe writes each source's command line next to its object. The
    # literal itself may not survive in the object (the compiler can fold a short compare into immediates), so the
    # strings are reported but the command decides.
    command = out / "NativeUfs.command.json"
    args = json.loads(command.read_text()) if command.is_file() else []
    bundle = (out / "root-policies.bin").read_bytes() if (out / "root-policies.bin").is_file() else b""
    result = {"archive": str(archive), "bytes": archive.stat().st_size, "missing_symbols": missing,
              "ufs_defines": [a for a in args if a.startswith("-DNATIVE_UFS_")],
              "strings_sm8250": "qcom,sm8250-ufshc" in strings, "strings_sm8550": "qcom,sm8550-ufshc" in strings,
              "policy_bundle_bytes": len(bundle), "policy_count": int.from_bytes(bundle[16:24], "little") if len(bundle) >= 24 else None,
              "report": json.loads((out / "report.json").read_text()) if (out / "report.json").is_file() else None}
    problems = [f"undefined pipa entry points: {missing}"] if missing else []
    if "-DNATIVE_UFS_SM8250=1" not in result["ufs_defines"] or result["strings_sm8550"]:
        problems.append(f"NativeUfs was not compiled for SM8250 (defines {result['ufs_defines']})")
    if result["policy_count"] != 0:
        problems.append(f"root policy bundle holds {result['policy_count']} policies; pipa ships none")
    result["problems"] = problems
    return result


def archive_undefined(archive):
    """External symbols the archive's members reference and no member defines: what the kernel link must provide."""
    defined, undefined = set(), set()
    for line in run(["xcrun", "nm", "-gP", archive]).splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].endswith(":"):
            continue
        (undefined if parts[1] in "Uu" else defined).add(parts[0])
    return sorted(undefined - defined)


def map_members(link_map, archive_name="libShengSourceStorage.a"):
    """Members of ARCHIVE_NAME that ld64's link map lists among the linked object files ("[  n] path(member.o)")."""
    out = []
    if not Path(link_map).is_file():
        return None
    for line in Path(link_map).read_text(errors="replace").splitlines():
        if line.startswith("# Sections:"):
            break
        m = re.match(r"^\[\s*\d+\]\s+(.*)$", line)
        if m and archive_name in m.group(1):
            member = re.search(r"\(([^()]+)\)\s*$", m.group(1))
            out.append(member.group(1) if member else m.group(1))
    return out


def print_storage_errors(tree):
    """The compiler errors of the storage recipe's per-source logs (also when it ran inside the kernel step)."""
    for log in sorted((tree / "build/sheng-source-storage").rglob("*.log")):
        if log.name == "pipa-recipe.log":
            continue
        errors = compile_errors(log.read_text(errors="replace"))
        if errors:
            print(f"== {log.relative_to(tree)}")
            print("\n".join(errors))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unixnu", type=Path)
    ap.add_argument("--tree", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--modules", type=Path, default=Path(os.environ["WORK"]) / "modules.json" if os.environ.get("WORK") else None,
                    help="pipa_unixnu.py's modules.json (the feeds.toml checkouts); default $WORK/modules.json")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--check-only", action="store_true",
                    help="the kernel step built the archive (component:ShengUfs): check it, do not run the recipe again")
    ap.add_argument("--errors", action="store_true", help="only print the recipe's compiler errors (after a failed step)")
    ap.add_argument("--linked", choices=("yes", "no"),
                    help="check the kernel link map: the archive's members are (yes) or are not (no) in the kernel")
    args = ap.parse_args()
    env = board_env()
    if env["UNIXNU_SOURCE_STORAGE_ROOT"] != "none":
        sys.exit("board.toml [storage] root is not \"none\": pipa mounts no root from userdata")
    if args.plan:
        print(json.dumps(env, indent=2))
        return
    if args.errors:
        trees = sorted(Path(args.unixnu, "out").glob("*/*/*/tree")) if not args.tree else [args.tree]
        for tree in trees:
            print_storage_errors(tree)
        return
    tree = (args.tree or find_tree(args.unixnu)).resolve()
    if args.check_only:
        result = {"env": env, "mode": "built by the kernel step (component:ShengUfs)", **check_archive(tree)}
        finish(result, tree, args)
        return
    storage, commit = iostorage(tree)
    print(f"tree {tree}\nIOStorageFamily {commit} at {storage}")
    inputs = ensure_inputs(tree, args.unixnu, args.modules)
    print(f"recipe inputs: {json.dumps(inputs)}")
    full = dict(os.environ, **env)
    full["PATH"] = ":".join(p for p in ("/opt/homebrew/opt/llvm/bin", "/opt/homebrew/opt/lld/bin", full.get("PATH", "")) if p)
    recipe = [sys.executable, tree / "scripts/build-sheng-source-storage.py", "--tree", tree, "--storage-source", storage]
    p = subprocess.run([str(c) for c in recipe], cwd=tree, env=full, capture_output=True, text=True)
    (tree / "build/sheng-source-storage").mkdir(parents=True, exist_ok=True)
    (tree / "build/sheng-source-storage/pipa-recipe.log").write_text(p.stdout + p.stderr)
    print((p.stdout + p.stderr)[-4000:])
    if p.returncode:
        # The tail is mostly warnings; the job log is the only place the errors can be read (artifacts are not), so
        # every error line with the source line after it goes to stdout as well.
        print("\n".join(compile_errors(p.stdout + p.stderr)))
        # build-sheng-source-drivers.py keeps each source's whole compiler output in <stem>.log and raises with
        # only its last 5000 characters: the errors are in those files.
        print_storage_errors(tree)
        sys.exit(f"build-sheng-source-storage.py failed ({p.returncode})")
    result = {"env": env, "iostoragefamily": commit, "inputs": inputs, **check_archive(tree)}
    finish(result, tree, args)


def finish(result, tree, args):
    archive = Path(result["archive"])
    if archive.is_file():
        result["undefined"] = archive_undefined(archive)
        print(f"{len(result['undefined'])} symbols the kernel must provide: {' '.join(result['undefined'])}")
    if args.linked:
        members = map_members(tree / "build/kernel-link.map")
        result["linked_members"] = members
        if members is None:
            result["problems"].append("no kernel link map to check the link against")
        elif args.linked == "yes" and not {"SourceStorage.o", "NativeUfs.late.o"} <= set(members):
            result["problems"].append(f"the kernel link map lacks the storage objects (has {members})")
        elif args.linked == "no" and members:
            result["problems"].append(f"the generic kernel links storage objects: {members}")
        print(f"link map: {len(members or [])} members of libShengSourceStorage.a in the kernel: {members}")
    print(json.dumps({k: v for k, v in result.items() if k not in ("report", "undefined")}, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    if result["problems"]:
        sys.exit("source storage archive checks failed")


if __name__ == "__main__":
    main()
