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

**File Target (.xlsx)** — 2 sheet, nama & kolom fleksibel (parser cocokkan
otomatis, tidak case-sensitive):
- Sheet target keseluruhan (nama mengandung "TARGET ALL"): butuh kolom yang
  mengandung kata "KODE" (untuk Kode Sales) dan "TARGET". Kolom "PERIODE"
  opsional — kalau tidak ada, target dianggap berlaku untuk periode berapa
  pun yang sedang difilter (cocok untuk file bulanan seperti
  `FILE_TARGET_SEP.xlsx`, sudah ditest).
- Sheet target per divisi (nama mengandung "TARGET DIVISI"): butuh kolom
  "KODE...", lalu boleh format LEBAR (satu kolom per divisi, mis.
  `5 - COFFE`, `6 - CEREAL`, `8 - INSTANT FOOD`, `16 - HOME CARE` — kode
  divisi diambil dari angka sebelum tanda "-") ATAU format PANJANG (kolom
  "DIVISI" + "TARGET" terpisah). Kolom "PERIODE" juga opsional di sini.

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
- **HKE (Hari Kerja Efektif)** sekarang jadi pembagi Gap Harian di semua
  menu (bukan HKA lagi). HKA tetap ada sebagai field terpisah di sidebar
  tapi untuk saat ini tidak dipakai di perhitungan manapun.
- **Dedup SKU produk WOW**: khusus produk yang namanya mengandung "WOW",
  varian kemasan/ukuran (mis. "GB" vs "10X(4+2)") DIBUANG dari kunci
  dedup-nya — jadi "WOW SPAGETI CARBONARA GB" dan "WOW SPAGETI CARBONARA
  10X(4+2)" dihitung 1 SKU. Sudah divalidasi ke data asli: dari 129 Pcode
  unik, 4 pasangan berhasil digabung (Goreng, Carbonara, Bolognese, Aglio
  Olio) jadi 125 SKU unik — sementara "Carbonara" tetap terpisah dari
  "Creamy Carbonara" (flavor beda, sengaja tidak digabung). Produk NON-WOW
  tidak kena aturan ini — kemasan tetap jadi pembeda SKU seperti biasa.
- **Menu SKU Sold (dulu "Must Have SKU")**: target SKU sekarang diambil
  dari klasifikasi channel di **DMP** (kolom NAMACLASS, Supermarket dari
  NAMACHANNEL) sesuai Memorandum Revisi 27 Agustus 2026 — BUKAN lagi dari
  Tipe Outlet di LBP. 9 kategori: Kantin(5), Warduh(5), Kios(7), Retail
  Large(10), Grosir Snack(10), Grosir Kelontong(15), Grosir Modern(15),
  Minimarket(20), Supermarket(25). Divalidasi: outlet "#AINI***/K." di DMP
  asli persis berklasifikasi "GROSIR KELONTONG" seperti contoh yang kamu
  kasih. Tier insentifnya juga berubah dari 60/70/80/90% jadi 50/60/70/80%
  — **nominal Rp per tier saya PERTAHANKAN sama seperti skema asli** karena
  memo revisi tidak menyebutkan perubahan nominal, cuma perubahan range &
  klasifikasi channel. Tolong dikonfirmasi kalau nominalnya ternyata ikut
  berubah.
- **Menu LATO**: sumber datanya adalah **DMP** (bukan LBP), supaya outlet
  yang belum pernah transaksi tetap ikut tampil (ditandai baris merah
  "BELUM ADA TRANSAKSI"). Kalau file DMP belum diupload, menu ini tidak
  bisa dipakai. Nominal transaksi mengikuti filter Periode/Week yang aktif
  di sidebar.
- **Menu Paretto**: baru placeholder, "akan dikembangkan lebih lanjut".

### Bug penting yang sudah diperbaiki (dari update sebelumnya, masih berlaku)

1. **Trailing pipe di LBP.txt** — bikin kolom geser 1 posisi kalau tidak
   pakai `index_col=False` saat `pd.read_csv`. Sudah ditangani.
2. **Retur (R) sudah negatif di sumber data** — neto yang benar `Bruto F +
   Bruto R` (bukan `F - R`), karena R sudah membawa tanda minus sendiri.
   Sudah diverifikasi ke seluruh data: Bruto F = Rp 5.010.609.612, Retur =
   Rp 123.645.763 → Pencapaian benar = Rp 4.886.963.849.
3. **Crash FileNotFoundError saat pakai "file yang sudah pernah diupload"**
   — akar masalahnya, Streamlit sempat mencoba membaca nama file yang saya
   tempelkan ke objek `BytesIO` seolah itu path asli di disk (lewat
   `os.path.getmtime`), padahal itu cuma nama file biasa — jadi crash kalau
   nama itu tidak match path relatif ke direktori kerja. Sudah diperbaiki
   dengan cara membaca file jadi `bytes` mentah dan mengirim `bytes` + nama
   sebagai argumen terpisah ke fungsi-fungsi loader, bukan objek file-like
   — pendekatan ini juga lebih cepat untuk caching Streamlit.

## Update terbaru (Standart Produktivity, DMP outlet count, LATO, Paretto)

- **Standar Team**: sekarang diambil lengkap dari Surat Standart Produktivity
  (No. 001-W/EDP/VII/2026, berlaku 03 Agustus 2026/W32) — 8 tipe salesforce
  (SE, TO Grosir, TO All, TO Retail, TO ST, KLK, KVS ST, Motoris), diklasifikasi
  dari KODE SF di depan kolom Salesforce (LBP)/KODESALESFORCE (DMP), bukan lagi
  tebak-tebakan substring nama. Salesforce yang tidak ada di 8 tipe ini (mis.
  MUH, Sales Office) tampil "Lainnya" — tidak punya standar CB Cover.
- **Skema Insentif KLK** ditambahkan (dari PDF Scheme KLK Agust-Sept 2026),
  sejajar dengan TO Retail & TO Grosir.
- **Pembagi %MHS/SKU Sold** sekarang JUMLAH OUTLET ASLI DARI DMP per Kode Sales
  (dikunci lewat SLSNO di DMP = Kode Sales di LBP), BUKAN lagi CB Standpro
  Team. Divalidasi: Salesman Fitri (896023) → 105 outlet di DMP, persis sesuai
  contoh yang diberikan. Kode Sales dipakai hanya untuk mengunci perhitungan
  di balik layar — tidak pernah ditampilkan di tabel manapun. **%OA** TETAP
  pakai CB Cover dari tabel Standart Produktivity (tidak berubah).
- **Menu LATO**: bug format Rupiah sudah diperbaiki — kolom Omzet mentah
  sekarang benar-benar tidak pernah ikut dirender (sebelumnya sempat lolos
  karena `Styler.hide()` tidak selalu ditaati oleh `st.dataframe`).
- **Menu Paretto**: filter Salesman + Rayon (pola sama seperti MHS), ranking
  40 toko omzet tertinggi (neto Bruto F+R), plus bar chart top 20 dari 40 itu.
- **Judul dashboard**: efek gradient dihapus, diganti efek 3D/emboss pakai
  tumpukan `text-shadow` (bukan gradient warna).
- **Tampilan mobile**: ditambahkan media query untuk layar ≤640px — judul,
  kartu KPI, dan tabel menyesuaikan ukuran font supaya tidak kepotong/kekecilan
  di HP.
