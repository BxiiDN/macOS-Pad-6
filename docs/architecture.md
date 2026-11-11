# Arsitektur

```
 Xiaomi ABL (fastboot boot, tidak menulis apa pun)
   └─ uefi-pipa (Mu-Silicium + UniXNU + DarwinBoot)        third_party/uefi-pipa
        └─ menu UniXNU → DarwinBoot memuat payload
             └─ XNU xnu-12377 (profil macOS UniXNU)         third_party/UniXNU
                  + patch FGE (repo ini)                    kernel/patches/xnu-12377
                  + driver pipa (UFS, CPU, touch, Adreno)   third_party/UniXNU-pipa
                  + kernel collection Mac17,11 (dari IPSW pengguna)
                       └─ diproses tools/isa/pacstrip, lalu
                          digerbangi tools/isa/audit --fail-on
             └─ userland macOS (dari IPSW pengguna)         masalah terbuka, feasibility.md §4
```

Repo ini tidak menduplikasi UniXNU atau UniXNU-pipa. Isinya hanya bagian yang belum ada di mana pun: lapisan yang membuat kode arm64e bisa berjalan di inti ARMv8.2.

## Komponen

| Path | Bahasa | Fungsi | Diuji |
| --- | --- | --- | --- |
| `kernel/fge/` | C (tanpa libc) | Emulator instruksi ARMv8.3–8.5: PAuth (null PAC), JSCVT, FlagM/FlagM2, SB, LRCPC2, DIT/SSBS, register kunci PAC | host: 24 tes di `tests/fge`, termasuk fuzz silang LLVM |
| `kernel/xnu/` | C | Glue XNU: dipanggil dari `sleh_synchronous()` untuk `ESR_EC_UNCATEGORIZED` | compile-check dengan shim header; **belum di-build di XNU** |
| `kernel/patches/xnu-12377/` | patch | Hasil `scripts/gen_xnu_patch.py`; apply bersih ke xnu `ac9718fb1af6` | `git apply --check` |
| `tools/isa/audit.py` | Python | Sensus instruksi yang butuh fitur yang tidak dimiliki SM8250, di Mach-O, fat, MH_FILESET, dyld shared cache | tes dengan Mach-O hasil llvm-mc |
| `tools/isa/pacstrip.py` | Python | Penulisan ulang statis PAC → ARMv8.2 yang setara | tes kesetaraan via decode LLVM |
| `tests/device/cpu_features_probe.c` | C (freestanding) | Membaca `AT_HWCAP` dan MIDR di tablet (Android, tanpa root) | dibangun; **belum dijalankan** di tablet |

## Alur build yang direncanakan (dengan UniXNU)

1. `unixnu fetch` / `build kernel` dengan profil macOS dan patch FGE ditambahkan ke seri patch board.
2. Setelah prelink: `python3 -m tools.isa.pacstrip kernelcache.prelinked out.kc`.
3. Gerbang: `python3 -m tools.isa.audit out.kc --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`. PACGA dan LDRAA berjangkauan jauh boleh tersisa karena FGE menanganinya.
4. `unixnu build payload` / `bootimg` seperti biasa; `fastboot boot`.

Langkah 2–3 belum terpasang ke `unixnu`. Itu butuh board pipa format 2 (lihat [roadmap.md](roadmap.md)).

## Keputusan desain

- **Null PAC, bukan PAC tiruan dengan kunci.** Meniru algoritma QARMA di software akan memberi proteksi, tetapi biayanya puluhan operasi per penandatanganan dan tetap mengharuskan setiap `RETAB` di-trap. Null PAC memungkinkan penulisan ulang statis yang menghilangkan trap sepenuhnya.
- **Integer-only di FGE.** FJCVTZS diimplementasikan dengan aritmetika bit, supaya aman dipanggil di konteks kernel tanpa menyimpan state FP kernel.
- **Gagal tertutup.** Instruksi yang tidak dikenal FGE kembali ke jalur asli XNU (SIGILL untuk user, panic untuk kernel). Akses memori yang gagal tidak mengubah state.
- **`fge=0`** di boot-args mematikan hook; `fge=2` mencatat setiap 2^20 trap per kelas.
- **Tidak ada signed thread state.** Glue menulis saved state langsung dan menolak dikompilasi bila `HAS_APPLE_PAC` aktif.
