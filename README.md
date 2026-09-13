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

- **LTD NPL**: sengaja belum dibuat — masih menunggu definisi rumus yang pasti.
- **Standar CB/EC/IPT**: baru untuk `TO-Retail` (300/20/6) dan `TO-Grosir` (90/12/10),
  dibaca dari substring `"TO RETAIL"` / `"TO GROSIR"` pada kolom `Salesforce`.
  Team lain (Motoris, MUH, Sales Office, dst) tampil dengan `% OA` = kosong.
- **CB Standpro Area** di top bar: nilai default adalah saran otomatis (jumlah
  standar CB dari salesman yang sedang difilter), tapi field-nya tetap manual
  dan bisa kamu timpa — ini yang menentukan `OA %` di top bar.
- **Menu MHS "SKU belum masuk"**: dibandingkan terhadap SKU yang pernah laku
  di outlet lain dengan Tipe Outlet yang sama (proxy), karena belum ada file
  master SKU per channel. Ganti fungsi `universe_sku_per_tipe_outlet()` di
  `app.py` begitu kamu punya file master SKU resmi.
- **Divisi**: ditampilkan sebagai kode mentah (`16`, `06`, dst) karena tidak
  ada tabel nama Divisi di data — tambahkan mapping-nya sendiri kalau ada.
- Bug penting yang sudah diperbaiki: file LBP.txt punya trailing `|` di akhir
  setiap baris. Tanpa `index_col=False` saat `pd.read_csv`, pandas salah
  mengira kolom pertama adalah index dan semua kolom lain geser satu posisi
  (kolom "Salesman" jadi berisi data "Salesforce", dst). Sudah ditangani di
  `load_lbp()`.
