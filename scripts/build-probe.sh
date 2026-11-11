#!/bin/sh
# Build tests/device/cpu_features_probe.c as a static-PIE AArch64 ELF that runs
# under Android without libc. Output: build/device/cpu_features_probe
# SPDX-License-Identifier: BSD-2-Clause-Patent
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$root/build/device"
out="$root/build/device/cpu_features_probe"
${CC:-clang} --target=aarch64-linux-android29 -mcpu=cortex-a55 -O2 -ffreestanding -fno-builtin \
	-fno-stack-protector -fPIE -nostdlib -static-pie -fuse-ld=lld -Wl,--no-dynamic-linker \
	-Wall -Wextra -Werror -o "$out" "$root/tests/device/cpu_features_probe.c"
# A static-PIE without a loader must not need run-time relocations.
if llvm-readelf -r "$out" 2>/dev/null | grep -q "Relocation section"; then
	echo "probe has relocations; it would crash without a dynamic loader" >&2
	exit 1
fi
echo "built $out"
