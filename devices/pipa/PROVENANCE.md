# Provenance

`package/`, `scripts/`, `configs/pipa_defconfig`, `README.md`, `LICENSE`, `.gitignore` and `.gitattributes` are copied
unchanged from [xVanTuring/UniXNU-pipa](https://github.com/xVanTuring/UniXNU-pipa) at `cdb3d62771e3` (BSD-2-Clause-Patent,
UniXNU contributors; `package/ShengPlatformPower.cpp` is MIT per its own header). They carry the upstream headers, not this
repository's SPDX lines.

The format 1 `board.toml` and `unixnu.lock` of that commit are kept as
`docs/evidence/board-migration/board-before.toml` and `unixnu-before.lock`; `before.json` is `unixnu status --json` of
that board with UniXNU 3fd6a3c.

New in this directory (format 2 migration, work in progress): `board.toml`, `feeds.toml`, `dts/pipa.dts`,
`configs/pipa_macos26_defconfig`, `patches/xnu/series`, `patches/xnu-12377/` (the SoC layer, `zzyf-pipa-amp.patch`
from UniXNU-sheng c7a0346, and the generated null-PAC and FGE patches moved from `profiles/macos-26.5/patches`).
