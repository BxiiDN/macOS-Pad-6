#!/usr/bin/env bash
# UniXNU on devices/pipa (Xiaomi Pad 6, macOS Tahoe 26.5 by default). Wrapper of scripts/pipa_unixnu.py:
#   scripts/pipa-unixnu.sh prepare                  UniXNU copy with the 26.5 profile, feeds.toml sources at their pins
#   scripts/pipa-unixnu.sh check [--adt] [--xnu X]  resolve both OS profiles of the board and check them
#   scripts/pipa-unixnu.sh status --os macos-26.5-25F71
#   scripts/pipa-unixnu.sh <any unixnu command>     runs it with -D devices/pipa and the pinned local modules
# Nothing here flashes a device; "unixnu bootimg" only writes files under build/pipa-unixnu.
# SPDX-License-Identifier: BSD-2-Clause-Patent
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
case "${1:-}" in
"" | -h | --help) exec python3 "$root/scripts/pipa_unixnu.py" --help ;;
prepare | check | run) exec python3 "$root/scripts/pipa_unixnu.py" "$@" ;;
*) exec python3 "$root/scripts/pipa_unixnu.py" run -- "$@" ;;
esac
