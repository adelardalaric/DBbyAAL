# Dashboard Operational Area MU42

Dashboard performa sales & insentif berbasis Streamlit, dibaca dari file LBP
(Laporan Buku Penjualan) dan file Target.

## Cara jalankan lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Cara deploy ke Streamlit Community Cloud

1. Push folder ini (`app.py`, `requirements.txt`, `.streamlit/config.toml`, `.gitignore`) ke repo GitHub.
2. Buka [share.streamlit.io](https://share.streamlit.io), hubungkan ke repo tersebut.
3. Set entrypoint ke `app.py`, deploy.
4. **Set password**: di halaman app kamu di Streamlit Cloud, buka Settings →
   Secrets, isi:
   ```toml
   APP_PASSWORD = "password-kamu-di-sini"
   ```
   Ini WAJIB kalau kamu mengaktifkan fitur "file yang pernah diupload"
   (poin di bawah), supaya file penjualan tidak bisa dilihat orang lain yang
   kebetulan tahu link app-nya. Kalau secret ini tidak diisi, dashboard bisa
   diakses tanpa password (cocok untuk develop lokal).
5. Setiap update data: upload ulang file LBP/Target/DMP langsung dari UI, atau
   pilih dari file yang sudah pernah diupload sebelumnya (lihat poin
   "File yang pernah diupload" di bawah) — tidak perlu push ulang ke GitHub.

## File yang pernah diupload (tidak perlu drag-drop ulang)

Setiap file yang kamu upload otomatis disimpan ke folder `saved_uploads/` di
server. Lain kali buka dashboard, di sidebar akan muncul pilihan "...atau
pakai file yang sudah pernah diupload" untuk LBP, Target, dan DMP — tinggal
pilih, tidak perlu upload ulang.

**Penting soal privasi**: folder `saved_uploads/` sudah masuk `.gitignore`
supaya data penjualan tidak pernah ter-commit ke GitHub. Tapi karena file ini
tersimpan di server yang menjalankan app, siapa pun yang berhasil login
(tahu `APP_PASSWORD`) bisa melihat/memilih file yang sama — jadi pastikan
password hanya dipegang orang yang memang boleh akses data ini. Di Streamlit
Community Cloud, penyimpanan ini juga bisa hilang kalau app di-redeploy atau
container-nya di-restart (bukan penyimpanan permanen jangka panjang) — jadi
tetap simpan file asli kamu di tempat lain sebagai cadangan.

## Format file yang dibutuhkan

**File LBP (.txt / .xlsx)** — pipe-delimited (`|`), bisa upload lebih dari satu
file sekaligus (tahun dideteksi otomatis dari `Tanggal Faktur`), kolom:
`No Outlet, Nama Outlet, Grup Outlet, Tipe Outlet, KG, Tanggal Faktur, Faktur, TRANSTYPE, Kode Sales, Pcode, Nama Produk, Kemasan, QTYPCS, AMOUNT, Harga Bruto, DISC, DISC1KH, PROAMOUNT, Total, XQTYPCS, Channel, Alamat, Kabupaten, Kecamatan, Kelurahan, Divisi, WEEK, Periode, Kode Pasar, Salesman, Salesforce, Sales Team, CALLCYCLE, Hari Kunjungan, Kredit Limit, SUBBRAND, SUBBRANDNAME`

**File Target (.xlsx)** — 2 sheet:
- `Target All`: `Kode Sales`, `Periode`, `Target`
- `Target Divisi`: `Kode Sales`, `Periode`, `Divisi`, `Target`

**File DMP (.txt)** — pipe-delimited, dipakai untuk kolom Rayon. Minimal
butuh `KODEOUTLET`, `RAYON`, `SALESMAN`, `LASTUPDATE`.

## Keputusan & asumsi yang perlu kamu tahu

- **LTD NPL & Performance SS**: baru tab placeholder — logic belum dibuat.
- **Standar CB/EC/IPT & skema Insentif**: baru untuk `TO-Retail` dan
  `TO-Grosir` (dibaca dari substring `"TO RETAIL"` / `"TO GROSIR"` pada
  kolom `Salesforce`). Team lain (Motoris, MUH, dst) tidak punya skema
  insentif dan tidak muncul di tab Insentif.
- **Dedup SKU (menu MHS)**: pakai normalisasi nama produk (buang kata
  "NEW", rapikan spasi/kapitalisasi) sebagai kunci unik, BUKAN Pcode
  mentah — sesuai instruksi kamu (contoh "Wow Goreng new" vs "Wow Goreng"
  dihitung 1). Divalidasi ke data asli: dari 129 Pcode unik, ketemu 1 kasus
  yang tergabung jadi 128 SKU unik ("WOW SPAGETI GORENG GB 5GBX12PCX79G").
- **DMP / Rayon**: baris "VACANT" dan Rayon kosong dibuang; kalau 1 outlet
  py>1 baris, dipakai `LASTUPDATE` paling baru. Dari data contoh, 4.956
  outlet punya Rayon valid, ter-mapping ke 27.418 dari 41.016 baris LBP
  (outlet yang tidak match DMP tampil Rayon kosong, tidak error).
- **CB Standpro Area** (sidebar): saran otomatis dari salesman yang
  difilter, tapi tetap manual dan bisa ditimpa.
- **Komparasi tahun**: upload LBP multi-file, tahun dideteksi otomatis.
  Toggle "Bandingkan dengan tahun lalu" menambahkan badge (▲/▼ % ) di
  KPI utama top bar. Pencocokan periode antar tahun pakai **nomor Periode
  yang sama** (Periode 9 2026 vs Periode 9 2025). Badge baru ditaruh di
  level ringkasan (top bar), bukan di setiap baris tabel, supaya tetap
  terbaca — beri tahu saya kalau kamu mau badge ini diperluas ke tabel lain.
- **Insentif**: menghitung 4 kriteria dari PDF skema M245 (Sales, Sales per
  Kategori x4 Divisi, Must Have SKU, Outlet Active), tier dicocokkan ke
  tabel nominal resmi. Bagian Reward & Punishment (Tagihan, Visit in
  Radius) TIDAK dihitung sesuai instruksi.
- **Pie chart Overview**: persis 6 irisan terbesar tanpa "Lainnya". **Pie
  chart By Wilayah/Subbrand/Divisi/Pasar**: top 10 + irisan "Lainnya".
- **Pasar "N/A"** dikecualikan dari menu By Pasar.
- **Divisi** di luar 5/6/8/16 masih kode mentah (belum ada tabel nama
  lengkap).
- Semua angka penjualan → teks `Rp 123,456,789`; kalau datanya belum ada
  (target/gap belum diupload) → tampil `-`, bukan `Rp nan`.

### Bug penting yang sudah diperbaiki (dari update sebelumnya, masih berlaku)

1. **Trailing pipe di LBP.txt** — bikin kolom geser 1 posisi kalau tidak
   pakai `index_col=False` saat `pd.read_csv`. Sudah ditangani.
2. **Retur (R) sudah negatif di sumber data** — neto yang benar `Bruto F +
   Bruto R` (bukan `F - R`), karena R sudah membawa tanda minus sendiri.
   Sudah diverifikasi ke seluruh data: Bruto F = Rp 5.010.609.612, Retur =
   Rp 123.645.763 → Pencapaian benar = Rp 4.886.963.849.
