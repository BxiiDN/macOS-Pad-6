# Arsitektur

```
 Xiaomi ABL (fastboot boot, tidak menulis apa pun)
   └─ uefi-pipa (Mu-Silicium + UniXNU + DarwinBoot)        third_party/uefi-pipa
        └─ menu UniXNU → DarwinBoot memuat payload
             └─ XNU xnu-12377.121.6 (profil macos-26.5-25F71) profiles/macos-26.5/unixnu
                  + seri SoC SM8250 + null-PAC + FGE        profiles/macos-26.5
                  + driver pipa (UFS, CPU, touch, Adreno)   third_party/UniXNU-pipa
                  + kernelcache Tahoe 26.5 J274AP (dari IPSW pengguna)
                       └─ diproses tools/isa/pacstrip, lalu
                          digerbangi tools/isa/audit --fail-on
             └─ userland macOS (dari IPSW pengguna)         masalah terbuka, feasibility.md §4
```

Repo ini tidak menduplikasi UniXNU atau UniXNU-pipa. Isinya hanya bagian yang belum ada di mana pun: lapisan yang membuat kode arm64e bisa berjalan di inti ARMv8.2.

## Komponen

| Path | Bahasa | Fungsi | Diuji |
| --- | --- | --- | --- |
| `kernel/fge/` | C (tanpa libc) | Emulator instruksi ARMv8.3–8.5: PAuth (null PAC), JSCVT, FlagM/FlagM2, SB, LRCPC2, DIT/SSBS, SHA3, SHA512, register kunci PAC | host: `tests/fge`, termasuk fuzz silang LLVM dan oracle QEMU untuk SHA |
| `kernel/xnu/` | C | Glue XNU: dipanggil dari `sleh_synchronous()` untuk `ESR_EC_UNCATEGORIZED` | compile-check dengan shim header; **belum di-build di XNU** |
| `kernel/patches/xnu-12377/` | patch | Hasil `scripts/gen_xnu_patch.py`; apply bersih ke xnu `ac9718fb1af6` | `git apply --check` |
| `tools/isa/audit.py` | Python | Sensus instruksi yang butuh fitur yang tidak dimiliki SM8250, di Mach-O, fat, MH_FILESET, dyld shared cache | tes dengan Mach-O hasil llvm-mc |
| `tools/isa/pacstrip.py` | Python | Penulisan ulang statis PAC → ARMv8.2 yang setara | tes kesetaraan via decode LLVM |
| `profiles/macos-26.5/` | TOML | Profil OS UniXNU Tahoe 26.5 (dibuat `scripts/make_tahoe_profile.py` dari bukti IPSW) | `unixnu status` |
| `devices/pipa/` | TOML + DTS + patch | Board pipa format 2: profil default 26.5, lapisan SoC arm64e, patch `zzyf-pipa-amp`, `null-pac-armv82`, `fge-armv82` | `scripts/pipa_unixnu.py check`, rantai 119/119 `git apply` |
| `tools/isa/ipsw.py`, `inspect_macho.py`, `tahoe_audit.py`, `scan.c` | Python + C | Baca IPSW resmi via HTTP range; dyld cache multi-file; sensus per image | tes host; dijalankan pada biner asli di `tahoe-audit.yml` |
| `tests/device/cpu_features_probe.c` | C (freestanding) | Membaca `AT_HWCAP` dan MIDR di tablet (Android, tanpa root) | dibangun; **belum dijalankan** di tablet |

## Alur build yang direncanakan (dengan UniXNU)

1. `unixnu fetch` / `build kernel` dengan profil macOS dan patch FGE ditambahkan ke seri patch board.
2. Setelah prelink: `python3 -m tools.isa.pacstrip kernelcache.prelinked out.kc`.
3. Gerbang: `python3 -m tools.isa.audit out.kc --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`. PACGA dan LDRAA berjangkauan jauh boleh tersisa karena FGE menanganinya.
4. `unixnu build payload` / `bootimg` seperti biasa; `fastboot boot`.

Board pipa format 2 sudah ada (`devices/pipa`, [board-migration.md](board-migration.md)) dan memasang patch null-PAC/FGE di seri device-nya. Build kernel belum dijalankan ([kernel-build.md](kernel-build.md)); `pacstrip` pada kernelcache juga belum terpasang ke langkah prelink `unixnu`.

## Keputusan desain

- **Null PAC, bukan PAC tiruan dengan kunci.** Meniru algoritma QARMA di software akan memberi proteksi, tetapi biayanya puluhan operasi per penandatanganan dan tetap mengharuskan setiap `RETAB` di-trap. Null PAC memungkinkan penulisan ulang statis yang menghilangkan trap sepenuhnya.
- **Integer-only di FGE.** FJCVTZS diimplementasikan dengan aritmetika bit, supaya aman dipanggil di konteks kernel tanpa menyimpan state FP kernel.
- **Gagal tertutup.** Instruksi yang tidak dikenal FGE kembali ke jalur asli XNU (SIGILL untuk user, panic untuk kernel). Akses memori yang gagal tidak mengubah state.
- **`fge=0`** di boot-args mematikan hook; `fge=2` mencatat setiap 2^20 trap per kelas.
- **Kernel tetap `HAS_APPLE_PAC`, kunci dimatikan (`HAS_NULL_PAC`).** XNU hanya menerima biner arm64e bila subtype host ARM64E, yang butuh `HAS_APPLE_PAC`. Patch null-PAC mempertahankan jalur itu tetapi mengganti hash thread state (5 PACGA per exception) dengan konstanta nol dan tidak memprogram kunci, sehingga handler exception tidak pernah trap ke dirinya sendiri.
- **Tidak ada signed thread state.** Glue menulis saved state langsung; ia menolak dikompilasi bila `HAS_APPLE_PAC` aktif tanpa `HAS_NULL_PAC`.
- **Akses memori teremulasi bersifat atomic** bila alamatnya natural-aligned (`copyin_atomic32/64`), sesuai single-copy atomicity instruksi aslinya.
