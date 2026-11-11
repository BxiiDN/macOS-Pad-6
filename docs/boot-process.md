# Proses boot

Rantai yang sama dengan upstream UniXNU-pipa; repo ini tidak mengubah firmware.

1. **Xiaomi ABL** (bootloader harus di-unlock). `fastboot boot boot.img` memuat image ke RAM saja; partisi tidak ditulis.
2. **uefi-pipa**: Mu-Silicium untuk `pipaPkg` dengan UniXNU, UniXNUDxe, driver ramdisk, DarwinBoot (`third_party/uefi-pipa`, cabang `pipa`). Log firmware ditulis ke area ramoops stok.
3. **Menu UniXNU**: memilih payload dari volume `PIPAESP` di dalam boot image (ramdisk).
4. **DarwinBoot**: membangun Apple Device Tree (`make-pipa-adt.py`: GICv3 `0x17a00000`/`0x17a60000`, A55+A77, timebase 19,2 MHz), memuat kernel collection, lalu menyerahkan kendali ke XNU.
5. **XNU**: root dari UFS (`PipaUfs`), lalu launchd.

Pemulihan: tekan kombinasi tombol reset hardware → fastboot → `fastboot reboot bootloader`. Android tetap utuh selama hanya `fastboot boot` yang dipakai.

Untuk macOS ada satu langkah tambahan di host antara prelink dan payload: `pacstrip` + gerbang `audit` (lihat [architecture.md](architecture.md)).
