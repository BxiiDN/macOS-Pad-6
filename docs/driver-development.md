# Pengembangan driver

Driver perangkat keras pipa **sudah ada** di UniXNU-pipa untuk iPadOS 17 dan tidak dibuat ulang di sini. Untuk macOS, setiap driver perlu diadaptasi mengikuti tabel adaptasi profil macOS UniXNU (`docs/porting/macos.md` §6), dengan UniXNU-sheng sebagai contoh kerja.

| Area | Komponen upstream | Adaptasi macOS yang diperlukan | Status |
| --- | --- | --- | --- |
| CPU, interrupt | `ArmCpu` (pipa) | Kompilasi arm64e; publikasikan hanya fitur yang ada di **kedua** cluster (A55 tanpa SSBS) | belum |
| Storage | `PipaUfs` | Binding kelas 26C5035r; tiga window root | belum |
| Display | `GopFramebuffer` + `LegacyDisplayProbe` | `IOMFBUUID`; frame half-float WindowServer (`fb-half=2` di sheng) | belum |
| Touch | `PipaNovatekTouch` + `QcomGeniSpi` | HID `offline-hid-home=1`; `displayUUID` dipasangkan ke framebuffer | belum |
| GPU | `Adreno650`, `AdrenoMetal` | Bundle macOS di `/Library/GPUBundles` (`gpu-addon=1`) | belum |
| Kripto | `SoftwareAES` | Dikompilasi terhadap layout kelas 26C5035r; probe board mendaftarkannya (AppleImage4 menunggu `IOAESAccelerator`) | belum |
| Baterai | `NativeBattery` | `IOPMPowerSource`; uji pertama di tablet | belum |
| Wi-Fi, Bluetooth, audio, USB host | tidak ada | Driver baru | belum |
| **Lapisan ISA** | **repo ini: FGE + pacstrip** | Prasyarat semua driver di atas pada inti ARMv8.2 | host-tested |

Aturan: setiap driver punya source, build test, dan validasi hardware sebelum statusnya berubah di [compatibility.md](compatibility.md).
