# ipsw-kernelcache audit (2026-11-11T02:22:16Z)

26.5 (25F71), j274ap, `kernelcache.release.mac13g`

- kernelcache SHA-256 (decompressed): `19ae26f46899eb893052436482ac7a7cbf3bbb2b7b0c46b964a849c14442d137`
- IM4P SHA-256: `395e16568e084a205226684a1e45ae0f255cfb579c8034be5ef7424fae04c554`
- fileset entries: 346
- early_security_init: `com.apple.driver.AppleMobileFileIntegrity=0xfffffe00096f17cc`
- fixups: {'64_KERNEL_CACHE': 2}
- pacstrip: {'rewritten': {'pac-dp1': 380640, 'pac-branch': 397598, 'pac-keyreg': 102}, 'left_for_fge': {'pacga': 42}}

UniXNU macOS 27.3 prelink roots present: 67/67; missing: none

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 397598 | yes |
| pac-dp1 | PAuth | 380640 | yes |
| eor3-bcax | SHA3 | 209 | no |
| sha512-rax1 | SHA512/SHA3 | 122 | no |
| pac-keyreg | PAuth | 102 | yes |
| xar | SHA3 | 48 | no |
| pacga | PAuth | 42 | yes |
| sha512su0 | SHA512 | 32 | no |
| dit-reg | DIT | 16 | yes |
| msr-dit | DIT | 11 | yes |
| sb | SB | 4 | yes |
| rcpc2 | LRCPC2 | 4 | yes |

- eor3-bcax: `mul ; mul ; mul ; eor3 ; eor3 ; eor3 ; eor3`
- eor3-bcax: `mul ; mul ; eor3 ; eor3 ; eor3 ; eor3 ; tbl`
- eor3-bcax: `mul ; eor3 ; eor3 ; eor3 ; eor3 ; tbl ; str`
- sha512-rax1: `eor3 ; eor3 ; eor3 ; rax1 ; rax1 ; rax1 ; rax1`
- sha512-rax1: `sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1 ; add ; add`
- sha512-rax1: `sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1 ; add ; add`
- xar: `rax1 ; rax1 ; rax1 ; xar ; xar ; xar ; xar`
- xar: `xar ; xar ; xar ; xar ; xar ; xar ; xar`
- xar: `xar ; xar ; xar ; xar ; xar ; xar ; eor`
- sha512su0: `ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1`
- sha512su0: `ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1`
- sha512su0: `ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1`
