# host audit (2026-11-11T02:22:04Z)

```
ProductName:		macOS
ProductVersion:		26.7.2
BuildVersion:		25G332
Darwin Kernel Version 25.6.0: Mon Oct 12 00:39:04 PDT 2026; root:xnu-12377.161.15.701.48~2/RELEASE_ARM64_VMAPPLE
VirtualMac2,1 Apple M1 (Virtual)
```

## dyld shared cache (arm64e, 3648 images, OS 26.7.0)

Files: dyld_shared_cache_arm64e, dyld_shared_cache_arm64e.01, dyld_shared_cache_arm64e.02.dylddata, dyld_shared_cache_arm64e.03.dyldreadonly, dyld_shared_cache_arm64e.04.dyldlinkedit, dyld_shared_cache_arm64e.05, dyld_shared_cache_arm64e.06.dylddata, dyld_shared_cache_arm64e.07.dyldreadonly, dyld_shared_cache_arm64e.08.dyldlinkedit, dyld_shared_cache_arm64e.09, dyld_shared_cache_arm64e.10.dylddata, dyld_shared_cache_arm64e.11, dyld_shared_cache_arm64e.12.dyldlinkedit, dyld_shared_cache_arm64e.atlas, dyld_shared_cache_arm64e.map, dyld_shared_cache_x86_64, dyld_shared_cache_x86_64.01, dyld_shared_cache_x86_64.02, dyld_shared_cache_x86_64.03, dyld_shared_cache_x86_64.04, dyld_shared_cache_x86_64.05, dyld_shared_cache_x86_64.06, dyld_shared_cache_x86_64.atlas, dyld_shared_cache_x86_64.map

Slide info versions: {5: 13}; executable bytes: 2951077628

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 15083492 | yes |
| pac-dp1 | PAuth | 11846358 | yes |
| fcadd | FCMA | 16239 | no |
| xar | SHA3 | 9037 | no |
| eor3-bcax | SHA3 | 5729 | no |
| fcmla-elem | FCMA | 5643 | no |
| fcmla | FCMA | 3392 | no |
| jscvt | JSCVT | 1009 | yes |
| sha512-rax1 | SHA512/SHA3 | 941 | no |
| pacga | PAuth | 724 | yes |
| sha512su0 | SHA512 | 256 | no |
| msr-dit | DIT | 101 | yes |
| dit-reg | DIT | 91 | yes |
| fmlal-elem | FHM | 56 | no |
| fmlal2-elem | FHM | 56 | no |
| pac-load | PAuth | 22 | yes |
| rcpc2 | LRCPC2 | 15 | yes |
| fmlal-vec | FHM | 8 | no |
| fmlal2-vec | FHM | 8 | no |
| sb | SB | 7 | yes |

Images containing each non-PAC rule:

- **jscvt** in 4 images: JavaScriptCore 523, JavaScriptCore 463, WebCore 12, WebCore 11
- **fcadd** in 1 images: libBLAS.dylib 16239
- **fcmla** in 4 images: libBLAS.dylib 3156, libSparseBLAS.dylib 228, VectorKit 4, ShazamKit 4
- **fcmla-elem** in 2 images: libBLAS.dylib 5642, libsystem_m.dylib 1
- **sb** in 7 images: dyld 1, libcorecrypto.dylib 1, libsystem_platform.dylib 1, libMobileGestalt.dylib 1, BootabilityBrain 1, libcorecrypto_noasm.dylib 1, libcorecrypto_trace.dylib 1
- **rcpc2** in 3 images: libsystem_m.dylib 11, libwebrtc.dylib 2, CryptexServer 2
- **msr-dit** in 7 images: libcorecrypto.dylib 30, libcorecrypto_noasm.dylib 30, libcorecrypto_trace.dylib 30, BootabilityBrain 5, dyld 2, libsystem_platform.dylib 2, libMobileGestalt.dylib 2
- **dit-reg** in 7 images: libcorecrypto.dylib 28, libcorecrypto_noasm.dylib 28, libcorecrypto_trace.dylib 28, BootabilityBrain 4, dyld 1, libsystem_platform.dylib 1, libMobileGestalt.dylib 1
- **eor3-bcax** in 67 images: Osprey 1140, AuthKit 1078, AppleAccount 1078, AOSKit 1078, libvMisc.dylib 145, AppleMediaServices 129, WebCore 112, libwebrtc.dylib 102
- **sha512-rax1** in 9 images: libcorecrypto.dylib 122, libcorecrypto_noasm.dylib 122, libcorecrypto_trace.dylib 122, libMobileGestalt.dylib 117, BootabilityBrain 117, dyld 112, libwebrtc.dylib 112, CryptexServer 112
- **xar** in 15 images: AuthKit 2197, AppleAccount 2197, AOSKit 2197, Osprey 2197, libcorecrypto.dylib 48, libcorecrypto_noasm.dylib 48, libcorecrypto_trace.dylib 48, libMobileGestalt.dylib 24
- **sha512su0** in 8 images: dyld 32, libcorecrypto.dylib 32, libMobileGestalt.dylib 32, libwebrtc.dylib 32, BootabilityBrain 32, CryptexServer 32, libcorecrypto_noasm.dylib 32, libcorecrypto_trace.dylib 32
- **fmlal-vec** in 1 images: libBNNS.dylib 8
- **fmlal2-vec** in 1 images: libBNNS.dylib 8
- **fmlal-elem** in 1 images: libBNNS.dylib 56
- **fmlal2-elem** in 1 images: libBNNS.dylib 56
- **pacga** in 7 images: Foundation 330, CoreGraphics 212, CoreFoundation 106, JavaScriptCore 35, JavaScriptCore 35, libobjc.A.dylib 4, libsystem_trace.dylib 2
- **pac-load** in 2 images: libc++abi.dylib 21, libsystem_m.dylib 1

Sample contexts (disassembly around hits; mnemonics only):

- jscvt: `blraa ; cbz ; ldr ; fjcvtzs ; ldr ; fjcvtzs ; orr`
- jscvt: `ldr ; b ; ldr ; fjcvtzs ; ldr ; fjcvtzs ; lsl`
- jscvt: `ldr ; fcmp ; b.vs ; fjcvtzs ; str ; ldp ; cmp`
- fcadd: `subs ; b.eq ; b ; fcadd ; fcadd ; fcadd ; fcadd`
- fcadd: `b.eq ; b ; fcadd ; fcadd ; fcadd ; fcadd ; fcadd`
- fcadd: `b ; fcadd ; fcadd ; fcadd ; fcadd ; fcadd ; fcadd`
- fcmla: `movi ; movi ; movi ; fcmla ; fcmla ; fcmla ; fcmla`
- fcmla: `movi ; fcmla ; fcmla ; fcmla ; fcmla ; fcmla ; fcmla`
- fcmla: `b.hs ; ldp ; movi ; fcmla ; fcmla ; movi ; fcmla`
- fcmla-elem: `ld1 ; ld1 ; ld1 ; fcmla ; fcmla ; fcmla ; fcmla`
- fcmla-elem: `ld1 ; ld1 ; fcmla ; fcmla ; fcmla ; fcmla ; fcmla`
- fcmla-elem: `ld1 ; fcmla ; fcmla ; fcmla ; fcmla ; fcmla ; fcmla`
- sb: `mrs ; ubfx ; msr ; sb ; ret ; tbnz ; msr`
- sb: `dsb ; isb ; ret ; sb ; ret ; mov ; movk`
- sb: `mrs ; ubfx ; msr ; sb ; ret ; tbnz ; msr`
- rcpc2: `umlal2 ; stnp ; ldapurh ; str  [3 undecodable]`
- rcpc2: `umlal2 ; stnp ; ldapurh ; str  [3 undecodable]`
- rcpc2: `str ; ldapur ; str  [4 undecodable]`
- msr-dit: `retab ; mrs ; ubfx ; msr ; sb ; ret ; tbnz`
- msr-dit: `tbz ; mrs ; tbnz ; msr ; mov ; b ; mov`
- msr-dit: `retab ; mrs ; ubfx ; msr ; sb ; ret ; tbnz`
- dit-reg: `ldp ; ldp ; retab ; mrs ; ubfx ; msr ; sb`
- dit-reg: `movk ; ldr ; tbz ; mrs ; tbnz ; msr ; mov`
- dit-reg: `tbnz ; mov ; b ; mrs ; cmp ; cset ; msr`
- eor3-bcax: `mov ; adrp ; add ; eor3 ; eor3 ; eor3 ; eor3`
- eor3-bcax: `eor3 ; eor3 ; eor3 ; eor3 ; eor3 ; eor3 ; eor3`
- eor3-bcax: `eor ; str ; ldr ; eor3 ; str ; subs ; b.ne`
- sha512-rax1: `add ; ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2`
- sha512-rax1: `eor3 ; rax1 ; rax1 ; rax1 ; rax1 ; rax1 ; xar`
- sha512-rax1: `add ; sha512su0 ; ext ; sha512h ; sha512su1 ; add ; sha512h2`
- xar: `rax1 ; rax1 ; rax1 ; xar ; xar ; xar ; xar`
- xar: `rax1 ; rax1 ; xar ; xar ; xar ; xar ; xar`
- xar: `eor ; eor ; xar ; xar ; xar ; xar ; xar`
- sha512su0: `ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1`
- sha512su0: `ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1`
- sha512su0: `ext ; ldr ; sha512h ; sha512su0 ; mov ; sha512h2 ; sha512su1`
- fmlal-vec: `fmul ; fmul ; stp ; fmlal ; fmlal2 ; fmlal ; add`
- fmlal-vec: `stp ; fmlal ; fmlal2 ; fmlal ; add ; add ; fmlal2`
- fmlal-vec: `ldp ; movi ; ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2`
- fmlal2-vec: `fmul ; stp ; fmlal ; fmlal2 ; fmlal ; add ; add`
- fmlal2-vec: `fmlal ; add ; add ; fmlal2 ; mov ; cmp ; b.ls`
- fmlal2-vec: `movi ; ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2 ; cbz`
- fmlal-elem: `ldr ; ldr ; ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2`
- fmlal-elem: `ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2 ; ldp ; fmlal`
- fmlal-elem: `fmlal ; fmlal2 ; ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2`
- fmlal2-elem: `ldr ; ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2 ; ldp`
- fmlal2-elem: `fmlal ; fmlal2 ; fmlal ; fmlal2 ; ldp ; fmlal ; fmlal2`
- fmlal2-elem: `fmlal2 ; ldp ; fmlal ; fmlal2 ; fmlal ; fmlal2 ; ldp`
- pacga: `b.lo ; mov ; ldr ; pacga ; sub ; cmp ; b.hi`
- pacga: `adrp ; add ; movk ; pacga ; adrp ; add ; bl`
- pacga: `and ; and ; mov ; pacga ; pacga ; lsr ; and`
- pac-load: `cbz ; ldr ; ldr ; ldraa ; mov ; mov ; mov`
- pac-load: `strh ; ldr ; ldr ; ldraa ; mov ; mov ; mov`
- pac-load: `cbz ; ldr ; ldr ; ldraa ; mov ; mov ; mov`

## Kernels

### kernel

fixups None; pacstrip {'rewritten': {}, 'left_for_fge': {}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |


### kernel.release.t6000

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 28601, 'pac-branch': 31568, 'pac-keyreg': 82}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31568 | yes |
| pac-dp1 | PAuth | 28601 | yes |
| pac-keyreg | PAuth | 82 | yes |
| pacga | PAuth | 42 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t6020

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23248, 'pac-branch': 31579, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31579 | yes |
| pac-dp1 | PAuth | 23248 | yes |
| rcpc2 | LRCPC2 | 592 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t6030

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23248, 'pac-branch': 31584, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31584 | yes |
| pac-dp1 | PAuth | 23248 | yes |
| rcpc2 | LRCPC2 | 594 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t6031

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23256, 'pac-branch': 31617, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31617 | yes |
| pac-dp1 | PAuth | 23256 | yes |
| rcpc2 | LRCPC2 | 594 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t6041

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23283, 'pac-branch': 31620, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31620 | yes |
| pac-dp1 | PAuth | 23283 | yes |
| rcpc2 | LRCPC2 | 594 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t6050

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 24275, 'pac-branch': 32521, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 48}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 32521 | yes |
| pac-dp1 | PAuth | 24275 | yes |
| rcpc2 | LRCPC2 | 606 | yes |
| pacga | PAuth | 48 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t8103

fixups {'ARM64E_KERNEL': 8}; pacstrip {'rewritten': {'pac-dp1': 28519, 'pac-branch': 31686, 'pac-keyreg': 102}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31686 | yes |
| pac-dp1 | PAuth | 28519 | yes |
| pac-keyreg | PAuth | 102 | yes |
| pacga | PAuth | 42 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 3 | yes |


### kernel.release.t8112

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23251, 'pac-branch': 31572, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31572 | yes |
| pac-dp1 | PAuth | 23251 | yes |
| rcpc2 | LRCPC2 | 592 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t8122

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23248, 'pac-branch': 31584, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31584 | yes |
| pac-dp1 | PAuth | 23248 | yes |
| rcpc2 | LRCPC2 | 594 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t8132

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 23275, 'pac-branch': 31588, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 31588 | yes |
| pac-dp1 | PAuth | 23275 | yes |
| rcpc2 | LRCPC2 | 594 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t8140

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 24188, 'pac-branch': 32414, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 42}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 32414 | yes |
| pac-dp1 | PAuth | 24188 | yes |
| rcpc2 | LRCPC2 | 601 | yes |
| pacga | PAuth | 42 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.t8142

fixups {'ARM64E_KERNEL': 6}; pacstrip {'rewritten': {'pac-dp1': 24267, 'pac-branch': 32491, 'pac-keyreg': 16}, 'left_for_fge': {'pacga': 48}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 32491 | yes |
| pac-dp1 | PAuth | 24267 | yes |
| rcpc2 | LRCPC2 | 606 | yes |
| pacga | PAuth | 48 | yes |
| pac-keyreg | PAuth | 16 | yes |
| dit-reg | DIT | 6 | yes |
| sb | SB | 1 | yes |


### kernel.release.vmapple

fixups {'ARM64E_KERNEL': 5}; pacstrip {'rewritten': {'pac-dp1': 28016, 'pac-branch': 30816}, 'left_for_fge': {'pacga': 17}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |
| pac-branch | PAuth | 30816 | yes |
| pac-dp1 | PAuth | 28016 | yes |
| pacga | PAuth | 17 | yes |
| dit-reg | DIT | 6 | yes |


## Kernel collections

### BootKernelExtensions.kc

fixups None; pacstrip {'rewritten': {}, 'left_for_fge': {}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |


### SystemKernelExtensions.kc

fixups None; pacstrip {'rewritten': {}, 'left_for_fge': {}}

| rule | feature | count | FGE |
| --- | --- | ---: | --- |


## Executables

| path | slices | fixups | non-PAC rules |
| --- | --- | --- | --- |
| /usr/lib/dyld | x86_64 arm64e | {'ARM64E_USERLAND24': 4} | {'sha512-rax1': 112, 'sha512su0': 32, 'msr-dit': 2, 'sb': 1, 'dit-reg': 1} |
| /sbin/launchd | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /usr/libexec/xpcproxy | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /bin/ls | x86_64 arm64e | {'ARM64E': 2} | - |
| /bin/zsh | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer | x86_64 arm64e | {'ARM64E_USERLAND24': 1} | - |
| /System/Library/CoreServices/Finder.app/Contents/MacOS/Finder | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /System/Library/CoreServices/Dock.app/Contents/MacOS/Dock | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /System/Library/CoreServices/SystemUIServer.app/Contents/MacOS/SystemUIServer | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /System/Applications/System Settings.app/Contents/MacOS/System Settings | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /Applications/Safari.app/Contents/MacOS/Safari | x86_64 arm64e | {'ARM64E_USERLAND24': 1} | - |
| /usr/libexec/amfid | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
| /usr/sbin/kextd | missing | | |
| /usr/libexec/kernelmanagerd | x86_64 arm64e | {'ARM64E_USERLAND24': 2} | - |
