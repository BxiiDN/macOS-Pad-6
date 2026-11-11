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

# The null-PAC mode of profiles/macos-26.5 must compile; a PACGA-signed
# thread state (HAS_APPLE_PAC without HAS_NULL_PAC) must be refused.
${CC:-clang} --target=arm64-apple-macos14 -std=gnu11 -ffreestanding -DKERNEL \
	-DHAS_APPLE_PAC=1 -DHAS_NULL_PAC=1 -Wall -Wextra -Werror -Wno-unused-parameter \
	-I "$tmp" -I "$here/include" -fsyntax-only "$root/kernel/xnu/fge_xnu.c"
if ${CC:-clang} --target=arm64-apple-macos14 -std=gnu11 -ffreestanding -DKERNEL -DHAS_APPLE_PAC=1 \
	-I "$tmp" -I "$here/include" -fsyntax-only "$root/kernel/xnu/fge_xnu.c" 2>/dev/null; then
	echo "fge_xnu.c compiled with a signed thread state; it must not" >&2
	exit 1
fi
echo "fge_xnu.c: null-PAC mode OK, signed-state mode refused"

# Run the glue on the build host against a fake user address space.
${HOSTCC:-cc} -std=gnu11 -O1 -DKERNEL -DFGE_HOST_TEST -Wall -Wextra -Werror -Wno-unused-parameter \
	-I "$tmp" -I "$here/include" -o "$tmp/glue_host_test" \
	"$here/glue_host_test.c" "$root/kernel/xnu/fge_xnu.c" "$root/kernel/fge/fge.c"
"$tmp/glue_host_test"
