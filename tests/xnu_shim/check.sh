#!/bin/sh
# Syntax and type check of kernel/xnu/fge_xnu.c against the XNU shim headers,
# for arm64 (Mach-O, as XNU builds). Not a kernel build: see docs/testing.md.
# SPDX-License-Identifier: BSD-2-Clause-Patent
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/arm64"
cp "$root/kernel/fge/fge.h" "$root/kernel/xnu/fge_xnu.h" "$tmp/arm64/"
${CC:-clang} --target=arm64-apple-macos14 -mcpu=cortex-a77 -std=gnu11 -O2 -ffreestanding \
	-DKERNEL -Wall -Wextra -Werror -Wno-unused-parameter \
	-I "$tmp" -I "$here/include" -c "$root/kernel/xnu/fge_xnu.c" -o "$tmp/fge_xnu.o"
echo "fge_xnu.c: OK (shim headers, arm64 Mach-O)"
