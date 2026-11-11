#!/usr/bin/env bash
# Run every check that does not need the tablet. Used locally and by CI.
#   XNU=path/to/xnu  also checks that the committed XNU patch is current.
# SPDX-License-Identifier: BSD-2-Clause-Patent
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

echo "== host unit tests (FGE, ISA tools)"
python3 -m unittest discover -s tests -t . -p 'test_*.py' -v 2>&1 | tail -n 4

echo "== FGE cross-compile for AArch64 (Cortex-A77, no FP registers)"
mkdir -p build/target
for t in aarch64-none-elf arm64-apple-macos13; do
	clang --target="$t" -mcpu=cortex-a77 -std=c11 -O2 -ffreestanding -fno-builtin \
		-mgeneral-regs-only -DFGE_FREESTANDING -Wall -Wextra -Werror \
		-c kernel/fge/fge.c -o "build/target/fge-$t.o"
done
# FGE must not contain the instructions it emulates (it runs in their trap handler).
python3 -m tools.isa.audit build/target/fge-arm64-apple-macos13.o \
	--fail-on PAuth,JSCVT,FlagM,FlagM2,SB,LRCPC2,DIT
echo "fge.c: builds for aarch64-none-elf and arm64-apple-macos13, ARMv8.2-clean"

echo "== XNU glue compile check (shim headers)"
tests/xnu_shim/check.sh

echo "== device probe build"
scripts/build-probe.sh

if [ -n "${XNU:-}" ]; then
	echo "== XNU patch is current and applies"
	python3 scripts/gen_xnu_patch.py "$XNU" --check
	git -C "$XNU" apply --check "$root/kernel/patches/xnu-12377/0001-fge-undefined-instruction-emulation.patch"
	echo "patch applies to $(git -C "$XNU" describe --tags 2>/dev/null || git -C "$XNU" rev-parse HEAD)"
fi
echo "all checks passed"
