# Berkontribusi

1. Jalankan `scripts/test.sh` sebelum commit (dengan `XNU=` bila menyentuh `kernel/`).
2. Bila mengubah `kernel/fge` atau `kernel/xnu`, buat ulang patch: `python3 scripts/gen_xnu_patch.py <xnu checkout>`. Jangan mengedit file `.patch` dengan tangan.
3. Encoding instruksi di tes harus berasal dari `llvm-mc`, bukan angka yang diketik tangan.
4. Status di `docs/compatibility.md` hanya boleh naik menjadi WORKING dengan bukti: log perangkat di `docs/evidence/` dengan tanggal, revisi, dan perintah.
5. Jangan commit binary, firmware, atau isi IPSW Apple.
6. Setiap file sumber memakai header `SPDX-License-Identifier: BSD-2-Clause-Patent`.
7. Perbaikan yang berlaku untuk port pipa secara umum sebaiknya juga dikirim ke UniXNU-pipa/UniXNU upstream.
