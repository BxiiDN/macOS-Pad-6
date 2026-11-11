# Pengujian

```sh
scripts/test.sh          # semua tes host, cross-compile, probe, cek patch (bila XNU tersedia)
```

Butuh: Python ≥ 3.11, clang dengan target AArch64, `llvm-mc`, `ld.lld`. Encoding instruksi di tes **dihasilkan oleh llvm-mc saat tes berjalan**, bukan diketik tangan.

| Tes | Yang dibuktikan | Yang tidak dibuktikan |
| --- | --- | --- |
| `tests/fge/test_fge.py` | Semantik setiap instruksi FGE terhadap model Python independen: FJCVTZS (model rasional dari pseudocode Arm, 40.000+ vektor), flag (tabel kebenaran lengkap), LRCPC2 semua ukuran/sign-extension, LDRAA offset/writeback, state tidak berubah saat fault | Perilaku di CPU nyata |
| `tests/fge/test_fge_fuzz.py` | Decoder FGE dan disassembler LLVM sepakat pada 28.000 encoding acak di sekitar setiap kelas | Encoding di luar sampel |
| `tests/isa/test_isa.py` | Mask fitur sepakat dengan LLVM; setiap rewrite pacstrip setara (decode LLVM sebelum/sesudah); data-in-code utuh; parsing fat, MH_FILESET, dyld cache | Kernel collection Apple asli |
| `tests/xnu_shim/check.sh` | Glue XNU lolos compile dengan deklarasi yang disalin dari xnu-12377.121.6 | Build kernel XNU sebenarnya |
| `scripts/gen_xnu_patch.py --check` | Patch yang di-commit sesuai sumber dan apply bersih ke xnu `ac9718fb1af6` | — |
| `tests/fge/test_fge_sha.py` | SHA3/SHA512 FGE = model Python; dengan `QEMU_SRC`, = helper QEMU (oracle, tidak di-commit) | — |
| `tests/isa/test_scan.py` | Scanner C (`scan.c`) = aturan Python, `rules.h` sesuai `features.py` | — |
| `tests/isa/test_inspect.py`, `test_ipsw.py` | Chained fixups, fileset, simbol, dyld cache multi-file + atribusi per image; ZIP64/CRC/IM4P/ADT | IPSW asli (dikerjakan di workflow `tahoe-audit.yml`) |
| `tests/xnu_shim/glue_host_test.c` | Glue XNU di host: register, jalur atomic, saklar `fge=` | Build XNU sebenarnya |
| `scripts/check_patch_chain.py --profile tahoe-26.5` | Rantai patch pipa Tahoe 26.5 apply 121/121 | Build kernel |
| `scripts/pipa_unixnu.py check --adt --xnu XNU` | `devices/pipa` di-resolve UniXNU untuk 26.5 dan iPadOS 17; urutan patch board = rantai di atas dan apply; SoC/ArmCpu dari pin `feeds.toml`; DTS → ADT dengan nilai `board.toml` | Build kernel, payload |
| `scripts/check_tahoe_profile.py` | Profil 26.5 juga di-resolve di board UniXNU-sheng (pembanding) | Build payload |
| `scripts/pipa_hw.py check` | 52 konstanta perangkat keras kode board (header, `*.c`/`*.cpp`, `board.toml`, `pipa.dts` + feed SoC) = DT mainline Linux `sm8250-xiaomi-pipa.dts`; uji negatif: satu konstanta diubah → gagal | Perangkat keras berperilaku sesuai DT; driver bekerja |
| `scripts/pipa_hw.py inventory --check` | `docs/evidence/hardware/pipa-mainline-inventory.md` sesuai DT mainline yang dipin | — |
| `tests/hw/test_fdt.py` | Parser FDT (range bertingkat, interrupt-parent ala Linux, `interrupts-extended`, phandle, label), ekspansi stream SMMU, PPID SPMI, pembaca konstanta | — |
| `scripts/test_board_package.sh` | Host test paket board pipa: tombol, gestur, daya GPU, baterai, touch, backlight (x86 dan arm64), urutan GMU A650 (arm64 saja) terhadap register yang dimodelkan | Perilaku chip di tablet |
| `build/device/cpu_features_probe` | Dibangun sebagai ELF static-PIE AArch64 tanpa relokasi | Hasil di tablet (belum dijalankan) |

## Uji di perangkat (non-destruktif)

Hanya probe yang aman dijalankan sekarang:

```sh
adb push build/device/cpu_features_probe /data/local/tmp/
adb shell /data/local/tmp/cpu_features_probe
```

Probe hanya membaca `/proc/self/auxv` dan sysfs. Simpan output ke `docs/evidence/`.

Repo ini tidak melakukan flashing otomatis. `fastboot boot` tidak menulis apa pun ke tablet. `fastboot flash userdata` (dibutuhkan root image UniXNU) **menghapus data Android**: cadangkan dulu.
