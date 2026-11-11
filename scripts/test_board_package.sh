#!/usr/bin/env bash
# Build and run the host tests of devices/pipa/package (UniXNU-pipa's board code). Used by CI on x86 and arm64.
# A650GmuTests needs UniXNU's AdrenoFirmware kit and an AArch64 host; elsewhere it is reported as skipped.
# SPDX-License-Identifier: BSD-2-Clause-Patent
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
pkg="$root/devices/pipa/package"
out="$root/build/board-package"
mkdir -p "$out"
cc=${CC:-cc}
flags=(-std=gnu11 -O2 -Wall -Wextra -Werror)
pass=0
for t in BacklightBoardTests ButtonsTests GeniI2cTests GesturesTests GpuPowerBoardTests NativeBatteryTests PanelBoardTests PipaStorageGuardTests PowerSupplyBoardTests TouchBoardTests TouchVendorTests; do
	"$cc" "${flags[@]}" -o "$out/$t" "$pkg/$t.c"
	"$out/$t"
	pass=$((pass + 1))
done
# The backlight kernel shim on a simulated tablet (two sources), and the same file in kernel mode against the XNU shim
# headers of tests/xnu_shim (a syntax and type check for arm64, not a kernel build).
"$cc" "${flags[@]}" -o "$out/PipaBacklightTests" "$pkg/PipaBacklightTests.c" "$pkg/PipaBacklight.c"
"$out/PipaBacklightTests"
pass=$((pass + 1))
if command -v clang >/dev/null; then
	clang --target=arm64-apple-macos14 -mcpu=cortex-a77 -std=gnu11 -ffreestanding -DKERNEL -Wall -Wextra -Werror \
		-I "$root/tests/xnu_shim/include" -fsyntax-only "$pkg/PipaBacklight.c"
	echo "PipaBacklight.c: kernel mode OK (XNU shim headers, arm64)"
fi
kit="$root/third_party/UniXNU/kits/AdrenoFirmware"
if [ "$(uname -m)" = aarch64 ] || [ "$(uname -m)" = arm64 ]; then
	if [ ! -f "$kit/AdrenoHfi.c" ]; then
		git -C "$root" submodule update --init --depth 1 third_party/UniXNU
		git -C "$root/third_party/UniXNU" submodule update --init --depth 1 kits/AdrenoFirmware
	fi
	"$cc" -std=gnu11 -O2 -Wall -Wextra -I "$kit" -o "$out/A650GmuTests" "$pkg/A650GmuTests.c" "$pkg/A650Gmu.c" \
		"$kit/AdrenoFirmware.c" "$kit/AdrenoHfi.c" "$kit/AdrenoHfiStartup.c" "$kit/AdrenoHfiVotes.c"
	"$out/A650GmuTests"
	pass=$((pass + 1))
else
	echo "SKIP: A650GmuTests (AdrenoFirmware's HFI transport builds for AArch64 only; this host is $(uname -m))"
fi
echo "board package: $pass host tests passed"
