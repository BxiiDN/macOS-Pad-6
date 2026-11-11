#!/usr/bin/env python3
"""Generate the ARMv8.2 layer of the pipa macOS 26.5 kernel on top of the rest of its chain.

    scripts/gen_tahoe_patches.py --xnu XNU --unixnu UNIXNU [--check]

Base state: xnu-12377.121.6 (macOS 26.5's kernel source) + every patch that
devices/pipa/board.toml applies before these two (scripts/check_patch_chain.py
--profile tahoe-26.5: UniXNU's arm64e series, the pipa SoC layer, the macOS 26.5
OS series, zzyf-pipa-amp). On top of it this writes, into
devices/pipa/patches/xnu-12377:

  xnu-12377/null-pac-armv82.patch   HAS_NULL_PAC: arm64e ABI without PAC keys
  xnu-12377/fge-armv82.patch        FGE in sleh_synchronous (kernel/fge, kernel/xnu)

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_patch_chain as cpc  # noqa: E402

OUT = ROOT / "devices/pipa/patches/xnu-12377"
PATCHES = ("null-pac-armv82.patch", "fge-armv82.patch")


def git(work, *args):
    return subprocess.run(["git", "-c", "user.name=gen", "-c", "user.email=gen@localhost", *args],
                          cwd=work, check=True, capture_output=True, text=True).stdout


def edit(path, old, new, count=1):
    text = path.read_text()
    n = text.count(old)
    if n != count:
        sys.exit(f"{path}: anchor found {n} times, expected {count}:\n{old}")
    path.write_text(text.replace(old, new))


NULL_PAC_BCM = """#if defined(__arm64e__)
#define HAS_APPLE_PAC             1
#define HAS_NATIVE_PAC            1
#endif"""
NULL_PAC_BCM_NEW = """#if defined(__arm64e__)
#define HAS_APPLE_PAC             1
/*
 * macOS-Pad-6: the board has no FEAT_PAuth (ARMv8.2 cores, e.g. Kryo 585 in
 * SM8250). The arm64e ABI stays (arm64e processes and kexts), and pointer
 * authentication is the identity ("null PAC"): no key registers, no SCTLR key
 * enables, no PACGA in the thread-state hash. Compiler-emitted PAC is rewritten
 * by tools/isa/pacstrip; what remains traps to FGE. PAC gives no protection.
 */
#define HAS_NULL_PAC              1
#define HAS_NATIVE_PAC            0
#endif"""

HASH_OLD = """.macro COMPUTE_THREAD_STATE_HASH
"""
HASH_NEW = """.macro COMPUTE_THREAD_STATE_HASH
#if HAS_NULL_PAC
	/* No PACGA on this CPU: a constant hash, so sign and check always agree. */
	mov		x1, #0
#else
"""
HASH_END_OLD = """	bfxil   x17, x1, #0, #32			/* add binding state */
	pacga	x1, x17, x5					/* X17(x5) hash (gkey + x16 hash) */
.endm"""
HASH_END_NEW = """	bfxil   x17, x1, #0, #32			/* add binding state */
	pacga	x1, x17, x5					/* X17(x5) hash (gkey + x16 hash) */
#endif /* HAS_NULL_PAC */
.endm"""

ADDRPERM_OLD = """LEXT(ml_addrperm_pacga)
	ARM64_PROLOG
"""
ADDRPERM_NEW = """LEXT(ml_addrperm_pacga)
	ARM64_PROLOG
#if HAS_NULL_PAC
	/* No PACGA: no permutation (it only hides addresses in logs). */
	orr		x0, x0, #0x1
	ret
#endif /* HAS_NULL_PAC */
"""
BLOB_OLD = """	ARM64_STACK_PROLOG
	PUSH_FRAME

	cbz		x0, Lsign_ret
"""
BLOB_NEW = """	ARM64_STACK_PROLOG
	PUSH_FRAME

#if HAS_NULL_PAC
	/* No PACGA: every blob signs to 0, so signing and checking agree. */
	mov		x0, #0
	b		Lsign_ret
#endif /* HAS_NULL_PAC */
	cbz		x0, Lsign_ret
"""
SCTLR_OLD = """#if   HAS_APPLE_PAC
#define SCTLR_PAC_KEYS_DEFAULT  SCTLR_PAC_KEYS_ENABLED"""
SCTLR_NEW = """#if   HAS_APPLE_PAC && !HAS_NULL_PAC
#define SCTLR_PAC_KEYS_DEFAULT  SCTLR_PAC_KEYS_ENABLED"""


def null_pac(work):
    edit(work / "pexpert/pexpert/arm64/BCM2837.h", NULL_PAC_BCM, NULL_PAC_BCM_NEW)
    asm = work / "osfmk/arm64/machine_routines_asm.s"
    edit(asm, HASH_OLD, HASH_NEW)
    edit(asm, HASH_END_OLD, HASH_END_NEW)
    edit(asm, ADDRPERM_OLD, ADDRPERM_NEW)
    edit(asm, BLOB_OLD, BLOB_NEW)
    # The no-op key switches of UniXNU's native PAC are right for null PAC too.
    edit(asm, "#if HAS_NATIVE_PAC\n\t/* The kernel and every process share one key set; nothing to switch. */",
         "#if HAS_NATIVE_PAC || HAS_NULL_PAC\n\t/* The kernel and every process share one key set; nothing to switch. */")
    edit(asm, "LEXT(ml_disable_user_jop_key)\n\tARM64_PROLOG\n#if HAS_NATIVE_PAC\n",
         "LEXT(ml_disable_user_jop_key)\n\tARM64_PROLOG\n#if HAS_NATIVE_PAC || HAS_NULL_PAC\n")
    edit(work / "osfmk/arm/machine_routines_apple.c", "#elif HAS_NATIVE_PAC\n",
         "#elif HAS_NATIVE_PAC || HAS_NULL_PAC\n")
    edit(work / "osfmk/arm64/proc_reg.h", SCTLR_OLD, SCTLR_NEW)


FGE_INCLUDE = "#include <pexpert/arm64/board_config.h>\n"
FGE_HOOK_OLD = ("#endif /* CONFIG_XNUPOST */\n"
                "\t\thandle_uncategorized(&context->ss);\n")
FGE_HOOK_NEW = ("#endif /* CONFIG_XNUPOST */\n"
                "\t\t/* ARMv8.3-8.5 instructions on ARMv8.2 cores (macOS-Pad-6 FGE). */\n"
                "\t\tif (fge_xnu_handle(context)) {\n"
                "\t\t\tbreak;\n"
                "\t\t}\n"
                "\t\thandle_uncategorized(&context->ss);\n")


def fge(work):
    edit(work / "osfmk/arm64/sleh.c", FGE_INCLUDE, FGE_INCLUDE + "#include <arm64/fge_xnu.h>\n")
    edit(work / "osfmk/arm64/sleh.c", FGE_HOOK_OLD, FGE_HOOK_NEW)
    edit(work / "osfmk/conf/files.arm64", "osfmk/arm64/sleh.c\t\t\tstandard\n",
         "osfmk/arm64/sleh.c\t\t\tstandard\nosfmk/arm64/fge.c\t\t\tstandard\n"
         "osfmk/arm64/fge_xnu.c\t\t\tstandard\n")
    for src, dst in (("kernel/fge/fge.c", "osfmk/arm64/fge.c"), ("kernel/fge/fge.h", "osfmk/arm64/fge.h"),
                     ("kernel/xnu/fge_xnu.c", "osfmk/arm64/fge_xnu.c"),
                     ("kernel/xnu/fge_xnu.h", "osfmk/arm64/fge_xnu.h")):
        shutil.copyfile(ROOT / src, work / dst)


HEADERS = {
    "null-pac-armv82.patch": "arm64e without FEAT_PAuth: null PAC (HAS_NULL_PAC)",
    "fge-armv82.patch": "arm64: emulate ARMv8.3-8.5 instructions on ARMv8.2 cores (FGE)",
}


def generate(xnu, unixnu):
    base = [p for origin, p in cpc.chain(unixnu, "tahoe-26.5") if p.name not in PATCHES]
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "xnu"
        subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "-q", "--shared", str(xnu),
                        str(work)], check=True)
        git(work, "checkout", "-q", cpc.XNU_REVISION)
        for p in base:
            git(work, "apply", "--whitespace=nowarn", str(p))
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "base")
        for name, step in (("null-pac-armv82.patch", null_pac), ("fge-armv82.patch", fge)):
            step(work)
            git(work, "add", "-A")
            diff = git(work, "diff", "--cached", "--no-color", "--no-ext-diff", "-U3")
            git(work, "commit", "-q", "-m", name)
            out[name] = (f"From: macOS-Pad-6 contributors\nSubject: [PATCH] {HEADERS[name]}\n\n"
                         f"Base: xnu {cpc.XNU_REVISION} (xnu-12377.121.6, macOS 26.5) + UniXNU arm64e\n"
                         "series + devices/pipa SoC layer + macOS 26.5 OS series (UniXNU macOS series\n"
                         "without the Darwin 26 patches) + zzyf-pipa-amp. Generated by\n"
                         "scripts/gen_tahoe_patches.py; do not edit.\n"
                         "\n---\n" + diff)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xnu", type=Path, required=True)
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    out = generate(args.xnu.resolve(), args.unixnu.resolve())
    stale = []
    for name, text in out.items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)} ({text.count(chr(10))} lines)")
    if stale:
        sys.exit(f"stale: {stale}; run scripts/gen_tahoe_patches.py")
    if args.check:
        print("tahoe patches up to date")


if __name__ == "__main__":
    main()
