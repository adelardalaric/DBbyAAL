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

## Update 3.0 (tampilan baru, filter global, Stock, kotak Divisi)

- **Tampilan**: tema gelap ala dashboard referensi (panel membulat, aksen pink/lavender,
  tab berbentuk pill). Kartu Target/Pencapaian/Gap Harian/OA di paling atas TIDAK diubah
  fungsinya. Judul tetap efek 3D, sekarang berwarna pink, plus watermark
  "© Created by Adelard" di bawahnya. Teks tahun/periode/salesman terpilih dihapus.
- **Filter salesman global**: pilihan di Option sekarang benar-benar jadi acuan SEMUA menu
  (Overview sampai Performance SS). Sebelumnya filter lokal tiap menu "menempel" di pilihan
  lama karena Streamlit mengingat state widget; sekarang key-nya ikut berubah setiap
  pilihan di Option berubah, jadi otomatis ter-reset ke salesman yang dipilih.
- **Grafik tren (Overview)**: garis halus (spline) + area, tombol Daily/Weekly/Monthly,
  pilihan metrik (Omzet Neto / OA / EC), angka muncul saat kursor diarahkan ke titik.
  Kalau "Bandingkan dengan tahun lalu" aktif, garis putus-putus tahun lalu ikut tampil.
  Weekly memakai kolom WEEK di LBP, Monthly memakai kolom Periode.
- **Capaian by Divisi (By Salesman)**: 4 kotak (Coffee & Cereal di atas, Instant Food &
  Homecare di bawah), masing-masing berisi Salesman | Target | Capaian | % | Gap Harian.
  Gap Harian = (Target − Capaian) / HKE; kurang → outline merah dengan tanda minus,
  sudah tercapai → outline hijau. Nilainya gabungan salesman yang sedang difilter
  (1 salesman → tampil namanya, >1 → "N Salesman"). Tabel rincian tetap ada di bawahnya.
- **Menu Stock** (upload di dalam menu itu sendiri, bukan di Option): upload 2+ file stok
  beda tanggal → tabel stok tidak bergerak + top stok cepat bergerak. Kolom kode/nama/qty/
  gudang dipilih lewat dropdown (ditebak otomatis), tanggal ditebak dari nama file dan bisa
  dikoreksi. Definisi: tidak bergerak = qty identik di semua file & > 0; cepat bergerak =
  total penurunan qty antar file berurutan.
- **Tabel lebar bisa di-scroll ke kanan**: `use_container_width` sudah deprecated di
  Streamlit terbaru. Tabel ≥ 8 kolom sekarang memakai lebar sesuai isi (bukan dipaksa muat)
  sehingga bisa digeser ke kanan; CSS overflow yang sebelumnya ikut mengganggu dihapus.
- **Bug lama yang ikut diperbaiki**: kalau `secrets.toml` tidak ada sama sekali, gerbang
  password crash — sekarang otomatis dilewati (sesuai yang tertulis di README).

## Update 3.1 (tabel seragam, Gap Harian hijau/merah, kartu Capaian Salesman, PDF di Stock)

- **Gap Harian hijau/merah**: kartu Gap Harian di paling atas, kotak per divisi, kartu per salesman, dan kolom
  "Gap Harian" di semua tabel — merah dengan tanda minus (`-Rp 5,265,712`) kalau belum tercapai, hijau
  (`✓ Tercapai`) kalau sudah. Target belum ada → `-` netral.
- **Perbaikan angka**: kartu Gap Harian atas dan Performance SS sebelumnya membandingkan capaian SEMUA salesman
  dengan target yang hanya ada untuk sebagian (bisa salah tampil "Tercapai"). Sekarang capaian hanya dari salesman
  yang punya target. Performance SS menampilkan catatan kalau ada salesman tanpa target.
- **Tabel seragam**: semua tabel sekarang berupa tabel HTML — semua kolom & header rata tengah, header menempel saat
  scroll, baris selang-seling, bisa digeser ke kanan/bawah. Konsekuensinya tabel tidak lagi bisa di-sort/cari lewat
  klik header (fitur bawaan `st.dataframe`); pakai tombol Download Excel untuk olah data. Tabel dibatasi 1.500 baris
  di layar (Download Excel selalu berisi data lengkap).
- **Capaian by Divisi**: kotak Salesman dihapus; tiap divisi berisi Target | Capaian | % | Gap Harian dalam satu
  baris (2 di atas: Coffee & Cereal, 2 di bawah: Instant Food & Homecare) plus bar progres tipis.
- **Menu baru "Capaian Salesman"**: satu kartu ringkas per salesman (Target, Capaian, %, Gap Harian). Ikut filter
  di Option + filter lokal, bisa diurutkan, opsi "Rincian per divisi", dan tombol **Download gambar (PNG)** untuk
  dibagikan (maks. 80 salesman per gambar).
- **Stock**: sekarang menerima **PDF** (berbasis teks, bukan hasil scan). PDF bergaris tabel dibaca otomatis (header
  yang berulang tiap halaman dibuang); PDF laporan teks berkolom dibaca dengan memecah spasi lebar, kolom bernama
  "Kolom 1..N" kalau header tidak terbaca rapi. Ada pratinjau 5 baris pertama untuk memastikan kolomnya benar.
  Library baru: `pdfplumber` (sudah ditambahkan ke requirements.txt).

## Update 3.2 (Capaian Salesman per divisi, menu tanpa scroll, Stock ditulis ulang)

- **Capaian Salesman**: tiap kartu = baris TOTAL (Target | Capaian | % | Gap Harian) + 4 baris divisi di bawahnya
  (Coffee, Cereal, Instant Food, Homecare) dengan kolom yang sama, Gap Harian merah/hijau per baris. Opsi "Rincian per
  divisi" sekarang aktif secara default. Gambar PNG ikut memuat rincian divisi (maks. 60 salesman per gambar).
  Divisi tanpa penjualan tetap tampil (Net Sales 0) selama salesman itu punya target divisi.
- **Tanpa scroll**: kartu Capaian Salesman tidak lagi punya area scroll sendiri (semua kartu mengalir ke bawah), dan
  deretan tab menu dibuat turun ke baris berikutnya kalau kepanjangan (bukan scroll horizontal).
- **Stock** (ditulis ulang, upload tetap di dalam menu Stock):
  1. Header tabel dicari otomatis (baris judul di atasnya dibuang); kolom Kode/Nama/Qty/Lokasi ditebak otomatis
     (kolom CTN diutamakan dibanding PCS) dan ditampilkan jelas di atas — bisa diubah di "Kolom yang dipakai".
  2. **Stok Tidak Bergerak**: produk yang qty-nya sama di semua file & masih > 0 (contoh: Torabika 10 → 10).
     Kalau file punya kolom lokasi/gudang/bagian, ada ringkasan posisi stok mati per lokasi.
  3. **Top Produk Paling Cepat Keluar**: diurutkan % stok keluar / qty keluar / kecepatan per hari
     (contoh: Energen Vanilla 300 → 10 = 96,7%).
  4. **Klasifikasi Produk**: Sangat Cepat (≥70% keluar), Cepat (≥40%), Sedang (≥15%), Lambat, Stok Bertambah,
     Tidak Bergerak, Kosong — batasnya bisa diubah di "Pengaturan lanjutan".
  % keluar = total penurunan stok antar file berurutan ÷ stok tertinggi sebelum file terakhir; restock di
  tengah periode tidak menutupi pengeluaran.

## Update 3.3 (latar hexagon, angka rapi, menu dua baris)

- **Latar belakang**: gambar hexagon **ditanam langsung di ujung `app.py`** (blok komentar `BG_B64_BEGIN ... BG_B64_END`,
  jangan diedit) sehingga cukup push `app.py` — tidak lagi bergantung pada folder `assets/`. Cadangan: kalau blok itu
  tidak ada, dibaca dari `assets/bg_hexagon.jpg`. Kalau dua-duanya tidak ada, muncul peringatan kecil di sidebar
  dan latar kembali ke warna gelap polos. Lapisan gelap diturunkan ke 6% dan panel dibuat lebih transparan
  (56% + blur) supaya pola hexagon benar-benar terlihat, sementara kartu angka & tabel tetap cukup pekat untuk dibaca.
  Di HP latar tidak dikunci (scroll bersama halaman).
- **Angka target/capaian/% di kartu**: "Rp" dan angkanya sekarang terkunci satu baris (spasi tak-terputus), tanda "%"
  menempel di angkanya, ukuran huruf menyesuaikan lebar kotak, dan "Rp"/"%" dibuat lebih kecil supaya angkanya
  menonjol. Berlaku di kartu Capaian Salesman, kotak Capaian by Divisi, dan kartu KPI paling atas.
- **Menu**: `st.tabs` diganti dua baris pill (baris 1: Overview → Insentif, baris 2: LATO → Read Me). Pill otomatis
  turun ke baris berikutnya kalau layar sempit, jadi tidak pernah perlu digeser ke samping. Sebagai bonus, hanya
  halaman yang dipilih yang dihitung sehingga dashboard lebih ringan. Konsekuensi: filter lokal di sebuah menu
  kembali ke bawaan kalau kamu pindah menu; file yang diupload di menu Stock tetap tersimpan selama sesi
  (ada tombol "Hapus semua"). Butuh Streamlit ≥ 1.40 (`st.pills`) — sudah ada di requirements.txt.

## Update 3.4 (transparansi, warna cyan, kartu Insentif, Breakdown Target, lebar penuh)

- **Latar makin transparan**: overlay gelap diturunkan dari 6% ke 2%, dan semua panel/kartu/tabel diturunkan
  opacity-nya (kira-kira 0.8 → 0.4, tabel 0.84 → 0.46) dengan blur ditambah supaya pola hexagon jauh lebih terlihat.
  Teks (angka, label, isi tabel) diberi bayangan tipis (`text-shadow`) supaya tetap kebaca jelas di atas latar yang
  makin tembus pandang.
- **Warna diganti dari pink/ungu ke cyan-biru** (`#5EEAD4` & `#38BDF8`) — judul, ikon KPI, tab aktif, bar progres,
  tag team, semuanya. Dipilih senada dengan garis neon biru di gambar hexagon (satu tone), tapi tetap kontras
  karena lebih terang dari latar yang gelap.
- **Menu Insentif**: sebelum tabel rekap, sekarang ada 3 KPI ringkas (jumlah salesman, total gabungan, rata-rata)
  lalu kartu per salesman (gaya sama seperti Capaian Salesman) — nominal Total Insentif besar di atas, lalu rincian
  4 kriteria (Sales, 4 Divisi, SKU Sold, Outlet Active) dengan %, nominal, dan warna hijau/abu-abu (hijau = kriteria
  itu menghasilkan insentif).
- **Menu baru "🧩 Breakdown Target"**: placeholder, "akan dikembangkan lebih lanjut" (di baris menu ke-2, sebelum
  Stock).
- **Lebar penuh dari ujung ke ujung**: ditambahkan CSS yang memaksa `block-container` selebar 100% (beberapa versi
  Streamlit membatasi ke lebar tengah meski `layout="wide"` sudah diset) — sekarang semua menu (Overview s.d. Read
  Me) selebar baris kartu Target–OA di paling atas.

## Update 3.5 (kotak EC, skema Insentif Okt-Des 2026, Stock qty & donut, Breakdown Target)

- **Capaian Salesman — kotak EC baru**: di bawah baris divisi Homecare, tiap kartu sekarang punya kotak "📞 EC"
  dengan 4 angka: **Target** (EC Standar × HKA — EC Standar dari tabel Standart Produktivity per Team, mis. 20
  untuk TO Retail, 12 untuk TO Grosir), **s/d Hari Ini** (EC Standar × (HKA−HKE), target pacing sampai hari ini),
  **Capaian** (EC aktual salesman), dan **Gap Harian** (hijau "✓ Tercapai" / merah kurang-sekian, dihitung dari
  Target penuh dikurangi Capaian dibagi HKE — basis & gaya sama seperti semua Gap Harian lain di dashboard ini).
  Ikut masuk ke gambar PNG yang bisa didownload juga.
- **Skema Insentif diperbarui ke periode Oktober-Desember 2026** (dari 4 PDF scheme resmi TO Retail/TO
  Grosir/KLK/SS, update 25 September 2026):
  - **Sales per Kategori** (4 divisi): nominal tier ≥110% sekarang **beda per divisi** (Coffee/Cereal/Instant
    Food/Homecare), tidak seragam lagi seperti skema lama.
  - Kriteria ke-4 TO Retail/TO Grosir/KLK berganti nama **"Outlet Active" → "Effective Call"** dengan range %
    baru (85/90/95, sebelumnya 90/95/100) — dasar hitungnya diganti ke **%EC** (EC aktual ÷ EC Standar×HKA,
    dikonfirmasi ke user karena namanya berubah jadi Effective Call).
  - Kriteria ke-4 SS berganti nama **"Outlet Active" → "Outlet Active Quality (Retail Channel)"** dengan range %
    baru (75/80/85) — dasar hitung **tetap %OA** biasa (vs CB Standar), karena syarat barunya (khusus channel
    Retail, transaksi min Rp150rb) belum dihitung presisi di versi ini (dikonfirmasi ke user).
  - **SS juga ikut diupdate** sesuai PDF SS Okt-Des 2026 yang baru (walau draft Update 3.5 sempat menyebut
    "tidak berlaku pada SS" — dikonfirmasi ke user itu keliru, karena PDF SS-nya sendiri ternyata berubah).
  - "SKU Sold by Channel" nominal tier teratas turun di semua team.
  - Menu Insentif, Performance SS & Read Me semuanya mengikuti skema baru ini.
- **Stock**:
  - Angka di seluruh menu Stock sekarang **tanpa pemisah ribuan** (mis. `300722`, bukan `300,722`) — khusus menu
    ini saja, menu lain tidak berubah.
  - Klasifikasi pergerakan diganti dari **% stok keluar** ke **qty absolut yang keluar** (karton): Tidak Bergerak
    (0) · **Sangat Lambat** (<10) · **Lambat** (10–49) · **Standar** (50–99) · **Fast Move** (≥100) — threshold
    bisa diubah di "Pengaturan lanjutan". Contoh: Torabika Creamy Latte 189→188 (keluar 1 karton) = Sangat Lambat.
  - Bagian "Stok Tidak Bergerak" diperluas jadi **"Stok Tidak Bergerak & Pergerakan Lambat"**, menggabungkan
    produk Tidak Bergerak + Sangat Lambat + Lambat dalam satu tabel yang bisa di-scroll.
  - Grafik batang di "Klasifikasi Produk" diganti **diagram donut** (warna per klasifikasi, total produk
    ditulis di tengah, irisan terbesar sedikit ditarik keluar).
- **Menu "🧩 Breakdown Target" (full build, sebelumnya placeholder)**:
  - Upload Excel Target (format sama seperti `TARGET_FILE_BD.xlsx`: kolom KD OUTLET, SKU, QTY, DIVISI, TARGET;
    sheet "REKAP TARGET") — dijumlah per kode divisi jadi **Target Area per Divisi**.
  - **Kontribusi %** tiap salesman dihitung dari file LBP yang sudah diupload: pencapaian salesman ÷ pencapaian
    area, dipecah per divisi (5-Coffee/6-Cereal/8-Instant Food/16-Homecare), dibulatkan 1 angka di belakang
    koma (mis. 4,3%).
  - Kolom **Adjustment %** bisa diedit manual per salesman per divisi (default = Kontribusi % hasil LBP) —
    **Target Teradjust** (= Adjustment % × Target Area Divisi) langsung ikut berubah saat Adjustment % diedit.

### Catatan/asumsi yang dikonfirmasi ke user di Update 3.5
Beberapa hal di spec tertulis ambigu atau (ternyata) kurang akurat dibanding PDF resminya — sudah ditanyakan
langsung dan dikonfirmasi sebelum dikerjakan:
1. Scheme SS tetap diupdate (bukan "tidak berlaku pada SS" seperti di draft Update 3.5 — PDF SS Okt-Des 2026
   ternyata memang berubah nominalnya).
2. Kriteria ke-4 TO Retail/Grosir/KLK ("Effective Call") pakai dasar %EC, bukan %OA lama.
3. Kriteria ke-4 SS ("Outlet Active Quality") tetap pakai %OA biasa (approximate), bukan logic baru
   "retail channel only, min Rp150rb" yang lebih presisi.
4. Gap Harian kotak EC pakai Target penuh periode (sama seperti Gap Harian lain di dashboard), dan kotak
   "Target" & "Target s/d Hari Ini" ditampilkan berdampingan sesuai mekanisme yang dijelaskan di spec.

## Update 3.6 (persen EC, menu Ikat Target)

- **Kotak EC di Capaian Salesman**: ditambah kolom **%** (Capaian ÷ Target penuh, mis. 325/480 = 67,7%), urutannya
  jadi Target | s/d Hari Ini | Capaian | % | Gap Harian. Ikut di gambar PNG (label PNG ditulis "EC" tanpa emoji
  karena font gambar tidak mendukung emoji).
- **Menu baru "🔗 Ikat Target"** (baris menu ke-2, setelah Breakdown Target): placeholder, menunggu gambaran
  yang akan dikirim terpisah.

## Update 3.7 (toggle 90%/110% di Capaian Salesman, Breakdown Target dibangun ulang)

- **Capaian Salesman — toggle 90% / 110%**: dua tombol kecil di sebelah kanan kotak Gap Harian (baris Σ TOTAL).
  Default **100%** (tidak klik apa-apa). Klik **110%** → Target jadi Target × 1,1 (mis. 100 → 110), Capaian tetap
  (80), dan Gap Harian dihitung ulang (gap 20 → 30). **% capaian dan bar tidak ikut berubah** (selalu dihitung
  terhadap target 100%, mis. tetap 101,6%); kalau 110% belum tercapai, Gap Harian merah seperti biasa. Klik tombol yang sama sekali lagi untuk
  kembali ke 100%. Toggle berlaku untuk baris Σ TOTAL **dan** keempat baris divisi; kotak EC tidak berubah.
  Gambar PNG yang di-download tetap memakai target 100%.
  - Teknis: dipasang murni lewat CSS (radio tersembunyi tanpa atribut `checked` + label), jadi tidak memicu
    rerun Streamlit dan tiap kartu punya toggle sendiri. Catatan: kalau urutan kartu berubah (ganti Urutkan /
    Filter), pilihan toggle bisa ikut posisi kartu, bukan nama salesman — tinggal klik ulang.
- **Breakdown Target** (dibangun ulang):
  - Baris = tiap salesman **TO Grosir, TO Retail, Motoris, KVS ST, Sales Office**, ditambah satu baris
    **MUH** yang menggabungkan semua salesman di luar kelima kode itu (Salesforce 116 MUH, BJMU-…, MTP-…, dst).
  - Kolom lurus ke kanan: **MU 245 | Coffee | Cereal | Instant Food | Home Care**; tiap kelompok berisi
    Kontribusi % (1 desimal), Adjustment %, dan Target. Kolom Entitas menempel di kiri, tabel bisa digeser ke
    kanan, dan semua angka tidak dipotong saat di-zoom.
  - **MU 245** = jumlah target 4 divisi per baris (tidak diedit langsung; ikut dari adjustment divisi).
    Baris subtotal di file Excel (divisi kosong) diabaikan supaya tidak terhitung dobel.
  - **Menu Adjustment**: tabel editable (Adjustment % per divisi per baris) di atas tabel utama; default =
    Kontribusi % dari LBP. Tombol "↺ Reset" mengembalikan semua ke default. Ada pengecekan total Adjustment tiap
    divisi (harus 100%, ditandai ⚠️ / merah di baris TOTAL kalau tidak).
  - **Total target semuanya**: 5 kartu di atas (Total Target MU 245 + tiap divisi, dari file Excel) dan baris
    **TOTAL** di tabel + tombol Download Excel.
