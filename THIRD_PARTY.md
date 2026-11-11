# Komponen pihak ketiga

| Komponen | Sumber | Lisensi | Cara dipakai |
| --- | --- | --- | --- |
| UniXNU | github.com/UniXNU/UniXNU @ `3fd6a3cf0e6f` | BSD-2-Clause-Patent | submodul `third_party/UniXNU`; build driver, profil macOS |
| UniXNU-pipa | github.com/xVanTuring/UniXNU-pipa @ `cdb3d62771e3` | BSD-2-Clause-Patent (sebagian MIT) | submodul `third_party/UniXNU-pipa`; board dan driver pipa |
| uefi-pipa | github.com/xVanTuring/uefi-pipa @ `1f6a1520f84c` (cabang `pipa`) | BSD-2-Clause-Patent | submodul `third_party/uefi-pipa`; firmware |
| XNU | github.com/apple-oss-distributions/xnu @ `ac9718fb1af6` (xnu-12377.121.6) | APSL 2.0 | target patch `kernel/patches/xnu-12377`; tidak disalin ke repo ini. `tests/xnu_shim` menyalin beberapa deklarasi struct/makro untuk compile-check |
| LLVM (llvm-mc) | sistem build | Apache-2.0 WITH LLVM-exception | alat tes saja; tidak didistribusikan |

Tidak ada kode proprietary Apple, firmware vendor, atau isi IPSW di repo ini. CI menolak commit dengan ekstensi binary payload.
