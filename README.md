# Dashboard Operational Area MU42

Dashboard performa sales & insentif berbasis Streamlit, dibaca dari file LBP
(Laporan Buku Penjualan) dan file Target.

## Cara jalankan lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Cara deploy ke Streamlit Community Cloud

1. Push folder ini (`app.py`, `requirements.txt`, `.streamlit/config.toml`) ke repo GitHub.
2. Buka [share.streamlit.io](https://share.streamlit.io), hubungkan ke repo tersebut.
3. Set entrypoint ke `app.py`, deploy.
4. Setiap update: upload ulang file LBP & Target langsung dari UI (tidak perlu upload ulang ke GitHub) — file diproses saat runtime, bukan disimpan di repo.

## Format file yang dibutuhkan

**File LBP (.txt / .xlsx)** — pipe-delimited (`|`), kolom mengikuti `LBP.txt` yang sudah diuji:
`No Outlet, Nama Outlet, Grup Outlet, Tipe Outlet, KG, Tanggal Faktur, Faktur, TRANSTYPE, Kode Sales, Pcode, Nama Produk, Kemasan, QTYPCS, AMOUNT, Harga Bruto, DISC, DISC1KH, PROAMOUNT, Total, XQTYPCS, Channel, Alamat, Kabupaten, Kecamatan, Kelurahan, Divisi, WEEK, Periode, Kode Pasar, Salesman, Salesforce, Sales Team, CALLCYCLE, Hari Kunjungan, Kredit Limit, SUBBRAND, SUBBRANDNAME`

**File Target (.xlsx)** — 3 kolom: `Kode Sales`, `Periode`, `Target`.

## Keputusan & asumsi yang perlu kamu tahu

- **LTD NPL & Komparasi Tahun (YoY)**: baru sebatas tab placeholder — logic
  belum dibuat, menunggu definisi rumus LTD NPL dan alur upload data
  pembanding tahun sebelumnya.
- **Standar CB/EC/IPT**: baru untuk `TO-Retail` (300/20/6) dan `TO-Grosir` (90/12/10),
  dibaca dari substring `"TO RETAIL"` / `"TO GROSIR"` pada kolom `Salesforce`.
  Team lain (Motoris, MUH, Sales Office, dst) tampil dengan `% OA` dan `% MHS` kosong.
- **CB Standpro Area** (di sidebar ⚙️ Option): nilai default adalah saran
  otomatis (jumlah standar CB dari salesman yang sedang difilter), tapi
  field-nya tetap manual dan bisa kamu timpa — ini yang menentukan `OA %`
  di top bar.
- **Pie chart Overview** dibatasi persis 6 irisan terbesar (salesman, wilayah,
  subbrand) tanpa "Lainnya", sesuai instruksi. **Pie chart By Wilayah / By
  Subbrand & Divisi / Pasar** dibatasi top 10 + irisan "Lainnya" supaya tetap
  terbaca untuk kategori yang jumlahnya banyak (Kecamatan/Kelurahan bisa
  puluhan).
- **Pasar "N/A"**: baris dengan keterangan Kode Pasar `N/A` dikecualikan dari
  menu By Pasar (mayoritas outlet di data kamu memang belum punya nama pasar
  resmi — dari 41.016 baris, cuma 6.825 yang punya nama pasar).
- **Menu MHS "SKU belum masuk"**: dibandingkan terhadap SKU yang pernah laku
  di outlet lain dengan Tipe Outlet yang sama (proxy), karena belum ada file
  master SKU per channel. Ganti fungsi `universe_sku_per_tipe_outlet()` di
  `app.py` begitu kamu punya file master SKU resmi.
- **Divisi**: ditampilkan sebagai kode mentah (`16`, `06`, dst) karena tidak
  ada tabel nama Divisi di data — tambahkan mapping-nya sendiri kalau ada.
- Semua angka penjualan ditampilkan sebagai teks berformat `Rp 123,456,789`
  di tabel (bukan kolom angka native) supaya formatnya konsisten dan tidak
  terpotong — trade-off-nya kolom itu jadi tidak bisa di-sort numerik di UI.
- Judul di Update.txt tertulis "MV42" (sketsa awal sebelumnya "MU42") — dipakai
  "MV42" sesuai instruksi terakhir. Kasih tahu kalau ini typo.

### Bug penting yang sudah diperbaiki

1. **Trailing pipe di LBP.txt** — setiap baris file diakhiri karakter `|`
   tambahan. Tanpa `index_col=False` saat `pd.read_csv`, pandas salah
   mengira kolom pertama adalah index dan semua kolom lain geser satu posisi
   (kolom "Salesman" jadi berisi data "Salesforce", dst). Sudah ditangani di
   `load_lbp()`.
2. **Retur (R) sudah negatif di sumber data, bukan positif** — ini akar
   masalah "pencapaian belum dikurangi" yang kamu laporkan. Di kolom `Harga
   Bruto`, baris dengan `TRANSTYPE == "R"` SUDAH tersimpan sebagai angka
   negatif (mis. `-490000`), bukan `490000` positif. Formula lama
   `Bruto F - Bruto R` jadinya malah MENAMBAHKAN retur ke pencapaian
   (minus dikali minus jadi plus) — hasilnya pencapaian bisa lebih besar
   dari bruto F, jelas salah. Formula yang benar adalah `Bruto F + Bruto R`
   (R sudah membawa tanda minus sendiri). Sudah diverifikasi ke seluruh data:
   Bruto F = Rp 5.010.609.612, Retur = Rp 123.645.763 → Pencapaian yang
   benar = **Rp 4.886.963.849** (versi lama salah menghasilkan
   Rp 5.134.255.375 — lebih besar dari Bruto F, mustahil). Sudah diperbaiki
   di `net_by_group()` dan `hitung_pencapaian()`.
