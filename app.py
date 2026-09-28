"""
Dashboard Operational Area MV42
================================
Cara jalankan lokal   : streamlit run app.py
Cara deploy           : push repo ini ke GitHub -> deploy di share.streamlit.io,
                         pilih app.py sebagai entrypoint.

CATATAN ASUMSI PENTING (baca sebelum pakai data asli) — lihat README.md untuk
daftar lengkap. Ringkasan perubahan besar di versi ini (Update 3.0):
1. Dedup SKU di menu MHS pakai NORMALISASI NAMA PRODUK (buang kata "NEW",
   spasi berlebih, kapitalisasi disamakan) — bukan lagi per Pcode mentah.
2. File DMP (.txt) dipakai untuk menambahkan kolom Rayon. Baris "VACANT"
   dan baris tanpa Rayon dibuang; kalau satu outlet punya >1 baris, dipakai
   baris dengan LASTUPDATE paling baru.
3. Target/Gap yang datanya belum ada ditampilkan "-", bukan "Rp nan".
4. File Target sekarang punya 2 SHEET: "Target All" (Kode Sales, Periode,
   Target) dan "Target Divisi" (Kode Sales, Periode, Divisi, Target).
5. Upload LBP sekarang bisa multi-file (>1 tahun sekaligus) — tahun dideteksi
   otomatis dari kolom Tanggal Faktur. Ada toggle Tahun Aktif + toggle
   "Bandingkan dengan tahun lalu" yang menambahkan badge komparasi di
   angka-angka utama tiap menu (bukan di setiap baris tabel, supaya tetap
   terbaca).
6. Menu Insentif sudah menghitung nominal insentif riil berdasarkan skema
   PDF TO Retail, TO Grosir & KLK M245 (Agustus-September 2026), kriteria: Sales,
   Sales per Kategori (Coffee/Cereal/Instant Food/Homecare), Must Have SKU,
   Outlet Active. Bagian Reward & Punishment (Tagihan, Visit in Radius)
   SENGAJA DIABAIKAN sesuai instruksi.
7. Menu "Performance SS" ditambahkan sebagai placeholder (akan dikembangkan).
"""

import os
import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Dashboard Operational Area MV42", layout="wide", initial_sidebar_state="expanded")

# =====================================================================
# 0. KONFIGURASI KOLOM & STANDAR BISNIS
# =====================================================================
COL = {
    "outlet": "No Outlet", "nama_outlet": "Nama Outlet", "tipe_outlet": "Tipe Outlet",
    "tanggal": "Tanggal Faktur", "faktur": "Faktur", "transtype": "TRANSTYPE",
    "kode_sales": "Kode Sales", "pcode": "Pcode", "nama_produk": "Nama Produk",
    "qty": "QTYPCS", "bruto": "Harga Bruto", "channel": "Channel",
    "kabupaten": "Kabupaten", "kecamatan": "Kecamatan", "kelurahan": "Kelurahan",
    "divisi": "Divisi", "week": "WEEK", "periode": "Periode", "kode_pasar": "Kode Pasar",
    "salesman": "Salesman", "salesforce": "Salesforce", "subbrand_name": "SUBBRANDNAME",
}
TARGET_ALL_COL = {"kode_sales": "Kode Sales", "periode": "Periode", "target": "Target"}
TARGET_DIVISI_COL = {"kode_sales": "Kode Sales", "periode": "Periode", "divisi": "Divisi", "target": "Target"}
DMP_COL = {"outlet": "KODEOUTLET", "nama_outlet": "NAMAOUTLET", "rayon": "RAYON", "salesman": "SALESMAN",
           "kode_sales": "SLSNO", "lastupdate": "LASTUPDATE", "namaclass": "NAMACLASS", "namachannel": "NAMACHANNEL"}

# Standart Produktivity Team M245 - GT Nasional, berlaku per 03 Agustus 2026 (W32).
# Kode SF & KODESALESFORCE di data (LBP kolom Salesforce, DMP kolom KODESALESFORCE)
# adalah angka di depan sebelum "-", dipetakan ke Type SF di sini.
KODE_SF_LABEL = {
    "106": "SE", "120": "TO GROSIR", "122": "TO ALL", "121": "TO RETAIL",
    "145": "TO ST", "220": "KLK", "226": "KVS ST", "213": "MOTORIS",
}
PRODUKTIVITY_STANDAR = {
    "SE":        {"cb_cover": 60,  "call_day": 10, "ec_day": 6,  "ipt_day": 15, "oa_month_pct": 100, "target_channel": "GMM"},
    "TO GROSIR": {"cb_cover": 90,  "call_day": 15, "ec_day": 12, "ipt_day": 10, "oa_month_pct": 100, "target_channel": "RT Large & SG Up"},
    "TO ALL":    {"cb_cover": 270, "call_day": 25, "ec_day": 20, "ipt_day": 8,  "oa_month_pct": 90,  "target_channel": "All Channel"},
    "TO RETAIL": {"cb_cover": 300, "call_day": 25, "ec_day": 20, "ipt_day": 6,  "oa_month_pct": 90,  "target_channel": "RT Large, Kios"},
    "TO ST":     {"cb_cover": 210, "call_day": 20, "ec_day": 15, "ipt_day": 6,  "oa_month_pct": 90,  "target_channel": "Warduh & Kantin"},
    "KLK":       {"cb_cover": 280, "call_day": 25, "ec_day": 20, "ipt_day": 8,  "oa_month_pct": 90,  "target_channel": "All Channel"},
    "KVS ST":    {"cb_cover": 360, "call_day": 30, "ec_day": 25, "ipt_day": 3,  "oa_month_pct": 90,  "target_channel": "Warduh & Kantin"},
    "MOTORIS":   {"cb_cover": 420, "call_day": 35, "ec_day": 25, "ipt_day": 3,  "oa_month_pct": 70,  "target_channel": "Kios"},
}
# Target SKU per klasifikasi channel — DARI MEMORANDUM REVISI 27 AGUSTUS 2026,
# diambil dari kolom NAMACLASS (dan NAMACHANNEL khusus Supermarket) di DMP,
# BUKAN lagi dari Tipe Outlet di LBP. Kriteria ini sekarang bernama "SKU Sold"
# (dulu "Must Have SKU by Channel").
TARGET_SKU_BY_CLASS = {
    "Kantin": 5, "Warduh": 5, "Kios": 7, "Retail Large": 10, "Grosir Snack": 10,
    "Grosir Kelontong": 15, "Grosir Modern": 15, "Minimarket": 20, "Supermarket": 25,
}


def classify_channel_memo(namaclass, namachannel) -> str | None:
    """Klasifikasi channel sesuai Memorandum 27 Agustus 2026. Divalidasi ke DMP
    asli: outlet '#AINI***/K.' -> NAMACLASS 'GROSIR KELONTONG' -> Grosir Kelontong."""
    nc = str(namaclass).strip().upper()
    nch = str(namachannel).strip().upper()
    if "KANTIN" in nc:
        return "Kantin"
    if "WARDUH" in nc:
        return "Warduh"
    if nc == "RETAIL KIOS":
        return "Kios"
    if nc == "RETAIL LARGE":
        return "Retail Large"
    if nc == "GROSIR SNACK":
        return "Grosir Snack"
    if nc == "GROSIR KELONTONG":
        return "Grosir Kelontong"
    if nc == "GROSIR MODERN":
        return "Grosir Modern"
    if nc == "MINIMARKET":
        return "Minimarket"
    if "SUPERMARKET" in nch:
        return "Supermarket"
    return None
TIPE_OUTLET_LABEL = {
    "111": "111 - Retail Small", "113": "113 - Retail Large", "114": "114 - Semi Grosir",
    "118": "118 - Kantin", "146": "146 - MUH", "115": "115 - Grosir",
    "999": "999 - Aneka Pembeli", "116": "116 - Big Grosir", "105": "105 - GMM Retail",
    "109": "109 - GMM Semi Grosir", "110": "110 - GMM Grosir",
}
DIVISI_LABEL = {"5": "Coffee", "6": "Cereal", "8": "Instant Food", "16": "Homecare"}

# Skema insentif M245 (Agustus-September 2026) dari PDF TO Retail, TO Grosir & KLK,
# dengan kriteria "SKU Sold" (dulu "Must Have SKU by Channel") sudah disesuaikan
# ke Memorandum Revisi 27 Agustus 2026 — berlaku untuk Salesman (SE, TO Grosir,
# TO All, TO Retail, KLK & TO ST) & Sales Supervisor, batas persentase turun jadi
# 50/60/70/80 (dari 60/70/80/90). Nominal Rp-nya TETAP sama seperti skema asli
# masing-masing karena memo revisi tidak menyebutkan perubahan nominal, cuma
# perubahan range & klasifikasi channel — tolong dikonfirmasi kalau nominalnya
# ternyata ikut berubah. Key dict ini mengikuti label Type SF (PRODUKTIVITY_STANDAR).
# Setiap list: (persentase minimum, nominal Rp). Reward & Punishment TIDAK dipakai.
INSENTIF_TIERS = {
    "TO RETAIL": {
        "sales": [(90, 500_000), (95, 650_000), (100, 1_000_000), (110, 1_400_000)],
        "category": [(90, 75_000), (95, 100_000), (100, 150_000), (110, 250_000)],
        "mhs": [(50, 500_000), (60, 650_000), (70, 1_000_000), (80, 1_400_000)],
        "oa": [(90, 300_000), (95, 600_000), (100, 1_000_000)],
    },
    "TO GROSIR": {
        "sales": [(90, 600_000), (95, 800_000), (100, 1_200_000), (110, 1_800_000)],
        "category": [(90, 100_000), (95, 150_000), (100, 200_000), (110, 300_000)],
        "mhs": [(50, 600_000), (60, 800_000), (70, 1_200_000), (80, 1_800_000)],
        "oa": [(90, 400_000), (95, 800_000), (100, 1_200_000)],
    },
    "KLK": {
        "sales": [(90, 550_000), (95, 750_000), (100, 1_100_000), (110, 1_600_000)],
        "category": [(90, 100_000), (95, 125_000), (100, 175_000), (110, 300_000)],
        "mhs": [(50, 550_000), (60, 750_000), (70, 1_100_000), (80, 1_600_000)],
        "oa": [(90, 300_000), (95, 700_000), (100, 1_000_000)],
    },
}

INSENTIF_TIERS_SS = {
    "sales": [(90, 800_000), (95, 1_100_000), (100, 1_600_000), (110, 2_350_000)],
    "category": [(90, 125_000), (95, 170_000), (100, 250_000), (110, 400_000)],
    "mhs": [(50, 800_000), (60, 1_100_000), (70, 1_600_000), (80, 2_350_000)],
    "oa": [(90, 500_000), (95, 1_000_000), (100, 1_500_000)],
}

ACCENT = "#F3A6E9"      # pink (aksen utama, mengikuti gaya referensi dashboard)
ACCENT2 = "#A9A6F7"     # lavender (aksen kedua)
PALETTE = ["#F3A6E9", "#A9A6F7", "#F7B98B", "#7DD3C0", "#8AB4F8", "#F28FAD",
           "#C4B5FD", "#FDE68A", "#86EFAC", "#93C5FD", "#FCA5A5"]
CHART_FONT = "#D9D9E3"


# =====================================================================
# 1. STYLE — tema gelap ala dashboard referensi (panel membulat, aksen pink/lavender)
# =====================================================================
_BG_BEGIN = "# BG_B64_" + "BEGIN\n"
_BG_END = "\n# BG_B64_" + "END"


def _bg_data_uri() -> str:
    """Latar belakang hexagon sebagai data-URI. Sumber utama: gambar yang DITANAM di ujung file app.py ini
    (jadi cukup push app.py saja). Cadangan: assets/bg_hexagon.jpg. Tidak di-cache supaya kegagalan
    sesaat tidak menempel. Return "" kalau dua-duanya tidak ada."""
    import base64
    try:
        me = os.path.abspath(__file__)
    except NameError:
        me = os.path.join(os.getcwd(), "app.py")
    try:
        with open(me, encoding="utf-8") as f:
            txt = f.read()
        a = txt.rfind(_BG_BEGIN)
        if a != -1:
            a += len(_BG_BEGIN)
            b = txt.find(_BG_END, a)
            if b != -1:
                chunk = "".join(ln[2:] if ln.startswith("# ") else ln for ln in txt[a:b].splitlines())
                if chunk.startswith("/9j/"):   # tanda awal file JPEG dalam base64
                    return "data:image/jpeg;base64," + chunk
    except OSError:
        pass
    path = os.path.join(os.path.dirname(me), "assets", "bg_hexagon.jpg")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    return ""


def inject_css():
    _h_css = "".join(".tbl-h-%d { max-height:%dpx; }" % (h, h) for h in range(120, 1001, 20))
    _pw_css = "".join(".pw-%d { width:%d%%; }" % (n, n) for n in range(0, 101))
    _bg = _bg_data_uri()
    if not _bg:
        st.sidebar.caption("⚠️ Latar hexagon tidak termuat (gambar tertanam & assets/bg_hexagon.jpg tidak ditemukan).")
    _bg_layer = (f'linear-gradient(rgba(4,6,12,0.06), rgba(4,6,12,0.06)), url("{_bg}") center center / cover no-repeat fixed'
                 if _bg else "#0B0B0F")
    st.markdown(f"""
    <style>
    /* ===== Latar belakang hexagon + panel semi-transparan supaya tetap terbaca ===== */
    .stApp {{ background:{_bg_layer} !important; }}
    [data-testid="stAppViewContainer"], [data-testid="stMain"], header[data-testid="stHeader"] {{ background:transparent !important; }}
    section[data-testid="stSidebar"] > div {{ background:rgba(6,8,14,0.66) !important; backdrop-filter:blur(10px); }}
    section[data-testid="stSidebar"] {{ border-right:1px solid rgba(140,160,210,0.16); }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius:18px !important; border:1px solid rgba(140,160,210,0.18) !important;
        background:rgba(10,12,19,0.56); backdrop-filter:blur(10px);
    }}

    /* Menu navigasi (pill, otomatis turun ke baris berikutnya — tidak pernah perlu digeser) */
    button[data-testid="stBaseButton-pills"] {{
        background:rgba(18,21,31,0.85); border:1px solid rgba(140,160,210,0.22); border-radius:999px; color:#D5D7E4;
    }}
    button[data-testid="stBaseButton-pillsActive"] {{
        background:rgba(169,166,247,0.24); border:1px solid {ACCENT2}; border-radius:999px; color:#fff; font-weight:700;
    }}

    .app-title {{
        text-align:center; text-transform:uppercase; letter-spacing:2px;
        font-size:3.2rem; font-weight:800; margin-bottom:0.1rem; line-height:1.1;
        color: {ACCENT};
        text-shadow:
            1px 1px 0 #d48ace, 2px 2px 0 #b874b2, 3px 3px 0 #9c5f96,
            4px 4px 0 #804b7b, 5px 5px 10px rgba(0,0,0,0.6);
    }}
    .app-watermark {{ text-align:center; color:#b9bccb; font-size:0.85rem; letter-spacing:0.6px; margin:2px 0 1.2rem;
                      text-shadow:0 1px 6px rgba(0,0,0,0.85); }}
    .app-subtitle {{ text-align:center; color:#b4b8c8; font-size:0.9rem; margin-bottom:1.2rem; text-shadow:0 1px 6px rgba(0,0,0,0.85); }}

    /* Angka: selalu satu baris ("Rp" tidak boleh terpisah dari angkanya), lebar digit seragam */
    .cur {{ font-size:0.74em; font-weight:600; opacity:0.72; margin-right:1px; }}
    .kpi-value, .dv-value, .sc-cell {{ white-space:nowrap; font-variant-numeric:tabular-nums; }}

    .kpi-box {{
        border:1px solid rgba(140,160,210,0.2); border-radius:18px; padding:16px 18px;
        background-color:rgba(10,12,19,0.80); backdrop-filter:blur(5px); height:100%; min-height:108px;
        container-type:inline-size;
    }}
    .kpi-icon {{
        width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center;
        font-size:1.05rem; background:rgba(243,166,233,0.16); margin-bottom:4px;
    }}
    .kpi-label {{ font-size:0.8rem; color:#a9aebf; margin-top:2px; }}
    .kpi-value {{ font-size:1.3rem; font-size:clamp(0.95rem, 8.4cqw, 1.5rem); font-weight:700; color:#F3F4F6; line-height:1.25; }}
    .kpi-sub {{ font-size:0.75rem; color:#a9aebf; margin-top:4px; }}
    .kpi-cmp-up {{ color:#34D399; font-size:0.78rem; margin-top:2px; }}
    .kpi-cmp-down {{ color:#F87171; font-size:0.78rem; margin-top:2px; }}
    .big-nominal {{
        text-align:center; font-size:2.4rem; font-weight:800; color:{ACCENT};
        padding:10px 0 2px 0;
    }}
    /* Kotak Capaian by Divisi (menu By Salesman) */
    .dv-box {{ border:1px solid rgba(140,160,210,0.2); border-radius:12px; padding:8px 10px; background:rgba(20,23,33,0.86);
               min-height:66px; min-width:0; overflow:hidden; }}
    .dv-label {{ font-size:0.62rem; color:#9ba0b3; text-transform:uppercase; letter-spacing:0.4px; }}
    .dv-value {{ font-size:0.92rem; font-weight:700; color:#f3f4f6; line-height:1.2; margin-top:2px; }}
    .dv-sub {{ font-size:0.62rem; color:#9ba0b3; margin-top:2px; }}
    .dv-gap-bad {{ border:2px solid #ef4444; }}
    .dv-gap-bad .dv-value {{ color:#fca5a5; }}
    .dv-gap-ok {{ border:2px solid #22c55e; }}
    .dv-gap-ok .dv-value {{ color:#86efac; }}

    /* Tabel seragam: semua kolom rata tengah, header sticky, bisa scroll ke kanan & bawah */
    .tbl-wrap {{ overflow:auto; border:1px solid rgba(140,160,210,0.2); border-radius:14px; background:rgba(10,12,19,0.84);
                 backdrop-filter:blur(5px); margin-bottom:6px; }}
    table.tbl {{ border-collapse:separate; border-spacing:0; width:max-content; min-width:100%; font-size:0.84rem; }}
    table.tbl th, table.tbl td {{ text-align:center; padding:8px 16px; white-space:nowrap; border-bottom:1px solid rgba(255,255,255,0.06); }}
    table.tbl thead th {{ position:sticky; top:0; z-index:2; background:#181b27; color:#C9CCDA; font-weight:600;
                          font-size:0.78rem; letter-spacing:0.3px; border-bottom:1px solid rgba(255,255,255,0.12); }}
    table.tbl tbody tr:nth-child(even) {{ background:rgba(255,255,255,0.035); }}
    table.tbl tbody tr:hover {{ background:rgba(169,166,247,0.12); }}
    table.tbl tr.row-alert td {{ background:#3b1414; color:#fca5a5; }}
    table.tbl td.c-bad {{ color:#f87171; font-weight:700; }}
    table.tbl td.c-ok {{ color:#4ade80; font-weight:700; }}
    table.tbl td.c-ok2 {{ color:#a3e635; font-weight:700; }}
    table.tbl td.c-warn {{ color:#fbbf24; font-weight:700; }}
    table.tbl td.c-slow {{ color:#fb923c; font-weight:700; }}
    table.tbl td.c-info {{ color:#7dd3fc; font-weight:700; }}
    table.tbl td.c-mute {{ color:#6b7280; }}
    {_h_css}
    {_pw_css}

    /* Panel Capaian by Divisi & kartu Capaian Salesman */
    .dv-panel {{ border:1px solid rgba(140,160,210,0.2); border-radius:14px; background:rgba(10,12,19,0.80);
                 backdrop-filter:blur(5px); padding:10px 12px; margin-bottom:10px; }}
    .dv-title {{ font-weight:700; font-size:0.95rem; margin-bottom:8px; color:#F0F0F7; }}
    .dv-grid {{ display:grid; grid-template-columns:minmax(0,1.4fr) minmax(0,1.4fr) minmax(0,0.8fr) minmax(0,1.5fr); gap:8px; }}
    .dv-panel, .sc-card {{ container-type:inline-size; }}
    .dv-grid .dv-box {{ padding:7px 8px; min-height:auto; }}
    .dv-grid .dv-value {{ font-size:0.78rem; font-size:clamp(0.6rem, 2.35cqw, 0.9rem); }}
    .dv-bar {{ height:4px; border-radius:4px; background:rgba(255,255,255,0.10); margin-top:9px; overflow:hidden; }}
    .dv-bar span {{ display:block; height:100%; background:{ACCENT}; border-radius:4px; }}
    .dv-bar.ok span {{ background:#22c55e; }}
    .sc-wrap {{ padding-right:2px; }}
    .sc-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(460px, 1fr)); gap:10px; }}
    .sc-card {{ border:1px solid rgba(140,160,210,0.2); border-radius:14px; background:rgba(10,12,19,0.80);
                backdrop-filter:blur(5px); padding:9px 11px; }}
    .sc-head {{ display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:7px; }}
    .sc-name {{ font-weight:700; font-size:0.88rem; color:#F0F0F7; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .sc-tag {{ font-size:0.62rem; color:#B9B6F5; border:1px solid #3a3a55; border-radius:999px; padding:1px 8px; white-space:nowrap; }}
    .sc-card .dv-box {{ min-height:auto; padding:5px 8px; }}
    .sc-row {{ display:grid; grid-template-columns:84px minmax(0,1.4fr) minmax(0,1.4fr) minmax(0,0.8fr) minmax(0,1.5fr);
               gap:6px; align-items:stretch; margin-bottom:5px; }}
    .sc-lab {{ display:flex; align-items:center; font-size:0.66rem; font-weight:700; color:#B9B6F5; letter-spacing:0.3px; white-space:nowrap; }}
    .sc-cell {{ border:1px solid rgba(140,160,210,0.18); border-radius:8px; background:rgba(20,23,33,0.86); padding:5px 6px;
                text-align:center; min-width:0; overflow:hidden; font-weight:600; color:#E6E6EE;
                font-size:0.74rem; font-size:clamp(0.52rem, 1.95cqw, 0.8rem); }}
    .sc-cell.gap-bad {{ border:1.5px solid #ef4444; color:#fca5a5; }}
    .sc-cell.gap-ok {{ border:1.5px solid #22c55e; color:#86efac; }}
    .sc-row.sc-total .dv-box {{ min-height:auto; padding:6px 7px; }}
    .sc-row.sc-total .dv-value {{ font-size:0.8rem; font-size:clamp(0.56rem, 2.2cqw, 0.92rem); }}
    .sc-sep {{ height:1px; background:rgba(255,255,255,0.08); margin:6px 0 6px; }}
    .sc-row.sc-divisi {{ margin-bottom:4px; }}

    /* Kartu KPI Gap Harian: hijau kalau tercapai, merah kalau belum */
    .kpi-box.kpi-bad {{ border:2px solid #ef4444; }}
    .kpi-box.kpi-bad .kpi-value {{ color:#fca5a5; }}
    .kpi-box.kpi-ok {{ border:2px solid #22c55e; }}
    .kpi-box.kpi-ok .kpi-value {{ color:#86efac; }}

    /* Mobile-friendly — layar sempit (HP) */
    @media (max-width: 640px) {{
        .stApp {{ background-attachment:scroll !important; }}
        .app-title {{ font-size:1.7rem; letter-spacing:1px;
            text-shadow: 1px 1px 0 #d48ace, 2px 2px 0 #b874b2, 3px 3px 5px rgba(0,0,0,0.5); }}
        .app-watermark {{ font-size:0.7rem; margin-bottom:0.7rem; }}
        .kpi-box {{ padding:10px 12px; min-height:auto; }}
        .kpi-label {{ font-size:0.7rem; }}
        .kpi-sub {{ font-size:0.65rem; }}
        .big-nominal {{ font-size:1.6rem; }}
        .block-container {{ padding-left:0.6rem; padding-right:0.6rem; padding-top:1rem; }}
        table.tbl {{ font-size:0.74rem; }}
        table.tbl th, table.tbl td {{ padding:6px 10px; }}
        .dv-grid {{ grid-template-columns:1fr 1fr; }}
        .dv-grid .dv-value {{ font-size:0.82rem; }}
        .sc-grid {{ grid-template-columns:1fr; }}
        .sc-row {{ grid-template-columns:70px 1fr 1fr; }}
        .sc-row > :nth-child(4) {{ grid-column:2; }}
        .sc-row > :nth-child(5) {{ grid-column:3; }}
        .sc-cell {{ font-size:0.72rem; }}
    }}
    </style>
    """, unsafe_allow_html=True)


def nice(txt) -> str:
    """Rapikan teks angka untuk HTML: 'Rp' dan angkanya dikunci satu baris (spasi tak-terputus), 'Rp'/'%'
    dikecilkan supaya angkanya menonjol, dan '✓ Tercapai' tidak terpotong."""
    t = str(txt)
    t = re.sub(r"Rp\s", '<span class="cur">Rp</span>&nbsp;', t)
    t = re.sub(r"%$", '<span class="cur">%</span>', t)
    return t.replace("✓ ", "✓&nbsp;")


def kpi_card(icon: str, label: str, value: str, sub: str = "", cmp_html: str = "", state: str = ""):
    """state: '' (netral) | 'ok' (hijau) | 'bad' (merah)."""
    st.markdown(f"""
    <div class="kpi-box {('kpi-' + state) if state else ''}">
        <div class="kpi-icon">{icon}</div>
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{nice(value)}</div>
        <div class="kpi-sub">{sub}</div>
        {cmp_html}
    </div>
    """, unsafe_allow_html=True)


def dv_box(label: str, value: str, sub: str = "", css_class: str = ""):
    st.markdown(f"""
    <div class="dv-box {css_class}">
        <div class="dv-label">{label}</div>
        <div class="dv-value">{value}</div>
        <div class="dv-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


MAX_ROWS_HTML = 1500


def _fmt_cell(v) -> str:
    import html as _html
    from datetime import date as _d, datetime as _dt
    if isinstance(v, (bool, np.bool_)):
        return "✓" if v else "✗"
    try:
        if v is None or pd.isna(v):
            return "-"
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        return f"{int(v):,}" if float(v).is_integer() else f"{v:,.1f}"
    if isinstance(v, (pd.Timestamp, _dt, _d)):
        return v.strftime("%d %b %Y")
    return _html.escape(str(v))


def show_df(df, height=None, highlight_mask=None, **_ignored):
    """Tabel HTML seragam: semua kolom (dan header) rata tengah, header menempel saat scroll,
    zebra, dan bisa di-scroll ke kanan/bawah. Kolom bernama '...Gap...' otomatis berwarna:
    merah untuk '-Rp ...' (belum tercapai), hijau untuk '✓ Tercapai'.
    highlight_mask: Series boolean (urut sama dengan df) untuk menandai baris merah."""
    base = getattr(df, "data", df)
    total = len(base)
    shown = base.iloc[:MAX_ROWS_HTML]
    cols = [str(c) for c in shown.columns]
    import html as _html
    head = "".join(f"<th>{_html.escape(c)}</th>" for c in cols)
    hl = list(highlight_mask.iloc[:len(shown)]) if highlight_mask is not None else [False] * len(shown)
    body = []
    for i, tup in enumerate(shown.itertuples(index=False, name=None)):
        tds = []
        for c, v in zip(cols, tup):
            txt = _fmt_cell(v)
            cls = ""
            if "Gap" in c:
                cls = "c-bad" if txt.startswith("-Rp") else ("c-ok" if txt.startswith("✓") else "")
            elif c == "Klasifikasi":
                cls = {"Sangat Cepat": "c-ok", "Cepat": "c-ok2", "Sedang": "c-warn", "Lambat": "c-slow",
                       "Tidak Bergerak": "c-bad", "Stok Bertambah": "c-info", "Kosong": "c-mute"}.get(txt, "")
            tds.append(f'<td class="{cls}">{txt}</td>' if cls else f"<td>{txt}</td>")
        body.append(f'<tr class="row-alert">{"".join(tds)}</tr>' if hl[i] else f'<tr>{"".join(tds)}</tr>')
    h_cls = f" tbl-h-{max(120, min(1000, int(round(height / 20.0)) * 20))}" if height else ""
    st.markdown(f'<div class="tbl-wrap{h_cls}"><table class="tbl"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)
    if total > MAX_ROWS_HTML:
        st.caption(f"Menampilkan {MAX_ROWS_HTML:,} dari {total:,} baris — pakai tombol Download Excel untuk data lengkap.")


def show_chart(fig):
    """st.plotly_chart selebar kontainer — pakai width baru, fallback ke versi lama."""
    try:
        st.plotly_chart(fig, width="stretch")
    except Exception:
        show_chart(fig)


def fmt_rp(n) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)) or pd.isna(n):
        return "-"
    try:
        return "Rp {:,.0f}".format(float(n))
    except (ValueError, TypeError):
        return "-"


def fmt_gap(g) -> str:
    """Gap Harian = (Target - Capaian) / HKE. >0 = masih kurang ('-Rp ...', merah);
    <=0 = sudah tercapai ('✓ Tercapai', hijau); kosong = target belum ada ('-')."""
    if g is None or pd.isna(g):
        return "-"
    return "-" + fmt_rp(g) if g > 0 else "✓ Tercapai"


def fmt_pct(n, decimals=1) -> str:
    if n is None or pd.isna(n) or (isinstance(n, float) and np.isinf(n)):
        return "-"
    return f"{n:.{decimals}f}%"


def compare_badge(curr, prev) -> str:
    """Badge HTML kecil untuk komparasi YoY. Kosong kalau data pembanding tidak ada."""
    if prev is None or pd.isna(prev) or prev == 0:
        return ""
    delta = (curr - prev) / prev * 100
    arrow = "▲" if delta >= 0 else "▼"
    css_cls = "kpi-cmp-up" if delta >= 0 else "kpi-cmp-down"
    return f'<div class="{css_cls}">{arrow} {abs(delta):.1f}% vs tahun lalu</div>'


# =====================================================================
# 2. LOAD DATA
# =====================================================================
@st.cache_data(show_spinner="Memproses file LBP...")
def load_lbp(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    from io import BytesIO
    name = file_name.lower()
    buf = BytesIO(file_bytes)
    if name.endswith(".txt") or name.endswith(".csv"):
        # index_col=False WAJIB: file LBP punya trailing "|" di akhir tiap baris,
        # tanpa ini pandas salah mengira kolom pertama adalah index dan semua
        # kolom lain geser satu posisi.
        df = pd.read_csv(buf, sep="|", dtype=str, engine="python", index_col=False)
    else:
        df = pd.read_excel(buf, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    for c in [COL["qty"], COL["bruto"], COL["week"], COL["periode"]]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df[COL["tanggal"]] = pd.to_datetime(df[COL["tanggal"]], format="%d/%m/%Y", errors="coerce")
    df[COL["tipe_outlet"]] = df[COL["tipe_outlet"]].astype(str).str.strip()
    df[COL["transtype"]] = df[COL["transtype"]].astype(str).str.strip().str.upper()

    def classify_team(x):
        m = re.match(r"^\s*(\d+)", str(x))
        kode = m.group(1) if m else None
        return KODE_SF_LABEL.get(kode, "Lainnya")

    df["team_simple"] = df[COL["salesforce"]].apply(classify_team)
    df["_divisi_norm"] = df[COL["divisi"]].astype(str).str.strip().apply(lambda x: x.lstrip("0") or "0")

    # Token kemasan/ukuran yang dibuang KHUSUS untuk produk WOW, supaya varian
    # kemasan (mis. "GB" vs "4+2"/RCG) dihitung sebagai SKU yang sama — special
    # case khusus WOW sesuai instruksi. Untuk produk lain, angka ukuran/kemasan
    # TETAP dipertahankan sebagai pembeda SKU.
    WOW_PACKAGING_TOKENS = {"GB", "RCG", "RC", "PC", "PCS", "BOX", "BND", "SCH", "CAR"}

    def normalize_product_name(name: str) -> str:
        s = str(name).upper()
        s = re.sub(r"\bNEW\b", "", s)
        if "WOW" in s:
            s = re.split(r"\d", s, maxsplit=1)[0]  # buang semua setelah digit pertama (kode kemasan/ukuran)
            s = " ".join(t for t in s.split() if t not in WOW_PACKAGING_TOKENS)
        s = re.sub(r"[^A-Z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    df["_produk_norm"] = df[COL["nama_produk"]].apply(normalize_product_name)
    return df


def _find_sheet(xls: pd.ExcelFile, name_contains: list) -> str | None:
    for s in xls.sheet_names:
        norm = re.sub(r"\s+", " ", s.strip().upper())
        if norm in name_contains:
            return s
    return None


def _find_col(columns, must_contain: list, must_not_contain: list = ()) -> str | None:
    for c in columns:
        norm = c.strip().upper()
        if all(tok in norm for tok in must_contain) and not any(tok in norm for tok in must_not_contain):
            return c
    return None


@st.cache_data(show_spinner="Memproses file target...")
def load_target(file_bytes: bytes):
    from io import BytesIO
    empty_all = pd.DataFrame(columns=["Kode Sales", "Periode", "Target"])
    empty_divisi = pd.DataFrame(columns=["Kode Sales", "Periode", "Divisi", "Target", "_divisi_norm"])
    if file_bytes is None:
        return empty_all, empty_divisi

    try:
        xls = pd.ExcelFile(BytesIO(file_bytes))
    except Exception:
        return empty_all, empty_divisi

    # ---- Target All ----
    target_all = empty_all
    sheet_all = _find_sheet(xls, ["TARGET ALL"])
    if sheet_all:
        try:
            raw = pd.read_excel(xls, sheet_name=sheet_all, dtype=str)
            raw.columns = [c.strip() for c in raw.columns]
            kode_col = _find_col(raw.columns, ["KODE"])
            target_col = _find_col(raw.columns, ["TARGET"])
            periode_col = _find_col(raw.columns, ["PERIODE"])
            if kode_col and target_col:
                out = pd.DataFrame()
                out["Kode Sales"] = raw[kode_col].astype(str).str.strip()
                out["Target"] = pd.to_numeric(raw[target_col], errors="coerce").fillna(0)
                # Kalau file tidak punya kolom Periode, target ini dianggap berlaku
                # untuk SEMUA periode yang dipilih (Periode = <NA>, bukan 0).
                out["Periode"] = pd.to_numeric(raw[periode_col], errors="coerce").astype("Int64") if periode_col else pd.array([pd.NA] * len(raw), dtype="Int64")
                target_all = out
        except Exception:
            target_all = empty_all

    # ---- Target Divisi ----
    target_divisi = empty_divisi
    sheet_divisi = _find_sheet(xls, ["TARGET DIVISI"])
    if sheet_divisi:
        try:
            raw = pd.read_excel(xls, sheet_name=sheet_divisi, dtype=str)
            raw.columns = [c.strip() for c in raw.columns]
            kode_col = _find_col(raw.columns, ["KODE"])
            periode_col = _find_col(raw.columns, ["PERIODE"])
            # Kolom divisi: format panjang ("Divisi" + "Target" terpisah) ATAU
            # format lebar (satu kolom per divisi, mis. "5 - COFFE", "16 - HOME CARE").
            divisi_col_long = _find_col(raw.columns, ["DIVISI"])
            target_col_long = _find_col(raw.columns, ["TARGET"])
            wide_divisi_cols = [c for c in raw.columns if re.match(r"^\s*\d+\s*-", c)]

            if kode_col and wide_divisi_cols:
                rows = []
                for _, r in raw.iterrows():
                    for dc in wide_divisi_cols:
                        kode_div = dc.split("-", 1)[0].strip()
                        rows.append({
                            "Kode Sales": str(r[kode_col]).strip(),
                            "Divisi": kode_div,
                            "Target": r[dc],
                            "Periode": pd.to_numeric(r[periode_col], errors="coerce") if periode_col else pd.NA,
                        })
                out = pd.DataFrame(rows)
                out["Target"] = pd.to_numeric(out["Target"], errors="coerce").fillna(0)
                out["Periode"] = out["Periode"].astype("Int64") if periode_col else pd.array([pd.NA] * len(out), dtype="Int64")
                target_divisi = out
            elif kode_col and divisi_col_long and target_col_long:
                out = pd.DataFrame()
                out["Kode Sales"] = raw[kode_col].astype(str).str.strip()
                out["Divisi"] = raw[divisi_col_long].astype(str).str.strip()
                out["Target"] = pd.to_numeric(raw[target_col_long], errors="coerce").fillna(0)
                out["Periode"] = pd.to_numeric(raw[periode_col], errors="coerce").astype("Int64") if periode_col else pd.array([pd.NA] * len(raw), dtype="Int64")
                target_divisi = out

            if not target_divisi.empty:
                target_divisi["_divisi_norm"] = target_divisi["Divisi"].astype(str).str.strip().apply(lambda x: x.lstrip("0") or "0")
        except Exception:
            target_divisi = empty_divisi

    return target_all, target_divisi


@st.cache_data(show_spinner="Memproses file DMP...")
def load_dmp(file_bytes: bytes) -> pd.DataFrame:
    from io import BytesIO
    df = pd.read_csv(BytesIO(file_bytes), sep="|", dtype=str, engine="python", index_col=False)
    df.columns = [c.strip() for c in df.columns]
    df = df[df[DMP_COL["rayon"]].notna() & (df[DMP_COL["rayon"]].astype(str).str.strip() != "")]
    df = df[~df[DMP_COL["salesman"]].astype(str).str.upper().str.contains("VACANT", na=False)]
    df["_lastupdate_dt"] = pd.to_datetime(df[DMP_COL["lastupdate"]], format="%d/%m/%Y", errors="coerce")
    df = df.sort_values("_lastupdate_dt", ascending=False).drop_duplicates(subset=[DMP_COL["outlet"]], keep="first")
    df["Kategori Channel"] = df.apply(
        lambda r: classify_channel_memo(r.get(DMP_COL["namaclass"]), r.get(DMP_COL["namachannel"])), axis=1)
    out = df[[DMP_COL["outlet"], DMP_COL["nama_outlet"], DMP_COL["salesman"], DMP_COL["kode_sales"],
              DMP_COL["rayon"], "Kategori Channel"]]
    return out.rename(columns={DMP_COL["outlet"]: COL["outlet"], DMP_COL["nama_outlet"]: "Nama Outlet (DMP)",
                                DMP_COL["salesman"]: "Salesman", DMP_COL["kode_sales"]: "Kode Sales (DMP)",
                                DMP_COL["rayon"]: "Rayon"})


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    return buf.getvalue()


def download_button(df: pd.DataFrame, label: str, filename: str, key: str):
    st.download_button(label, data=to_excel_bytes(df), file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=key)


# =====================================================================
# 3. PERHITUNGAN INTI
# =====================================================================
def net_by_group(df: pd.DataFrame, group_cols, value_col_name="Omzet") -> pd.DataFrame:
    # PENTING: "Harga Bruto" untuk baris TRANSTYPE == "R" SUDAH negatif di sumber
    # data (mis. -490000). Neto yang benar = F + R (R sudah membawa tanda minus).
    pv = df.pivot_table(index=group_cols, columns=COL["transtype"], values=COL["bruto"],
                         aggfunc="sum", fill_value=0)
    for tt in ["F", "R"]:
        if tt not in pv.columns:
            pv[tt] = 0
    pv[value_col_name] = pv["F"] + pv["R"]
    pv["Bruto F"] = pv["F"]
    pv["Bruto R"] = pv["R"].abs()
    return pv[[value_col_name, "Bruto F", "Bruto R"]].reset_index()


def hitung_pencapaian(df: pd.DataFrame):
    bruto_f = df.loc[df[COL["transtype"]] == "F", COL["bruto"]].sum()
    bruto_r_raw = df.loc[df[COL["transtype"]] == "R", COL["bruto"]].sum()
    pencapaian = bruto_f + bruto_r_raw
    bruto_r = abs(bruto_r_raw)
    pct_retur = (bruto_r / bruto_f * 100) if bruto_f else 0
    return pencapaian, bruto_f, bruto_r, pct_retur


def hitung_oa(df: pd.DataFrame) -> int:
    return df.loc[df[COL["transtype"]] == "F", COL["outlet"]].nunique()


def top_categories_for_pie(df_agg: pd.DataFrame, name_col: str, val_col: str, n: int, add_other: bool):
    d = df_agg.sort_values(val_col, ascending=False).reset_index(drop=True)
    top = d.head(n).copy()
    if add_other and len(d) > n:
        sisa = d.iloc[n:][val_col].sum()
        top = pd.concat([top, pd.DataFrame({name_col: ["Lainnya"], val_col: [sisa]})], ignore_index=True)
    return top


def pie_chart(df_agg: pd.DataFrame, name_col: str, val_col: str, title: str = ""):
    fig = px.pie(df_agg, names=name_col, values=val_col, hole=0.5, color_discrete_sequence=PALETTE, title=title)
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=13,
                       marker=dict(line=dict(color="#0E1117", width=2)))
    fig.update_layout(height=420, margin=dict(t=50, b=10, l=10, r=10),
                       legend=dict(orientation="h", yanchor="bottom", y=-0.25),
                       font=dict(size=13))
    return fig


def bar_chart(df_agg: pd.DataFrame, x_col: str, y_col: str, title: str = ""):
    fig = px.bar(df_agg, x=x_col, y=y_col, title=title, color_discrete_sequence=[ACCENT], text_auto=".2s")
    fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), font=dict(size=13))
    return fig


def gauge_chart(value: float, title: str, max_value: float = 100):
    value = 0 if pd.isna(value) else value
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=round(value, 1),
        title={"text": title, "font": {"size": 16}},
        number={"suffix": "%", "font": {"size": 32}},
        gauge={
            "axis": {"range": [0, max_value]},
            "bar": {"color": ACCENT, "thickness": 0.3},
            "bgcolor": "#1C1F26",
            "steps": [
                {"range": [0, max_value * 0.6], "color": "#3A1F1F"},
                {"range": [max_value * 0.6, max_value * 0.9], "color": "#3A331F"},
                {"range": [max_value * 0.9, max_value], "color": "#1F3A28"},
            ],
        },
    ))
    fig.update_layout(height=320, margin=dict(t=60, b=20, l=30, r=30), font=dict(color="#E6E6E6"))
    return fig


def tier_lookup(pct, tiers) -> int:
    if pct is None or pd.isna(pct):
        return 0
    value = 0
    for min_pct, v in tiers:
        if pct >= min_pct:
            value = v
    return value


def ringkasan_by_salesman(df: pd.DataFrame, target_all: pd.DataFrame, periode_sel, hke: float) -> pd.DataFrame:
    f_only = df[df[COL["transtype"]] == "F"]

    net = net_by_group(df, [COL["kode_sales"], COL["salesman"], "team_simple"], "Net Sales")
    oa = f_only.groupby([COL["kode_sales"], COL["salesman"]])[COL["outlet"]].nunique().reset_index(name="OA")
    ec = (
        f_only.groupby([COL["kode_sales"], COL["salesman"], f_only[COL["tanggal"]].dt.date])[COL["outlet"]]
        .nunique().groupby(level=[0, 1]).sum().reset_index(name="EC")
    )
    avg_sku = (
        f_only.groupby([COL["kode_sales"], COL["salesman"], COL["outlet"]])["_produk_norm"]
        .nunique().groupby(level=[0, 1]).mean().reset_index(name="Avg SKU")
    )

    out = net.merge(oa, on=[COL["kode_sales"], COL["salesman"]], how="left")
    out = out.merge(ec, on=[COL["kode_sales"], COL["salesman"]], how="left")
    out = out.merge(avg_sku, on=[COL["kode_sales"], COL["salesman"]], how="left")
    out[["OA", "EC", "Avg SKU"]] = out[["OA", "EC", "Avg SKU"]].fillna(0)
    out["Avg SKU"] = out["Avg SKU"].round(1)

    out["CB Standar"] = out["team_simple"].map(lambda tm: PRODUKTIVITY_STANDAR.get(tm, {}).get("cb_cover"))
    out["% OA"] = np.where(out["CB Standar"].notna(), (out["OA"] / out["CB Standar"] * 100).round(1), np.nan)

    if not target_all.empty:
        tgt = target_all.copy()
        if periode_sel:
            tgt = tgt[tgt[TARGET_ALL_COL["periode"]].isna() | tgt[TARGET_ALL_COL["periode"]].isin(periode_sel)]
        tgt = tgt.groupby(TARGET_ALL_COL["kode_sales"])[TARGET_ALL_COL["target"]].sum().reset_index()
        out = out.merge(tgt, left_on=COL["kode_sales"], right_on=TARGET_ALL_COL["kode_sales"], how="left")
        out = out.rename(columns={TARGET_ALL_COL["target"]: "Target"})
    else:
        out["Target"] = np.nan

    out["% Capaian"] = (out["Net Sales"] / out["Target"] * 100).round(1)
    out["Gap Harian"] = ((out["Target"] - out["Net Sales"]) / hke).round(0) if hke else np.nan

    out = out.rename(columns={COL["kode_sales"]: "Kode Sales", COL["salesman"]: "Salesman", "team_simple": "Team"})
    return out.sort_values("Net Sales", ascending=False)


def format_cols(df: pd.DataFrame, rp_cols=(), pct_cols=()) -> pd.DataFrame:
    out = df.copy()
    for c in rp_cols:
        if c in out.columns:
            out[c] = out[c].apply(fmt_gap if "Gap Harian" in str(c) else fmt_rp)
    for c in pct_cols:
        if c in out.columns:
            out[c] = out[c].apply(fmt_pct)
    return out


def universe_sku_per_kategori(df_f: pd.DataFrame) -> dict:
    """Proxy 'master SKU': semua SKU (dedup nama produk ternormalisasi) yang pernah
    laku di tiap Kategori Channel (dari DMP) dalam data yang sedang difilter."""
    universe = {}
    for kategori, g in df_f.groupby("Kategori Channel"):
        universe[kategori] = g.drop_duplicates(subset=["_produk_norm"])[[COL["pcode"], COL["nama_produk"], "_produk_norm"]]
    return universe


def hitung_mhs_resume(df_scope: pd.DataFrame) -> pd.DataFrame:
    f_only = df_scope[df_scope[COL["transtype"]] == "F"]
    group_cols = [COL["outlet"], COL["nama_outlet"], COL["kode_sales"], COL["salesman"],
                  COL["channel"], "Kategori Channel"]
    if "Rayon" in f_only.columns:
        group_cols.append("Rayon")
    sku_terjual = f_only.groupby(group_cols)["_produk_norm"].nunique().reset_index(name="SKU Terjual")
    sku_terjual["Target SKU"] = sku_terjual["Kategori Channel"].map(TARGET_SKU_BY_CLASS)
    sku_terjual["Kekurangan SKU"] = (sku_terjual["Target SKU"] - sku_terjual["SKU Terjual"]).clip(lower=0)
    sku_terjual["Lolos MHS"] = sku_terjual["SKU Terjual"] >= sku_terjual["Target SKU"]
    return sku_terjual.dropna(subset=["Target SKU"]).rename(
        columns={COL["outlet"]: "No Outlet", COL["nama_outlet"]: "Nama Outlet",
                 COL["salesman"]: "Salesman", COL["channel"]: "Channel"})


def hitung_mhs_by_salesman(tampil: pd.DataFrame, df_scope: pd.DataFrame, outlet_count_dmp: pd.Series) -> pd.DataFrame:
    """outlet_count_dmp: Series jumlah outlet dari DMP, index = Kode Sales.
    Ini pembagi %MHS yang baru (ganti CB Standpro), dikunci per Kode Sales
    tapi kode sales-nya sendiri tidak ditampilkan di tabel hasil."""
    if tampil.empty:
        return pd.DataFrame(columns=["Salesman", "Team", "Jumlah Outlet (DMP)", "Total Outlet Bertransaksi",
                                      "Outlet Lolos MHS", "% MHS"])
    agg = tampil.groupby("Salesman").agg(Total_Outlet=("Lolos MHS", "count"),
                                          Outlet_Lolos=("Lolos MHS", "sum")).reset_index()
    team_map = df_scope.drop_duplicates(subset=[COL["salesman"]])[[COL["salesman"], "team_simple", COL["kode_sales"]]]
    agg = agg.merge(team_map, left_on="Salesman", right_on=COL["salesman"], how="left")
    agg["Jumlah Outlet (DMP)"] = agg[COL["kode_sales"]].map(outlet_count_dmp)
    agg["% MHS"] = np.where(agg["Jumlah Outlet (DMP)"].fillna(0) > 0,
                             (agg["Outlet_Lolos"] / agg["Jumlah Outlet (DMP)"] * 100).round(1), np.nan)
    out = agg.rename(columns={"Outlet_Lolos": "Outlet Lolos MHS", "Total_Outlet": "Total Outlet Bertransaksi",
                               "team_simple": "Team"})
    return out.drop(columns=[COL["kode_sales"]])


# =====================================================================
# 4. AKSES & SIDEBAR — password gate, Option (upload / pakai file lama),
#    Tahun, Pilih Salesman, Periode/Week/HKA/CB
# =====================================================================
inject_css()

SAVED_DIR = "saved_uploads"
SAVED_SUBDIRS = {"lbp": "lbp", "target": "target", "dmp": "dmp"}
for _sub in SAVED_SUBDIRS.values():
    os.makedirs(os.path.join(SAVED_DIR, _sub), exist_ok=True)


def _file_name(file) -> str:
    return file if isinstance(file, str) else file.name


def list_saved_files(subdir: str):
    d = os.path.join(SAVED_DIR, subdir)
    try:
        files = [f for f in os.listdir(d) if not f.startswith(".")]
    except FileNotFoundError:
        return []

    def safe_mtime(f):
        try:
            return os.path.getmtime(os.path.join(d, f))
        except FileNotFoundError:
            return 0

    # File bisa saja hilang di antara listdir() dan getmtime() kalau ada rerun/
    # sesi lain yang menimpa folder yang sama di saat bersamaan (filesystem
    # Streamlit Cloud dipakai bareng antar rerun) — buang yang sudah tak ada.
    files = [f for f in files if os.path.exists(os.path.join(d, f))]
    return sorted(files, key=safe_mtime, reverse=True)


def save_uploaded_file(file, subdir: str) -> None:
    path = os.path.join(SAVED_DIR, subdir, file.name)
    with open(path, "wb") as f:
        f.write(file.getvalue())


def check_password() -> bool:
    """Gerbang password sederhana. Password diset lewat Streamlit Secrets
    (APP_PASSWORD) — kalau secret ini tidak diset (mis. saat develop lokal),
    gerbang dilewati otomatis supaya tidak menghalangi development."""
    try:
        app_password = st.secrets.get("APP_PASSWORD")
    except Exception:  # tidak ada secrets.toml sama sekali (mis. jalan lokal) -> tanpa password
        app_password = None
    if not app_password:
        return True
    if st.session_state.get("app_authenticated"):
        return True
    st.markdown('<div class="app-title">Dashboard Operational Area MV42</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-watermark">&copy; Created by Adelard</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Masukkan password untuk mengakses dashboard</div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        pw = st.text_input("Password", type="password", label_visibility="collapsed")
        if st.button("Masuk", width="stretch"):
            if pw == app_password:
                st.session_state.app_authenticated = True
                st.rerun()
            else:
                st.error("Password salah.")
    return False


if not check_password():
    st.stop()

with st.sidebar:
    st.markdown("### ⚙️ Option")
    target_file = st.file_uploader("Upload File Target (.xlsx, sheet 'Target All' & 'Target Divisi')",
                                    type=["xls", "xlsx"])
    if target_file is not None:
        save_uploaded_file(target_file, SAVED_SUBDIRS["target"])
    else:
        saved_targets = list_saved_files(SAVED_SUBDIRS["target"])
        if saved_targets:
            pilih_target = st.selectbox("...atau pakai file Target yang sudah pernah diupload",
                                         ["(tidak pakai)"] + saved_targets, key="pilih_target_saved")
            if pilih_target != "(tidak pakai)":
                target_file = os.path.join(SAVED_DIR, SAVED_SUBDIRS["target"], pilih_target)

    lbp_files_uploaded = st.file_uploader("Upload File LBP (.txt / .xls) — bisa lebih dari 1 tahun sekaligus",
                                           type=["txt", "csv", "xls", "xlsx"], accept_multiple_files=True)
    for _f in lbp_files_uploaded:
        save_uploaded_file(_f, SAVED_SUBDIRS["lbp"])
    saved_lbp = list_saved_files(SAVED_SUBDIRS["lbp"])
    pilih_lbp_saved = []
    if saved_lbp:
        pilih_lbp_saved = st.multiselect("...atau pakai file LBP yang sudah pernah diupload", saved_lbp,
                                          key="pilih_lbp_saved")
    lbp_files = list(lbp_files_uploaded) + [os.path.join(SAVED_DIR, SAVED_SUBDIRS["lbp"], f) for f in pilih_lbp_saved]

    dmp_file = st.file_uploader("Upload File DMP (.txt) — untuk info Rayon", type=["txt", "csv"])
    if dmp_file is not None:
        save_uploaded_file(dmp_file, SAVED_SUBDIRS["dmp"])
    else:
        saved_dmp = list_saved_files(SAVED_SUBDIRS["dmp"])
        if saved_dmp:
            pilih_dmp = st.selectbox("...atau pakai file DMP yang sudah pernah diupload",
                                      ["(tidak pakai)"] + saved_dmp, key="pilih_dmp_saved")
            if pilih_dmp != "(tidak pakai)":
                dmp_file = os.path.join(SAVED_DIR, SAVED_SUBDIRS["dmp"], pilih_dmp)

def _read_bytes_and_name(file):
    """UploadedFile atau path string (file lama yang disimpan) -> (bytes, nama).
    Cache Streamlit di-key dari BYTES mentah (primitif aman), bukan dari
    objek file-like — ini yang menghindari bug lama: Streamlit sempat mencoba
    mem-vstat nama file sebagai path asli lewat os.path.getmtime dan crash
    kalau nama itu bukan path yang valid relatif ke direktori kerja.
    Return (None, None) kalau file lama ternyata sudah hilang dari server."""
    if isinstance(file, str):
        if not os.path.exists(file):
            st.warning(f"File '{os.path.basename(file)}' yang tersimpan sebelumnya sudah tidak ada di server "
                       "(kemungkinan app sempat di-restart) — silakan upload ulang file ini.")
            return None, None
        with open(file, "rb") as f:
            return f.read(), os.path.basename(file)
    return file.getvalue(), file.name


if not lbp_files:
    st.info("Upload minimal 1 file LBP di sidebar (⚙️ Option), atau pilih dari file yang sudah pernah diupload.")
    st.stop()

lbp_by_year: dict[int, pd.DataFrame] = {}
for f in lbp_files:
    f_bytes, f_name = _read_bytes_and_name(f)
    if f_bytes is None:
        continue
    d = load_lbp(f_bytes, f_name)
    for y, g in d.groupby(d[COL["tanggal"]].dt.year.dropna().astype(int)):
        lbp_by_year[y] = pd.concat([lbp_by_year.get(y, pd.DataFrame()), g], ignore_index=True)

if not lbp_by_year:
    st.error("Tidak ada data LBP yang berhasil dimuat. Silakan upload ulang file LBP.")
    st.stop()

_target_bytes, _ = _read_bytes_and_name(target_file) if target_file is not None else (None, None)
target_all, target_divisi = load_target(_target_bytes) if _target_bytes is not None else (
    pd.DataFrame(columns=[TARGET_ALL_COL["kode_sales"], TARGET_ALL_COL["periode"], TARGET_ALL_COL["target"]]),
    pd.DataFrame(columns=[TARGET_DIVISI_COL["kode_sales"], TARGET_DIVISI_COL["periode"],
                           TARGET_DIVISI_COL["divisi"], TARGET_DIVISI_COL["target"], "_divisi_norm"]))

_dmp_bytes, _ = _read_bytes_and_name(dmp_file) if dmp_file is not None else (None, None)
dmp_master = load_dmp(_dmp_bytes) if _dmp_bytes is not None else pd.DataFrame(
    columns=[COL["outlet"], "Nama Outlet (DMP)", "Salesman", "Kode Sales (DMP)", "Rayon", "Kategori Channel"])
rayon_channel_map = dmp_master[[COL["outlet"], "Rayon", "Kategori Channel"]] if not dmp_master.empty else pd.DataFrame(
    columns=[COL["outlet"], "Rayon", "Kategori Channel"])
for y in lbp_by_year:
    if not rayon_channel_map.empty:
        lbp_by_year[y] = lbp_by_year[y].merge(rayon_channel_map, on=COL["outlet"], how="left")
    else:
        lbp_by_year[y]["Rayon"] = np.nan
        lbp_by_year[y]["Kategori Channel"] = np.nan

# Jumlah outlet per Kode Sales dari DMP — pembagi %MHS yang baru (poin 2),
# menggantikan CB Standpro Team. Dikunci ke Kode Sales, TIDAK ditampilkan
# ke tabel manapun.
outlet_count_dmp = (dmp_master.groupby("Kode Sales (DMP)")[COL["outlet"]].nunique()
                     if not dmp_master.empty else pd.Series(dtype=int))

available_years = sorted(lbp_by_year.keys())

with st.sidebar:
    st.divider()
    st.markdown("### 📅 Tahun Data")
    tahun_aktif = st.selectbox("Tahun Aktif", available_years, index=len(available_years) - 1)
    bisa_banding = (tahun_aktif - 1) in lbp_by_year
    bandingkan = st.checkbox("Bandingkan dengan tahun lalu", value=False, disabled=not bisa_banding,
                              help="Aktif kalau kamu upload data LBP tahun sebelumnya juga.")

    st.divider()
    st.markdown("### 👥 Pilih Salesman")
    salesman_opts = sorted(lbp_by_year[tahun_aktif][COL["salesman"]].dropna().unique().tolist())
    pilih_semua = st.checkbox("Pilih Semua Salesman", value=True)
    salesman_terpilih = st.multiselect("Salesman Terpilih", salesman_opts,
                                        default=salesman_opts if pilih_semua else [])

import hashlib


def fkey(name: str, *selections) -> str:
    """Key widget filter lokal per-menu yang ikut berubah kalau pilihan salesman di
    sidebar (atau filter induknya) berubah. Tanpa ini Streamlit mengingat pilihan lama
    dari key yang sama, sehingga menu tidak ikut mengikuti salesman yang dipilih di Option."""
    raw = "|".join(",".join(map(str, s)) for s in (salesman_terpilih, *selections))
    return f"{name}_{hashlib.md5(raw.encode()).hexdigest()[:8]}"


df_lbp = lbp_by_year[tahun_aktif]
df_sales_scope = df_lbp[df_lbp[COL["salesman"]].isin(salesman_terpilih)] if salesman_terpilih else df_lbp.iloc[0:0]

with st.sidebar:
    st.divider()
    st.markdown("### 📅 Periode, Week & HKA")
    periode_opts = sorted(df_sales_scope[COL["periode"]].dropna().unique().astype(int).tolist())
    week_opts = sorted(df_sales_scope[COL["week"]].dropna().unique().astype(int).tolist())
    periode_sel = st.multiselect("Filter Periode", periode_opts, default=periode_opts)
    week_sel = st.multiselect("Filter Week", week_opts, default=week_opts)
    hka = st.number_input("HKA (Hari Kerja Aktif)", min_value=0, value=24, step=1)
    hke = st.number_input("HKE (Hari Kerja Efektif) — pembagi Gap Harian", min_value=0, value=24, step=1)

df_filtered = df_sales_scope.copy()
if periode_sel:
    df_filtered = df_filtered[df_filtered[COL["periode"]].isin(periode_sel)]
if week_sel:
    df_filtered = df_filtered[df_filtered[COL["week"]].isin(week_sel)]

team_per_salesman = df_filtered.drop_duplicates(subset=[COL["kode_sales"]])[[COL["kode_sales"], "team_simple"]]
saran_cb = int(team_per_salesman["team_simple"].map(lambda tm: PRODUKTIVITY_STANDAR.get(tm, {}).get("cb_cover", 0)).sum())

with st.sidebar:
    cb_standpro_area = st.number_input("CB Standpro Area (saran otomatis, bisa ditimpa)",
                                        min_value=0, value=saran_cb, step=1)

# --- Data tahun pembanding (kalau toggle aktif) ---
df_filtered_prev = None
if bandingkan:
    df_prev_scope = lbp_by_year[tahun_aktif - 1]
    df_prev_scope = df_prev_scope[df_prev_scope[COL["salesman"]].isin(salesman_terpilih)] if salesman_terpilih else df_prev_scope.iloc[0:0]
    if periode_sel:
        df_prev_scope = df_prev_scope[df_prev_scope[COL["periode"]].isin(periode_sel)]
    if week_sel:
        df_prev_scope = df_prev_scope[df_prev_scope[COL["week"]].isin(week_sel)]
    df_filtered_prev = df_prev_scope

# =====================================================================
# 5. HEADER & TOP BAR
# =====================================================================
st.markdown('<div class="app-title">Dashboard Operational Area MV42</div>', unsafe_allow_html=True)
st.markdown('<div class="app-watermark">&copy; Created by Adelard</div>', unsafe_allow_html=True)

pencapaian, bruto_f, bruto_r, pct_retur = hitung_pencapaian(df_filtered)
oa_total = hitung_oa(df_filtered)

kode_sales_scope = df_filtered[COL["kode_sales"]].unique().tolist()
target_total = 0
if not target_all.empty:
    tgt_df = target_all[target_all[TARGET_ALL_COL["kode_sales"]].isin(kode_sales_scope)]
    if periode_sel:
        tgt_df = tgt_df[tgt_df[TARGET_ALL_COL["periode"]].isna() | tgt_df[TARGET_ALL_COL["periode"]].isin(periode_sel)]
    target_total = tgt_df[TARGET_ALL_COL["target"]].sum()

# Gap Harian harus membandingkan yang sebanding: capaian HANYA dari salesman yang punya target
# (kalau semua salesman dijumlah tapi target cuma ada untuk sebagian, kartu bisa salah "Tercapai").
kode_bertarget = tgt_df[TARGET_ALL_COL["kode_sales"]].unique().tolist() if not target_all.empty else []
pencapaian_bt = (hitung_pencapaian(df_filtered[df_filtered[COL["kode_sales"]].isin(kode_bertarget)])[0]
                 if kode_bertarget else 0)
n_bertarget = len(kode_bertarget)
gap_harian_total = ((target_total - pencapaian_bt) / hke) if hke else 0
oa_pct = (oa_total / cb_standpro_area * 100) if cb_standpro_area else 0

pencapaian_prev = oa_prev = None
if bandingkan and df_filtered_prev is not None:
    pencapaian_prev, _, _, _ = hitung_pencapaian(df_filtered_prev)
    oa_prev = hitung_oa(df_filtered_prev)

k1, k2, k3, k4 = st.columns(4)
with k1:
    kpi_card("🎯", "Target", fmt_rp(target_total))
with k2:
    kpi_card("💰", "Pencapaian (Neto F+R)", fmt_rp(pencapaian),
              f"Bruto F {fmt_rp(bruto_f)} &middot; Retur {pct_retur:.2f}% ({fmt_rp(bruto_r)})",
              compare_badge(pencapaian, pencapaian_prev) if bandingkan else "")
with k3:
    if not target_total:
        kpi_card("📉", "Gap Harian", "-", "target belum ada")
    elif pencapaian_bt >= target_total:
        kpi_card("📉", "Gap Harian", "✓ Tercapai", f"lebih {fmt_rp(pencapaian_bt - target_total)} &middot; {n_bertarget} salesman ber-target", state="ok")
    else:
        kpi_card("📉", "Gap Harian", "-" + fmt_rp(gap_harian_total),
                 f"kurang {fmt_rp(target_total - pencapaian_bt)} &middot; HKE {hke} &middot; {n_bertarget} salesman ber-target", state="bad")
with k4:
    kpi_card("🏪", "OA (Outlet Aktif)", f"{oa_total} outlet",
              f"{oa_pct:.1f}% dari CB Standpro Area ({cb_standpro_area})",
              compare_badge(oa_total, oa_prev) if bandingkan else "")

st.divider()

# =====================================================================
# 6. TABS
# =====================================================================
STOCK_HEADER_KW = ("kode", "code", "sku", "pcode", "item", "barang", "nama", "name", "produk", "product", "desc",
                   "qty", "stok", "stock", "saldo", "jumlah", "ctn", "karton", "carton", "pcs", "gudang", "lokasi",
                   "warehouse", "satuan", "unit", "bagian")
STOCK_CLASSES = ["Sangat Cepat", "Cepat", "Sedang", "Lambat", "Stok Bertambah", "Tidak Bergerak", "Kosong"]
STOCK_CLASS_COLOR = {"Sangat Cepat": "#22c55e", "Cepat": "#a3e635", "Sedang": "#fbbf24", "Lambat": "#fb923c",
                     "Stok Bertambah": "#7dd3fc", "Tidak Bergerak": "#ef4444", "Kosong": "#6b7280"}


def stock_pdf_rows(file_bytes: bytes) -> list:
    """Baris-baris tabel dari PDF berbasis teks. Coba deteksi tabel bergaris dulu; kalau tidak ada,
    pecah tiap baris teks pada spasi lebar (2+ spasi) seperti laporan ERP."""
    from io import BytesIO
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("Library 'pdfplumber' belum terpasang (tambahkan ke requirements.txt).") from e
    rows, from_text = [], False
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                for r in tbl:
                    if r and any(c not in (None, "") for c in r):
                        rows.append([("" if c is None else str(c).replace("\n", " ").strip()) for c in r])
        if not rows:
            from_text = True
            for page in pdf.pages:
                for line in (page.extract_text(layout=True) or "").splitlines():
                    parts = [p.strip() for p in re.split(r"\s{2,}|\t", line.strip()) if p.strip()]
                    if len(parts) >= 2:
                        rows.append(parts)
    if not rows:
        raise ValueError("Tidak ada tabel/teks tabular yang terbaca (PDF hasil scan/gambar tidak didukung).")
    if from_text:  # ambil hanya baris dengan jumlah kolom paling umum (buang judul/total/nomor halaman)
        from collections import Counter
        mode_n = Counter(len(r) for r in rows).most_common(1)[0][0]
        rows = [r for r in rows if len(r) == mode_n]
    width = max(len(r) for r in rows)
    return [r + [""] * (width - len(r)) for r in rows]


@st.cache_data(show_spinner="Membaca file stok...")
def stock_read_raw(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """Baca file apa adanya (tanpa header) — header dicari otomatis oleh stock_promote_header."""
    from io import BytesIO, StringIO
    name = file_name.lower()
    if name.endswith(".pdf"):
        return pd.DataFrame(stock_pdf_rows(file_bytes))
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(BytesIO(file_bytes), header=None, dtype=str)
    text = file_bytes.decode("utf-8-sig", errors="replace")
    return pd.read_csv(StringIO(text), sep=None, engine="python", header=None, dtype=str,
                       index_col=False, on_bad_lines="skip")


def stock_promote_header(raw: pd.DataFrame, forced: int | None = None):
    """Cari baris header (baris dengan kata kunci kolom stok terbanyak di 30 baris pertama) lalu jadikan
    nama kolom. Baris judul di atas header dan header yang berulang tiap halaman dibuang."""
    df = raw.fillna("").astype(str)
    df = df[df.apply(lambda r: any(str(c).strip() for c in r), axis=1)].reset_index(drop=True)
    if df.empty:
        return df, 0
    if forced is None:
        scan = min(len(df), 30)
        scores = [sum(1 for c in df.iloc[i] if str(c).strip() and any(k in str(c).lower() for k in STOCK_HEADER_KW))
                  for i in range(scan)]
        hdr = int(np.argmax(scores)) if max(scores) > 0 else 0
    else:
        hdr = min(max(forced, 0), len(df) - 1)
    header = [str(c).strip() for c in df.iloc[hdr]]
    cols = []
    for i, h in enumerate(header):
        h = h or f"Kolom {i + 1}"
        while h in cols:
            h += "_"
        cols.append(h)
    body = df.iloc[hdr + 1:].copy()
    body.columns = cols
    body = body.apply(lambda s: s.str.strip())
    same_as_header = (body.values == np.array(header, dtype=object)).all(axis=1)
    return body[~same_as_header].reset_index(drop=True), hdr


def stock_guess_date(file_name: str):
    from datetime import date
    m = re.search(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})", file_name)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[-_.](\d{1,2})[-_.](20\d{2})", file_name)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def stock_to_num(s: pd.Series) -> pd.Series:
    def conv(x: str) -> str:
        x = re.sub(r"[^\d,.\-]", "", str(x).strip())
        if "," in x and "." in x:  # 1.234,56 atau 1,234.56
            return x.replace(".", "").replace(",", ".") if x.rfind(",") > x.rfind(".") else x.replace(",", "")
        if "," in x:
            head, _, tail = x.rpartition(",")
            return head.replace(",", "") + "." + tail if len(tail) <= 2 else x.replace(",", "")
        if "." in x:  # format Indonesia: 1.000 / 12.345 / 1.234.567 = pemisah ribuan
            parts = x.split(".")
            if len(parts) > 2 or (len(parts[-1]) == 3 and parts[0].lstrip("-") not in ("", "0")):
                return x.replace(".", "")
        return x
    return pd.to_numeric(s.apply(conv), errors="coerce").fillna(0)


def stock_numeric_ratio(s: pd.Series) -> float:
    v = s.astype(str).str.strip()
    v = v[v != ""]
    if v.empty:
        return 0.0
    return float(pd.to_numeric(v.str.replace(r"[.,\s\-]", "", regex=True), errors="coerce").notna().mean())


def stock_detect_columns(df: pd.DataFrame) -> dict:
    """Tebak kolom kode / nama / qty / lokasi dari nama kolom. Untuk qty: utamakan kolom CTN/karton,
    lalu kolom stok/qty/saldo; kalau tidak ketemu, ambil kolom yang paling berisi angka."""
    cols = [str(c) for c in df.columns]
    low = [c.lower() for c in cols]

    def find(kws, exclude=()):
        for kw in kws:
            for i, c in enumerate(low):
                if kw in c and not any(x in c for x in exclude):
                    return cols[i]
        return None

    kode = find(["pcode", "kode barang", "kode", "sku", "item", "code", "artikel", "material"],
                exclude=("gudang", "lokasi", "warehouse", "satuan"))
    nama = find(["nama barang", "nama", "name", "desc", "produk", "product", "barang"], exclude=("kode", "code"))
    lokasi = find(["gudang", "lokasi", "warehouse", "location", "bagian", "rak"], exclude=("kode",))
    qty_ex = ("kode", "nama", "name", "isi", "per ", "konv", "harga", "price", "satuan")
    qty = find(["ctn", "karton", "carton"], exclude=qty_ex) or find(
        ["qty", "stok", "stock", "saldo", "jumlah", "akhir", "onhand"], exclude=qty_ex)
    if qty is None or qty in (kode, nama, lokasi):
        best, best_r = None, 0.0
        for c in cols:
            if c in (kode, nama, lokasi):
                continue
            r = stock_numeric_ratio(df[c])
            if r > best_r:
                best, best_r = c, r
        qty = best
    if kode is None and nama is None and cols:
        kode = cols[0]
    return {"kode": kode, "nama": nama, "qty": qty, "lokasi": lokasi}


def stock_compute(snaps: list, names_map: dict, has_loc: bool, thr=(70, 40, 15)):
    """snaps: [(date, Series qty per (Lokasi,)Kode)] urut tanggal. Return (res, date_cols, n_days).
    Klasifikasi (dari % stok yang keluar terhadap stok tertinggi sebelum snapshot terakhir):
    Tidak Bergerak = qty sama di semua file & > 0 | Stok Bertambah = hanya ada tambahan, belum keluar |
    Sangat Cepat / Cepat / Sedang / Lambat = % keluar >= thr[0] / thr[1] / thr[2] / sisanya | Kosong = selalu 0."""
    date_cols = [d.strftime("%d %b %Y") for d, _ in snaps]
    wide = pd.concat([s for _, s in snaps], axis=1).fillna(0)
    wide.columns = date_cols
    wide.index.names = ["Lokasi", "Kode"] if has_loc else ["Kode"]
    vals = wide.to_numpy(dtype=float)
    diffs = vals[:, 1:] - vals[:, :-1]
    keluar = np.clip(-diffs, 0, None).sum(axis=1)
    masuk = np.clip(diffs, 0, None).sum(axis=1)
    base = vals[:, :-1].max(axis=1)
    pct = np.where(base > 0, np.minimum(keluar / np.where(base > 0, base, 1) * 100, 100), np.nan)
    n_days = max((snaps[-1][0] - snaps[0][0]).days, 0)
    static = (vals.max(axis=1) == vals.min(axis=1)) & (vals[:, -1] > 0)
    kosong = vals.max(axis=1) == 0
    klas = np.select(
        [kosong, static, keluar == 0, pct >= thr[0], pct >= thr[1], pct >= thr[2]],
        ["Kosong", "Tidak Bergerak", "Stok Bertambah", "Sangat Cepat", "Cepat", "Sedang"], default="Lambat")
    res = wide.reset_index()
    res.insert(len(wide.index.names), "Nama Produk", res["Kode"].map(names_map))
    res["Keluar"] = keluar
    res["Masuk"] = masuk
    res["% Keluar"] = np.round(pct, 1)
    res["Keluar/Hari"] = np.round(keluar / n_days, 1) if n_days > 0 else np.nan
    res["Klasifikasi"] = klas
    return res, date_cols, n_days


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
TREND_METRICS = ["Omzet Neto (Rp)", "OA (Outlet Aktif)", "EC (Effective Call)"]


def build_trend(df: pd.DataFrame, gran: str, metric: str, shift_year: bool = False) -> pd.DataFrame:
    """Data grafik garis. gran: Daily/Weekly/Monthly. Kolom hasil: x (sortable), label, y."""
    empty = pd.DataFrame(columns=["x", "label", "y"])
    if df is None or df.empty:
        return empty
    d = df.copy()
    d["_date"] = d[COL["tanggal"]].dt.normalize()
    key = {"Daily": "_date", "Weekly": COL["week"], "Monthly": COL["periode"]}[gran]
    f = d[d[COL["transtype"]] == "F"]

    if metric.startswith("Omzet"):
        s = d.groupby(key)[COL["bruto"]].sum()          # F + R (R sudah negatif) = neto
    elif metric.startswith("OA"):
        s = f.groupby(key)[COL["outlet"]].nunique()
    else:  # EC: outlet unik per hari per salesman, dijumlahkan per bucket
        daily = f.groupby([COL["kode_sales"], "_date"])[COL["outlet"]].nunique().reset_index(name="v")
        if key == "_date":
            daily["_k"] = daily["_date"]
        else:
            kmap = d.drop_duplicates("_date").set_index("_date")[key]
            daily["_k"] = daily["_date"].map(kmap)
        s = daily.groupby("_k")["v"].sum()

    out = s.reset_index()
    out.columns = ["x", "y"]
    out = out.dropna(subset=["x"]).sort_values("x").reset_index(drop=True)
    if gran == "Daily":
        if shift_year:  # geser +1 tahun supaya menimpa tahun berjalan
            out["x"] = out["x"] + pd.DateOffset(years=1)
        out["label"] = out["x"].dt.strftime("%d %b")
    elif gran == "Weekly":
        out["x"] = out["x"].astype(int)
        out["label"] = out["x"].apply(lambda w: f"W{w}")
    else:
        out["x"] = out["x"].astype(int)
        out["label"] = out["x"].apply(lambda p: MONTH_ABBR[p - 1] if 1 <= p <= 12 else f"P{p}")
    return out


def trend_figure(cur: pd.DataFrame, prev: pd.DataFrame | None, gran: str, metric: str,
                 year_cur: int, year_prev: int | None) -> go.Figure:
    is_rp = metric.startswith("Omzet")
    val_fmt = "Rp %{y:,.0f}" if is_rp else "%{y:,.0f}"
    fig = go.Figure()

    def add(df_, name, color, dash, fill):
        if df_ is None or df_.empty:
            return
        x = df_["x"] if gran == "Daily" else df_["label"]
        hover_x = "%{x|%d %b %Y}" if gran == "Daily" else "%{x}"
        fig.add_trace(go.Scatter(
            x=x, y=df_["y"], name=name, mode="lines+markers",
            line=dict(color=color, width=3, shape="spline", smoothing=1.1, dash=dash),
            marker=dict(size=8 if not dash else 6, color=color, line=dict(color="#0B0B0F", width=2)),
            fill="tozeroy" if fill else None,
            fillcolor="rgba(243,166,233,0.12)" if fill else None,
            hovertemplate=f"{hover_x}<br>{val_fmt}<extra>{name}</extra>",
        ))

    add(cur, str(year_cur), ACCENT, None, True)
    if prev is not None and not prev.empty:
        add(prev, str(year_prev), ACCENT2, "dot", False)

    if gran != "Daily":  # urutan kategori sesuai waktu (gabungan tahun berjalan & pembanding)
        both = pd.concat([cur, prev if prev is not None else cur.iloc[0:0]]).drop_duplicates("label").sort_values("x")
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=both["label"].tolist())
    else:
        fig.update_xaxes(tickformat="%d %b")

    fig.update_layout(
        height=400, margin=dict(t=20, b=10, l=10, r=10), hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CHART_FONT, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)", zeroline=False, tickformat=",.0f" if not is_rp else ".2s"),
    )
    return fig


def hitung_divisi_long(df_scope: pd.DataFrame) -> pd.DataFrame:
    """Capaian per Salesman x Divisi (5/6/8/16): Target (sheet Target Divisi), Net Sales, % Capaian, Gap Harian.
    Setiap salesman SELALU punya 4 baris divisi — divisi tanpa penjualan tetap tampil (Net Sales 0)
    supaya target yang belum tersentuh tidak hilang dari perhitungan."""
    cols = ["Salesman", "Divisi", "Target", "Net Sales", "% Capaian", "Gap Harian"]
    if df_scope.empty:
        return pd.DataFrame(columns=cols)
    sm = df_scope[[COL["kode_sales"], COL["salesman"]]].drop_duplicates()
    grid = sm.merge(pd.DataFrame({"_divisi_norm": list(DIVISI_LABEL.keys())}), how="cross")
    net = net_by_group(df_scope, [COL["kode_sales"], COL["salesman"], "_divisi_norm"], "Net Sales")
    net = net[[COL["kode_sales"], COL["salesman"], "_divisi_norm", "Net Sales"]]
    d = grid.merge(net, on=[COL["kode_sales"], COL["salesman"], "_divisi_norm"], how="left")
    d["Net Sales"] = d["Net Sales"].fillna(0)
    d["Divisi"] = d["_divisi_norm"].map(DIVISI_LABEL)
    if not target_divisi.empty:
        t = target_divisi.copy()
        if periode_sel:
            t = t[t[TARGET_DIVISI_COL["periode"]].isna() | t[TARGET_DIVISI_COL["periode"]].isin(periode_sel)]
        t = t.groupby([TARGET_DIVISI_COL["kode_sales"], "_divisi_norm"])[TARGET_DIVISI_COL["target"]].sum().reset_index()
        d = d.merge(t, left_on=[COL["kode_sales"], "_divisi_norm"],
                    right_on=[TARGET_DIVISI_COL["kode_sales"], "_divisi_norm"], how="left")
        d = d.rename(columns={TARGET_DIVISI_COL["target"]: "Target"})
    else:
        d["Target"] = np.nan
    d["% Capaian"] = (d["Net Sales"] / d["Target"] * 100).round(1)
    d["Gap Harian"] = ((d["Target"] - d["Net Sales"]) / hke).round(0) if hke else np.nan
    return d.rename(columns={COL["salesman"]: "Salesman"})[cols]


def gap_state(tgt, cap):
    """(kelas css kotak, teks utama, teks kecil) untuk kotak Gap Harian: merah kalau belum, hijau kalau tercapai."""
    if pd.isna(tgt) or not tgt:
        return "", "-", "target belum ada"
    if cap >= tgt:
        return "dv-gap-ok", "✓ Tercapai", f"lebih {fmt_rp(cap - tgt)}"
    gap_h = (tgt - cap) / hke if hke else np.nan
    return "dv-gap-bad", ("-" if pd.isna(gap_h) else "-" + fmt_rp(gap_h)), f"kurang {fmt_rp(tgt - cap)}"


def box_html(label: str, value: str, sub: str = "", css: str = "") -> str:
    return (f'<div class="dv-box {css}"><div class="dv-label">{label}</div>'
            f'<div class="dv-value">{nice(value)}</div>' + (f'<div class="dv-sub">{sub}</div>' if sub else "") + "</div>")


def bar_html(pct) -> str:
    w = 0 if pd.isna(pct) else int(max(0, min(100, round(pct))))
    ok = " ok" if (pd.notna(pct) and pct >= 100) else ""
    return f'<div class="dv-bar{ok}"><span class="pw-{w}"></span></div>'


def divisi_panel_html(icon: str, label: str, tgt, cap) -> str:
    pct = (cap / tgt * 100) if pd.notna(tgt) and tgt else np.nan
    css, gtxt, gsub = gap_state(tgt, cap)
    return ('<div class="dv-panel">'
            f'<div class="dv-title">{icon} {label}</div><div class="dv-grid">'
            + box_html("Target", fmt_rp(tgt)) + box_html("Capaian", fmt_rp(cap))
            + box_html("%", fmt_pct(pct)) + box_html("Gap Harian", gtxt, "", css)
            + "</div>" + bar_html(pct) + "</div>")


DIV_ICON = {"Coffee": "☕", "Cereal": "🥣", "Instant Food": "🍜", "Homecare": "🧴"}


def _pil_font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf"] if bold
             else ["DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)   # Pillow >= 10.1 (font bawaan bisa diskalakan)
    except TypeError:
        return ImageFont.load_default()


def salesman_card_html(name: str, team: str, tgt, cap, div_rows: list | None = None) -> str:
    """Kartu ringkas satu salesman: baris TOTAL (kotak berlabel) + optional 4 baris divisi di bawahnya.
    div_rows: list of (icon, label, target, capaian)."""
    import html as _html
    pct = (cap / tgt * 100) if pd.notna(tgt) and tgt else np.nan
    css, gtxt, _ = gap_state(tgt, cap)
    tag = f'<span class="sc-tag">{_html.escape(team)}</span>' if team and team != "Lainnya" else ""
    out = ['<div class="sc-card">',
           f'<div class="sc-head"><span class="sc-name">{_html.escape(name)}</span>{tag}</div>',
           '<div class="sc-row sc-total"><div class="sc-lab">Σ TOTAL</div>',
           box_html("Target", fmt_rp(tgt)), box_html("Capaian", fmt_rp(cap)), box_html("%", fmt_pct(pct)),
           box_html("Gap Harian", gtxt, "", css), "</div>", bar_html(pct)]
    if div_rows:
        out.append('<div class="sc-sep"></div>')
        for icon, lbl, d_tgt, d_cap in div_rows:
            d_pct = (d_cap / d_tgt * 100) if pd.notna(d_tgt) and d_tgt else np.nan
            d_css, d_gtxt, _ = gap_state(d_tgt, d_cap)
            g_cls = {"dv-gap-ok": " gap-ok", "dv-gap-bad": " gap-bad"}.get(d_css, "")
            out.append(f'<div class="sc-row sc-divisi"><div class="sc-lab">{icon} {lbl}</div>'
                       f'<div class="sc-cell">{nice(fmt_rp(d_tgt))}</div><div class="sc-cell">{nice(fmt_rp(d_cap))}</div>'
                       f'<div class="sc-cell">{nice(fmt_pct(d_pct))}</div><div class="sc-cell{g_cls}">{nice(d_gtxt)}</div></div>')
    out.append("</div>")
    return "".join(out)


def render_capaian_png(rows: list, title: str, subtitle: str) -> bytes:
    """Gambar PNG semua kartu salesman untuk dibagikan (WhatsApp dsb).
    rows: dict(name, team, tgt, cap, divisi=[(label, tgt, cap), ...] atau None)."""
    from io import BytesIO
    from PIL import Image, ImageDraw
    W, PAD, GAP = 1120, 24, 12
    LAB_W, CG = 104, 6
    f_title, f_sub, f_name = _pil_font(30, True), _pil_font(15), _pil_font(19, True)
    f_lab, f_val, f_small = _pil_font(12), _pil_font(17, True), _pil_font(11)
    f_dlab, f_dval = _pil_font(12, True), _pil_font(13, True)
    weights = [1.4, 1.4, 0.75, 1.5]
    inner_x0, inner_w = PAD + 12, W - 2 * PAD - 24
    unit = (inner_w - LAB_W - 4 * CG) / sum(weights)

    def card_height(r):
        n_div = len(r["divisi"]) if r.get("divisi") else 0
        return 40 + 56 + 13 + (10 + n_div * 30 if n_div else 0) + 12

    H = PAD + 78 + sum(card_height(r) + GAP for r in rows) + 44
    img = Image.new("RGB", (W, max(H, 200)), "#0B0B0F")
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD), title, font=f_title, fill="#F3A6E9")
    d.text((PAD, PAD + 42), subtitle, font=f_sub, fill="#9A9AA8")
    y = PAD + 78

    def col_x(i):  # x awal & lebar kolom ke-i (0..3)
        x = inner_x0 + LAB_W + CG + sum(weights[:i]) * unit + i * CG
        return x, weights[i] * unit

    for r in rows:
        tgt, cap = r["tgt"], r["cap"]
        ch = card_height(r)
        pct = (cap / tgt * 100) if pd.notna(tgt) and tgt else np.nan
        css, gtxt, _ = gap_state(tgt, cap)
        gtxt = gtxt.replace("✓ ", "")
        d.rounded_rectangle([PAD, y, W - PAD, y + ch], radius=14, fill="#111116", outline="#23232b", width=1)
        d.text((inner_x0, y + 9), r["name"], font=f_name, fill="#F0F0F7")
        if r.get("team") and r["team"] != "Lainnya":
            tw = d.textlength(r["team"], font=f_small)
            d.rounded_rectangle([W - PAD - 12 - tw - 16, y + 10, W - PAD - 12, y + 30], radius=10, outline="#3a3a55", width=1)
            d.text((W - PAD - 12 - tw - 8, y + 14), r["team"], font=f_small, fill="#B9B6F5")
        by = y + 40
        d.text((inner_x0, by + 20), "TOTAL", font=f_dlab, fill="#B9B6F5")
        vals = [("TARGET", fmt_rp(tgt), "#F3F4F6", "#2a2a33", 1), ("CAPAIAN", fmt_rp(cap), "#F3F4F6", "#2a2a33", 1),
                ("%", fmt_pct(pct), "#F3F4F6", "#2a2a33", 1),
                ("GAP HARIAN", gtxt, "#86EFAC" if css == "dv-gap-ok" else ("#FCA5A5" if css == "dv-gap-bad" else "#F3F4F6"),
                 "#22c55e" if css == "dv-gap-ok" else ("#ef4444" if css == "dv-gap-bad" else "#2a2a33"), 2 if css else 1)]
        for i, (lab, val, vcol, ocol, ow) in enumerate(vals):
            x, w = col_x(i)
            d.rounded_rectangle([x, by, x + w, by + 56], radius=10, fill="#14141a", outline=ocol, width=ow)
            d.text((x + 9, by + 7), lab, font=f_lab, fill="#8b8b98")
            d.text((x + 9, by + 27), val, font=f_val, fill=vcol)
        bar_y = by + 56 + 9
        d.rounded_rectangle([inner_x0, bar_y, inner_x0 + inner_w, bar_y + 4], radius=2, fill="#23232b")
        if pd.notna(pct):
            fw = inner_w * max(0, min(100, pct)) / 100
            if fw > 2:
                d.rounded_rectangle([inner_x0, bar_y, inner_x0 + fw, bar_y + 4], radius=2,
                                    fill="#22c55e" if pct >= 100 else "#F3A6E9")
        if r.get("divisi"):
            ry = bar_y + 4 + 10
            for lbl, d_tgt, d_cap in r["divisi"]:
                d_pct = (d_cap / d_tgt * 100) if pd.notna(d_tgt) and d_tgt else np.nan
                d_css, d_gtxt, _ = gap_state(d_tgt, d_cap)
                d_gtxt = d_gtxt.replace("✓ ", "")
                d.text((inner_x0, ry + 6), lbl, font=f_dlab, fill="#B9B6F5")
                cells = [(fmt_rp(d_tgt), "#E6E6EE", "#23232b", 1), (fmt_rp(d_cap), "#E6E6EE", "#23232b", 1),
                         (fmt_pct(d_pct), "#E6E6EE", "#23232b", 1),
                         (d_gtxt, "#86EFAC" if d_css == "dv-gap-ok" else ("#FCA5A5" if d_css == "dv-gap-bad" else "#E6E6EE"),
                          "#22c55e" if d_css == "dv-gap-ok" else ("#ef4444" if d_css == "dv-gap-bad" else "#23232b"),
                          2 if d_css else 1)]
                for i, (txt, tcol, ocol, ow) in enumerate(cells):
                    x, w = col_x(i)
                    d.rounded_rectangle([x, ry, x + w, ry + 26], radius=7, fill="#14141a", outline=ocol, width=ow)
                    d.text((x + 8, ry + 6), txt, font=f_dval, fill=tcol)
                ry += 30
        y += ch + GAP
    foot = "© Created by Adelard"
    d.text(((W - d.textlength(foot, font=f_sub)) / 2, y + 6), foot, font=f_sub, fill="#8b8b98")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


ringkasan_sales = ringkasan_by_salesman(df_filtered, target_all, periode_sel, hke)
mhs_resume_all = hitung_mhs_resume(df_filtered)
mhs_by_sales_all = hitung_mhs_by_salesman(mhs_resume_all, df_filtered, outlet_count_dmp)

# =====================================================================
# MENU NAVIGASI — dua baris pill (tidak pernah perlu digeser ke samping).
# Hanya halaman yang dipilih yang dihitung/ditampilkan, jadi dashboard juga lebih ringan.
# =====================================================================
NAV_ROW1 = ["📊 Overview", "🧑‍💼 By Salesman", "📇 Capaian Salesman", "🗺️ By Wilayah",
            "🏷️ By Subbrand & Divisi", "📦 MHS", "🎯 Insentif"]
NAV_ROW2 = ["📋 LATO", "🆕 LTD NPL", "📐 Paretto", "🗃️ Stock", "📈 Performance SS", "📖 Read Me"]

if st.session_state.get("page") not in NAV_ROW1 + NAV_ROW2:
    st.session_state["page"] = NAV_ROW1[0]


def _nav_pick(row_key: str):
    v = st.session_state.get(row_key)
    if v:                                   # klik pada pill yang sedang aktif = None -> abaikan
        st.session_state["page"] = v


# sinkronkan tampilan kedua baris dengan halaman aktif (sebelum widget dibuat)
st.session_state["nav_r1"] = st.session_state["page"] if st.session_state["page"] in NAV_ROW1 else None
st.session_state["nav_r2"] = st.session_state["page"] if st.session_state["page"] in NAV_ROW2 else None
st.pills("Menu baris 1", NAV_ROW1, selection_mode="single", key="nav_r1", label_visibility="collapsed",
         on_change=_nav_pick, args=("nav_r1",))
st.pills("Menu baris 2", NAV_ROW2, selection_mode="single", key="nav_r2", label_visibility="collapsed",
         on_change=_nav_pick, args=("nav_r2",))
page = st.session_state["page"]

# ---------------------------------------------------------------- Overview
if page == "📊 Overview":
    with st.container(border=True):
        h1, h2, h3 = st.columns([1.5, 1.2, 1.5])
        with h1:
            st.markdown("#### 📈 Tren Penjualan")
        with h2:
            trend_metric = st.selectbox("Metrik grafik", TREND_METRICS, key="trend_metric", label_visibility="collapsed")
        with h3:
            if hasattr(st, "segmented_control"):
                trend_gran = st.segmented_control("Periode grafik", ["Daily", "Weekly", "Monthly"], default="Daily",
                                                   key="trend_gran", label_visibility="collapsed")
            else:
                trend_gran = st.radio("Periode grafik", ["Daily", "Weekly", "Monthly"], horizontal=True,
                                       key="trend_gran", label_visibility="collapsed")
        trend_gran = trend_gran or "Daily"

        trend_cur = build_trend(df_filtered, trend_gran, trend_metric)
        trend_prev = None
        if bandingkan and df_filtered_prev is not None:
            trend_prev = build_trend(df_filtered_prev, trend_gran, trend_metric, shift_year=True)
        if trend_cur.empty:
            st.info("Belum ada data untuk ditampilkan pada filter saat ini.")
        else:
            show_chart(trend_figure(trend_cur, trend_prev, trend_gran, trend_metric,
                                     tahun_aktif, tahun_aktif - 1))
            st.caption("Arahkan kursor ke titik grafik untuk melihat angkanya. Garis putus-putus = tahun lalu "
                       "(aktif kalau 'Bandingkan dengan tahun lalu' dicentang di sidebar).")

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🏪 Klasifikasi Outlet & Omzet per Tipe Outlet")
        f_only = df_filtered[df_filtered[COL["transtype"]] == "F"]
        jumlah_outlet = f_only.drop_duplicates(subset=[COL["outlet"]]).groupby(COL["tipe_outlet"])[COL["outlet"]] \
            .nunique().reset_index(name="Jumlah Outlet")
        net_tipe = net_by_group(df_filtered, [COL["tipe_outlet"]], "Omzet")
        tbl_tipe = jumlah_outlet.merge(net_tipe, on=COL["tipe_outlet"], how="outer").fillna(0)
        tbl_tipe["Tipe Outlet"] = tbl_tipe[COL["tipe_outlet"]].map(TIPE_OUTLET_LABEL).fillna(tbl_tipe[COL["tipe_outlet"]])
        tbl_tipe = tbl_tipe.sort_values("Omzet", ascending=False)

        colA, colB = st.columns([1.1, 1])
        with colA:
            show_df(format_cols(tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]],
                             "Download Excel (Klasifikasi Outlet)", "overview_klasifikasi_outlet.xlsx", "dl_ov1")
        with colB:
            pie_tipe = top_categories_for_pie(tbl_tipe[["Tipe Outlet", "Omzet"]], "Tipe Outlet", "Omzet", 6, False)
            show_chart(pie_chart(pie_tipe, "Tipe Outlet", "Omzet", "Omzet per Tipe Outlet"))

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🏆 Top Contributor (6 Terbesar)")
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            st.markdown("**👤 Salesman**")
            show_df(format_cols(ringkasan_sales[["Salesman", "Net Sales"]], rp_cols=["Net Sales"]),
                         hide_index=True, use_container_width=True, height=240)
            pie_sales = top_categories_for_pie(ringkasan_sales[["Salesman", "Net Sales"]], "Salesman", "Net Sales", 6, False)
            show_chart(pie_chart(pie_sales, "Salesman", "Net Sales"))
        with oc2:
            st.markdown("**📍 Wilayah (Kabupaten)**")
            net_wil = net_by_group(df_filtered, [COL["kabupaten"]], "Omzet").sort_values("Omzet", ascending=False)
            show_df(format_cols(net_wil[[COL["kabupaten"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=240)
            pie_wil = top_categories_for_pie(net_wil[[COL["kabupaten"], "Omzet"]], COL["kabupaten"], "Omzet", 6, False)
            show_chart(pie_chart(pie_wil, COL["kabupaten"], "Omzet"))
        with oc3:
            st.markdown("**🏷️ Subbrand**")
            net_sb = net_by_group(df_filtered, [COL["subbrand_name"]], "Omzet").sort_values("Omzet", ascending=False)
            show_df(format_cols(net_sb[[COL["subbrand_name"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=240)
            pie_sb = top_categories_for_pie(net_sb[[COL["subbrand_name"], "Omzet"]], COL["subbrand_name"], "Omzet", 6, False)
            show_chart(pie_chart(pie_sb, COL["subbrand_name"], "Omzet"))

# ---------------------------------------------------------------- By Salesman
if page == "🧑‍💼 By Salesman":
    with st.container(border=True):
        st.markdown("#### 🧑‍💼 Kinerja per Salesman")
        st.caption("% OA dihitung dari standar CB per Team (Read Me). EC = akumulasi jumlah outlet unik "
                   "bertransaksi (F saja) per hari, dijumlahkan sepanjang periode. Target/Gap kosong "
                   "ditampilkan '-' kalau file Target belum diupload.")
        salesman_filter_sales = st.multiselect("Filter salesman khusus menu ini", salesman_terpilih,
                                                default=salesman_terpilih, key=fkey("sales_salesman_filter"))
        ringkasan_view = ringkasan_sales[ringkasan_sales["Salesman"].isin(salesman_filter_sales)] if salesman_filter_sales else ringkasan_sales.iloc[0:0]
        show = format_cols(ringkasan_view, rp_cols=["Net Sales", "Bruto F", "Bruto R", "Target", "Gap Harian"],
                            pct_cols=["% Capaian", "% OA"])
        kolom_tampil = ["Kode Sales", "Salesman", "Team", "Target", "Net Sales", "% Capaian",
                        "OA", "% OA", "EC", "Gap Harian", "Avg SKU"]
        show_df(show[kolom_tampil], hide_index=True, use_container_width=True, height=380)
        download_button(ringkasan_view, "Download Excel (By Salesman)", "by_salesman.xlsx", "dl_sales")

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🗂️ Capaian by Divisi")
        st.caption("Divisi 5-Coffee, 6-Cereal, 8-Instant Food, 16-Homecare. Target diambil dari sheet "
                   "'Target Divisi' pada file Target.")
        df_div_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_filter_sales)] if salesman_filter_sales else df_filtered.iloc[0:0]
        tbl_div_long = hitung_divisi_long(df_div_scope)

        # Kotak ringkasan per Divisi (gabungan salesman yang difilter): 2 di atas, 2 di bawah.
        # Capaian hanya dari salesman yang PUNYA target di divisi tsb, supaya % tidak menyesatkan.
        def _agg_divisi(lbl: str):
            sub_t = tbl_div_long[(tbl_div_long["Divisi"] == lbl) & tbl_div_long["Target"].notna()]
            if sub_t.empty:
                return np.nan, 0
            return sub_t["Target"].sum(), sub_t["Net Sales"].sum()

        for pair in (("Coffee", "Cereal"), ("Instant Food", "Homecare")):
            cols_pair = st.columns(2)
            for col_, lbl in zip(cols_pair, pair):
                with col_:
                    tgt_, cap_ = _agg_divisi(lbl)
                    st.markdown(divisi_panel_html(DIV_ICON[lbl], lbl, tgt_, cap_), unsafe_allow_html=True)

        st.markdown("**Rincian per salesman**")

        # Pivot memanjang ke kanan: tiap Divisi jadi 4 kolom (Target/Net Sales/% Capaian/Gap Harian)
        # bersebelahan, satu baris per Salesman — bukan satu baris per Salesman x Divisi.
        wide_parts = []
        rp_cols_wide, pct_cols_wide = [], []
        for lbl in DIVISI_LABEL.values():
            sub = tbl_div_long[tbl_div_long["Divisi"] == lbl].set_index("Salesman")[
                ["Target", "Net Sales", "% Capaian", "Gap Harian"]
            ].copy()
            sub.columns = [f"{lbl} — {c}" for c in sub.columns]
            rp_cols_wide += [f"{lbl} — Target", f"{lbl} — Net Sales", f"{lbl} — Gap Harian"]
            pct_cols_wide.append(f"{lbl} — % Capaian")
            wide_parts.append(sub)
        tbl_div_wide = pd.concat(wide_parts, axis=1).reset_index() if wide_parts else pd.DataFrame(columns=["Salesman"])

        show_df(format_cols(tbl_div_wide, rp_cols=rp_cols_wide, pct_cols=pct_cols_wide),
                     hide_index=True, use_container_width=True, height=280)
        download_button(tbl_div_long, "Download Excel (Capaian by Divisi)", "by_salesman_divisi.xlsx", "dl_sales_div")

# ---------------------------------------------------------------- Capaian Salesman (kartu ringkas)
if page == "📇 Capaian Salesman":
    with st.container(border=True):
        st.markdown("#### 📇 Capaian Salesman — kartu ringkas untuk dibagikan")
        st.caption("Satu kartu per salesman: baris TOTAL (Target, Capaian, %, Gap Harian) lalu rincian tiap divisi "
                   "di bawahnya. Gap Harian merah = belum tercapai, hijau = tercapai. Ikut filter Periode/Week "
                   "di sidebar. Tombol PNG di bawah membuat gambar siap kirim.")
        fc1, fc2, fc3 = st.columns([3, 1.6, 1.4])
        with fc1:
            sel_card = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih,
                                       key=fkey("salcard_filter"))
        with fc2:
            sort_card = st.selectbox("Urutkan", ["Nama A–Z", "% Capaian tertinggi", "% Capaian terendah", "Net Sales tertinggi"],
                                      key="salcard_sort")
        with fc3:
            show_div_card = st.checkbox("Rincian per divisi", value=True, key="salcard_div")

    data_card = ringkasan_sales[ringkasan_sales["Salesman"].isin(sel_card)].copy()
    if sort_card == "Nama A–Z":
        data_card = data_card.sort_values("Salesman")
    elif sort_card == "% Capaian tertinggi":
        data_card = data_card.sort_values("% Capaian", ascending=False, na_position="last")
    elif sort_card == "% Capaian terendah":
        data_card = data_card.sort_values("% Capaian", ascending=True, na_position="last")
    else:
        data_card = data_card.sort_values("Net Sales", ascending=False)

    div_by_sales = {}
    if show_div_card and not data_card.empty:
        dl = hitung_divisi_long(df_filtered[df_filtered[COL["salesman"]].isin(sel_card)])
        for _, x_ in dl.iterrows():
            div_by_sales.setdefault(x_["Salesman"], {})[x_["Divisi"]] = (x_["Target"], x_["Net Sales"])

    rows_png, cards_html = [], []
    for _, r in data_card.iterrows():
        tgt_c = r["Target"] if pd.notna(r["Target"]) else np.nan
        div_rows = None
        if show_div_card:
            got = div_by_sales.get(r["Salesman"], {})
            div_rows = [(DIV_ICON[lbl], lbl, *got.get(lbl, (np.nan, 0))) for lbl in DIVISI_LABEL.values()]
        cards_html.append(salesman_card_html(r["Salesman"], r["Team"], tgt_c, r["Net Sales"], div_rows))
        rows_png.append({"name": r["Salesman"], "team": r["Team"], "tgt": tgt_c, "cap": r["Net Sales"],
                         "divisi": [(lbl, t_, c_) for _ic, lbl, t_, c_ in div_rows] if div_rows else None})

    if not cards_html:
        st.info("Pilih minimal 1 salesman.")
    else:
        st.markdown('<div class="sc-wrap"><div class="sc-grid">' + "".join(cards_html) + "</div></div>",
                    unsafe_allow_html=True)
        png_rows = rows_png[:60]
        png_bytes = render_capaian_png(png_rows, "Capaian Salesman",
                                       f"Periode {', '.join(map(str, periode_sel)) or '-'}  |  HKE {hke}"
                                       + (f"  |  ditampilkan {len(png_rows)} dari {len(rows_png)} salesman" if len(rows_png) > 60 else ""))
        st.download_button("⬇️ Download gambar (PNG) untuk dibagikan", data=png_bytes,
                           file_name="capaian_salesman.png", mime="image/png", key="dl_salcard_png")

# ---------------------------------------------------------------- By Wilayah
if page == "🗺️ By Wilayah":
    icon_level = {"Kabupaten": "🏙️", "Kecamatan": "🏘️", "Kelurahan": "🏠"}
    # Kelurahan cenderung py banyak kategori kecil sehingga irisan "Lainnya" bisa
    # mendominasi pie chart dan tidak informatif -> untuk level ini pie TIDAK
    # pakai bucket "Lainnya", cukup tampilkan top 15 kontributor asli.
    pie_config = {"Kabupaten": (10, True), "Kecamatan": (10, True), "Kelurahan": (15, False)}
    for label, col in [("Kabupaten", COL["kabupaten"]), ("Kecamatan", COL["kecamatan"]),
                        ("Kelurahan", COL["kelurahan"])]:
        with st.container(border=True):
            st.markdown(f"#### {icon_level[label]} Penjualan by {label}")
            agg = net_by_group(df_filtered, [col], "Omzet").sort_values("Omzet", ascending=False)
            colL, colR = st.columns([1.1, 1])
            with colL:
                show_df(format_cols(agg[[col, "Omzet"]], rp_cols=["Omzet"]),
                             hide_index=True, use_container_width=True, height=380)
                download_button(agg, f"Download Excel ({label})", f"wilayah_{label.lower()}.xlsx", f"dl_wil_{label}")
            with colR:
                n_pie, other_pie = pie_config[label]
                pie_data = top_categories_for_pie(agg[[col, "Omzet"]], col, "Omzet", n_pie, other_pie)
                show_chart(pie_chart(pie_data, col, "Omzet", f"Kontribusi Omzet by {label}"))
        st.write("")

    with st.container(border=True):
        st.markdown("#### 🏬 Penjualan by Pasar")
        st.caption("Kode Pasar dengan keterangan 'N/A' (belum ada nama pasar resmi) dikecualikan. Pie tidak "
                   "pakai bucket 'Lainnya' supaya tidak didominasi satu irisan — tampil top 15 pasar asli.")
        dfp = df_filtered.copy()
        dfp["_pasar_desc"] = dfp[COL["kode_pasar"]].astype(str).str.split("-", n=1).str[-1].str.strip().str.upper()
        dfp = dfp[dfp["_pasar_desc"] != "N/A"]
        agg_pasar = net_by_group(dfp, [COL["kode_pasar"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.1, 1])
        with colL:
            show_df(format_cols(agg_pasar[[COL["kode_pasar"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(agg_pasar, "Download Excel (Pasar)", "wilayah_pasar.xlsx", "dl_pasar")
        with colR:
            if agg_pasar.empty:
                st.info("Tidak ada data pasar dengan nama resmi (selain N/A) pada filter saat ini.")
            else:
                pie_pasar = top_categories_for_pie(agg_pasar[[COL["kode_pasar"], "Omzet"]], COL["kode_pasar"], "Omzet", 15, False)
                show_chart(pie_chart(pie_pasar, COL["kode_pasar"], "Omzet", "Kontribusi Omzet by Pasar"))

# ---------------------------------------------------------------- By Subbrand & Divisi
if page == "🏷️ By Subbrand & Divisi":
    with st.container(border=True):
        st.markdown("#### 🏷️ Kontribusi per Subbrand")
        agg_sb = net_by_group(df_filtered, [COL["subbrand_name"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.1, 1])
        with colL:
            show_df(format_cols(agg_sb[[COL["subbrand_name"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(agg_sb, "Download Excel (Subbrand)", "subbrand.xlsx", "dl_sb")
        with colR:
            pie_sb2 = top_categories_for_pie(agg_sb[[COL["subbrand_name"], "Omzet"]], COL["subbrand_name"], "Omzet", 10, True)
            show_chart(pie_chart(pie_sb2, COL["subbrand_name"], "Omzet", "Kontribusi per Subbrand"))

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🗂️ Kontribusi per Divisi")
        st.caption("Divisi ditampilkan sebagai kode mentah untuk kode selain 5/6/8/16 (belum ada tabel nama Divisi lengkap).")
        agg_dv = net_by_group(df_filtered, [COL["divisi"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.1, 1])
        with colL:
            show_df(format_cols(agg_dv[[COL["divisi"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(agg_dv, "Download Excel (Divisi)", "divisi.xlsx", "dl_dv")
        with colR:
            pie_dv = top_categories_for_pie(agg_dv[[COL["divisi"], "Omzet"]], COL["divisi"], "Omzet", 10, True)
            show_chart(pie_chart(pie_dv, COL["divisi"], "Omzet", "Kontribusi per Divisi"))

    st.write("")
    with st.container(border=True):
        st.markdown("#### 👤 Breakdown Subbrand per Salesman")
        st.caption("Pilih satu salesman untuk melihat kontribusi Omzet, EC, dan OA di setiap subbrand-nya.")
        salesman_for_breakdown = st.selectbox("Pilih salesman", salesman_terpilih, key=fkey("divisi_salesman_breakdown"))
        df_one_sales = df_filtered[df_filtered[COL["salesman"]] == salesman_for_breakdown]
        f_one_sales = df_one_sales[df_one_sales[COL["transtype"]] == "F"]

        net_sb_sales = net_by_group(df_one_sales, [COL["subbrand_name"]], "Omzet")
        ec_sb_sales = (
            f_one_sales.groupby([COL["subbrand_name"], f_one_sales[COL["tanggal"]].dt.date])[COL["outlet"]]
            .nunique().groupby(level=0).sum().reset_index(name="EC")
        )
        oa_sb_sales = f_one_sales.groupby(COL["subbrand_name"])[COL["outlet"]].nunique().reset_index(name="OA")

        tbl_breakdown = net_sb_sales.merge(ec_sb_sales, on=COL["subbrand_name"], how="left") \
            .merge(oa_sb_sales, on=COL["subbrand_name"], how="left").fillna(0)
        tbl_breakdown = tbl_breakdown[[COL["subbrand_name"], "Omzet", "EC", "OA"]].sort_values("Omzet", ascending=False)
        show_df(format_cols(tbl_breakdown, rp_cols=["Omzet"]), hide_index=True, use_container_width=True, height=340)
        download_button(tbl_breakdown, "Download Excel (Breakdown Subbrand per Salesman)",
                         f"breakdown_subbrand_{salesman_for_breakdown}.xlsx", "dl_breakdown_sb")

# ---------------------------------------------------------------- MHS
if page == "📦 MHS":
    with st.container(border=True):
        st.markdown("#### 📦 MHS — SKU Sold vs Target SKU")
        st.caption("SKU dihitung dari NAMA PRODUK yang sudah dinormalisasi (buang kata 'NEW', spasi, kapitalisasi; "
                   "khusus produk WOW, varian kemasan seperti GB vs 4+2/RCG juga digabung jadi 1 SKU). Target SKU "
                   "sekarang diambil dari klasifikasi channel di DMP (NAMACLASS), sesuai Memorandum 27 Agustus 2026 "
                   "— bukan lagi dari Tipe Outlet di LBP.")
        colf1, colf2 = st.columns(2)
        with colf1:
            salesman_mhs = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih, key=fkey("mhs_salesman_filter"))
        with colf2:
            rayon_opts = sorted(df_filtered["Rayon"].dropna().unique().tolist())
            rayon_mhs = st.multiselect("Filter Rayon", rayon_opts, default=rayon_opts, key=fkey("mhs_rayon_filter", salesman_mhs))

        df_mhs_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_mhs)] if salesman_mhs else df_filtered.iloc[0:0]
        if rayon_opts:
            df_mhs_scope = df_mhs_scope[df_mhs_scope["Rayon"].isin(rayon_mhs)] if rayon_mhs else df_mhs_scope.iloc[0:0]

        tampil = hitung_mhs_resume(df_mhs_scope)
        tampil_with_rayon = tampil

        colL, colR = st.columns([1.5, 1])
        with colL:
            kolom_mhs = ["No Outlet", "Nama Outlet", "Salesman", "Rayon", "Kategori Channel", "Channel",
                         "Target SKU", "SKU Terjual", "Kekurangan SKU"]
            kolom_mhs = [c for c in kolom_mhs if c in tampil_with_rayon.columns]
            show_df(tampil_with_rayon[kolom_mhs], hide_index=True, use_container_width=True, height=380)
            download_button(tampil_with_rayon, "Download Excel (MHS Resume)", "mhs_resume.xlsx", "dl_mhs")
        with colR:
            n_lolos = int(tampil["Lolos MHS"].sum()) if not tampil.empty else 0
            n_belum = int((~tampil["Lolos MHS"]).sum()) if not tampil.empty else 0
            pie_mhs = pd.DataFrame({"Status": ["✅ Lolos MHS", "⚠️ Belum Lolos"], "Jumlah": [n_lolos, n_belum]})
            show_chart(pie_chart(pie_mhs, "Status", "Jumlah", "Status Kelolosan MHS"))

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📈 % MHS Keseluruhan (vs Jumlah Outlet DMP)")
        mhs_by_sales = hitung_mhs_by_salesman(tampil, df_mhs_scope, outlet_count_dmp)
        total_lolos = mhs_by_sales["Outlet Lolos MHS"].sum() if not mhs_by_sales.empty else 0
        total_cb = mhs_by_sales["Jumlah Outlet (DMP)"].dropna().sum() if not mhs_by_sales.empty else 0
        pct_mhs_overall = (total_lolos / total_cb * 100) if total_cb else 0
        colg, colt = st.columns([1, 1.4])
        with colg:
            show_chart(gauge_chart(pct_mhs_overall, "% MHS Keseluruhan"))
        with colt:
            show_df(format_cols(mhs_by_sales, pct_cols=["% MHS"]), hide_index=True,
                         use_container_width=True, height=320)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🔍 Detail SKU per Outlet")
        if tampil.empty:
            st.info("Tidak ada outlet pada filter saat ini.")
        else:
            outlet_pilihan = st.selectbox("Pilih outlet", tampil["No Outlet"] + " - " + tampil["Nama Outlet"])
            no_outlet_sel = outlet_pilihan.split(" - ")[0]
            f_only_mhs = df_mhs_scope[df_mhs_scope[COL["transtype"]] == "F"]
            kategori_sel = f_only_mhs.loc[f_only_mhs[COL["outlet"]] == no_outlet_sel, "Kategori Channel"].iloc[0]
            universe = universe_sku_per_kategori(f_only_mhs)
            semua_sku_tipe = universe.get(kategori_sel, pd.DataFrame(columns=[COL["pcode"], COL["nama_produk"], "_produk_norm"]))
            sku_outlet = f_only_mhs.loc[f_only_mhs[COL["outlet"]] == no_outlet_sel].drop_duplicates(subset=["_produk_norm"])[
                [COL["pcode"], COL["nama_produk"], COL["qty"], COL["bruto"]]]

            cL, cR = st.columns(2)
            with cL:
                st.markdown("**✅ SKU sudah masuk**")
                show_df(sku_outlet, hide_index=True, use_container_width=True, height=300)
            with cR:
                st.markdown(f"**⚠️ SKU belum masuk** (vs SKU lain yang laku di kategori '{kategori_sel}')")
                sudah_norm = f_only_mhs.loc[f_only_mhs[COL["outlet"]] == no_outlet_sel, "_produk_norm"]
                belum_masuk = semua_sku_tipe[~semua_sku_tipe["_produk_norm"].isin(sudah_norm)][[COL["pcode"], COL["nama_produk"]]]
                show_df(belum_masuk, hide_index=True, use_container_width=True, height=300)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📋 Summary per Outlet (untuk dicek / dibagikan ke Salesman)")
        st.caption("List toko sesuai filter Salesman & Rayon di atas, dengan status SKU masuk/belum — format "
                   "ringkas supaya gampang dicek atau di-share langsung ke salesman yang bersangkutan.")
        summary_outlet = tampil_with_rayon.copy()
        summary_outlet["Status"] = np.where(summary_outlet["Kekurangan SKU"] <= 0, "✅ Lengkap", "⚠️ Kurang")
        kolom_summary = ["No Outlet", "Nama Outlet", "Salesman", "Rayon", "Target SKU", "SKU Terjual",
                          "Kekurangan SKU", "Status"]
        kolom_summary = [c for c in kolom_summary if c in summary_outlet.columns]
        summary_outlet = summary_outlet[kolom_summary].sort_values(["Salesman", "Kekurangan SKU"], ascending=[True, False])
        show_df(summary_outlet, hide_index=True, use_container_width=True, height=380)
        download_button(summary_outlet, "Download Excel (Summary per Outlet — siap dibagikan)",
                         "mhs_summary_per_outlet.xlsx", "dl_mhs_summary")

# ---------------------------------------------------------------- Insentif
if page == "🎯 Insentif":
    with st.container(border=True):
        st.markdown("#### 🎯 Insentif — Skema TO Retail, TO Grosir & KLK M245 (Agustus-September 2026)")
        st.caption("Bagian Reward & Punishment (Tagihan, Visit in Radius) TIDAK dihitung sesuai instruksi. "
                   "Salesman di luar team ini (SE, TO All, TO ST, KVS ST, Motoris, dst) belum punya skema, "
                   "jadi tidak muncul di sini.")
        salesman_insentif_opts = ringkasan_sales.loc[ringkasan_sales["Team"].isin(list(INSENTIF_TIERS.keys())), "Salesman"].tolist()
        salesman_insentif_opts = [s for s in salesman_insentif_opts if s in salesman_terpilih]
        salesman_pilih_insentif = st.multiselect("Filter salesman", salesman_insentif_opts,
                                                  default=salesman_insentif_opts, key=fkey("insentif_salesman_filter"))

        rows = []
        for _, r in ringkasan_sales[ringkasan_sales["Salesman"].isin(salesman_pilih_insentif)].iterrows():
            team = r["Team"]
            if team not in INSENTIF_TIERS:
                continue
            tiers = INSENTIF_TIERS[team]
            kode_sales = r["Kode Sales"]

            pct_sales = r["% Capaian"]
            insentif_sales = tier_lookup(pct_sales, tiers["sales"])

            insentif_kategori = 0
            detail_kategori = []
            for kode_div, label_div in DIVISI_LABEL.items():
                net_div_row = net_by_group(
                    df_filtered[(df_filtered[COL["kode_sales"]] == kode_sales) & (df_filtered["_divisi_norm"] == kode_div)],
                    [], "Omzet"
                )
                net_val = net_div_row["Omzet"].sum() if not net_div_row.empty else 0
                tgt_val = 0
                if not target_divisi.empty:
                    t = target_divisi[(target_divisi[TARGET_DIVISI_COL["kode_sales"]] == kode_sales) &
                                       (target_divisi["_divisi_norm"] == kode_div)]
                    if periode_sel:
                        t = t[t[TARGET_DIVISI_COL["periode"]].isna() | t[TARGET_DIVISI_COL["periode"]].isin(periode_sel)]
                    tgt_val = t[TARGET_DIVISI_COL["target"]].sum()
                pct_cat = (net_val / tgt_val * 100) if tgt_val else np.nan
                nilai_cat = tier_lookup(pct_cat, tiers["category"])
                insentif_kategori += nilai_cat
                detail_kategori.append(f"{label_div}: {fmt_pct(pct_cat)} → {fmt_rp(nilai_cat)}")

            pct_mhs_row = mhs_by_sales_all.loc[mhs_by_sales_all["Salesman"] == r["Salesman"], "% MHS"]
            pct_mhs_val = pct_mhs_row.iloc[0] if not pct_mhs_row.empty else np.nan
            insentif_mhs = tier_lookup(pct_mhs_val, tiers["mhs"])

            pct_oa_val = r["% OA"]
            insentif_oa = tier_lookup(pct_oa_val, tiers["oa"])

            total_insentif = insentif_sales + insentif_kategori + insentif_mhs + insentif_oa
            rows.append({
                "Kode Sales": kode_sales, "Salesman": r["Salesman"], "Team": team,
                "% Capaian Sales": pct_sales, "Insentif Sales": insentif_sales,
                "Insentif Kategori (4 Divisi)": insentif_kategori, "Detail Kategori": " | ".join(detail_kategori),
                "% MHS": pct_mhs_val, "Insentif MHS": insentif_mhs,
                "% OA": pct_oa_val, "Insentif OA": insentif_oa,
                "Total Insentif": total_insentif,
            })

        tbl_insentif = pd.DataFrame(rows)

    st.write("")
    if tbl_insentif.empty:
        st.info("Belum ada salesman TO Retail/TO Grosir/KLK yang cocok dengan filter saat ini.")
    else:
        with st.container(border=True):
            st.markdown("#### 💵 Total Insentif")
            if len(tbl_insentif) == 1:
                st.markdown(f'<div class="big-nominal">{fmt_rp(tbl_insentif["Total Insentif"].iloc[0])}</div>',
                            unsafe_allow_html=True)
                st.caption(f"Salesman: {tbl_insentif['Salesman'].iloc[0]} ({tbl_insentif['Team'].iloc[0]})")
            else:
                st.markdown(f'<div class="big-nominal">{fmt_rp(tbl_insentif["Total Insentif"].sum())}</div>',
                            unsafe_allow_html=True)
                st.caption(f"Total gabungan {len(tbl_insentif)} salesman terpilih")

        st.write("")
        with st.container(border=True):
            st.markdown("#### 📋 Summary Ketentuan yang Sudah Masuk")
            show_ins = format_cols(tbl_insentif, rp_cols=["Insentif Sales", "Insentif Kategori (4 Divisi)",
                                                            "Insentif MHS", "Insentif OA", "Total Insentif"],
                                    pct_cols=["% Capaian Sales", "% MHS", "% OA"])
            show_df(show_ins[["Kode Sales", "Salesman", "Team", "% Capaian Sales", "Insentif Sales",
                                    "Insentif Kategori (4 Divisi)", "% MHS", "Insentif MHS", "% OA", "Insentif OA",
                                    "Total Insentif"]], hide_index=True, use_container_width=True, height=340)
            with st.expander("Lihat rincian per Divisi (Coffee/Cereal/Instant Food/Homecare)"):
                show_df(tbl_insentif[["Salesman", "Detail Kategori"]], hide_index=True, use_container_width=True)
            download_button(tbl_insentif.drop(columns=["Detail Kategori"]), "Download Excel (Insentif)",
                             "insentif.xlsx", "dl_insentif")

# ---------------------------------------------------------------- LATO
if page == "📋 LATO":
    with st.container(border=True):
        st.markdown("#### 📋 LATO — List Outlet & Transaksi")
        st.caption("Semua outlet yang terdaftar di DMP untuk salesman/rayon yang difilter — BUKAN cuma outlet "
                   "yang sudah transaksi. Outlet yang belum ada transaksi (sesuai filter Periode/Week yang aktif "
                   "di sidebar) ditandai baris merah, supaya gampang dicek atau dibagikan ke salesman.")

        if dmp_master.empty:
            st.warning("Upload file DMP di sidebar (⚙️ Option) dulu untuk memakai menu ini — LATO butuh daftar "
                       "outlet lengkap dari DMP, bukan cuma yang sudah transaksi di LBP.")
        else:
            cf1, cf2 = st.columns(2)
            with cf1:
                salesman_lato = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih,
                                                key=fkey("lato_salesman_filter"))
            with cf2:
                rayon_lato_opts = sorted(dmp_master.loc[dmp_master["Salesman"].isin(salesman_lato), "Rayon"].dropna().unique().tolist())
                rayon_lato = st.multiselect("Filter Rayon", rayon_lato_opts, default=rayon_lato_opts, key=fkey("lato_rayon_filter", salesman_lato))

            master_lato = dmp_master[dmp_master["Salesman"].isin(salesman_lato)] if salesman_lato else dmp_master.iloc[0:0]
            if rayon_lato_opts:
                master_lato = master_lato[master_lato["Rayon"].isin(rayon_lato)] if rayon_lato else master_lato.iloc[0:0]

            net_outlet = net_by_group(df_filtered, [COL["outlet"]], "Omzet")
            tbl_lato = master_lato.merge(net_outlet[[COL["outlet"], "Omzet"]], on=COL["outlet"], how="left")
            tbl_lato["Omzet"] = tbl_lato["Omzet"].fillna(0)
            tbl_lato["Nominal Transaksi"] = tbl_lato["Omzet"].apply(lambda x: fmt_rp(x) if x > 0 else "BELUM ADA TRANSAKSI")
            tbl_lato = tbl_lato.rename(columns={"Nama Outlet (DMP)": "Nama Outlet"})
            tbl_lato = tbl_lato[["Salesman", "Rayon", COL["outlet"], "Nama Outlet", "Nominal Transaksi", "Omzet"]] \
                .sort_values(["Salesman", "Omzet"])

            n_belum = int((tbl_lato["Omzet"] <= 0).sum())
            st.caption(f"{len(tbl_lato)} outlet ditampilkan &middot; {n_belum} outlet BELUM ada transaksi "
                       f"(sesuai filter Periode/Week yang aktif).")

            is_belum = (tbl_lato["Omzet"] <= 0).reset_index(drop=True)
            display_cols = ["Salesman", "Rayon", COL["outlet"], "Nama Outlet", "Nominal Transaksi"]
            tbl_lato_display = tbl_lato[display_cols].reset_index(drop=True)
            show_df(tbl_lato_display, height=460, highlight_mask=is_belum)
            download_button(tbl_lato_display, "Download Excel (LATO)", "lato.xlsx", "dl_lato")

# ---------------------------------------------------------------- LTD NPL
if page == "🆕 LTD NPL":
    with st.container(border=True):
        st.markdown("#### 🆕 LTD NPL")
        st.info("Menu ini akan dikembangkan lebih lanjut setelah definisi rumus LTD NPL dikonfirmasi.")

# ---------------------------------------------------------------- Paretto
if page == "📐 Paretto":
    with st.container(border=True):
        st.markdown("#### 📐 Paretto — Ranking 40 Toko Omzet Tertinggi")
        st.caption("Omzet dihitung neto (Bruto F + Bruto R, sesuai filter Periode/Week yang aktif di sidebar).")
        cf1, cf2 = st.columns(2)
        with cf1:
            salesman_pareto = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih,
                                              key=fkey("pareto_salesman_filter"))
        with cf2:
            rayon_pareto_opts = sorted(df_filtered.loc[df_filtered[COL["salesman"]].isin(salesman_pareto), "Rayon"]
                                        .dropna().unique().tolist())
            rayon_pareto = st.multiselect("Filter Rayon", rayon_pareto_opts, default=rayon_pareto_opts,
                                           key=fkey("pareto_rayon_filter", salesman_pareto))

        df_pareto_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_pareto)] if salesman_pareto else df_filtered.iloc[0:0]
        if rayon_pareto_opts:
            df_pareto_scope = df_pareto_scope[df_pareto_scope["Rayon"].isin(rayon_pareto)] if rayon_pareto else df_pareto_scope.iloc[0:0]

        agg_pareto = net_by_group(df_pareto_scope, [COL["outlet"], COL["nama_outlet"], COL["salesman"], "Rayon"], "Omzet")
        agg_pareto = agg_pareto.sort_values("Omzet", ascending=False).head(40).reset_index(drop=True)
        agg_pareto.insert(0, "Rank", range(1, len(agg_pareto) + 1))
        agg_pareto = agg_pareto.rename(columns={COL["outlet"]: "No Outlet", COL["nama_outlet"]: "Nama Outlet",
                                                 COL["salesman"]: "Salesman"})

        show_df(format_cols(agg_pareto[["Rank", "No Outlet", "Nama Outlet", "Salesman", "Rayon", "Omzet"]],
                                 rp_cols=["Omzet"]), hide_index=True, use_container_width=True, height=460)
        fig_pareto = bar_chart(agg_pareto.head(20), "Nama Outlet", "Omzet", "Top 20 dari 40 Toko (visual)")
        show_chart(fig_pareto)
        download_button(agg_pareto[["Rank", "No Outlet", "Nama Outlet", "Salesman", "Rayon", "Omzet"]],
                         "Download Excel (Paretto)", "paretto.xlsx", "dl_pareto")

# ---------------------------------------------------------------- Stock
if page == "🗃️ Stock":
    with st.container(border=True):
        st.markdown("#### 🗃️ Stock — Stok Tidak Bergerak, Cepat Keluar & Klasifikasi Produk")
        st.markdown(
            "**Cara membaca** (upload minimal 2 file stok dengan tanggal berbeda):  \n"
            "🧊 **Tidak bergerak** — mis. *Torabika bubuk* tgl 25 = 10 ctn, tgl 26 = 10 ctn → stok sama, tidak ada yang keluar.  \n"
            "🚀 **Sangat cepat keluar** — mis. *Energen Vanilla* tgl 25 = 300, tgl 26 = 10 → 97% stok sudah keluar.  \n"
            "🏷️ Di bagian bawah, semua produk diklasifikasikan: Sangat Cepat, Cepat, Sedang, Lambat, Tidak Bergerak, dst.")
        cu1, cu2 = st.columns([4, 1])
        with cu1:
            stock_files = st.file_uploader("Upload file stok (.xlsx / .xls / .csv / .txt / .pdf)",
                                            type=["xlsx", "xls", "csv", "txt", "pdf"], accept_multiple_files=True,
                                            key="stock_uploader")
        with cu2:
            stock_unit = st.text_input("Satuan qty", value="ctn", key="stock_unit")
        st.caption("Upload hanya di menu ini. PDF: hanya PDF berbasis teks (hasil cetak/export sistem), bukan hasil scan. "
                   "Baris judul di atas tabel dan header yang berulang tiap halaman dibuang otomatis.")

        # File stok disimpan di sesi supaya tidak hilang saat pindah menu lalu kembali ke Stock.
        cache = st.session_state.setdefault("stock_cache", {})
        for f_ in stock_files:
            cache[f_.name] = f_.getvalue()
        if cache:
            cc1, cc2 = st.columns([5, 1])
            with cc1:
                st.caption("File stok yang dipakai: " + " · ".join(f"**{n_}**" for n_ in cache))
            with cc2:
                if st.button("🗑️ Hapus semua", key="stock_clear"):
                    st.session_state["stock_cache"] = {}
                    st.rerun()
    stock_items = list(st.session_state.get("stock_cache", {}).items())

    if len(stock_items) < 2:
        st.info("Upload minimal 2 file stok (tanggal berbeda) untuk mulai membandingkan.")
    else:
        raws = []
        for name_, bytes_ in stock_items:
            try:
                raws.append((name_, stock_read_raw(bytes_, name_)))
            except Exception as e:  # noqa: BLE001
                st.error(f"File '{name_}' gagal dibaca ({type(e).__name__}: {str(e)[:160]}).")

        if len(raws) < 2:
            st.warning("Kurang dari 2 file yang berhasil dibaca.")
        else:
            with st.expander("⚙️ Pengaturan lanjutan (biasanya tidak perlu diubah)"):
                sa1, sa2, sa3, sa4 = st.columns(4)
                with sa1:
                    hdr_manual = st.number_input("Baris header (-1 = otomatis)", min_value=-1, max_value=200, value=-1,
                                                  key="stock_hdr")
                with sa2:
                    thr_sc = st.number_input("Sangat Cepat jika % keluar ≥", 1, 100, 70, key="stock_thr1")
                with sa3:
                    thr_c = st.number_input("Cepat jika % keluar ≥", 1, 100, 40, key="stock_thr2")
                with sa4:
                    thr_s = st.number_input("Sedang jika % keluar ≥", 1, 100, 15, key="stock_thr3")
                st.caption("Di bawah batas 'Sedang' = Lambat. % keluar = total stok yang berkurang ÷ stok tertinggi "
                           "sebelum file terakhir.")

            frames = []
            for fname, raw in raws:
                df_s, hdr_idx = stock_promote_header(raw, None if hdr_manual < 0 else int(hdr_manual))
                frames.append((fname, df_s, hdr_idx))
            cols0 = [str(c) for c in frames[0][1].columns]
            det = stock_detect_columns(frames[0][1])
            sig = hashlib.md5("|".join(cols0).encode()).hexdigest()[:6]

            with st.expander("🔧 Kolom yang dipakai (terdeteksi otomatis — klik untuk mengubah)"):
                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    c_kode = st.selectbox("Kolom Kode Produk", ["(tidak ada)"] + cols0,
                                           index=(1 + cols0.index(det["kode"])) if det["kode"] in cols0 else 0, key=f"stock_ck_{sig}")
                with m2:
                    c_nama = st.selectbox("Kolom Nama Produk", ["(tidak ada)"] + cols0,
                                           index=(1 + cols0.index(det["nama"])) if det["nama"] in cols0 else 0, key=f"stock_cn_{sig}")
                with m3:
                    c_qty = st.selectbox("Kolom Qty Stok", cols0,
                                          index=cols0.index(det["qty"]) if det["qty"] in cols0 else 0, key=f"stock_cq_{sig}")
                with m4:
                    c_loc = st.selectbox("Kolom Lokasi/Gudang/Bagian", ["(tidak ada)"] + cols0,
                                          index=(1 + cols0.index(det["lokasi"])) if det["lokasi"] in cols0 else 0, key=f"stock_cl_{sig}")
                st.caption(f"Pratinjau 5 baris pertama '{frames[0][0]}' (header terbaca di baris ke-{frames[0][2] + 1}):")
                show_df(frames[0][1].head(5))

            key_col = c_kode if c_kode != "(tidak ada)" else c_nama
            has_loc = c_loc != "(tidak ada)"
            if key_col == "(tidak ada)":
                st.error("Pilih minimal kolom Kode atau Nama Produk di 'Kolom yang dipakai'.")
            else:
                st.success(f"Kolom dipakai → Produk: **{key_col}** · Qty: **{c_qty}** (satuan: {stock_unit})"
                           + (f" · Lokasi: **{c_loc}**" if has_loc else " · Lokasi: -"))
                from datetime import date as _date
                st.markdown("**📅 Tanggal tiap file** (ditebak dari nama file — koreksi kalau salah):")
                date_cols_ui = st.columns(min(len(frames), 4))
                stock_dates = []
                for i, (fname, _df, _h) in enumerate(frames):
                    with date_cols_ui[i % len(date_cols_ui)]:
                        stock_dates.append(st.date_input(fname, value=stock_guess_date(fname) or _date.today(),
                                                          key=f"stock_date_{fname}_{i}"))

                snaps, names_map, problems = [], {}, []
                for (fname, df_s, _h), dt in zip(frames, stock_dates):
                    df_s.columns = [str(c) for c in df_s.columns]
                    need = [key_col, c_qty] + ([c_loc] if has_loc else [])
                    if any(c not in df_s.columns for c in need):
                        problems.append(fname)
                        continue
                    t = pd.DataFrame({"Kode": df_s[key_col].astype(str).str.strip(), "qty": stock_to_num(df_s[c_qty])})
                    if has_loc:
                        t["Lokasi"] = df_s[c_loc].astype(str).str.strip()
                    if c_nama != "(tidak ada)" and c_nama in df_s.columns:
                        names_map.update(dict(zip(t["Kode"], df_s[c_nama].astype(str).str.strip())))
                    t = t[t["Kode"].ne("") & t["Kode"].ne("nan")]
                    snaps.append((dt, t.groupby((["Lokasi"] if has_loc else []) + ["Kode"])["qty"].sum()))
                if problems:
                    st.warning("Kolom yang dipilih tidak ada di file: " + ", ".join(problems) + " — file ini dilewati.")

                snaps.sort(key=lambda x: x[0])
                if len(snaps) < 2:
                    st.warning("Butuh minimal 2 file dengan kolom yang sesuai untuk dibandingkan.")
                elif len({d for d, _ in snaps}) < len(snaps):
                    st.warning("Ada file dengan tanggal yang sama — koreksi tanggalnya supaya urutan perbandingan benar.")
                else:
                    res, date_cols, n_days = stock_compute(snaps, names_map, has_loc, (thr_sc, thr_c, thr_s))
                    if c_nama == "(tidak ada)":
                        res["Nama Produk"] = res["Kode"]
                    loc_cols = ["Lokasi"] if has_loc else []
                    base_cols = loc_cols + ["Kode", "Nama Produk"]
                    u = stock_unit.strip() or "qty"
                    last_col, first_col = date_cols[-1], date_cols[0]

                    def show_fmt(d_):
                        o = d_.copy()
                        o["% Keluar"] = o["% Keluar"].apply(lambda v: "-" if pd.isna(v) else f"{v:.1f}%")
                        return o.rename(columns={"Keluar": f"Keluar ({u})", "Masuk": f"Masuk ({u})",
                                                 "Keluar/Hari": f"Keluar/Hari ({u})"})

                    nm = res[res["Klasifikasi"] == "Tidak Bergerak"].sort_values(last_col, ascending=False)
                    sc = res[res["Klasifikasi"] == "Sangat Cepat"]

                    k1s, k2s, k3s, k4s = st.columns(4)
                    with k1s:
                        kpi_card("🧊", "Produk Tidak Bergerak", f"{len(nm):,}", f"dari {len(res):,} produk")
                    with k2s:
                        kpi_card("📦", f"Stok Tidak Bergerak ({u})", f"{nm[last_col].sum():,.0f}")
                    with k3s:
                        kpi_card("🚀", "Produk Sangat Cepat Keluar", f"{len(sc):,}")
                    with k4s:
                        kpi_card("📅", "Rentang Data", f"{n_days} hari", f"{first_col} → {last_col}")

                    # ---------- A. Stok tidak bergerak (dimana / di bagian mana) ----------
                    st.write("")
                    with st.container(border=True):
                        st.markdown("#### 🧊 Stok Tidak Bergerak")
                        if nm.empty:
                            st.success("Tidak ada stok yang diam — semua produk berubah antar file.")
                        else:
                            st.caption(f"{len(nm):,} produk dengan stok SAMA di semua file dan masih ada isinya "
                                       f"(total {nm[last_col].sum():,.0f} {u}). Diurutkan dari stok terbanyak.")
                            if has_loc:
                                per_loc = nm.groupby("Lokasi").agg(Produk=("Kode", "count"), **{f"Total Stok ({u})": (last_col, "sum")}) \
                                    .reset_index().sort_values(f"Total Stok ({u})", ascending=False)
                                st.markdown("**Posisi stok yang tidak bergerak (per lokasi/gudang/bagian):**")
                                lc1, lc2 = st.columns([1, 1.2])
                                with lc1:
                                    show_df(per_loc, height=260)
                                with lc2:
                                    figl = px.bar(per_loc, x=f"Total Stok ({u})", y="Lokasi", orientation="h",
                                                  color_discrete_sequence=[STOCK_CLASS_COLOR["Tidak Bergerak"]])
                                    figl.update_layout(height=max(240, 34 * len(per_loc) + 60), margin=dict(t=10, b=10, l=10, r=10),
                                                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                                       font=dict(color=CHART_FONT), yaxis=dict(autorange="reversed"))
                                    show_chart(figl)
                            nm_out = nm[base_cols + date_cols + ["Klasifikasi"]]
                            show_df(nm_out, height=380)
                            download_button(nm_out, "Download Excel (Stok Tidak Bergerak)", "stok_tidak_bergerak.xlsx", "dl_stock_static")

                    # ---------- B. Top produk paling cepat keluar ----------
                    st.write("")
                    with st.container(border=True):
                        st.markdown("#### 🚀 Top Produk Paling Cepat Keluar")
                        b1, b2 = st.columns([1, 1])
                        with b1:
                            top_n = st.slider("Tampilkan berapa produk", 5, 50, 15, key="stock_topn")
                        with b2:
                            rank_by = st.selectbox("Urutkan berdasarkan", ["% stok keluar (tertinggi)", "Qty keluar (terbanyak)",
                                                                            "Kecepatan keluar per hari"], key="stock_rank")
                        moving = res[res["Keluar"] > 0]
                        sort_cols = {"% stok keluar (tertinggi)": ["% Keluar", "Keluar"], "Qty keluar (terbanyak)": ["Keluar", "% Keluar"],
                                     "Kecepatan keluar per hari": ["Keluar/Hari", "Keluar"]}[rank_by]
                        fast = moving.sort_values(sort_cols, ascending=False).head(top_n).reset_index(drop=True)
                        if fast.empty:
                            st.info("Tidak ada penurunan stok antar file.")
                        else:
                            fast.insert(0, "Rank", range(1, len(fast) + 1))
                            fast_out = fast[["Rank"] + base_cols + date_cols + ["Keluar", "% Keluar", "Keluar/Hari", "Klasifikasi"]]
                            show_df(show_fmt(fast_out), height=420)
                            fc = fast.copy()
                            fc["Produk"] = fc["Nama Produk"].fillna(fc["Kode"]).astype(str).str.slice(0, 34)
                            figf = px.bar(fc.iloc[::-1], x="Keluar", y="Produk", orientation="h", color="Klasifikasi",
                                          color_discrete_map=STOCK_CLASS_COLOR, labels={"Keluar": f"Keluar ({u})"})
                            figf.update_layout(height=max(320, 26 * len(fc) + 90), margin=dict(t=10, b=10, l=10, r=10),
                                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                               font=dict(color=CHART_FONT), legend=dict(orientation="h", y=1.05, x=0))
                            show_chart(figf)
                            download_button(fast_out, "Download Excel (Top Cepat Keluar)", "stok_cepat_keluar.xlsx", "dl_stock_fast")

                    # ---------- C. Klasifikasi semua produk ----------
                    st.write("")
                    with st.container(border=True):
                        st.markdown("#### 🏷️ Klasifikasi Produk")
                        st.caption("Semua produk dikelompokkan menurut % stok yang keluar (batasnya bisa diubah di "
                                   "'Pengaturan lanjutan'). 'Stok Bertambah' = hanya ada tambahan stok, belum ada yang keluar.")
                        summ = res.groupby("Klasifikasi").agg(Produk=("Kode", "count"), **{f"Stok Terakhir ({u})": (last_col, "sum"),
                                                                                             f"Total Keluar ({u})": ("Keluar", "sum")}) \
                            .reindex(STOCK_CLASSES).dropna(subset=["Produk"]).reset_index()
                        summ["Produk"] = summ["Produk"].astype(int)
                        sc1, sc2 = st.columns([1.2, 1])
                        with sc1:
                            show_df(summ, height=300)
                        with sc2:
                            figc = px.bar(summ, x="Klasifikasi", y="Produk", color="Klasifikasi", color_discrete_map=STOCK_CLASS_COLOR,
                                          text="Produk")
                            figc.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=CHART_FONT))
                            show_chart(figc)
                        sel_cls = st.multiselect("Tampilkan klasifikasi", STOCK_CLASSES,
                                                  default=[c for c in STOCK_CLASSES if c != "Kosong"], key="stock_cls_filter")
                        allc = res[res["Klasifikasi"].isin(sel_cls)].sort_values(["Klasifikasi", "% Keluar"], ascending=[True, False])
                        order = {c: i for i, c in enumerate(STOCK_CLASSES)}
                        allc = allc.assign(_o=allc["Klasifikasi"].map(order)).sort_values(["_o", "% Keluar"], ascending=[True, False]).drop(columns="_o")
                        allc_out = allc[base_cols + date_cols + ["Keluar", "% Keluar", "Keluar/Hari", "Klasifikasi"]]
                        show_df(show_fmt(allc_out), height=460)
                        download_button(allc_out, "Download Excel (Klasifikasi Produk)", "klasifikasi_produk.xlsx", "dl_stock_class")

# ---------------------------------------------------------------- Performance SS
if page == "📈 Performance SS":
    with st.container(border=True):
        st.markdown("#### 📈 Performance SS")
        st.caption("Rekap gabungan dari salesman yang difilter di bawah ini — anggap ini sebagai tim yang "
                   "dihandle satu Sales Supervisor. Insentif dihitung pakai skema Sales Supervisor (IBN) M245, "
                   "bukan skema per-salesman.")
        salesman_filter_ss = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih,
                                             key=fkey("ss_salesman_filter"))
        st.info(f"Tim yang direkap saat ini: **{len(salesman_filter_ss)} salesman**.")

    df_ss_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_filter_ss)] if salesman_filter_ss else df_filtered.iloc[0:0]
    kode_sales_scope_ss = df_ss_scope[COL["kode_sales"]].unique().tolist()

    pencapaian_ss, bruto_f_ss, bruto_r_ss, pct_retur_ss = hitung_pencapaian(df_ss_scope)
    oa_total_ss = hitung_oa(df_ss_scope)

    target_total_ss = 0
    if not target_all.empty:
        tgt_df_ss = target_all[target_all[TARGET_ALL_COL["kode_sales"]].isin(kode_sales_scope_ss)]
        if periode_sel:
            tgt_df_ss = tgt_df_ss[tgt_df_ss[TARGET_ALL_COL["periode"]].isna() | tgt_df_ss[TARGET_ALL_COL["periode"]].isin(periode_sel)]
        target_total_ss = tgt_df_ss[TARGET_ALL_COL["target"]].sum()
    kode_bt_ss = tgt_df_ss[TARGET_ALL_COL["kode_sales"]].unique().tolist() if not target_all.empty else []
    pencapaian_bt_ss = (hitung_pencapaian(df_ss_scope[df_ss_scope[COL["kode_sales"]].isin(kode_bt_ss)])[0]
                        if kode_bt_ss else 0)

    team_per_salesman_ss = df_ss_scope.drop_duplicates(subset=[COL["kode_sales"]])[[COL["kode_sales"], "team_simple"]]
    cb_standpro_ss = int(team_per_salesman_ss["team_simple"].map(lambda tm: PRODUKTIVITY_STANDAR.get(tm, {}).get("cb_cover", 0)).sum())
    oa_pct_ss = (oa_total_ss / cb_standpro_ss * 100) if cb_standpro_ss else 0

    st.write("")
    with st.container(border=True):
        st.markdown("#### 💰 Omzet")
        net_divisi_ss = net_by_group(df_ss_scope, ["_divisi_norm"], "Omzet")
        net_divisi_ss = net_divisi_ss[net_divisi_ss["_divisi_norm"].isin(DIVISI_LABEL.keys())]
        net_divisi_ss["Divisi"] = net_divisi_ss["_divisi_norm"].map(DIVISI_LABEL)

        col_all, col_div = st.columns([1, 2])
        with col_all:
            kpi_card("💰", "Omzet All (Neto)", fmt_rp(pencapaian_ss))
        with col_div:
            show_df(format_cols(net_divisi_ss[["Divisi", "Omzet"]].sort_values("Omzet", ascending=False),
                                     rp_cols=["Omzet"]), hide_index=True, use_container_width=True, height=180)

    st.write("")
    with st.container(border=True):
        st.markdown("#### ⚙️ Productivity")
        ec_total_ss = int(ringkasan_sales.loc[ringkasan_sales["Salesman"].isin(salesman_filter_ss), "EC"].sum())
        mhs_resume_ss = hitung_mhs_resume(df_ss_scope)
        mhs_by_sales_ss = hitung_mhs_by_salesman(mhs_resume_ss, df_ss_scope, outlet_count_dmp)
        total_lolos_ss = mhs_by_sales_ss["Outlet Lolos MHS"].sum() if not mhs_by_sales_ss.empty else 0
        total_cb_ss = mhs_by_sales_ss["Jumlah Outlet (DMP)"].dropna().sum() if not mhs_by_sales_ss.empty else 0
        pct_mhs_ss = (total_lolos_ss / total_cb_ss * 100) if total_cb_ss else 0

        p1, p2, p3 = st.columns(3)
        with p1:
            kpi_card("📞", "EC (akumulasi)", f"{ec_total_ss}")
        with p2:
            kpi_card("🏪", "OA", f"{oa_total_ss} outlet", f"{oa_pct_ss:.1f}% dari CB Standpro Area ({cb_standpro_ss})")
        with p3:
            kpi_card("📦", "% MHS", fmt_pct(pct_mhs_ss), f"{int(total_lolos_ss)} / {int(total_cb_ss)} outlet DMP")

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🎯 Insentif Sales Supervisor (Skema IBN M245)")
        st.caption("Reward & Punishment (Tagihan, Visit in Radius) tidak dihitung, sama seperti menu Insentif salesman.")

        n_tanpa_target_ss = len(kode_sales_scope_ss) - len(kode_bt_ss)
        if kode_bt_ss and n_tanpa_target_ss > 0:
            st.caption(f"⚠️ {n_tanpa_target_ss} dari {len(kode_sales_scope_ss)} salesman belum punya target di file Target — "
                       "% Capaian Sales dihitung dari salesman yang ber-target saja supaya sebanding.")
        pct_sales_ss = (pencapaian_bt_ss / target_total_ss * 100) if target_total_ss else np.nan
        insentif_sales_ss = tier_lookup(pct_sales_ss, INSENTIF_TIERS_SS["sales"])

        detail_kategori_ss = []
        insentif_kategori_ss = 0
        for kode_div, label_div in DIVISI_LABEL.items():
            net_val = net_divisi_ss.loc[net_divisi_ss["_divisi_norm"] == kode_div, "Omzet"]
            net_val = net_val.iloc[0] if not net_val.empty else 0
            tgt_val = 0
            if not target_divisi.empty:
                t = target_divisi[target_divisi[TARGET_DIVISI_COL["kode_sales"]].isin(kode_sales_scope_ss) &
                                   (target_divisi["_divisi_norm"] == kode_div)]
                if periode_sel:
                    t = t[t[TARGET_DIVISI_COL["periode"]].isna() | t[TARGET_DIVISI_COL["periode"]].isin(periode_sel)]
                tgt_val = t[TARGET_DIVISI_COL["target"]].sum()
            pct_cat = (net_val / tgt_val * 100) if tgt_val else np.nan
            nilai_cat = tier_lookup(pct_cat, INSENTIF_TIERS_SS["category"])
            insentif_kategori_ss += nilai_cat
            detail_kategori_ss.append(f"{label_div}: {fmt_pct(pct_cat)} → {fmt_rp(nilai_cat)}")

        insentif_mhs_ss = tier_lookup(pct_mhs_ss, INSENTIF_TIERS_SS["mhs"])
        insentif_oa_ss = tier_lookup(oa_pct_ss, INSENTIF_TIERS_SS["oa"])
        total_insentif_ss = insentif_sales_ss + insentif_kategori_ss + insentif_mhs_ss + insentif_oa_ss

        st.markdown(f'<div class="big-nominal">{fmt_rp(total_insentif_ss)}</div>', unsafe_allow_html=True)

        tbl_ss = pd.DataFrame([{
            "% Capaian Sales": pct_sales_ss, "Insentif Sales": insentif_sales_ss,
            "Insentif Kategori (4 Divisi)": insentif_kategori_ss,
            "% MHS": pct_mhs_ss, "Insentif MHS": insentif_mhs_ss,
            "% OA": oa_pct_ss, "Insentif OA": insentif_oa_ss,
            "Total Insentif": total_insentif_ss,
        }])
        show_df(format_cols(tbl_ss, rp_cols=["Insentif Sales", "Insentif Kategori (4 Divisi)", "Insentif MHS",
                                                    "Insentif OA", "Total Insentif"],
                                 pct_cols=["% Capaian Sales", "% MHS", "% OA"]),
                     hide_index=True, use_container_width=True)
        with st.expander("Lihat rincian per Divisi (Coffee/Cereal/Instant Food/Homecare)"):
            for line in detail_kategori_ss:
                st.write(line)
        download_button(tbl_ss, "Download Excel (Performance SS)", "performance_ss.xlsx", "dl_ss")

# ---------------------------------------------------------------- Read Me
if page == "📖 Read Me":
    with st.container(border=True):
        st.markdown("#### 📖 Standart Produktivity Team M245 (berlaku per 03 Agustus 2026, W32)")
        st.caption("Sumber: Surat No. 001-W/EDP/VII/2026. CB Cover dipakai sebagai pembagi % OA di seluruh "
                   "dashboard. Pembagi % MHS/SKU Sold TIDAK memakai tabel ini lagi — lihat catatan di menu MHS.")
        df_prod_std = pd.DataFrame([
            {"Type SF": k, "CB Cover": v["cb_cover"], "Call/Day": v["call_day"], "EC/Day": v["ec_day"],
             "IPT/Day": v["ipt_day"], "OA/Month": f'{v["oa_month_pct"]}%', "Target Channel": v["target_channel"]}
            for k, v in PRODUKTIVITY_STANDAR.items()
        ])
        show_df(df_prod_std, hide_index=True, use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📖 Target SKU per Klasifikasi Channel (acuan SKU Sold) — Memorandum 27 Agustus 2026")
        st.caption("Klasifikasi diambil dari kolom NAMACLASS di file DMP (Supermarket dari NAMACHANNEL). "
                   "Outlet yang tidak masuk 9 kategori ini tidak dihitung ke SKU Sold.")
        df_sku_std = pd.DataFrame(
            [{"Kategori Channel": k, "Target SKU": v} for k, v in TARGET_SKU_BY_CLASS.items()]
        ).sort_values("Target SKU")
        show_df(df_sku_std, hide_index=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📖 Mapping Divisi")
        show_df(pd.DataFrame([{"Kode Divisi": k, "Nama": v} for k, v in DIVISI_LABEL.items()]), hide_index=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📖 Skema Insentif M245 (Agustus-September 2026)")
        st.caption("Sumber: Scheme TO Retail, TO Grosir & Sales Supervisor (IBN) Agust-Sept 2026 (PDF resmi). "
                   "Reward & Punishment tidak dipakai.")
        all_tiers_readme = dict(INSENTIF_TIERS)
        all_tiers_readme["Sales Supervisor (SS)"] = INSENTIF_TIERS_SS
        for team, tiers in all_tiers_readme.items():
            st.markdown(f"**{team}**")
            df_show = pd.DataFrame({
                "Kriteria": ["Sales M245"] * len(tiers["sales"]) + ["Sales per Kategori (x4 Divisi)"] * len(tiers["category"]) +
                            ["SKU Sold"] * len(tiers["mhs"]) + ["Outlet Active"] * len(tiers["oa"]),
                "Min. %": [t[0] for t in tiers["sales"]] + [t[0] for t in tiers["category"]] +
                          [t[0] for t in tiers["mhs"]] + [t[0] for t in tiers["oa"]],
                "Nominal": [fmt_rp(t[1]) for t in tiers["sales"]] + [fmt_rp(t[1]) for t in tiers["category"]] +
                           [fmt_rp(t[1]) for t in tiers["mhs"]] + [fmt_rp(t[1]) for t in tiers["oa"]],
            })
            show_df(df_show, hide_index=True, use_container_width=True)
        st.caption("Tabel ini acuan statis dari spesifikasi awal.")

# ===== Gambar latar (hexagon_dark, dikompres) — JANGAN DIEDIT, dibaca otomatis oleh _bg_data_uri() =====
# BG_B64_BEGIN
# /9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAsHCAoIBwsKCQoMDAsNEBsSEA8PECEYGRQbJyMpKScjJiUsMT81LC47LyUmNko3O0FDRkdGKjRNUk
# xEUj9FRkP/2wBDAQwMDBAOECASEiBDLSYtQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0P/wgARCAQ4
# B4ADASIAAhEBAxEB/8QAGgABAQEBAQEBAAAAAAAAAAAAAAECAwQFBv/EABgBAQEBAQEAAAAAAAAAAAAAAAABAgME/9oADAMBAAIQAxAAAAH8kE
# AAumKzZqUEAUAAAAABQKAbxTXD1+YtxuApQAAAAAUABRZ0rtw7+Gy9c6zQoAolBZQEUAFKoLZTv9T430NZ+Lv6nxsa9cWooWWqChAKlEogCi2a
# p25e+zr4vR4rmZM7FFlKlsqUFIoi0zaJQAkolU9fq+Z9TWefm7VPIdJr3+71eCZ6zlDpnnmus4Q9GeGTvnhK754ZX0TzQ9WfNiPkcvofO5dO3R
# wrKM22WrZSlQKAiyEsEpYAUY2OG5mOvt8V1Pb5foeOzlLM2TUIsUBLASAAAGdcRXSNctYoqAFKUAEsAEoyIAWbJzpVEAFJQAAAAAqWgAAN65dq
# 82rjLYqgAAAAFAAFC+nlrU4YnXNooCwFABZQEUFiqCgtg1146s+3+e+n3ufg+rx+nG9K0lCgoRQSwAShZS6z0rr78cd45ckzpCUAUWWwoUBSVS
# KqNDM0jDUIsL6fLqvr+Tebjj9rxfWl83hznU1M5XeZk1mZl1mZNZzI1mSWsjTMOng9kj52I570lFWlVFKAKICCIsAAUEzz7c1nTj0j0+n5/wBD
# efFO3GWSyEpYAQEKiAKkM5li9ZmsiAFloUAASwAAyIFFvMmpVBAFgUAAAAABQKAAayO/l9GTncbiigAAAFABZRZ3rfi7+dNdJZQoUlABYKApAK
# KFBQUalN/X+P6t58nj/S/msX1uXZYqigEoAIolgtmierl7dTfh51EJoBYqgKQUUFBSrc0SiTUMyoksLc06+75n10+j4vZ8jWWZm2zMlsQgjM1l
# USEsIsJRWsk8fm+t8rGllzbqWy0ooKIsEsEoiyEoiiKJKOLWJeu+Wq+h8+4s1Ms3TMNzI0yNSQ0yNMjWKM6z6DPLeSKiKoolAABKIACIi3I3y7
# YqCAAFAAAAAACgCgAANd/P0rg9HnjaCoKg0yNM0qC3I0yOvfjnU47z0zaloCgFAASoKlAKKtgoKBQ1rNs+r4p9XWfyvt81579Lzq9LzD1PMPS8
# w9LzD0vNT0vMs9LzaPp+L1fOs4+3zZzr3DUSqlIoopJQtzS3NLVoUiiSwhmCADX6r53a58nnY0ZkzayNzIsRWdQk1Ik1CKIsJKV5vRuPkas561
# ZqxVpZQUiiAkokoggACLBx7ZXl152LKIACAASiAAA6a7eazMqWKJQAAAASwAAyIA1vlusN4gACgAAAAAAUoAAUlBrPUvDWDdABQCgCiURZTXm9
# dPJ18/eWillAFAEFJQAWWgKUAUFBqasv0vH21PP28HuyrTUzaMtjLQy1TLVMtDM2PBx+78DN1x6zOu3b530dQrQACKBRYTTNNXFNXNoUyomajK
# jPfj+kj0fG9nz+mJz1iamaiSxQAAEsIoyqM2iSwhDn4Pq/PzrG+e83VlstlBSASjKwkoiiCAEoi8Vx6eH3LPnTeEksWKIsIqJKICKJHKX1ce3O
# zCyUABLAAAAgAAyIAqU6ct2uYgCgAAAAAFAoBYKAUutcKzrO4AAoAABQADXs8PbU8+ff8/N9DG6AFAASwFgoKKUBQCgWUus+iz0/N9Xjs6XKXV
# xTTNKg0zTTI0za0yKzI9vPh79Z+QMb59c8Y+kzvpCwAiiUKkTSDTNNXNKirEgsEo9v3XgufLjXPTONZlyslSiAKJKIok0MtDKiSyMywmdWX5mu
# 3DGumsas1rNKAKiyJNZIsEsgCKJQzw11l9+fV83pjEsxqBYsABACKiAY3B6fH6bOc6c1SogEogAAEAADIgCgdOeqzOvICFAAAAAqpQAAWCgbz1
# rPBYtAABZQAABZQBrNr2+Tfpufmd/P0zroKWCpQEAUFiqAClJQqUtza6e3hxufN1zrOiCoLYq2UFRc0qUEEQd/OPX8/wCn4Ezjaant+b7Tqjcq
# VEsAUAIWC2LLrNKgAfW+b+tk83ye/n6ZzjWVxnpmXKiTQy1Iiwk1FlUijM0MzUMzUjOdRcTcieD6PCXzb5bzelzbNs6BAQSwiwSyAAGN+dX2vD
# 9DWfL5rmVEgFSiAiwAiyAAMzfM9vn3dTkM2AEAAEsAAAjIAFgoOmHSuIipQAAABZQKAAWCpo1np5xqaAAAKAAAAACgvq8u7N+P63yzreXVQAKg
# oKEAqKoKg0gtlL05+2y/L6w0JUolBZaWUWVAKCKJLDM1F6ejxeuz52+3HNmOnGPo683o3Kasj2WPE9g8T2w8T2jxX2F8d9dTx31jyPXTxvXxPt
# d+Xj1iYud2Z1IzKly1DLUJNQijKjM3IiwSiTUXE1kmdZjOdSWazg8rXPGuuue7NayNQEsEsEogJYKiOfN9Q9Ph9Xg3mS5xoCLFSiAQAIoiogGd
# Dn7fH0q578CLIAgABAAADIgCgAbxa1z7ciWWAAAAAKKAAAvTGq55m8qKAAAoAAAAFACivRrz+7Wfk9pzxruKAWChKlAFKFIoWUVo69enzdZnSX
# OgoICllKlKlRYKABKM51FzrMj3/L9jU8sXF5fQ8XWvV9j5v3unP1b+Ks+1Pij7U+ND7E+ND7Wvhj7r4Y+4+HT7d+JT7fn+Z9FPh9+/kmusjRFM
# tDLUWLCSyCAACAkozNJcTUMy5hmxc/N9fjxWs3N6b57rolsqUSiAgIsJaJx6+eXp93hz1jz8rJqSyBFASwASwAAASoiwmOmD045eqzzyyUCLAA
# CLAADIgUlAADd59a4tZigAAALBQCgBo3x6cS6UlAAUAAAAWCgAAop2409fzfp+Wznvz+jNChQVAKKAAoKUejl7tTzeXPWCliiKJQUAKhLBalSl
# IqszUjOdRXt8HVPNr1+KN539A+s7eHvzqFSiSyJEKyltxTd52zowOnXhT7P536/OTxa4dWrEsoAJLJYQsQsCpQBNZGbImblWbImdeGXzbjnrnr
# NjfTl006axqy3NKgIAABg4+nzffkvyvT5dsyzNghBQEABLAAAACCEo5+jhDvz9PCzIlSiLAACAAyIUAAAGs6rfLpzCiKJQAKIoiiKHSZOZqApZ
# QACgAAFJQAAAUpZTr6/n+rWfn79Xhxr0FqKFEUoolAUlUV1rt5/V8253uWaJQAgpQApAIBQtzSyqiyJnUMTWZfX5N9rPP+n+Z9LeOPM2CCqksj
# M1DM0lzQKJVpZU6fV+R67Pm363xMa9DN00zSxCTWYkCKIsLcjaBLCRImbFksjl8vtnnrXHt55Vll1vnuzrrG7LSiwAQC0nl64j3e/r83eeGbM6
# ksIIEAVAAiwAAAELCAJjpk6b83rs87eZYBKIAABKMCKAAAC7zqsOvbWPK9azyX1DyvWPI9Y8j1jyPYrx31jyX1jz+f3eTOstTOosFABZQAAABQ
# AAooAC7xT6HyvbdZ8O+bGujmOl5jpeSut5Dq5Dq5jq5VOv0PldrNOfVVKAAAKAAALKSKUVBSKqZ1IxN5lz6fN9y59/i6eftjTNl0lKikSEgqFA
# KI0TNousU+v8f0e9PhdPP2zrQ0qCTUjM1CSwiolQopLIksWS5J5/R8nFz1lzrPHeMgLcjpvjqut5K7OVOjmOjmOmuWkx9fyfb3jxfP78FxLM6g
# EsgCBYAACAAAAggADG84PX52TTMNsDcyNMjTKNMgUlAABZurz1zOnbzas9DgT0POr0OA9Dzj0POPRfMPTfLT068m7Pp/M9munP50rj2zKllABZ
# QAAACpQUlKAAKFnQ6+fv5LPb18FPdr56z6Ovm0+jfm2vpX5g+pflk+rfk0+rfk0+t1+L7bPk6+t8Pnv3Mb0AFIAUAAAAWCpUWUpKEiZ1k9H3uW
# OmOUSqg0yNSQrMl1cU0loiKlqywJI3eds6fR+Z0rfi+9+fw9DG7UqszcjE3DKwSiKISERUZEYjzeSdee0vKMEl1ck6dfNqvf6flb1n7PT4u9T7
# N+OPsT5MPrPkj6+vjaT6Ps+P9Lrx8Pm+r83n14Z6Yx0ysBCwhBUogAEAAABKiAEMM+46cpx1O84yO84l7OMOziO05Dq5DAyoAALuZrBZbYSpaA
# AAqCoKlLc07/Q+X6+nPjw+r8tJneefWAAAAqUAAWUAooAUFHp5WzzpuVZQBZUWUWKqUqC3I3vlo+z8T2evWfg+vxenGug0AAAWCgAAAWUWEslE
# Qnv8P6W5z4946REUIWQskLAqDVzSgiiWCglQ3rnqz6OfH9dPz/fnc66RNRKMyyWRCygokozNZlzneDPg9fy+et7Jc8bMkFWUWU1vnuzrvnqzoz
# aqAQ1rFOvfy9N4+18z09enD4/P0cePp5zUlgEsEqIFSwAQAAAEoiocd4OntnHU5wzUABAAAAwqAAGpupy1mGpQAACpQAKAWUWDXXjqz6nlnt7c
# fkNTj1zLJoABQAAAoAKKAFGs9k6eHtyNUUolBYKEFAolFg1c039X5Po1Ofh/R/nMPa4d7SKAAAqCgoQhagqEEGW4+n69+LrhBQIsBBAAoCgoFE
# 1CAihvNrp6/FpPpfB/QfKjnePNfVPLI9U8pfU8g9c8o9Tyj0vMPTPNDvnjxzfPnHXnpz3xISUBYKC7xqzpvnuulzbKlIBYN656s9H1fjezrwz4
# vtfKzvzZ6Y59YASAIsUQsAQAAASwLzjPfh9KzHl3gElAAgAAEoyIAFK1yqFloQAABYKAKAUALc06e/53feO/g+x8zeOU1nl1glAKAAAFlAFKAF
# Ndp57MbmpQFAUBFgqCoKlolFlLrNPpcvP9bWfzXs4TGvSTQCoKlFlARKIpYoSxGbmWfY+KT7/H5/u6Z0yrTNLILIEJQLZUqWqlKaIqpNDLSJUr
# TI9H0Pg+LLfh74575OiOToOc6ww3V5uhOc6l5Og5OsiVK54MoFAAoLrOk3vnvTpc2zQEsAFg6deG9Z+x5uX0O3n+Jz9Xn4ejmsmoIASlkoiwAg
# AAAicdU9V7ePUyTNAAAQAAAMiAGpqs4IalAAAAFAKAFAAALvFs9/TxfQ68flPR5+fTM1M7gAKAABZQCigHTHoTPltW2UAoFgqVAAAAFgqUtza3
# 7fDuz6Hwv0Xx5G/H62kQtWhUFIoTQy1CKMtQzjpzlxrNjP0vndK+lrN6Y0yqxYiwSiLSUq3Oi2UtlpRFQsCTWSZvml48Wees5TNqAQqUAEKAQA
# cenGVLJQABRZRrOk1rG63rGrNCgBCoNaxU7fR+X36cvX877PzLPJnpjl3ksgBLBKWLACAEKlGdcYn0PN67OPGxUsgAAABKIsAMoioN51zoWWhA
# AAABQKAWCgAAWDp6/F01n6Xy/pefry8mdTj2kqWWCoKABQWUClmjc6+OxuXNFoCpQBYKlAQogFgqWllLrNPX7PlfT1n4Hb1fOxr1SdK+j9X4Le
# f0F/P2z9Dfz1r9Dfz1P0M+APvT4UPuvhQ+6+CPu5+Hs8nC55buaj3ej5X1Ok1V1mKIoAKIoAtlLYrVxU2zoSypGYz87v5Oe5m4zYIAgFgqCgAS
# wWdDyztwlSogUCgoKE1rGq3vGq1ZbCUEBCoOm+W7Po9Pn/U7ef5HL3ePl35zUzqCAIFSwAgEoijGHpj0cOvl1BM2wAAAEsAAAOYlBAVqEoAAAA
# AKKAAoAAALrFPV7/le7ry8Off8/NizHSWCpQABZRZQKvbn1s485rNopQAoAAKEAAKIqpQWC3I3289Pr/n/AKeLnw+/h3alzLOjFN3FN3FrTA3M
# jTMjbENct+eMEzVgevyyvr3n16ZUsFIoKIoWUCqg0yNs1KkHHr4M3jz1jntjWYAIAAAALAAvXO63876fE8KzFixVlFlBUFGpqtamqpbCUQCIWC
# 6xa6+vxb3z+r8z6PDfP5+OmOPoyIAgVASwAAc98Y19HlNTnglQgAAgsAAAADm0jLQzc6UEqUAAAAUAoAUlAAAADXbhuz6nzOmN8+E7sdPO9CXz
# vSPM9I8z1K8z1DyvWTyX1jjn1+IuufWWCqlAACgChACiUIBZaAJRZS+rye7Wc8/qfN1nmTG7c1bc01c2ygFIsJUHk9fklgyAsU7e/wCR9Pc7De
# aBqDVxTTNKlCqyshENM0qZOfi1x56ax2l5Z7aOD02vLPWPG9cPK9Q8r1DzPSPNPUPLfSMNCejh0s+Zj6vysWLM0VQRQVaupo1ZqxSgIsBIEKg3
# rnbPX6/ie/pz8OPoZ59PnveXwPejwPcPDPcPC9sPG9Y8j1jya9HKX2+Ppx1BM0AAACAAAAAwIbxak6co1YKlAAAAKAKAAqCoKAAC9MWsXGo2yN
# sDbKtXA2yNsDo503edT0b83v1Pjddcca7CgAAAKgoKEAAqCpaEKBZo6/Y8nt7efyePpxx1kTO1lLZRSy2Q0gKBC8uo8TeMUBYLvGT7DzenrkpI
# oayrVzTVyNMi5QEKkL5+vhzZgxrXQq6mrFBLBAgAFAACEKlPT8v3bT4yuW4BZQWmpoumqVbBQCAkogiFHHpwl7fX5cN4xOcmuk5o2wNsQ2wXbE
# NsDczC89yOuefos4ypYAACLAAAAADAgDeW646zZdISgAAAooAABYKgoABsvHeC6goBQABYKlFiqlL24VPb8r6vks474d86CgAAKgoKgAoQQqFW
# Etlq+rh9XePT4fV87pyzz1jl3QlqUUNJbKgqCgoLA5+b2+eXirIBQfU+V6tT2stzVxTVwOl5rOjFKkLJI1MxdzODl57jnq9OfclmrNWapLBAii
# AAAEKgSgB6PPs83j+58XNyMUC2aq6mquppFloABLBLBKiLyOfo8/2ifO7cNRLM6AIBCoAhAASjHXnk74686yIAAELAAAAAwIAazS8+3IqUqUAA
# AFAAoABYKAC9JzrGpqKAACgAAWUAqKtg6+vwerWfna9ngxruiqAAACgWUBAUBLChGnWz0/V447+fzcNc+faZM6lhalFC2WwAoAWC2UZ0PFPRwz
# YIqUZ1D6W/jNPsvjE+xfjU+xfjD7F+MPsvjD7E+RD675BfseTxdxFjpaq7zqygVBmwQAACCgENMipRYOvHfos+I6c+WxRqaLuasVaAsBAAiiKM
# +bpnN93o7/N3jnLM6gWKIAQAASyAAJnQvTz+iuTWYAAAgAAAAMCAANXHSuOkltEAAAAqCgCgAFBZ0HGi2UAAWCgAAoAApQbxT6HyvZ01n53Tj1
# xqillAFAAChEpYsFgtls19Dy/Z6ctfM7+TWc89Z59pKlAoFlFlFlsUBSULrNLFrPk9nOPKMWLAQBQAAAACCpRrOi9ufSxvO7GpaWBEACBCAAAA
# AVYSim8DfzPr/PjhZrGm5qrVsUBCoABCyhnXnjH2PnfYs8vk1hZLIEWwABASAAABADNZPRz1KyIAIKgAAAAwIAAWDpx65qXG5QQAAAAoACgFlN
# NcRqUqUAAqUAAFAAApQA17fB2s48fq/JjsztYCpQCpQBYKlEEqUam7Poe3xZ7+fHO45d5CagFgsUAtgoKLLc0tg0g0loDyc/Z48WKiS5UAAAAA
# ABYNWVO7HTS7lstgsozNQyogBBLJQKQqVAUEAA308fnJrOsa1vOrLSgEsBCoAFlMcHsy+h5fX83pnOdTGsrFgAEoggQAAASwASwnfhsTeABAAA
# AASwyIAAAvTlqsOnKNgFqKIqIqgAABRqbMYmigAqUAqCgALAUAKoACpT2ed7NZ+P25axraqAFABUiiUIolqr6+H0OnHh49eXO/bnNmglqKqUqU
# WCoLYNJbKUlC3I1ci3Kr5vTmPHLMWSxQAAAABSKBTXafS1n5Po8/WXrZdRQSwSiSiAhBCUACoKgqCpQcDz2XFbxs1qa1AAEsFgsABy6+WW/d8n
# bWPNxSagiEUQsAICoqIAABLACAZ1DtznSuYgQqAAAADIgAABZTpy3uuOpolEKIoiiKIoiqi2Lz68ValAAFgoBQAABYKlFiqABYL6fNqzv8/wCv
# 81Lcal0iy3NKg0zSoKkNMjVx6bPRz7/O6cs8tZ4956vD6V6osWUWKtzSwFlFC2LNIKlKgqUAsuDjy9/lzeMslAAAAAAqC6x3Tft8nXc7+D7nx0
# 1efVZKIsBCwBBCEFQKACoKCKTPh7YzbjfOXW+NO+vPa9Dz1O7gXvOA7uA7uA7uAMfXT0fO6+bURM1BYsEolgoIBLIAAEAAIADPXmOvXXDU6Tij
# s4l6uI7OI7OI7OIwMgAAFWnfl69Zl5TWOzgPQ849DgO9849Dzj0POPQ89rvOKOfL0eXHTollAAAoAKAAABZQCpaAAWU79OPHWfpb8vXpy7ONs7
# XhTteNTq5U6XlTo5DpOeDs8uVxwy49mbM6md4PY49tRZRZaAAoC0lUWWwQAAtgctes9Hh7+aznOkzebZeboOd6Qw2MOg5ulTm2Ma0LrOq9fXxf
# U1n4XXpwxrrNZqLBKIQELElQAFgqCkKlGdeQx3z6JM+b6nz9Y5a6dMdOWvR11PHfdU8D6EPBPfF8M9o8T2DxvYPn/U+fqJm5VLJQEAQAACBAAC
# AASiAAm+XtJ59ZpCAAABCoMiAABRqbrp2vl6csxOfSoWoKgqCoKg0yNMjvw3uzzdOes60LAAKBYKlAAAAKlAqgAbz1TnjG11ck1cU1cDbFrbA3
# eY2wNZmYrEN41zl2gso5+vzaPRTUUFKKAKlKCosqCoKlLHONfT4c9TGElEigAEKgqDSWgALc06ejy7s+l8T7HlTy649ppAhCwEsiTRczQzQAEK
# goOfCdst+7h07cPL5tc+Xa3NzrprnqzdyrcgsgqIEKguNQ7crawJQEBKIAAIAgAIABLABLk766eayElAAAELAAyIAAVavo5ereMeXWJUszoIAA
# AqCgCgHXlS8vV5TbOhZQBYKBYKgqCgAWCpRZaFNY6+ZNUlClgoFgqUSiEGbmGbC3GiazoAc+uT078fr1LYqgFJQqUAoosAkqKmuX00eLpypDNS
# iKIAQBalRYKCirYN6509P0Pke3Wfl36Py8a7ZqoAiEogUgqCwEsAHHr5I36Ofs1jr4PR4dZzmzj2azTesarVzUqUSwEWoLAWDHo55TU6cwhQAI
# AAISwASwAELAEJ6eHqs5c7JQIAABAAAyIAFGp1s656+TpiROfQIAAAAAqCgACts9a8vTMzd2LKACpQBYKgqCgAWUAdcWzmzqWgAAWKqUWACTWS
# S5hAliN5WrYKgx6eOT22NSigKgWUtzSoKlRZaY1zj09+nj1MRM0goAEAFAqEoBRZQWlg3vlT63xvZ1ufl9OHTOqCKWLABKIogIQqZjkx3jftz5
# u3Dhx1jj3QltlNXOjViqESiBUsALAuNU3jHZOYUgEKiLAAAAgBAAQuL0O/LfGwiUAAACAAAyIApa16uPbfPjxszuCUiKAAAAAACoKgusq6+f08
# Sa59ICgFgqCgAqCpQBYKm61w6YKIAWCpQKqUAAksiZ1kghLBvFGorSUY2Nejw7r1vIPW8g9byD13yE9d8Y9l8Sva8Q9zxdTr6/J9HWePnuVsII
# KgoIoiiSiUVYSoNM0qUtzatzTX0Pm9rOXD6/xcu7x5mvc8I9rxD2PGPY8aPW8g9byD1zyj1eaDp6eXu6cp83r55Zmzn1CLZaus6LZaoRLFAQAA
# AJqYOmevJBJbAIKgsAQqCwCCwBCezlbM5iUAAAAQAAAyIFG8+jU6+Xt5tYQx0QgCoKAAAAAAABQ1049a8+t8o6JaAAAqCoKgoFgqUvTOLMallo
# AAKlAqgAAk1DM1IzLASAXUasM6KgAAAAAKItIompT13x51PdM2yywKAAEAFSiUACDTNKhKAQ0mD0efglzKzYoiiKIsIoiiVR0z11nvvp8/rx58
# 7nh3CUUWaq6zqqChEoixYsAAAEomuXYxLInTXs1PE9A87uOD0Dzu8OE7jg7SOLtDi7Q48+1l6cLmggAAABLAAADIhWq16ueenPllOe0slAAAoA
# AAAAAAFgtiu/l7U475blt3qzk6jk6q5Oo5OqOTqrk7E43sON7U5clloFlAAKgoKKALBKMzUjM1DIhLBrJbpmzQAAKgqBYFlAALYLKNejxerU2K
# BBSUCABYAAWLAAoAEL5unLJLmWoKlBCwABCgamrNe3ze3rx8/i3y59JEzuiFlq1S0q2UBIsVKIsBCoKgAZ1mN416LPR5u/k1EszoAAQEBIAIFg
# kCgAAAAgAAAMojXXl69Z15OnKxEzsIAAWCoKAAAAAAABZaduOjm7czW+Y6MDbA2wNsDbCujnTd5jp1820nP2eMqWUBQAqUAWWllAAJLDM1IzNQ
# ksgC3O6lxTTI0yNIKgqC3I0yNM0sz0CiLg9jn13AAAASLFqVKgAEKhSCoLHKMRM2zI0yNMjTI0yNMioLcje+XfWfd5e/g6cs5Tj3JYAtmqamhS
# qAESxRAAQsAIiwEJ9Xg3nlzM1LFAAEAIIAgAJNZFlAAAEsAAAADNN+rx9tZnL2+NMrM7ggAAACpQAAAAAACoFmqRQAACoKgoFgqUA7zn6dTxVM
# 2gWUAAqUWKqUAASiSyJnUMrCKiELuStMjTI0yNXFNMDbI3cU6b5asmPZ4yiUCery9K7o1KgqUAqCpUEKhbASiWCoiefWYY0lusQ2wNTI0wNsDb
# A0yNXA3rmSxFEigWWrVLZaUFgqCwAICACEAQax9Czp4unGhJagsAQsAIQACAADNQoAAEsAAAhKMgu8WvZyz6enLwzU59MrJQAAAFgqCpQAAAAA
# CilAAAAACpQACgdeVrv5fZ5kyllAqUAAqUWKoAAEozNSM51CCJZqoIAAACggqlUupa6a5d7PJTNAZ1D03z99SgClgqCpQAgsAABjXCIZzc9IIU
# k0MzUIsgAAAADWNWsWWALZqlUUoBZQAQASwAIgQsQ7ex5t5xEzoBLAAASAAAEAABnUJYKACLAAAADIhZTXp8nTU7+X3eTWOazHSCAAAAAFgAWC
# oKgoFloUlCVCoKlAAKAACgA6dvN6dTx3rxzaABYKgoKlAqoKACTUMzUjOdwTUIoiiKIoiiKC0amqURZle3l780QlAz6OI9I1FgpCpQQqUACgBI
# 58yVhqGVLVJNQzNQkoioiiKIqoqJqKjfMtUalLZaAVAAAAQsAIQEsHp830tTl5tZIJRCoAAiLAAAQAAAAysFgqCwAAAAMiALrFr09PL6+nPxTt
# yxvKzNEBsw2MNjDdOborm6Dneg5ug5ulOTpzi2KoAAAAFABQAWUAAu+dr1+L0yzzpc0ABYKlAKlAqoKBKMrIx0lMKIoiiKIoiiLSVRqWqEmdZW
# awjG0KBnQ6dPN6aUsAAAIKABZRx6cIS85bbkWaLVpNQzNSMqJLSKIoijLQy0EvQ46zsVaAAAAIAAAgQAkuz0zv4t5iM6AASiLAIgABAAAQqCoE
# oiUAAAAAAyIAWDXbhqz2eP1Y6Y80s59IJWpUqK0yNMjVyNMjTI0yNM07cN7rhc3KigAAAFlAFlAAFlAFg36vH11OM9XklqIWCpQCpRYKlApYKg
# vPXQvPeUiliiTQiiAKIolUWVEozNZXMsjXPVDOgCamD0PMPQ849Dzj0POPQ849LzD0vMPS8w7TOiZmiRS2aLVoCTUJNDLSMtKy0MtCTQy0M6C8
# /T50tlUoiwEKgssAgABASwn0PL6dTlySAUCVAAASAAIsAACAAACSwqUAAAAAyIAAqWuvq8PfeOWPX5Jc1calAAACpQAKAAvXjoY7+ctiKKAAAU
# AFgoAAKABYPX5tdtTxjNAqUAWCgWCoKBZkd5mxBVAAQAAAKBUAEGdRc51IzvAavM2BLAAAAlBCpQAC51g1mwVS1S2WllIsAAAAACiKIsNb5dbP
# PpJaABKIsAAiKAIBm4L247NChCwAAgQAELAAAEAAABkzZZazU0yNMjTI0yNSFlhKAAC6xa9nnnp3z8k3nHSCAAAFgqUAACgOkz1PPSKloAABZQ
# AACgAAWCgd+CriWAFABYKAABZRM96YBYKgqUSiUBAAoBFlAIsMzWVzNSLlszcbIQsAAAAAAUlDOs0hYamqalqlIoSiKIsAABSKIogFg7eXvlMs
# 6VLAAIAAQAAJyqNCusx0qLAIASwAEKgsAACLAAACYslBAUAAAAAsQAAFWE16fLvU7cOvJIM6AAAAAAoAoBvA6cfRxIIooABYKlAAAAKgqUAuNc
# yOtOLuOD0Dz3uOD0DzvTTyvVTyPWTydO2FXnaoKgqUAAAWCoKgqUAqEsBLFznUjNQsZNEKgqCoKgqCoKg1jWY1JRVq1S2WgCglBCwACCpQAAgA
# vbhEznp2PG9Y8j1jyPWPI9Y8j1yXyvUPK9UPM9I8ut5AG8U2KCEAAQAAAASiAAAS8xYlAAAKIoiiKSAABUBZS2VAoSKlAAAAAKAAKA1vl1OF3g
# WWAoAACgAAAAAVDMm43rla6uSut5Dq5Ds5Ds41OziOziO3Ty7rlj2+HN7MbApYKlAAAAAAFgqUASjOd5M51iG0DKKgqCoKgqC3I0yNM7rnqJda
# mrGpaoAFlAIACLAAAAAADPN0j1XXl3nvOCXu4DvOCO7gO84js4js4jtOULy685SUA3efQAQAEogABCwAAAAM5WVAAAWCoTTNKgqCABUsALZQEA
# AFAAAAAAAKlAFiu3n6jmlipQKAAqUAAAAFHPWC6AUAWUAAqCgAWD0+fXfU8HXlrN3ZQAWosKgsACoLAqUAAAS5Mx1jPPWRLIAAAAALAoWK3z7Y
# GsdC2WgLAAAASwASgAAABjfGH0PP6NTjzJUAIAEAAAAFg5auSgayOgpCAIABAAAAAAY1iFRQEoAAAqVAAIFEAFlKEAAAWCpQAAAABYLAqCgdeW
# qw68SiKgooBYKAAAAZJZqApZQABYKgoFgqCoL24arfl+h4U6Xl1lCgFgAAAAAqCoKACZuI3vfGzMslkqIoiiKIoiiKJQWWtduHavP06cY6WKoA
# ACCoAAACUAAEMZeyO3m6cNRCUIEAAAACUAAvLoMJQC757ACAQsAAAAgqCpCRZYAAAAACpUAAhFAAqDQQAAACpQAAAAAAABYKDpy1iqIAWCigAK
# gqCpSZItKAAWCgAAAqCgAWDrvh6dTwdXPN7AACgAAgKAAAoEuSdeXpTnz1lcrIk1CKIoiiKIoAFJVGpT0+PvrU8++XTNoqwAAAIBQEKgqUAct8
# o6fQ5Y1MZSUASAAAIAAAUAWDE6cjQBDolIBLAAAQAAAYslAABAUAABZUAAyFAAsoXOgEAAAAqCgAAAAAAAUqRqM3SstDLVMNjDdMNjDYw2M53z
# JqWWiwAABYKgWCgAAAoHTnT0eH28rOe+HaUUihKAAAAoAICmLY7Z3y1JKlkqJNQiiKI0M2iKIoiiKFKvo8205z1eNeiWAAAAAAAAABgz14/Rsv
# l1ikJRIAAELAAAAAWUINc9U53NAFnU4O44Ow4uw4uo5OsOboObojm6Dld4UAQoAAAAKEAAyFAFAJUNJUAAAAAAAoAAAABRm5G800yrTI2wNsU1
# cDbA2wNsDv5utOSWKgooAAAAAACgAWUA16PL2s8uu/ll7JQBYKgoAoASKgsuSenl0sxkUBKIqIAqoqIqgEoiiUAFg78b2s8msazaogKAgoAAAC
# UnLUPR215tSRM2wABCwAAACUAAAAWCY6cyiOnW8dTTml2xDoxDbA2wNMjTMNsDXPcjJFqUAABAVRAAAIhbAUAEoXNKEAAAAAAAqUAAAVKiWKAA
# ABYKAKAAduOjM7cC2IqWgAAAAAFgqUAAWC2D0+TtuzydeO5dsU0yNMjTI1cDbA2wNsC5vU6crmwFIgBQihKIoIKKAAAAAbxTXD1+VNXCXTI0yN
# MjTI2wNsDbA3M5J6/P7LOfJFCBCwAAAAEsAAAFgqABAz34+kzysEAAAAACLIAAzN4VQAAAFQAAADIUCpUAASxdJUAAAAAAWBQAAAuLBQoAAAAF
# gqUCgAOmHU89lhZaAAAAAAAqUAAAAvfhCY7ek8D6Fs+e+gPnX6A+e+gPnvoU+c+iPnPoj5z6I8HoeVe0lhYLAAAAAAAqCgCgBCiANXiMPoWz5z
# 6A+e+gPnvoU+c+iPnPoj5z6I+c+iPnPoYM54aWkiwAAACUAASwAAAAAQEaOud8aQgAAAAASLAAASjIUAABRAAAAMhQFgoQACazVoQAAAAABYKg
# qUGQUAWUAAAAAAAoCC7wrfL0cAIpKoAAAAAAAKAABGzWUKgqCoNM0qKqIqC3KvR5unRPJ05bl0QqCgSgAgqACoKAAAABLgnp497MYFqCyWAKyr
# TI0yNSItyN8uvI0lAAABCwAAAAAAACBLB357M4AAAAAAASLAAAAk1lQABQEAAAAyFAAWUBAEsW2UBAAAAAAAFlJBVEAWCgAAAAAAAAA3rn1rhb
# mKCpQKAAAAAAqCgS5L0kCCoKgqUAAAWCoL24apx9njjozoAAAAAAAAWUAAAEJl1OvPXKwJQAAAAACCoNa57OWkNAAEKgsAAAAAAAQAh1N8tcwA
# AAIACgggAAAASjIUBZUAAAAAyFAAAoQACVFqC3I0yNMjTI0yNMjTI3EBQEAAWCgAAAAAAAAaza68OuTFlgACpQKAAAAAWBc9BmwAAAAWCoKAAA
# DrMd7PHuSXYAACCoKlAAFgqCoLAZuC+rmsmSUAAAQqCwLAAAWDpx2Jc0oAIsAAABAAAABCL3znTMIACAApLIsAAAAAAAQTUIFUQAAAADIUAABY
# KhKAFAAAAAAAABFAAAAACgAAAAAAAAvXjuubpzKIAAWCigAAAEsNW5AAAAAAAAAKgqUbwOvm9XAlxsqCoKgAAAWCpQAAkJc+g1x1iqiKgqCoAA
# AAAAAG8UxrXM0AAAAAgAAAASyGseinHWQAIEBSAAAAAAASiAAAixVlQAAAADIUAAAAChAAUAAAAAAAChAAAAAFlCUAAAAAAAWDpyspYigAAWCp
# QAKEG8bIgqCoKgqCoKgoAAAAANdOPWvPrfKNgAAAAAAAoBBm5N9XOoIAAAAAAAEAAAAN4ujFxoqCoAAAAEIAqADWuO6AAQhYLAAAAAAAJRLAAA
# BJVWCpUAAAAysUAAAABZQEAAABQAAALneRc6AQAAAAAABYKlAAAABAABQAAAWCoKBm01mygAAAAAAAFgqCgAAWDv5ew5a57KAAAAAAAAZJ15ek
# xiwELAWCoKgqCpQQsAAAABrITfM0lDYw0MtDDYw2MNwy0MtDOenOKCgqAAAAAAAAAQAAAAS5VUKBYSoKQqCwVAAAAAAAqUBAAAAUAAC3Okxbld
# JUAAAAAAAAAqUAAAZsVcjTI1cDbA2wNsDbA2wOkxodMrAAAAAAAAAAAFgqCoKgvXjs5ztwOjml6OZOjmXo5jpMDd5jo5jo5k3mbOk3y0SyAAAA
# AAAAAAACCoLAqaMd+eyzmOjmOjmOjmOjmNsDbmOjmN4QCFlLAAAAAAAEKgAAAAECVYCoKgqCoKgqCpSAAAAWUBAAUAAAAAABYTWbTNzVoQAAAA
# AAAABYKBLCBdWLKAACoKlAALGjlWY2gsolgqCgCgAAAAAAAABDTPUIrUAAgoBC3I0gvLojmzoAAAAAAAAAAIAgAABGzpz1igAABCogAABKIACp
# QAAAQqCoAAAAAAGbFssFQqUAoQAADIUAAACgAABAAUAAAAAEazSTeFtlQAAAAAAAAABYEFWVAAAAFlAAAFg6ceuazcblBAFgqCoKlAAAAAAoAB
# m2Ny4oAAAAAAAC9OWjOe3E0lAAAAAAACCwgAAAAQdsqyAAAIgAAAAAIsAFgoAAIAAAAAAAAQllWWUgAKAAAACAAAAWCgAAAABAAUAAAAE1FMWV
# alAQAAAAAAAAQBaEAAAAAWCoKgoHTnqubpyjYAAAAAAAAAFgoApLkdcaJAAAAAAAAAA3ls42WKiggAAAAAAAAAAQXPamLkqIWAAAAAAAABKMhQ
# S2BYAAAAAAAAAJLFsUQAAKlAAAAIAAABYKAAAAAAEABQAAAFlRneVWCpUAAAAAAAAhFtlQAAAAAAAAABYOnPVrnrGpaEAAAAAAAAAAqBGzWLKA
# AAAAIFgWCoKlGsi468ipYAAAAAAAAAAAS5N7YqCAAAAAAAAAAAJLABYWhAAAAAAAAEuVVBYAAAFgoAQACBQAAAKgoAAAAAAQAAFAAAqaTFRagt
# yLcjUg1INMjTI0yNQCaCEoAAAAAAAAAAHTnaZ68Y2lAAAAAAAAAAEsHSSiIAAAAAAAAAAA1cbrlbIoAAAAAAAAAEsG8dazkAgAAAAQqCoKgAAA
# AgUBYKyNMjTI0yNMjTI0yNMixRAAAAAAoAAQCBQAAAAAKgoAAAAAAAAAAAAQFAAAAAAAEKBYKlQgqUAAAAAAAAA0m646iXSEqUAAAAAAAEFz0G
# SggAAAAAAAAAABYN8ukrNzYoAAAACCgELLBKNzWKCAACUILAAAAAAAAASwBQAAAAAAAABAAAAABZQAAACAAAAAAAAWCpQAAAAAAAEBRACoKEBQ
# AAAAJQBAUAAAEFAAAAAAAFg1z64CUAqCoKgpCoKgqURDVuaCAAAAAAAAAAABCgbxaxd840gWAACoAFgAAnXlTUgsAAAAAAAAAAAAAACABQAAAA
# AAAIAAAAABQAAAAgAAAAAAAAAKgoAAAAAAARLFAAAWCoKgqCoLAoAAQAAAAFAWCoSoKgoAALc0xblaAAAAgqUJQgu8aRAsAAAAAABUKgWAAAAC
# oN4trBJalBCoKgoABCpQEqUAAAAAAAAAAAAAAEJYWoKgqCoKgqCoKgsAAAAAACgAAAAgAAAAAAAAAAAKgoAAAAEAAAAACoKgqUWCxUzZVAAABA
# AAAAAUCoSoWpUAQNazDo5q6OY6OY6OY6OY6OY6XkOrkN8+mIJQAAAAAAAAAAAAAACWbNucrq5Dq5Dq5Dq5Dq5Dq5Dq5DrnFMtZhYWhAAAAAAAA
# AAAAAJLFUKgqCwCCoKgqCoAAAAAAFgoAAAASBQAAAAAAAAAAAAKAABAAAAAAAAAUAFCQKEBQAAAAQAAAAAAFsEUAAAAAAAAALormJaEAAAAAAA
# AAAAAAQLoMgAAAAAAAAsCBVAEAAAAAAAAAAQUCAoAAAIAAAAAAAAAAACgABEFA//xAAsEAACAQQBAwQCAwADAQEAAAAAAQIDERJAExAhMQQUIF
# AiMDJgcAUjM0Ek/9oACAEBAAEFAvn42kVFtQjd1p5S2KUrPHmpSRTexBEf+unJ7dFleHLRT5Kcl19L6ZVY+xpnsaZ7KkeypHsqR7KkeypHsqR7
# KkeypHs6J7Sie0oHtaB7Wge0oD9LQSq9plGN5TlsPounppd5x1ZdfGy9tDVmteKJvCmLZpSbXrqd+id1qruUoZSqzyk9tOxSqEv/AM9ecbMpU3
# VqdoR9xM9xUPczPcTPcTPcTPcTPcTPcTPcTPcSPcSOeRzzOeZzTHUlIrQuvI/xT2X8L8tKa1oj2H2W2ifdC1oInLOS2oSxdPGSq03TnB2erBWU
# v+unJ7tKVm1zUqcs6cj0dLjp+on8Lly5cuXLly5f5OOE29p9F0o1OOdSFnpS6eW9l992LJxxerFFV4xFt0Werp8tFkHdacVd0YonK73qcyusZ0
# aSq1Kk8U2XLly5f9typHKO2+i6UnyUprRfWKtF7D3kNZRFpoj+Kbu1uJ2dKpY9VR4aqdnpwiVbRUt+MrOLUlQp8FGvPKVy/wA7l/1Irxs9xdIT
# cJVbWuX/AHvpFZN/cJlRd9OKK0u+9RlZ1afPQZTelBd1NUY8yk/oPQQydaeMdWSyi+z2n0XTJ20rYxew+630L8kxaMUXwgLfo1GeupKM/DTuv3
# 2IRu61TkmyEslvRi5SjBUqdWectVFeH2NOI9lDVnvoqq+lT7urPOX0FOWMlFVYTi0/GgnZ1aijQGQli970FLGPqJ2Wpbr5JRxltPotLy2sR7KP
# K30XtBK5gYGBgYGBgYHGYGBgcZxnGcYqOTI/Q022V5L1HqvZHsj2J7E9keyPZHsj2R7I9keyPYnsT2J7E9kV6Do9ZFKV1uUKTrVZNRjKWT2Ksc
# o7T6UqLqLgOA4ThOE4jiOI4jiOI4jiOI4zjOMpvGo9tEt9Im7tFy5cuXLly5cuXLly5cuRK8b9F336aK0+KjBEatlzHMcxzHMcxzHKcxzHMcxz
# HMcwqqvbmh4YxPFrvuejo8dH1Mu+1UjjLZmyKu5JU4uRkZGRkZGRkZFzIyMi5cuN9hPKD+5RL8Yi0U7EGicXGUd5dymic3Wq6UJXXrI5dZFKW3
# 6Ojy1as8U9uayjsPsj0kcI1HZaUJYykttEt1Ik7vTgyqs6ZF7sEeqlhFKy0oys4tMlF0qnTw4vJfrv+6jT4KVeeUtytGz15O7o03UnUkiTu9Om
# 8ovbQ1Z7SKnZasJWdanhNdntxV3FqEe8palNlePJST6SRSlZ7H/H0byrzxjutXTVnqyYihHio1JajE7N9x7SH3W0u3RasGNclMi9uET1U7y1b2
# ITs60OKp0ZTllHWhB1JxiqUKk85fotqorR7ar7v0tLkqVZ3b1qTGttMkrPYSJvYhJnqIWe1BDlxU4rXgyUeWlHo+5CWMtb/j6WMPUz7fQSWMtO
# bEYcNKo++q+l8ovaR5Wui+MRa8XZxWcWrOL2acLutPlqbEJM9TC0ukilLt0inJ+0rntK57Sue0rntK57Sue0rntK57Sue0rntK57Sue0rntK57
# Sue0rntK5OnKlL3aG8nuW6yngSqKa0n2PJ6On3qS2acsZSW2iWukSd3swZ6hZITvrwRWlx0o7MXZq04+H0X4tO/T0dPGEayS56Zz0znpnPTOeB
# zwOamc1M56Z7ime4pnPTOemc9M56Zz0yrT5oQdhMvv1JZS05shFylNKEZu7130i8oPbWsiXaO0uxBoqQcJxdnqru4JEpOrU2oO69THKK6NFNlC
# ny1HIbu/l263Lly/wpTyXrqdpJ3XytsVpWUT/7oydkj0kOOFV2W1GWMpLbRLutRDd3twZVjyUiL1YI9TLFLstpOzhJEounU6eD00OOjUelB4yx
# U42dOout9puybyl4WlJ3dCk6tSrJEnd7dN3T20NWekie9CVnWp4TXbUirtPjivye5BlWPJTj09HR5as5alGV162nlCLuluV5kUS0pvsijDhoVX
# uM8N909pD7rS8b8GY8tMi9OET1M8prehOxUjhNdynBUac5XZf9nY7fGLs4tNVqfBW25yxj5ZLzo+X6SjyVK02296kxraQ+y0Uib+ghI9THuLRg
# iUuKlBb8WNZx/wCPpE3ZalyhPv6mny0oMWpf5VpZSjpzYkYcNKq7vdfS+UXsofd6CH2X0EXZw/NSi4uLLly5kZGRkZGRkZGRkZGRkUVmVZ8tX6
# ClF1J9oqUsn+2xYt8blynUuvV0+Orfrf5WLfvrTxiukvHwuZGRmZmZmZmZmZmZl09FTsVZ2X0FOWMp9thDIxucZxnGcZxnGcZxnGcZxnGcZxnG
# cZxlWD+ig+3qbSWiqjUE0hfQeip8dOo9ik8ZTpctOPZrYqSzku3SWlCnkVbUyo7vffRyutlOxkzNmbM2ZszZmzNmbM2ZszZmzNmbM2KbP5xnGz
# +ghG7qSzlCtO3LM5ZnLM5ZnNM5pnNM55nPM5pnNM55nPM9xUPcVD3FQX/6Izi06b773p6XNVm187ly/wC+/SjPKPrqfdO6/Zb9VefaPR/G4pMj
# UkKtMVeZzzOeZzzOeZzzOeoc9Q56h7iZzOU5RyhND32RV3L8DJmTMmZMyZkzJmTMmZMyZky7/XLTRTZWjdb8So8IaVKV162GcSLut2hT4aNR9b
# l9aDxdlKMoulUXW2lJ2TeUuktNMoTK0Em1vPpRWKk9fwtSLIu8asMXvRJSc5aUXZ0pRK9J0qkHZ7noqWdSctO5cv0uXLl+lCR62lnTj3S1K8ru
# PRv9S/XCVj/0hND3WU45ym0PWQ3rU5WdSN4vs9xFZ2WpSkeohzUGU3dbSV3GmqUJu7212cJXVenwVtOpLGPl9H3eoijIrRuSVtyXSCwpyesh9l
# rRZTd1WhZ7aF+C86qKNTF+ro8VRPF7Xoadio7LdoTs/UU+alBi+F/3Vp5SXST14sg841Ij3KMMpTlfYb2ISJLOMlbbiirK71qUrNw56LKT2aUH
# VqPsm7v9Ny+pSnkvW0+OomOvA9xA54HPA54HPA54HPA54HPA54HPA54HPTOaBzQKlZYx26UrOrHKM1tS6WwjJ672UykyvHaQ3hBbFKbPXU+/hp
# 3Wv6RKnSnL9t9OnPGUoxqwk3ExMTExMTExMTExMTExMTExMRdJPZiylPtWhi3tUESf2UGfzjUjZ7EVcnLOWxCWLp2qRqRcZU3Z7FCXf9VtWpKy
# Hpvtt052cllCa2GRi5OVkN3etLbRTkVo3XjXRUeMdqlK69ZDkpsi8lr+CEso70nd6ku72kUZFaKGtZ9KKwhJ6/hbkWQd41YYvWiN5Pai7OjNX9
# TSdGrF2fW1zFmLMWYsxkYsxZizFmMi0i0i0jFmLMZDTF0ZSljLcuVZD1Jdt2DP/SM1rMpQzlOWw96nKznHKL7PUSKz3aUitDn9OyD7dPTVJUjn
# kc7OdnOz3DPcM52c7OeRzs9wz3DPcM9wznkc8jmkVsVV60pZR25Oyk+j033e4ijIrK5JakukVx05vXfjeiykytDUR/CO9RqtP1lJU6i7Mgu9y5
# f98amHxhLGS26sh9HpR81Y4vdiyDyjUhZ6lCGUpy+4gxrOMlZ6UVcqyylvU5WdlWpMgJWWjPx8GUJbU3inqoxzjvUp2dVXjNaUhD/CMnf7hMpy
# K8b6SJPCH0EJnq1kUYj/AG3+M/PxTs4vJa9ypK7b1Iroj1EN6LKU+1WNm9BvpQjYk/uosTyjUVnoU2rzlnL6BOzT7W2WUZWevUlZPpFXlJd8WY
# sxZizFmLMWYsxZizFmLMWYsxZizF9UKzUouEt2nKzqyXG9GEXKU7D76tixYt2+hRljH+ZhEwiYRMInHE44nHE44nHE44nHA44HHA4oHFA4oEaE
# ZOScWn9DSiVIqFN6T7P505ZR+Ny/72Sd30j2WrE9RDOG43ZKTKUOSHFTOKmcVM4qZw0zhpHFTOKmcVM4qZxUzjgccDjgccDjgccCMsJvZQ1b6F
# Dd2i5cuXLly5cuZGRkZGRkZEHc9RHKInv043dGBWlk3pTV186UsZfK5f8AdVY+kVdvu9aLK1Pjqbcn3pxc5VLRTmZmRkZGRkZGRkZGRkZGRkN9
# IO8Xsvut9EnZaS7EGirTdOa3kUoFV4Rk9SSs/kyjO6027Jvr/GOvFlWPLS2pOyPTR46VR6aeLeymSVvoPL04Mqx5KRF7tKJT/CNSV29SSuvnGW
# Ml306krvpBd/L2Is9TTxnst3dCly1Ks7t99Smx7PlbqJ61OdivTwn43Iq7owuV5j1px+bKMv0XLl/lcuSlZdX2WymY8kH22JsRCPDQqPW8p7Mt
# xHha0HZ25KbI7dGIv+unNj1n3Xz8OMsl1uX/AGTd30h23Is9VG+v4PJ6SmpTqzbetB2bWytxIk7vXgz1Mei2YK7owu607t7FRfNmbRySOSRnI5
# JHJI5JHJM5JnJM5JnJM5JnJI5JHJI5JF7oSu3uXI2ZOLhLVmyKuSjxQm7vXX5RezLutlD7R2IuzjaSnFxcXs0ok/8ArpyY9lqz2Y/jHdiyvHOn
# qN2R6OGKqS2YvFvZQ1Z7CG7vZgz1Ec4C16cbuirFWd29qautiKu27veiytT456cnd0qbqTquKJO72YO6ez5WuifZbSdinIrU+Oa1kUolaWKb3J
# qz1/Ed+LJx5KelN2SPTx4aFR7fhvZRJbHncgyceSkR1UUm6cZSy3ZK6113+gnKyUpabd36Wjy1K08m9yA9nytVE3vU5HqIYy1EUoZS9RIpy3qi
# 1qtPAX0Enk9KbEKPDRqPvu3unsIlq+FvQdnbkg0R04q5/wCdOTH2ad1uPVp+VHkh4I71WXZaTdjyejppyqzb34Oza2UNW00Sd3vwkepjfou+ii
# jArTyZIhKz3GT00WKfderhfotG/wCtuyfd6U2RTbnanGbu99d4qOUnb9Fy5fpf9aH3WlLsvoE7OFmTg4SR3O53O53O5dl2XZdl2XZdl2XZ3IK5
# N4Rb6sg7rc9PTzlUjjLRiukezp4snB06i3KrIofS5kzNmbM2ZszZmzNmbM2ZszZmzNmb6ekjhGb7fQJ2a/GMnsQ88aMEYRMEYIwRgjBGCMEYIw
# iYRMImETCJhEwRU8/Qwfaq1JRoprgRwI4EcCPbntz257c9ue3Pbntz2x7c4EcKPxpk55fBkXZ7TH3bjxwqfk8UYoxRijFGKLIxRijFGKMUYoxR
# ijFGK+FJnqYclIW1J2S7s47pwZhI4pnBUPb1T21Y9tWPbVj21Y9tWPbVT29U9vVPb1T29U9vVPb1SUHB1aivJ3f0FOOUpPYRBEpd8jIyMjIyMj
# IyMjIyMjIyMjIqfkvoUN5ShUduQ5DkOQ5TlOVnKzlOU5TlOY5mcrHVZnc8P4MpvabseljiTl21V2KU7HqKXDVvtTd3FEUVPwVzIUxVDlOU5TmO
# U5TlOQ5DkOQ5TlKjcyDyi/obYRexFE3ZaSZJYvfRUdkvnf8AXcl3S+Php32YxdSpOw3d61KVnUjzUSOxOVlFCKf4qo9P+Mnvsook9hEfxUnpof
# 5RFveDy9Tw/gym9hlGGFOezTmesp4z2G8mkU43dWQ9NlNj3ksm+w9iCKj1Uyas91FR63lL5Rd1rUYctScrvZhKzxVSDTi09aoyKIoX4Qm7vUkX
# yW4yksYy2Efxi9VHlC20fxitd/FkHZ6siMeKnN7dOd16yOaL31H2XlopRu607t60HjJq25COcpPYRTRUlfXRUW4kTeUthfFlN3Wp6aF5TluRdn
# BxKsHSqLUqPvFEUS/CEnryE8o7TIrCEtiKJfjF7CGrNbKJO0Vsv5ReL0/5NpQjLu9ynI9QuWiLSk7JCKSsVZXb2E8JNbVKN3J7CIInK72ES7xF
# sIbye14fwZTekz00cYz7b9Odj1FPiqaUndogrlV4pvZZB3Wx5P4xb2Iom7LaTJqz10Te4+6Xx8PkZyM5GcjORnIzkZyM5GcjORnIzkkckjkkcs
# iE8iEXVqTaG779N2co8tIdRnJI5JHLI5ZHJI5JHJI5JHJI5JHIzkZyM5GcjM2REQ/GM3fb8N7FJD2ER/FSe2i2URa3g87vh6qKdVU48uf0Kr2K
# 0lOdixbpYsWLFv0WEU4XdaY9yD+Kpza4qhxVDiqHFUOKocVQ4qhxVDimcczjmcczjmcczCZhIcWhLJvZgio91MqLWRN993ylr+Gu63pOy04o/h
# Tk77rP5LpShyTnIyRkjJGaM0ZmaMkZGRkZGRkZGRJ3IfinsI/jF7qF3QtS9kt967Kb327vSRSiVp3b3ovFvpGPHTm/q4InK73kVO/VRusDAwMD
# AwMDAwMDAwOM40caONGHZu7+gWxF3W5N6kUT/CMnvsXdUIXlOX1cUS/GL+gRJWaEXLmRkZGRkZGRkZGRkZGRkRZUjjL6B6i+EXZ7b1EUlYqSu3
# 9Ar5NYRk7v6qmTd39AiXdaUWWzj9D4dy5cuXLly5cuXLly5cuXH8WQd1tSfR+Lly5cuXLly5cuXLly5cuU+7qSsm/ofTxspv6nsdjsU7WmrP7W
# LKq+hR2Ox2Ox2Ox2OxZFkdjsdiyLRLRMYFSFkvinZ7Ldl0fm0S0S0S0T8Tsdjsdjsdjsdjsdjsdul/oYRc5SaG7v6uLJLKP2qdhdxqz+uuXZcj
# Yawl8GQey3djI9Lly/739DSWFOb+tRBlSNn9rFlRZLeWnEqLKC+Sd1rSfXy9Txv0oZznL6+LP5Rf20WTjjLc86sWTjhL4weu+/Ri7LUfjeS46c
# 39eiDKi+2iySyhuf/NRDWUV8ou61JPqu71n2e5Qj3m/sUL8lJfbRZVji9pK+umTXf4xdnpvt1keNfyttK7doqTu/sYsqK6+1iy2cdllrLX8i7f
# KD05PrHZktugsVN/ZogycbP5WMTExMTExMTExMTExMTEwMBx7bsWVlsMgtqQviuz0ZOy6Pu9ldzw9iEc5zaH3+0iySyi/ncuXLly5cuXLly5cu
# XLiGrPcXYQ1i9by3t+H8YysZozRmjNGaM0ZozRmjNGaM0ZozRmjNDd+jFtImrpbFOOFOb+1RBlSOuiSvHdiyoso6rIKy233S+NixYsWLFixYsW
# LFixYsWF08vbiSWEtalFSnOX26Z/KLWumTVnuxZOOMtRLKT3EPs9ZnhbaJLKC1l9zFlRX10eVuxY1lDTkJYx3fKWsu+9F2KkcZaj6L6B/C5cuX
# Lly5cuXL/qRB3JK2uia3lKxO2WlBXbe/LVe+i2UVpv7xMl+Udh9vsGeF9B4emvoEyqtNi6ree3TlYmrPWRJXW4+ty5cuXLly5cuXLly7Lsv2h9
# FLT8/RLufxbZdl2XZdl2XLly5cuXLly5f5Lce4hyutdElZ7T6cbOKRxSOKRxSOKRxSOGRwyOGRwSOCZwTPbzPbzPbzOCZKlKKzE7/Q3ErmLLMs
# yxYsWLFizLMsyzMWYsxZizx9FkNuo/bzPbzPbzPbzPbzPbzPbzPbzPbzPbzOCZwTOCZwTOCZwTOCZODh9C/0WLFixYsWLFvpUNXW4mXMjIyMjJ
# GSMkZIyRkjJGSMjJGSItE44yX2j+hb6UVjHKxmjNGaMkZIyRkjJGSMkZIyRkjIyRkh9/ktp/bpk1svUiyazgR+gXjSQ+z32U45ylIvpS/qyPO0
# tSMrFWOMt9K7eo1dC3ZdILCnJ7K2H9yieu9aLLZxIvdZa0XqImrPeoxylOWrL+roas9Za0WVlvQV23qotkhbculsIyet4+K1n92iXdfWIXcas1
# ufxT1kVVtvpQjYk9d/Jaj+9TH50ntRZVWURbVJWHrojZjWLWy2Qi5SkPvsP/BYsnHGS7bKWUnsoqrKItd9KSwhJ7L+S0n/AG2JJZwI7EFjF7UW
# TjhLXZShnKbvty+TZcv/AE7ExMTExMTExMTFmLMGYMwZgzBmDGrb0WVY2evBZSk9tMks4C1ZdEsISf0PGzjZxs42cbONnGzBmDMGYMwZgzAxMT
# Bjjb+gXLly5cuXLly5cuXLly/R+dxH8okdViWMXuRZVjZ61GN3KW6/hBXbZcuXLly5cuXLly5cuXL/AHr1ETV1uxZWV+i1Ka7t7qLZIWmxDWKf
# 0P8AFP8AsSZJWe4hElZrU8J7yKqvpvpRVlJ776U0N/016yH3juxZUWUS5cuXLmRkZGRkZGRkZGRkX6U1Yf0CGsWZGRkZGRkZFzIyMjIyMjIyGR
# jlKTH9Ba7Y/wCyJk1Z7sZWJKz0V3ba+hROzjpU7RhJ/Qw7J6z/AKejyt6BdF0XRdF0XRdF0XR2Ox2Loui6Louiok0L6BiWTvFF0XRdF0XRdF0X
# RdF0XRcuXRdF0NxZ4f0EVdt/2dE93y/1XLly5cuXLkWTjjLffSCxi/13Ll/jPuvoF+MX/aENWe3HstKJJZQFvwjlKTvppjVnvQV23/aUS7raXd
# vUiypGz3X0Sxi9R94re8J/2pMkrPYZ4Woi2SFu013b1USVnuQQ/wC1o8rYjroqrcfR9k9byttK7f8AbUTWx410Ias1t01YexLbj2T/ALd5147K
# JrKItlLJt7KPD2Iq7b/t6Javl7SZNYvZj+MXtS7rY8J/3BPVXZbSGsoi14LJt7aGrPWja7f+Cru9xMqLvqvp/GL3PK/xzxuo8oWrBDe9L+zv7S
# O+iavq+R9vovJhIwkYSMZGMjGRjIxkYyMZGLMWYsxZizFmL/ydDVnpw7J/QS6Lsrly5cuXLly5cuXLly5cuP8Aqb+yX0KJd1pRV239FFd2/wDB
# bGJiYmJiYmJiYmJiYmJiYmI49r/RZEY3OM4zjOM4zjOM4zjOM4zjOM4zjOM4zvEv9F4T+7sWLFixYsW+kf0Fy5cuXLly5cuXLly5cuJklZ/Qru
# y5cuXLly5cyMi5cuXLmRcl3X0MB/4ujyhfQLstJMkrPf8AL/xlEl9BFXb00eVvx7J/2p/YefoPC1EyS3krt/45Lejr+d5dk/7Y/sEPt9rLcih/
# 48+6247T7Pa8f29/YIattLu9p91sx/yHytldltIas9fy/wDIpbC3fK112T/zrxvS1krt/wCSPWX2vhf5K/tX/nflaa+ifb/Orj07/RPx/nSLly
# 5cuXLly5cuXLly5cuPv9Gi5cuXLly5cuXLly5dl2XZcv8A54/ov/n+m+foV/YP/8QAKBEAAgEDBAEFAAMBAQAAAAAAAAERAjBAEiExUFEDECJB
# YBMycCCw/9oACAEDAQE/Ac5XWLe4xXn7ySbm5ubm5ubivsX4FbO5y8Gcp+eyV9idpiUYDuLAX4Hi0sF/nX7bm5ubm5ubm4nnK82bm/XsWAvOU8
# xWn1HF/m4vF55j8doryuO88t7CuPqHd5vce9RBBBBBBBGErfL7ZW3fYhu2spsXbO2sGp23lcvOdSRrRrRrRrRrRrRrR/Iilzg8Oy8FsVzi6rbq
# +hZ0EEEEEEEGk/rVgogg0o0o0o0o0o0o0i3wOXeWDBpRpRpRpRpRWtLlFLnAftGLXTJRVOVw79Tv8W1cqUlD0vT1FXxcivK2xO9zgL2gggj/AI
# i96lP2UVSrzyalJQ/rK4utSRgRjsXwqF09ajcpc5VPjtfUplHp1TceW0U/FxlM59oIIIIIIII93eWSyr41SJ21mV0lDlZS2eUsuqmUem/p9QqY
# ftJJJJJJOEymrVdeSr9VG8kkkkkkkk+y6d4PqOdilRkK9xf5fZK/U4R6ane+8lXWxdkxb3qvk4EsCCCCCCCCCM1b79pxdrqhHp0x1St1eO1Yrb
# P7VC6qLXAu24t+pV9FFMLKby3u+4Vlso+TnBm2vGS3Alm1OCGaWaWaWaWaWaWaWaWLBg0PyaKvJoq8miryaKvJoq8miryaKvJ/GxKMFW3fbKG2
# bm5LJZLJZLJefy+15uq9W9T0iXTVMpUdoxXWLe5XVCPTp+3lO4xbue15v8O4/lULpqvAl18EEEez8YDEQQQQQQQR7V1QUUwumbKV99rGDFllPy
# qnBk3Nzc3N8F7uMiSSe2rf0UqMFYtTgpWWu0ZQp3wecapSUv8AQMWO9nOYvwnOQ0Uv6/PPKqX2J/uFs4/OPMqRS5/ccP8AcNSU5kkkkkolEonr
# ZJRKJRKJRKJRK/CL/I3+OXVL/YlceFJP+pK0/wArJJJJJJJOHJJJJJJJJP8A4D//xAAnEQACAQQCAQQCAwEAAAAAAAAAARECEjBAITFQEEFRYC
# AiMmFwoP/aAAgBAgEBPwHReV5V8HWRDzdo79IbLWWlpBCIpIpP1HnTgf0GrnkW574noL48O8bzoajEiZ0JFjqWg39BfKESSSSSSSSNnWhT8/TI
# 0VwKPcikikikhEIhEIhDUei3KlmpUnBwcHBwcHBx4lD40H8Yu9Cnc6xLxHaz9LI/n0p3HjZSvJoqWVD5yL8ZJJJJJJJJKVt9jyLxC5y9LM+fRF
# KktRaWkEEEFpaLQqxMp48O87+caO8yHx6dLFV8528aUj8sh8Yn8aHZQvfJ1mfI8S4WgsypZYyxljLGWMsZYyxlSjRfKwp6Ky1LgWSp+jwqke9J
# JJJJJJJcP9losllxcXMuLi4k7OtClQsqGoeTv8VUXElxJJTyoKloLkkn0nTocFajafIs1Kl52pQniqeRMq50OlsL9lGd40NRmXC0KuCSUSiUSi
# USiUSs1D9ipZkPYpcFa98vWXtCyJwTOg6vYesj+SHl62qXPA1GNZkypCyJ+IocFayL520yrlTjefs69EySSV8Er4JRJJK9aXmb2l+ygaxdj3KG
# VKHtNSLC/VcZW8jWelwVr3xLjdQ6pRBBBBBBBGlSVKML/Cl5G/SCCCCCCCCPRDUZ6a+ILWWstLS0ggggfh1ydaFKgqew3mfKzrhE+Rq+c9Kkqe
# N/hS9mpZaVI/JIfGZcIeheXl5eXl5eXF06HeXpeUfKy0IqeV7tS98dKH5RFSjJ0s73JxdnXlu1joRVVztJSLZZSvLoqXvhSKuFHos/94kNZ36y
# SSSSSSLkej0ST6SST+VKJRKLkXIuRci5FyLkPRkVVJdSXUlyLkSi5FyL0Nzodjx9rOkVpIhEItRai1EIhEIWisvS8Qsq4y1L3zU8KRva6yUobn
# G95Y0PKvg6xspUlb9tpZXwo8r1nfOT+KH4an5Hle9JJJJJJJJIvnQQ+CS4uJJJJJ9KKSuqdpZEir48rOjOFD/VRopEIhEIhEIhEI4zLhaUEEEE
# EEEEbqzvFQvcqc6HY9WlSVPbflEVuONFcLWpZUtvvafqvEJSPXXK3H9E6WwmVL321tPxKHs0/A1tvdWF+WQ+VO2h7skkkkkkk6DyLcpZUo2+/r
# va+8JwPbghkMhkMhkMhkPxsfBDIZDIZDIZDIf0CSSSR+M6JJJJJJJJ+id+LX057Szrkf1xbfS+oPbeRD0YIII84jrGtvr6l3tvEtFfQ4ILS0tL
# S0tLTrSggggtLS0tIJ+3L7Q/9xf++L/aOPx4OP8Aht//xAA7EAAABAMFBgUDBAEDBQEAAAAAAQIRMTJAEiFBUJEDM0JhcaEQUWCSsRMgcCIwYo
# HRgJDBY3KCouGy/9oACAEBAAY/AsitedUwulKFUeyxijr4NUOLXEqFYwfi2fwLWJXK+y0szIsGEyxMsTLEyxMsTLE20EyxMsTL7CbadhNtOwm2
# nYTbTsJtp2E207B7W07Ay8LSoJD41lhUquxhsSqGzRsDDVPNXxV8yBbcuKbrUtgUQ+FaSh/01fAZ/AkFiLpUkMBhoMBwjD7f/g/+DDQYDAYCJB
# jMP5eFnWut8RXKp3zZ/KNRfAohzrDQqRYNColUWeJV51zA9nxFekWcU/HhbOZfwLOtGZ6V98DuMN6ksYxOtYfVKZFyulOajlSDM698SBbZEFfI
# /hEwZ5pZ4kQ6B6TrUtX8yprR4BzrXDs5HEgacIpPlStiC2ZYRyE0HBQJHFFQbAqV/OvJRYC0UqoejHDlA6WyUE17CzxovT/jwaj+ocYJGOQ2zg
# j5HM6Zg1ez3UbY451Z0pLWJwyElFEhbTJtL+h0bC6UriyEkpiYJBQSHp7WY2jgWeWtaJnHLDIeQPYnxS8jDHEqFx+mbadiyL6x43JFnzqWy9iF
# ksM8PmIiJCYhMQmITEJiExCYhMQmITEJiExCYhMQmIMSkvkZJIwZkZER4/8AI3+z7jfbPuN9s+432z7jf7PuN/s+432z7jfbPuN9s+432z7jf7
# PuN/s+43+z7jf7PuN/s+432z7jfbPuCvJRHAy+xq0kF/Y8kpK4PU8yrTO4iLExvEjeJG8SJ0idInSJ0idInITkJ0ichOQnITEJiExeDZ5yo/qF
# jHrkLj+S/jwgICAgICAgICAgICAgICAh4HsjxvT1DHkDnMv4FkqvlVsUTBbIuGPM6PmVY1fzOksqlUDI4lkF8pXmDUdHzIFtixuV1+xqu+VN5g
# 1Zue2Poikccqx63kHpbWKY9MgLZFE71UppVIq4waVYfY9USMYq6jkVa9SSCxDJkTcVLZxKGc2daZ8A2GFce0VBPcwalUrC3xIj0+xvOp+qcEw6
# jmde1Ra4tp2INSuQcoHWdKt6izxJvKtbEFs0wT3OncXSxLpVklMTBJKVIevenvkK9QNR09nzzdvKocoi0Uqqy3xHckPTsLPEm9NX9U4ql6CyWa
# t4Fs+I71f4DVFrHGsapfSqPZnjDqL6oiF0pXFUuUSFtMqvsbxYicxulDdKG6UN0obpQ3ShulDdKG6UN0obpQ3ShulDdKG6UN0obpQL6iDJxci7
# C8PkMKU9qqVHcw+J1N8DiGrHzP6hdFVLizxL+Ks9meMOoY/u+pidyQyjvE3YR7CPYR7CbsJhMJhN2E3YTdhMJhN2E3YRBpxinqGzYiKJgtkmCc
# fM6vmVY1PzOsY5VRBpPCodUqbzBqOsLal0V9jAk6iFxQouZAtqmCo9cgamPbHE7kf5DVbjkdY9M9YwfiR8VBbIuqq1jlVcYNJ/ZfMu8+gajNJw
# UDSquemJBf2fkLrkJJirbOmYtXOLoHeVMe0PCHUWjrWD8SPjxdUiLzBmcfsiI/v2R9QopuVXWab+e07EGrrRY1nSjfILHEV6aViiCQmVPevIxd
# KcBcC2eMVdRGkccjDYYdKx6b9Uib1A1HX2TgeXtgWQPiQtpgr5pLXEq5OQ2ccAe1Vwy9aey4umTeQar5FSN4FssYr65C+OPo89mcFdjBkcSoi8
# sQ/Dh0yEkpiYsplTUEeItJlVeVVzP9yAgICH3ntlQRLzMczyHljVMIkIkIpEUiZIikRSJkiZImSJkiZImSJkiZImSJkiZIf4yNK+I7jolIKCsi
# +ocy7i6BqjkYNGnUWTqXpTYFsygnvkZF5ZZ1+ciYcsAzwEwiIiYTCbsJuwm7CbsJuwm7CbsJuwm7CbsJuxA9ntIqlPyMGRxINXknCJ9A+GFVzI
# FtSxm61Fn9qIiIiYTdhN2EewmLQTdhN2E3YTdhaPAf8AbDpkTELKcKhqS+Bh8cchbFXxR8yBbcui+uQNxKvUGqnBpVKoGhWFM9RzKAulOGQ28Y
# Jy6/8AvIHOBAzOkMlSLJjCkKiVdbVKjuHONZZH1CmTHpTWalixvLICIXQKGXOOnxX/AE9aVhaKfZR5prWKJgtmWEetc+Abhw6Uj1TecOotecet
# f/JXxmDYlAXQrTWeEKclELpFXprD2x9E17eYYpk3kGo+RVd+Nx9Q2NbfKUQ+Y9YVjBigVOwPZ8Sb0f48GqSQWIIkyphkD4i2mVXyHERER+yIiI
# iIiIiIiIiI/SdZfA4h8SuOtsYxOoaqYWqt8ThUkZRIFtUy7Tsfg9RaNrS+xBiyDkD2Z4w6g045dfhHoGq7Z4Q65p1jVvhVHslQX2MGlUSDVLek
# HF2F5dKoiKJiyUE5pyMPiUamzicatgW3KJXL/wA1b+kGxiQcoHU28TuLNunxUOcCDnWX3oUTGDQf9H5/bAxA9BA9BA9BA9BA9BKeggeggeggeg
# lPQSnoJT0ED0ED0Ep6CU9BA9Ps5HXNmfX5qG1HIoZs4+KewWEa1h/PZd0/axKMiMbw/cJ//YbzuN53G87jedxvO43ncbzuN53G87ifuJ+4n7je
# dxvO4mcKsSvd9nMvSDeYta9af+So5w2OAcoHS2tK8lkHTIu9Pi9EeQtSuLoHX39DDHSucqYh856/NIwYoFDID2WMUdfBqmzmNnSv5YjmXxSkjX
# Om8xa1o+ash5kPqlxR6h6p8x+oWMetf07kOVH9Q8IZ5f0OivgHyI0nA6tqy7xgICH7EBAQEPtNJwUDScSrnH/5oiSUTDFKnPOovMRMRPQRPQTH
# oJj0Ex6CJ6CY9BMegmPQTHoJj0EytBMrQTK0Ex6BiWegY4lkbYnmr+dPbxTcdeZqUZIITq9onV7ROr2idXtE6vaN4r2idXtE6vaJ1aCdWgmVoJ
# laCZWgmVoJj0Ex6CY9BdD0gW0KMFZE5wKs5UzVfLENhhWkkomC2aZUd6NsSqumQtSXynEGk8hsa1reVRzOpbiTeVae1OZVyf8AIajcXQPOXpWD
# 8SPjILelc9I3i+BVTkLSZVQqyTqYuuSVxFS2dKpq9qYjF0p3lXEQYoFX2aazVmjzh1qW8G49pefIg1NaqnrXqLGMU1z4nkL0lqt+oWM3WptKkR
# eYNRxOnY4HVNW8qjmPqFBUetZyqn/YuMTGJjExiYxMYmMTGJjExiYxMYmMTGJjExiY/sbAq1lSmDSeFM3gWyKJXq61PMqp6vrVGhUFAyOJVbYn
# HNXxOvtYpj0pz258Nyeo5n6oYfUxK5VVaOBelXDYYUpITEwSUSIuKrbyqulS1ZyOINOlTYLDNWyGzxFeVL9Tj2lyegarcPgeYvWsP5Ih0qLZ/w
# Bel5jpGO5JXqPkDVhgVbZqmp2riMoh0yqvKnugQauemI4kZZo3gSONV6v8Bq56p6V8gPZ+3rTc1Zsez85eoavalPaKkR3MGo4nX8vSH1Cxm60l
# /wDecFtixuV1zNiiYLZJ4Y8zyHmQYXJJhKWggQgQgQgQgQgQgQgQgQgQgX7j0fXIrJyqBpOJUbYnHIjUqVMaY0qlVcYNColWtSntjjBGR8zqoi
# J6CJ6CJ6DHQY6DHQY6DHQY6CJ6CJ6CJ6CJ6DHQY6DHQY6ZIgzm/wCBBftEF+0QX7RBftEF+0S7T2iXae0S7T2iXae0S7T2iXae0S7T2iXae0S7
# T2iXae0Q2ntEF+0P+r+yyJiBbMsI9f24ftsLfEiPSvM/IQMSmJFaDdr0G6X7RuV+0bnae0bnae0bnae0blftG6X7Rul+0bpeg3S9Bul6DdL0G6
# XoP1JNPUESZEl+nIr4FEPU3/tR/ZfXI3ETEwmEwmEwm7iY9RMeom7ibuJu4m7iY9RMeomPUTBjgYb7mqz2p4XJ61DxLEg3DFPSus+Xz4REwm7i
# buJu4n7ifuJz1E56ic9ROeonPUTmJj1Ex6iY9Q5hsShkVnHGqbNbOtI+QElOIIkyphUMLPEm9Nba/oqRyDlA8gtHhVPS8yyBzwD1bVNriXDoGq
# SMokLaZV9jq2F0MKWyf9V7ELJQKqalcXQOvslhml8sTD1Z7I+KHIwZHGnbx5q+KZxa1rrWJwzGzXPpmtniVeqtLbF0XU3wxqGOB1rDlmVrWt5V
# DVltUqfkPjWsqRVxg0HhSt4t/Z1PMqzmdV1qWOBhqvmdU9UxAtmWEetcwtcWz7lT2jwzVzgQepvq3xKrfIWo/qH0TkBKIXSnemmslhV2dKqzrV
# NmtnXM7wSSF0pQyE0cRXp8LqO1jAqxw/nUWtKp61sSqHzVV154hshxcgakkz0bC6GFbZ8/tuSYkMSGJDEhiRQkUJFCRQkMSGJTEpiUxKYlMSmL
# yMMGKBVTVzlA6dvL1XzV8V76+LYYjyIR+yP2REfsiI+L4nnNn0c2Z3wKOQcvFuJV5+jbWvjETCYTCYTCYTCYTCYTCYhMQnITkJyFx+l2pbOuQ9
# BaOVIc45Z1yHkGo3F0DhkL+ibXlDrkVwsFhHr6P6UlnT1SxBigWRfUP/x9S2ixyOAgICAgICAgICAgICAgIdxKeotJhksO4h3EBAQEBAQEBAQE
# BAQEBDIySWIYpUwy7pm9k4GGPMmOBgyP7mrHo3yF+JXwG9TWvKOZvin0rfKUQ/qfkGzJxywyDrmlnE7zzJ835pzNsSh6TtnBPyOfqlxdA4Zm5Y
# 1zZmxAkFAs0fXN7OlW1Q1a9S9XbxgnPYiIiIiIiIiIiIiIiIiIiIiIevt+cal6p81aqJIugUM26ZuxwMMdOwbyyG/L7WtT/JXwG9H9K+1iUad/
# OFZ0zXkYanvlK8w+cNU8q9vVHNPpF6hq9sShS8zrmzVxdA4ekGqXr/00bnAsgfNbOnpF/RTZA1K+Q2ix9UvmFrInzVjgYY/wNhqMNRhqMNRhqM
# NRhqMNRhqOHUcOo4dRw+4cPuHD7hw+4cPuDn8iHpgrrxw+4cPuHD7hw+4cPuHD7hw+4cPuHD7hw+4cOo4fcOHUcPuHDqOHUcOov/At8DiG9MW8
# TuL8Mc0/GRPmrDlh6qbLnF0DhmvTIeavVj5dZxwyDmdNyr3OUoh/w3bLGuc4FT2dK8ka+rumXWTgYY62zrUWixrfqeUOv4etYlGstaVLHAwx1Z
# EUTDFAvw9yDVTEGKBVVrEo1drFUPxBzTVPidXyDVLYYh8PW2AwGAwGAwGAwGAwGAwr3F0DqOVbzTUticciwHDqMNRhqMNRhqMNRhqMBgMBgMBg
# MBgMPSLV9nSobE41rhygdO5wSHyHkQf1E9fb840znAq+zpT2fKORNr+AmOBhjpbOQW9aW3pkVry9S8yr3xKNJa0yFjgYY6NiDFAsibAvU3LMro
# ZE+JUb4nkT+p2r3EidBInQSJ0EidBInQSJ0EidBInQSI0EiNBIjQSJ0EidBIjQbtGgkRoJEaC0RN55GxBiSk+pCRGgkRoJEaCRGgkRoJEaCRGg
# kRoJEaCRGgkRoJEaCRGgkRoJEaCRGgaykugb8FPmHINkT4nRvkPM/wANcyyHlmnIvVb+WYOHKB5A2Jxpele34cs6V7nAs0tfgZ6i1rXWfKnasY
# cvVz+dQ1QxwMNWWtKl6t/P1e1O9U+JVbC6BfiR/RfM6vpUt+IuZVPLNL/xI5QOobX8sNTv5fjp8gta0zeVe32QMQMQMQMQMQMQMQMQMQMQMQEB
# AQEBD8T8g1Ja0yF/Dr+OelJyyK/8DREREREREREREhEhEhEhEhEhEhEhEhHJIsJiExCYhMQmITEJiExCYhMQmITEJiExCYhMQmIGWRt+TX8sif
# 8AHfX/AESP+G2yBqZ/x29c9O35Zaof8rvmrfm9/wDUk/5wbNn/AB29M/8AoQf/AG4Y/wCxf//EACwQAAIBAQcDBAMBAQEBAAAAAAABESEQMUBB
# UWFxIIGRMFDw8aHR4bHBYHD/2gAIAQEAAT8h6kTCfFixDeSSEuvc2LEQCiI9KEpeIoeTK7jMaaO4xOqhq8/S9Tt6KtzBX7HatSNQhv0J3J3J9L
# t0rkzb4KBuq7/yR8/kJkTnW1pmGNQ+Yj7RD/sI+6R8dHxUfMR81D+tHYoD6YE5oTs0aC6IruC5CHak93khrlr3rR6S5jHysSndFGfAy/amFGpA
# i+g6PzG8OkPL2xScMi5YHMa9DYfMKN/OwtJxCFisBSlRSqy/sdGVsgjorbJJNnY7egjaEQVys2xLXEolNyGl+vQp6UkhNOqIWjuo/AinVV05fo
# mIHo9Rl8Lm0Q0iqICHPSjg3g3fEet4D1PEeqvBurwcHg3l4N5B6qD1Qf1jc8Dc8B/yBbCjYpe8OqEQSuV7Vjy8SkMuYq2KB8JRkLnXBug6suFh
# T7DYdDcjsWKfITf0WGwqUsQ3kVPAe/OuWiEl4lEC/JINww3poxUkPhlNdz6K+uhWVCLxo4rwK0MuhJPTQoUtkkm2PT8leXMX+wHNFcbe4XMpJo
# bDK8iRsnY4Hd6IBL6FDVwvKTQxSyrHysrKTSdUTT1V6eq1GocYJshCTUkMrlch1w6/CGlIsZA5yd5Iq9ZMVMLApIhL302JCxFSoiVTyuIi4+XI
# xYL/AL16Xc7+jwRK1Zyx14mPojo8HgoU1KFCllCh2O3R3tramMaSUCLkMqtMyFvb2tBTXsiRtu9jECBAgSSNkkkvpkncUHeIimuQ78WsOxpVlU
# PM3aDKYFoRexlSzucDYdDwvyxz5FD3FxhSSxkxVLm7GMqN3i1xXYQ5CXomKko1lmiEKvyMhW/PRHTQlE9UW3CKokDS81Y0u2hQp009OCCCOvi8
# xgek9HkycL1w89CmAYYknknknk8k82k+hFij7v8AXSsM1KsaHZfMsR5Gn9CViSSSSSSSSSSSSSSsRxqqx5c4SHoQ9CHoQxUqxix0TSXoSuAF2D
# bRK9lB+4diULGIfU0dwx96feWYXMpzyu64IIII6Itkk7kNqZagv9KRCN5voizsdjt6E4GXTpbicuyhjGdzv0UKDtjoqSSJwIc1zEbmvVixK5jH
# lWODNFzGCZQZlcMSSI8X2BoYiY2f5CQ63jYGRyOVsP3sXPGoRkA4W1xSfkRWZXogmrYI6Ox2tggggqZGLG703K9RQdhIZUc8/VggjrqSyX0xYr
# CXwkMHoVerzZI5LkMdskk+jTogixQhleIQsS1AnDwbJm/2DHzd7xLZnAZewPQgJc6chKuBpXgnmVFXaJsJS8ei/JleMd1M+yMaGnQ0JQiSupXU
# 7nc7ldSupL1Jep3O5XUl6kvUncYhMhXTUKx4BKELKOJd9lSuBp0Ox2TbMIr/AEsbCVb3A2Nj56PJ5PNkEMgi2lsWIsolSa8BC6YI9GPSWUMbLB
# JNVRsUiii89WNLxSKGau9gvjquxIjXF1ISSP2kfvI/efHPTbX8cnzyfPI6QmuQ5Q1cXPQhDpROug+AqU1TkQ/h+h8y/Q+JfofEh8iHyL9D5l+h
# 8y/Q+ZfofMv0IfwEf5D4F0AJn836DN3VdzdqQyor16kk+r2toCTe0WbKGVATYc172PkfI+TuQtSmtkk9VSpLJZLO53KalBFcSBCF6MEetQpJYi
# 7g5CP82Q/iyP2nzSfFJ8iZ8iZH+DPlTPlk+ST5ZPhk+GT55Pnkh/Ji1Nul0/8ARWpa/FsJWVc8fM0kXfcohoeBAAB9LyIthtFzGhPqUweYXBQF
# d+P7IFOpGps2iGvycvk5PJ8ZOXyQ1+Tk8nN5OTz1P1ENImoIt1al5f2KWKhrKxJQ5L0KCaudnkpv6Ukk+jTopXFd7ZEIeSV41yMZJQpodjt0Ru
# Rud7JJtggjoTlF0XrhCtWFkcaDVIlkJEZrV75f0IlwqHA4HA4HA4HA4HE4HDrfeOXuhc8UnAqqWZdjUzG+DSxMDMkYm4Ie25fpg0PHK2hFWaVy
# 6IUFE5aLJdUkkkk9FChSyTXQpj/h19xOVYmZne1k9cHy+ySeiSeh9NxfzOiGNFXIk3LvY+w+UPm2m5Tc+X29zud+ipXp7HayUhLFnkXCYmSThH
# BVM0H5s32KIr3gmoZBXlmtUQOlWqmNQ8WSV+WMVRWdyrGvYWDyCOXT3ZGMkWNiU6nxQdEcxbJJJPqdxk8ixij+hl/M0OxlaV6Fp9BJJJNiSbZ2
# O3WpbhS27kd8Ig+NN3CGxv5I2ST00KenJNne1FE53iExMqLB8AXjrX6blLST2dSSeCalWTDan6C54tlncygYtBos19hKMGnDkjLzUa1RNI5er6
# obFHazgBAidwvAhNsS25b1fpz1STbRl2IpLiN2rsTKyRSVFdaqV2PHTQp60mnJ3/wXHPOP5Ufyox9EWzbBBB3O53K9FSuxXboQ5O5jHNehCFg4
# lGbEKuVKnxzMr3wiDFXiIov1LEh4phOXFEpZQb5Xcjbbl3vDIHBP/wDQrNDMrFsoilhDBN+/IxKFHo+Dx0V160zSiMimnRrVZokVU1XW0sMvS9
# Xk9dSpWyvRQp1Kml8IoVov13HNyZcDY2T0xYjbogiypX0IItZXUJIb1eIQrF1yT6Fw1QTFSmbYoyWi00Q0uXhHVWX73XdmO7rF5hcFzuxOQr2V
# o3f6xCjVJBCVxVWzzRcxOVOJkc6D3y+I3ZErII6Ox2sj1InLMnL/AHDVDZWJAqGWYq4aeXkbNQtaqrHAxkckEbkbkEEEWyihBFvg8HjqcjIIKN
# E4sshMTFZ39SCLQgvgDuEkFyxCi4OYsPFMRuMsQhyDpiTiBDhrfQOYkhqjRE4wEEdaUsglxq9NzPd07CWXrQR6NM6GEGqKvDzQnKsSsk0t6tSX
# mXJHwF1gAAifMR8xHxF6CIAIiLlU12qJUpkqhMiHse9jG2SST6VChCIRHJBBBG4+hqxFikm+ci+FNZyITFYrYI9Jkkl4VEzcp9lf9HpNnOImds
# QgbbFsLkzw8zgu+5UQsTKt0R6qvya97ImIlPOjXb+xYU5sWCoUKFB2ccxLhL7TIKXqhpxFjUqB3LmiAms7GOdf4mbE6FwNp5Gx8jY+RtfI23kP
# ReGfKmfOmbfyNh5Gw8j5Uz4Ez5GPkYkur4ZNq1gYzcbcMTbJNsdVNbYIIIsnYnogaGhlSyyIhJCELASONBacvhIg0d/5DOHyxCWX1+9C54pOGV
# VXMahw8Kg1L6LFiXlJWVVR+xfpt5w4LQK2grsGe27tNuiCOjsdjtbPJPJ5PPRUqV6KA70Z4Py5MaVZnEVXYator20WYpXRVCaIaxtHbooUJErU
# nc5HI5HImybJIAQzsFUJldMHYQQytngptb4PB46ex2sY+imXV38CS5G5CEIVi9TkBJZEi+/7f8FEXseJahjlJ9iJpWohqHiybhX4RVEzdyvHOb
# MWMFA3Fd/4GSLdYWBTmzPV+XJdheoqVKk+rHTUipqq7BloO/Xe2JEe0hXBkRXjNLym5Te2uvTLJZLJfTHOkZjjfFE6aMa7Q04ZQzsTscCdjtZH
# TBBBXohELphFLVOa5DnN3u0QhC9bgim5PYZsaekHRDHN4pqVZNPff+guKQ3hlIwaDQo8uxYtUZGKk9VqUq5S7DSknB8QLhzurrkJtZLbmdWIkn
# piypUqVK+j26WazgfDqjz/ACNKELgvyOiIE1UPk7nexAjcjez5dZWyChQkkmysL1cQ3+0LJnMIqRHT3O9kk21KkO2hCOx2O1j6JnDK8zB6WIQh
# erFDNiFddEy/jmZd8jxaCbQ1ehkq4/BiQ8VoE58ESFQ3yu5LxY2BxqOTV9ghmVg3uFSzFaTVuzYkKLKepJPXS2CBjFRySE90L55wKiSS3cKI6K
# mo24id7E2+SeSbO/4O/wCCNyFqRqI1EK1DVJeicRKoa2GMv3m1CcOSUSuhsbJJJJJ6JJJ6WiCOSOSabsKa2d9jzaQhMVsEdbopG3MKmSn/AC7l
# 6O8ipy8Y7Kr/AELHVTvWLNyPBZCJHD2AbRHAJirXWmZFzGlTgZXOhMI/wCzZmCtggj1p6Isix2xONSRyK/qVkqNG7+BV+5ZCKalLKb+Cmj8FNH
# bJJJPRB4OyELcQyUO4k73fFmiRDQdjtZQoUsknqqdipPA3wdhPBNvgoiBIVjq7UIQvTyncmKY33+OxRVcvYCh5VP2FriU8D1MClS95u4gSx/AC
# KAq4fgYouGQ0QScTicTgcDgcDgcTicTicTicDiJoOIS2izJ5KJRdPWST6sEEDVl9rQOAiEQv+sZJbG53sknooUIVp3EMh2SIKNxHNy8jlR2x5o
# SOGiUSiBKKWQiLSCCLKldSpXo8E7klwbAsuxuhIgtgtpw6QDh+TgcDgcSG3UUyGQnxuvGMczmDHjmi8L1OAimmSSSSSSSSSSSST6h4X5GlOWQ/
# uQ/sQ/sQ/oQ/sQ/sQ/oQ/oQ/oQ/oQ/oR/oR/oR/oR/oR/oR/oIQ0NZZBqpHsFyeRW/8AIxnZJJJJJJJJJJJJJJJJHxmai+rqMmpXRHoSSST6js
# dsr/gOZi0o9yhJJJJJIyUSjsRsRweDwSSTbFndl6N5gpu6urvISfQc3bmgjpnoqV6u53t7HYbhSSuTISFj1jAIQ9WhS8RV39L2bJNjQ8dcsa0E
# kkkkkkkkkkkk+khUq8huR7UN43DcNw3DcNw3DcNw3DcNw3DcNwkXijwOLQPHIYhGlq9C7blOBEppKiPiSPhSPhSF9RHwJHyIfMh8SGy8DbeBt/
# A2XgfMhsPA2HgbIGkSguVsCEIZDWhHJn6/Y7eh26WMnCi1dBUQhFCaLJDq5ZS2SdjhaTudzuV1JJsoQQQRZNiSgSHbNDLUPkE20VJ6a2dyNyLE
# b+hJFBneJnY0KS+tkkibUWzEv4R9SjQ/CFovCNl4Gy8DZ+B9INp4G08BaTwFovAj69yIyLrctJ3fyZ4g8c9YGqRLdEJBQa3qzcN43vwbn4Nz8G
# 4bhuG4bhuG4b3pJDeFi6JJ6ZJ6mhi5jcG2VP2HRjxyZlF7+wQsDQAj3V014PuNQyv559Hc7nf14IPBQoUtZFMvxiyRK4KiJ2J2ODJaEvRkvRld
# CuhOxNlChCKFLZdvYnayBq/IUEGiH+y88aH+xoZBFiCCpX4ipDIs79ckku1yGObvYqKxpcdSEJiF1yJkTLhKtRNVmiYSaZ4ETgaHjGhCJt/gqy
# JRrhkjM8DsWBRlC9oo4DGoQ8YqsVVueWXhTF6skkk2R7M4+0dS+6b9VqcO/SknrqVPBNr6GJcjOe7JDkm6o7neyCEQiCLZ6pJ2OBwsTY5HIQTH
# NS7ELoO8PQd6INFLe53t7W1K2UKfGdh8DPBTFyvEzsiXoITsL0ExMcyavVwo/QF5oz9LDxjSxqXO96DTihccBpc4ZMiZ7ZWLBITghPJC6VYStw
# mNFpyRyZV5iFgkZ3sUOpfBsKUXNYKSetjVJbZCRumH1zFx3K62LZs72+SPSnoQh4Gr0KRCWvX/AAcxL1X1CedsEEMh2duqUSiljFuzZCVo3oCE
# JiYvQTGhleuLzaCkVQrjTMicNDxTQoEV7+IysMg3I8MiJnfBu1QiS8qhaDxSyx1CMiasvNu8WEZpyhydKzWqzQuOtE+w6UVVK65JsrsV2KlfQc
# lbWyBkfLm+xRFMshkEEEIgi2bfFsEFChQpZ4J4J4J4EITKhuuciWo/M6oVe7EbihJJIlksqVK6ldSCCCBpDgcaFx6CFhWQKPSQhC9BMTMoTA1O
# 1yMem2uCDWKbliOSiQ3L8Mo7Ikc2LCocmmnVCIFu2PNEjFvbSXsUvT1vvhkVFcyhvymFM329GSfQkknobL2Vr9NyDlCo4DnNs7nfokkklkrE7k
# 7k7k7nez5cfLifkEk8HiyuxUqVsT3GpR0XkaqKq2zIkSQScOpbG68G+8G+/Bv/AIN/8G68G+8G+8G+8HzI33g3Xg3Hg33g3vgcdMl0El8WOiG5
# c+ihCEL0EIQngA1j33RkDGPENkJDj/0dCRxphkPC/LEIiZm3E3PRktCib1oy5wPELmdnexZuwsKhFYocLi4vl5UVkV6IpLZ9eNyLWxsbHXJV+E
# i4obk9Ek2vi2UQJVnc7lCmp3PJCKFOiSSdmdmX1MrxziWdN2QT3VzhjfVE9UT1RPVEtUS1RLVE9UT1RPVE9SepPVE9US1RLVEtRIUWZXpoQhei
# hEDFPOhCa/ySMpWTFGsO3CLxaburrUPvzeGQqKdBuxYdWCaqbNjyYxyeReh4ZVJ0XJVb2J+5cS0QsRWcsxGPpPwMShD4aKoufp1K+ixsbGqEMt
# zusmzuS9TvbBBAhEHy7pggh7EPREPRWUKdHmzM6sbGJJJwDQk39NCEL0kxMcpL0KjyOXR2M4Y8M8sUVLIRFT97V5vDwkNlksUhoYpOugzVFDdo
# x1Dwy5kXueGghYdCKwmUR4u/+YSGc7nbJJNsEdcEWsZe7LxFSrn1yU0KFCFqRuRv+SPk2SSSyfkFfi6OxOxJJ3HOo92TzGxvon12oeohCEIkkn
# rQ8MfcufSIPI5RE4HhXhCJRv8AN1ZEowyMzxasSjKL2rCHuJlCHhEpYiU/v9hjb5ixMjVNCFGgOqZVGiugyZx+fQmuM4R9uPtx9uPtx9mPtR9s
# Pth9sPsR9yPuR92Ptx9qH/RCarZElSKY7TuS7ZJJZ2O1kk8Hg8W+TydihQp0NjFGGd4w3TBtD1kIQvSQiFqL1cKIea2zrubdUMeEaWNXlvbRCm
# 5ShUJsNy5wyQ8uxYtMahBVHJTwFwp5mQx+wYsUhEVfYuq6lfkXYQng70NkmuwYeYiC14WsK1h3FoJ2R2Nvk3I3o3I3A3JrzNc1Mpiq51qrWoZT
# H1EWRZBB5PNlCmhOxOxJOx26mSDZI22PCG9cQhWR6EiYxVm4WfR5MySG6LoIGPBtSBFFersWSKkYZMo5Y5EDGtaFf0FJ7ghaDwSyxOR77uYq1E
# sFFsEEEWoTadBCtVl/wjDS4tuwzmJlSTbAwrCSSSSSSSSeCUSiSRs4iPyNzbEjFPyVKU6WQyCNjsU0KWdzv0SSdjsdumhQY2SOFyGsvYKnYEy6
# leuhC9NCsk73+LHMvENDwLcDqxDNU3bEjb3vFLGozZqhFDjtYy/BTkl7EbD/ALCx1CdzE499/juLDrRlT/EoFskkk9E8k8k9PceORJNuolUsrh
# WdjsdiuhUqdyLYII6a9FBwJlzyGwiqUjkZ7+Q/WQhdEeghMqTq1E2KtfRb1yMgcjwLZCS6XsRJb1V9WSNvd0RMzrpm0ZAorcmjLmPALmfibZCQ
# ljpHQmm9QSyXS70/shU87huieCeCSembE2wNd06mLavQtKZi6O1kWQQQRuRudzudyup3PNk2SMXPcrR3YKhJB+aLpFKdnqkIQvUQiBk0Ilrd5E
# TyzVT1RQx9FPTgVkRo0LqyJbvFLHoyhW4/iyXTyHgEFTxmGNbstELGT0VgmWSv4yhXD6e55PJ3O/oUG5c9aubnb4PHXS2LZJJJJJKCoVexrIpE
# bqpGwbZvjfWLZNk2TZNs2zZ6UglNVEEFDE0RuNy+BIfqIQvWVjVJeipZX/8ASK3UeAv0QZIuyF+xpThYashqyGrHfKxewm7K1p7Eqp88H0WAJS
# CBGQpQr1a06AgbumgYKDIaK1fYWwhAZK+4RePPRBB59DuSOqEcHXcxannnZJNk8Wk2dzv1ySSSNCke5jdib+hCQl0wQQRZUr6LZESv+ysn6aEI
# SI9VFQJF7GNxYumWP57/AKP57/p89+z579nx37Pgv2fPfv0/bGfva3u6sM8nYVqk4llncyRAvYE8FfyyGqTJk9iexMmTJkyRIkS0RLREtiWxUa
# mXp/FjJlj+CEV1xjWt3uwySempJNskkkklYzXW1KL2vX9U2k7ncqVJJs8nk82UKGS72qPlmNwZC6YIIRQhFPTThi05allCaomr95tV6SEJEEEE
# epJsQkGXwhmIridWbGTSIJbE9iexPYnsT2JbEtiWxLYlsS2JbEtiWw1oZ4I8CZ4hCcthY9vB3iFgWlJdotMcDKaueq1Gh45JZcIUhMq8iQb9Pu
# SSiUSujjPQVNeJJ6Ox2tjokknknZk7E7E8yRtskkVxycCF6ck9FSvTkEj/ANIs16KEIXr8gxH/AAgaz/4IVDBMYlMhVR7AajEQVJFLndjkKFVc
# huRsWE1CVV5/gZIoxMWokcipjZflaB+n2J2J9XLxygyRNRDsgi2SSSSSSu1skkklIXIbskkBtyPMQralfR7ek9NXiFREV9jzXWhCFgYchor9JZ
# ip0gbJDSl4Nk0vnXkJiERuMrFjEGy5X84VOBjJXKFfw6JyJnFIoBKQhFNNQ8jHb2OxUr6MdEETnUgjpTMzz4J4J4J3JJJ5J5OFpPRNjkc3kN2X
# lAmV/IhC6IIsoSiUUs8+jJJExo5vqfQI2aahrqQhC6II9KBWCUN9CIlcMsIy5yhuJM7+RIeITFyZ4xCd7chCwtEyY5WV5NBBssUjN1PAK4JHYd
# tLJ9GpBHSqgkdHHWm5leiJRHZHgm0kmyhQoUKalNShKOHyG7Eg2yu5EIRBHB4PFk9Ekk2V6e53KFLOxQ3RQq0f9O/UhC9duEsblI1JpcuiL1MH
# huMBl8nfiEVVXMahwxYqSEikK5RYh8Jq4TtLSuCyFzGlYhWNflEq+CbiiyVh4WbP2utC5OS2PtLE+8PtD7Q+0PuD7g+4PuD7g+wPtD7Q+0sRVC
# sYhLMe5NAQiCLK9NSvRHRPRWybFBkJ3TD/AGX7LdCEIXr1oDGSSluiQrXw6/ycAsMxj1NhiYhCbhX2LEIPzf4ELD1Adgb2jyYgqGQyB4hEa3Gg
# 3gkdh+nJT02pKViFZ+AOBCwPY7WQRZXoqZBTunu6CEL16wKrFKOh119hiV+JKrlmLDjLLEt4KQLEJrcrytixMyuUIFI/GZMY8rDIrGglHqnIx7
# bqxhv0pJsknonrrma6ng+OzKh4ELoqQRZQlW+COCCPU7lxG1eWa1RMpV6vqrEIQvUrbxCL7zgyhEmurKliGMqe+pYkhrlsLDm3Lq7FiWNKIXLq
# qE1Qy8Fe2qGh4ZJZdpCEs3ckw2P0IIIIt7Ha2Sdzv1cI8MrI3jqxCF6Pc7ncgjo7+pUiSWT/AFdVYhIS9flGITjURwZ33KcO+KYm1JkQcIDUYh
# syByrnhkJwpXIltLFi6wpWRO7MhjZYVdB6Y5VEepelmN7De1vY7dU8k9EdEEWU6aFhlY+a8SEjud7POBgj0LrvdxOlUd7ELAVog3QNgE3IlNBZ
# IaXLxjzLZ3ciYhCX+CxYRCpG5f7joXcgv/nZqhUYqrBoOQlmLcLToqy7DfVPJPJPXJPVXopbC91rwSU0RPU6snvmiiorO3V39KCCPTruWREKBC
# FgIht47ayEsFyxjGUXniTCzTnfYsEkTvLkIWN4RiVhe6toGJw6NDZevHROSFf8WyJnYK/6FOmnoSST1JKhoahxY8CihWxbi+ptP6IbNlDWQ2Vl
# SttPRpoQtDt6ckkMOd4uY3UQhetAkvCwZqx4ENGZcPHUB3qMgo8QiFzuZIhi9KCCLI6EyLguV3sDGr6oodrs/qxoWQQQQQQQQQQQQQQQIIbyKJ
# 4DGvwhsqRSsnb39CvpSSdrZJJGIStcGsiD8iI6P+XV3ENKskn06ksl2JJ65skG8hnO72XKxCF60jjQWkSyEhW9KqfynDK7HMY/yKDlJmRvyCJQ
# pX8yV/MlfzJX8yV/MlfzIfzIfzIfzJX8yH8/ULuleQVKlSpUqVKlSpUqVKlSorxqef8AixY+sFRckPbcviSCSuJEiRIkTaDgOA4DYRsI2FYSL6
# 7led5n/CJmMYsM55Yx0UkW5r7nkhjlllgqciQ8TIFz+DRilKsMeHjJXHK8zC6NwTsOA4TjOM4zhOA4DgOA4DgOA4BVIdf9Wb7EcM37DUhPm0Mj
# DqwSb2rcomnQkKd0d8d8d8d89/p8xjHePePeN65wzt8qCfYYYMnwVxvXIJjTU+kc57wDAMAxDAMAwDGyvG211FcuEKbJDbct3jY3ZUirk4tNCp
# eghyWZ1mIVKpD0zYNhGwbBsG0bJs2LZNg2DaNo2jaIEIlX4jlqqcb8r7CHlcWwR00IRC66leuXfgQEiV2L/ZJ/5H1on3eYJt3mn34+xH3A+4H3
# A+5H24+/H3s+8n3k+wn2ERlNaII5NIJNtSQb9gYrmQnbbEIRqbmfA9zORyORyJaktSWpLUkJaktSWpLUlqS1J6iZ5nJqgYnKx6FWdyvGkQg1Ru
# T1eTm8k9Xknq8ktXknqtQhPV5E9fkS1+RPWJEYRlNQ8kkb5BtvYb6FzJ1stknpknqgjojokgED4gr2GLcypUr0wQQUKdE9KgeSaJCjJTUWaJBZ
# bVNQoOSfRjo7+pd9yIEPboq5DJKf2G83vyJ9Xkbq8jdYTawn1ieryJavIn/YS/sPiY+Rj5GPkbJkl/YSIwkbe7O+3h7CdWUOZUvLw6Jnsb1vY3
# LskkkkkmybJJskmySLdO8nV4E4fsCAS91CQrJJJJJsSSSSSSSSNjYhzivGldKbm0EJKwVfiK/F0upfpNCGXJUfsVgkkknogizsdvRQioLmSyq/
# 3lmhDZev2O3oUlXskYssTd/l1JXS5DdiEJkkkkk9Uk2S1cyIuNYQ8cxVaqXd2MvzeIQVSsv9JHg3yFo7i4sbGqrE0juhVzevJI2Nkifga4+lcy
# NyzwHcknpY8Ire4jZ/Q+HITHVUElC4rJeRC1FVSdvRp116aFZ8ESGqS9i4i6UcB7UIXTJPoJKJ5zvyx5ibx3EVTP8AqxpeHSJ2ZK5fnCxQl4uT
# UIuxqE7Vx+TEoWBdqY7jND5dLUMVPnmdzv68EW0HBRKEq6InIwslotBtty+iSeqSSfSQji3eKhVVP4BBcI4a0ZE4KlcJRh3MwkZecjwJRjdqEL
# 10hwHDzXch4xiUfQ/YbLELJnZ3IeXhWhiU2q7kY2LQbkzugXPDJ5iw5VzL+hJRw79Dv09iSeiCBjZDU/IURI406pJJ6Jskkn0UJlIbqiNNfzZP
# uSKDB1GqMrNmxBOgVbYkN8tNhh9CwF6JzQGOZp3rFyMT5PRE7pRFCWw3Lw6EpIpcqLDsSQmf5WKqxUzguS5RYdCqvwGy6VqUTNYRuFIhypqxrk
# QyrXvSkm2CLZ9BCIJjkslPZL1Vr9VqNDwkugrQ536USOR9CFYvXSkniV8DxTHmd7IbLDokY1DP/A0vDpwx1UBzmvQ2KUr6RPTn1UV/6E5XQ1KK
# iJypXqwR0NjTSuW3CW5dgX2uYfg9aSSvpyJmf7FERFX45EjyrYI6ZJ9CrZ5CSxBMkUurVjLydRh4es5f6iJ0udViW4OTJjW217xCCkpuXskG8S
# +QvmHFjTh0JrcrxjWwj6lvczIfSuZ+t6cdPexoRKX35c2NCM36EdMEYBOHMk+o1UX7C8yuTYThyX4Hj0LCHskr3cJVcfm83ZPqQsCso3sqh4h1
# UIiW9V5Ezw6JmfmLHXFROcsyj5XoTh4hEochUWKReM0NK6a0sjh8HD4OE4fBwnCcJw+Dh8HH4OPwcfg4vBxeDi8HB4HNF4zQc9FqUSWExwGNJJ
# JJPRJL2Jfqz6FEdzPjJ3oQg4hBxeDi8HB4ODwcXg4vBxeDi8HF4OLwcfg4fBw+Dh8HD4G1RQSRZYs+d/Vk7Yb61g3K0INJbvwHhmyGXy/Ify8Q
# glVl/pI8W+Q+4CsbLCoTSN8v9FVLxieY1wdULQhaELQhaELQhaELQhaELQhaELQhaELQhaELRELRCKSul09iIUE1bQoUwFeqSSSSSSWmlqEx9V
# amt8yGhDQhoiFoQ0IaENCGhDQhaELQhaELQhaELQhaCTQQi9WeiEOlEITYcfWsG1KKza65yPokTaecH0J9SfUn1J9QfUH1B9QfSn1p9efVn0Z9
# GfUn1gmlJcDkpex0oAbl4dErMlcsbdNXkLX6AuFhEyJoLgqYxEUM1cPlhVYm5NBoHJHpThOYdjwKJGa1xXYTmxvrWFXMmHPcHZGSi82iENzcUS
# 0Vk3jeNywQ1Nw3iAgIashqyGrIWDkXDISXYIfLELLM7N0Q841oZBzZ3cjUOo2DQ6vN0WPJlLlZic4dC5Z46SsWPAIQS3OqDHTe7xh42gu9RiQ4
# shn/AMFZImcTdgk4xCROcRlj3oJBJxYTkTJFdiGjwQ0eCGjwyGjwyGjwQ0eCGjwQ0eCGjwQ0eCOjwR/kyH8mfQM+gZ9Ay+aXF5xWWPQq01KHDw
# k1i10ZVs87JJ6p9mCFZPvr+ehIx9aw6jcv+BTk5j3eSH1dLe1yMahn/gaXj04Y6ud6jGObKw0HE42nA4HA4HA4HA4HA4HA4EcId2XsBCyvyE5W
# CmFJd5tZxz6p649doUjcux4BCSQW6/6DMBvYFgSS3ciIuqtw472pCqJdyvGsb9hfISvn/gVMFA41HIzX+wl+GZRDoESJEgQIECBAiRIkRpI6VM
# d66pJs7Hb0u/XM40saBvIkSJEiRIkSJEiRIkCIlKO8dwtGmLfV2T9gkr5U5akKiavDPBxo/JGj8iWj8lQsneNYn7CjLCSKc0V1dX9n7Ck1ZGn8
# ka3kjW8kfYR9hGp5I1PJGt5N15N15I1vJGt5I1vJuvItR5FrwgqEoauNTcxpXQ0VoVV1dsDPTFcEJVGm3ybkbkbjyRqeSNbyRreSNbyRreSNby
# RreSNbyRreSNbyRreSNbyRreRNK6U+RuT7BekBWLkgVj2tMjZWM/8AA1D9gWFmEVbNzRjHXix97NiSSWSyWSyWSyWSyWSyWSyQgT5jtNzwx2Su
# pnu2Hkm2GhCwvxG4JEiRLJZLJZLJZLJZLJZJJPsdXs5Ow/exDwrH4/8AC4LsvYHhqUETno/bHMSFOBVj5Hbs90PK6bmVDDxKNbctDjK5YNb3Md
# UY9SlqH2J2/FDcufbUQORpQd0LDxy1w6cORCvq1GtiS8Hqsaqh4O4hayZoum9Xh0sgcO5+lQp6bGlNjwoF5A8GhJlmhY6M+JoiVxksU8KxG48G
# WueOeIyjy0t1jGJRueBQrXhwd7gfLpZyHqSTsST1ZVqVncN54VOBODGzumfzZBtW72MeFceg8/8ASJ+7XaXoqurxaZsh4VjL1eiJLoJyuh4MII
# KEl9jZFz8hiFg0RQzyFi2KRLbhC7sL1eZwHuKZE9mbluDo8UsXA9ioz38sVoOQzHhWJwy42zKkPpZIo09KpLJZXqmcaWNwhMw3YhYRETSXMWKl
# Xvf0ZAo1xzwrCWq3XMml1x+h8IPhB8IPhBD6EPoQ+hH6EfoR+hH6kfqR+pH6kPqQ+pDE5Sx0y3RLCbOWIoRePldyPDMYmLK/MaV0tUE5Ur1pJ6
# QuCHosuhelBFsEEEEWISDe5iuGLEPUZ3vRGyKhNhpS/c0QOTkP8CQ+lCcYEAEHXZ3k+sa8pHTT0t/se2+WHcrQgkkuDIwjGMuE1ncxqm+liKLh
# u/g3fwbv4N38G7+DdN03TfN38G6bpvm7+Df/AAb/AOCTOVjwhYU5u4dq6oIwCmr1QVLEVJr/AI+ws8Kx+Mgcq51WHfI5L/GOyimtHhhnhG96A8
# O7UxeUPTpeAAB+YrVs34tXoQR0wR6CGU10GNa3nXEahK2/vEuZeiJ4fOKgr12NThyR1vTvRNXlenqsLSsv+Dy9ErsQ+hsxbq53YZD5CXIx2rpj
# BvkfKpQ9MKx6z7E6sWFTI2Qo3P8A0eGaGRN4Y6tB3o/phGyKTuPgbxLtRG4yHywtxUl3DedqxUhIVvVYU+Qrh8vYHyEOhOFAAwhZ5/6Tnh3Mjn
# fjqZ3NFc7jrxgrjkwZI5eKfQmLlzE5WEfIuUecc1SqzX8x8sG0IVXanKxzcF9jr0xbHrxMTeqjGsMnDFDo7mJJp41uEJzgqnCIiXvyN4t23CrV
# cxXDwcwjW6ELF+RFRczZicrBPL6DVxzCxKJEO50ZTsO+RvBX415slktSWpLUlqS1JaktSWpLUlqS1JaktTcNwXeFiWyu5G8a7UJK1K8TlYJ1Qh
# 6ZL2BOCKP9QQ23iHzQ3jeNw3DcJaktSWpLUlqS1JaktSWpLUlrYuhpWMaFi0NBGJ5YhsyhZZYthiapD4UPhQ+VT5VPlU+VT4VPjU+ZT4lPgU+R
# D4EPgQ+BD5EImKNpDoShCRAxrtuKchtw4PJxeTi8k/jJ/GT28k9vJP4ye3k+UnF5OLycXk4PJweTg8nB5E6ifYaaJCHVWlMz50PlQ+BD4kPiQ+
# ZD5kPmQ+ZD4EPkU+RD5FPkQ+RT4FPgUYJRro56U4eMaX0QQQQSJEiRIl8ZMkS9lcoeauxbYqkBEgQIEPQAAOYjucxyCzzKjgPc+Vz1Hh+wMvcI
# dKLIlEokkkkkkkkkkkkklEiyp82LHxKx7/hasaUM5DkOQ5ra5jm6KuayjbShdL4phWX+nPqrGZxA5VzxLDFgsgqKX/cMaVGNYxixuXDwX4CUBW
# rGNLI26s3ohTcpQihNEOTnAoTMXQqF+JdXY/dWhlx6ri7D3DEwjmSi+RBOHjmUseeMGjkf8CxxsrKNvPZZIysG6oufS+WIfIXvDiT/ALxC/CwM
# qebnoMyMY7Cotx4U8OSrK9VCFi3QdWL3F3bEjb3vCITMXSnKwzcWv3dOGQzuZIJ4V0Hh2ZNUXNxf2ZcJysW2c6DJm28MU/NfyEacW2QlLpeOOX
# qvMkeFvGpdLQ8MwrF7w+QlXP8AxhWy94doZFGzd0eo514h4cYpjq4Q1AmX5DYZ33Rc3V7ZiFXEtCsrG2E5K+rwyFlC6WlYRoXvsLISi7BsMWIo
# QQS6H/LGPKxDG4Kh8qch8O0MgP8AW7jG3iGjEzMvEgdJK74W+48pw6Fh9KcPCNy/fblhGLEpw5I3VSyhrYe7weqGliGxirxjqmgIbl4h6QQK6H
# /DENTDvCsnG0ti1MrEpKF0tgmxy9gbl4N2LFNkeRluhjUjDMbO01cD5YlUFJy6tRrYmbyyeqE4w7SyByKtoiU4QlEtENy8ShMxdNIlqS1JepL1
# JepLJZLJZLJZLJZLJZPvzorJbeSW3klt5JbeSW3klr5EtfIlr5E9fI3vI3vI3PI3PI3PI3PI3PI3PIesuI2GLGRtJehU+vX6E4YnOGozuVfAhu
# YhZLF5RQd5cCGwrZWR+74ZIrRi70XPpT0nROrN8N8twtwtwtwt4t7yNzyPgZueRueRLXyJ6+RPXyNzyGJNPOPWOdRCfSECBAgQIECBDo6hptcx
# GmTvxrwxJOe+/kNDZYRjHcx+g+WMamkvQjfNfrCtwi9i261y8kOcs6vGrmK2vvUZM2xHQjoRIkSJEiQIdYDcj970YR8jcKo8d5EUSbORcNKwbF
# tv3DL5u941oYpb515Fzh4Q+QjbSSlsQteTVjy8c6O2Ic94eXgn/wCPVDxO8k14xrQx009JY194h4eCZe4Q4UmV+7Gl456FAmdOVirgWhWSzZU5
# kC5x9SEQVcOTzPCPHr3A+QmOjIOx3gMVNSJEiR3IbkNyG5AgQIECBAgRGRG99wbHpwx050Bjm3iJggQ3IbkNyG5AgRIbkNyG5DchuQIENxpHIv
# mIpcUIaX7AmSleyCSQGl4R+8XLEZyKgr12NTgkTSM0Lak5WTIIIIIIIIIIIIIIIIIEgUxuXZqKIbn2BtSKkrp7odSCCCCCCCCCCCCCCCCCQkrv
# hGQvYU37oh8vdSxDriGhkTePOObgSK0nonmL0ZCEIQhCDIMgT1EakKUjbhcVjSvYGljk3jFQmWdR+pWFK97Upa1iWPR71hWUjNLiG5vYYdZZiu
# Erhv8A8Y8Uwk053842KSHorkSS9SXqTuTuTuTuyXqS9SWpLVktSWpLUlqyWrJakLrVqNbEl4PVCcPHtFnaauByXqyXqyXqyXqyXqyXqS9WS9WS
# 9WS9WS1ZLVktWS9WS9SdxMTdqjE/YEocg+WIePXuCoQdHcxjE8sW2JUzY8E2R5JW6sbHNyylPc3sSpuWSwcD2zKXllj6o9wznfin7m8Y2Qm6vY
# teLMacJDCXo5skXY1srO5j9B8GhKWdywsa1EvfkaXin/5DOKNlliiVDN3jwjwxS2zryLhssXNi237ljqt3vCtFSsK53Y2KWyu5Hxj9xeOYap5q
# qxKS5XIbwzySwudOVic4phVcK8ok5bsaXhUxKbXdyLQWKYpMxkqK4Ny//GTT2BsyBwuw51cFzZh2hjpzuA57XoauJdLID7Q2HQs09xPFLvrnA+
# WOf/j04YqG2dxdhWxIX4DxD5HaI+LGxDcjkpmKu0CG5eIhc7mNTJ4mjZZk1f8A17CyvzwqVAb0uWJRE5iVmii5XoTjDt2LV+kbLEoSrneFiEt8
# 6sb2B/8Aj0Iubox0eDYnIx4p8igbixBl63Ksmc4tocnFZYe+ZK8mZn/7F4ROAbxl01eiHDAayNy6hsWhqhmrhYZf+Qap7qyIR5xrQxKZ87uRqH
# DGwtad3+jMzxqeYkOVc8K7F7A/b0JD9geESssh45iJDiwngmJNkleyCJbv9DcvHKq3F1LEm0JSz6I+iPoj6o+qPqj6o+qPqra7fm/N0bo35u/A
# 004f/kUXqxY9YK9wXU0x6cDK53rxzmyE8C6WLJmuDY9FX+rO7HI5HI5ENSOpzORyORDU5HI5HI5HL2I/cUJjng5oUqfHsLZCV8/8YODQrK5cN+
# wL8HDK8zME+hYx+530sWOW0cBwnAcBwnCcPpbbbbaGSR8EhOfYUy0IcwTc+eSP3kfvI/eQ+8h958c2sfBJ8ckPvPjk+eT55Pnk+eSW9hlXsMjo
# eQ3vMbkbnI5HI5HI5HI5exo1Y5E4EAAIHtmUDwKnsKRJDelyOJxOJxOJxOJxOBwOJxOJxOJwKxd9esWPYkV5XDYN9KxT9OSSSSSSfZENRinhWG
# qeau9gMYtXP/A8FBUoWWXsCTgWY6UVyHX/ANOh1VixSwjZkTlXP2C8Lsxs8Gw1TzV1ixrF3DuG9yfu6YkP29Co/AYsYxkbzMeEzCJwueO/7Q2H
# f/k0XrFLDJiz/uxYxayyG8KhUbri4WLYlHN3/wDrCEz9wbJ3MSUMWLvcIdFDIeGTFn/WLZM5dyGzxLxL9729wRfM1YsUkL8B4hb3MSg8Vey5+Q
# 3/AOtRqwyxTRUmbZYpKA34xKFqZqxYdix/gb9yfvqGo9vRFDNXWLEJyMeKbM4jLEJUB6K5D/8AYPCLGJiZLniFl1uQ3ni0RQzysWFYtTNjf/IU
# KvIagWGiEeR4xMTyw3EZjZ//ACNCyvysWEUPHKtNS54RiVDN3j/+SJ+BIcCwd7gemmPQsr8v/nSH3FZJJJJJJJJJJJJJJJJNiQp1H7AvwJKLJJ
# JJJJJJJJJJJJJJ/wDlKgQml2CV9Rp7DIye5e6P/wBFJI/Y6Kk9SWpLUlqS1JaktSWpPUnqT1J6k9SepPUnqT1KU5qxewpLKbqInqT1J6k9SepP
# UnqT1J6k9SepPU3jesk9Rs6N0GofsdxJJJP/AJ6/2JVeDTFh7exKm5jwTquPYl/6R+wqiwaLkeLFj0l7DeEah/8Ai//aAAwDAQACAAMAAAAQDD
# HF4/8A4wx//wD/ALBBR0v9hXBBBfjH78cW88wkqXjXlVemoe+cUTzLTvXYqzaSKdJzvLj/AK2+2dQcTue1+UnS0gnrDm2Yd10vunpYbj99PFBv
# vvpa3cx5YQVSUQwz+v8A/uMNPPf8kEEUwv0FHMf/ALDPiUbw8cgUq3jlVVH9R740UXjHNdPoIJCCeN1H7r0wajX8lUPmVWRRerHz+K0/Fdx5rn
# DG/om2IXS8EkO+OHOjHp5BBV9BPLjm/wD74w0//wD/ALBBB9KXBX//AP4162LSgGJMLhk10eXX4sbbkFHww87y6uyjrMEWZ55SPAGwSSviTIa9
# F54YAQdp5dUdVWZ338+z0MHhn617TWfcc9UZXbUfQf7/AFf/APjDDHf/APwwRXfQEQcdTSc4x2RSFEOgvxy11RdxthYf/ngshmgWSpNnLlMYS7
# 8GMHIwcZTS/wBOZxdf+MjrrPEnvMllm8MPdifIsP8ArR99pjdxtNNBBV5B/wDzU/8A8MMMff8A/hR95hO2ieiM8whpOpMoOiP7jTp15Pmm5wP1
# t15pdNB9bbwcA0YxbPso4fp6lWLUwA40oPrTNMutn6uatdxrDTg4X8oFzbP7SvnLDX/xBN5B/wD28F/www3/AP8A7BVtBBYJv/D/AP8AsPLzoh
# zoL9+9dWVlcepcEWktdt/gC+UR/wAEM0oVxf8A/d11HITZmPMHMEOOA7SkNYtrJtcV4855gc7tOBKMvrxREq0/6QXfYf8A8NHH+MPP/wDxhB1t
# BwJhB/rzzfrCsDNAmKT/AJ7UdUb2jH4rlpKCSyx/bcwQoCVfOIhpa46U9+dTWdz1qomHO+MoDFWpttdVwxyCDj4kDNKNvvlVQvx/wVfQQ/8A+8
# NLcsNf/wDrBB9tN6ZBX/DzHPf/AFt6pCPjth3zUXRbn3GkpqKC8w+z+EOB5lezZcZCZe6V3AXopleaVz3wtRXiZHZntlUSbT0YR69mOHAMMvvg
# JNw/YRfaQf8A8MPFisMN/wD/AAQQVXKwQX/wzzz/AOJZTl0DCZNv+V30vYv7yJzhgu8c8tgozfjepxK7bwjB8MkmEQBa7sGHnojczWHZPpImmW
# GA5jMbpShTAwxLY2t4Pe0HW0H/ALjDXe3DDP8A94wQVZMYRew0/wD+8NL4T7CoRptcH31VMxXTzyyT49B9vnNg+sE6Bwt0qolXLMJ3W065dUn/
# AHTcfuSDoxuLt9BZjQ97eicoUIAAA+6ezrT3tB9t/jDD/wCZkdbTQQQRSl/aRfw3/wDuMb76CgkbLaeVGXmsAGAgDzwzMv8AzPVHZGCZ02QP96
# uWodd88IEyJB1FGxL8D/yy9Xm2BdwFC6B7niYg08AAEeOrFyLT/tJR/DDX/aRzvC++wsEQa1hRrDDPfie+AEcSxeeisk8wZb2oUwMQIw2TWbbR
# DiLx7TMrZA0kFx+BHYEyXRvn1DSF3crBXpkYAAi8tppXrq8oAsIgA+2CNalNd9jD7jX/AKbHVzcQVbKudKWYVawwx/y2pDHNGtLrYuNASecZKE
# KPODPqALu/wRwWBXSQbriDvFDncN1kJmlUUZ0pIaAvg/F/RhonxH8tRW3kPKHLDAEvkvkF2hPGIPww/wCmA9nHHEU3labdIEH/APLHfr2Ac4Iq
# 4oSrrl5BlaI74sIA0yMMMqvb9zqUii+9d+mquGmRfqfJ69Vx5m1+Ifeoy53Ki0CYjS5x1bqUAcoMMYyZwifjf/BBzDXhjH//APywwfaRbbK3l/
# 4wx/wvgPOB/wBTKa5fsFm1OC8ICATxzYNrI898ZKLYV3VXfJpYrawLD0dihSyg2Z5q765L3wEnmFVH/wCJHrmEcE88oU2ZfHzD/vBRDDDRUT//
# AP7w1fYUStfJe/8AMMPet6DTyzT6ZpO888kmnZhGDwxigdnDBUpMP0ll054NltpDT6Ri5SmlUgFCyajv774StxUFUFSxHuH+9J7QjwwAJ0ab8s
# N//sMMNGutf/8A/jBd5BR113D6/wDww963gMK0CHBrm88/97y0c77HsGSfE9AZRj/owU93y1aRjJ928UWfw9y094x/ddvvuCq2j9bRTR27/l71
# 3tCLBCFpuF/4ww09/wAMeFQMd/8A/wCwVbQQQdhTFWrzx/46lLEZuHCkrij0/wC8kHeZWmJJx4IITzjQfSEFF3f9aoC9v2nY38P289PNe81H74
# YZc+6EkXV0BLzk8PpYixziSSZ/+MNf/wDr+/gvDT3/AP8A8FX0EEFE7IOK8sPeqpxlbyT4LL5f/wDzxhh9KHglRyo8c2GvnvRal5/W+K0YUZvX
# 2/zLhB1/fvNin2oKbT3SRZZPv8VrSvD6cU8wlUIf7jPf/wC6w85yPyw//wD+MFXmEEEFXNcmbL7QRWVPrxjz7J4N/OP+lGmH2C+rqFfuecAME/
# xUWEopqCJb6c+LYwjDDAxjD64WUIefFJOU2Ufd9sw7gItvEkFKyb8MMP8AvDBBz1PnLDH/APwwdfTTQQQSLMjkLMFGu4kAFPsvntk9/wA8mUE7
# 8YTgbUUXFfEMGd9CNOXEaJ2UX1jg298m0212m1m+s+/n/DHkmlkvsZeA/sfoShTpFu8sPf8AJDLBDfh8PDT/APwQVfbTQQU6jU+hnrmpGH9ygA
# Nvjtjvg1/r4YLFGCMkTTRUw4NT58RurheZX1jHgl21u+eccdYUUasD3yfKyUQVVW90lVgDNDMnrkviOwwx3/4wwQw2/wDcsP8A/wCwwUfbQVYP
# Q0/gtvqkhJEShAAPvAqgwglh81oy7HNodcQba+8fywxDaZ7zxXCPaLfp0XTQTQVTeZcbSfo/e03YYQfh46sPBPCFrgu6Pwww/wD9uEEOMdmiMN
# f/APPDBR1hfBLDXuW++Cy8godR8oEiW+DS2ugC98YUUqithJziYpL3PQwwwwgMIWeLri/hJfznPbyvBRJLgVhVN9lRbsq3Ec4Em++uG7tozjPP
# /wC4wQw933Sg09//APMNH21IUtPcoL7oL7yBBqXDwjZrK4r8teEMiyxhyZZG2dZiwbMzyzjzzzyxuSW9LPH0Vb5Ys5v/ALJOvxhV1t55PRTi8A
# QuGyyiX7HWCDf/AAwwVQx3/wA18fnHPEEU3lI1/wDLzOG+26OwEcYmJwE6W73v3kJQ9yMYIuOmZZ/PmsVfww08884wQiuOmWbZ5haCSe+OKAj+
# pFtVpRFU5srkkc+My++qWD/J87FN95xxDvP/AK8nLwwww/8A3PakH28Psb765qwBCzU9ZWlcsPc5qo5gOuShyiYVXkVveNJQAADBTwx/aDBre9
# 03tp5IYIb/ALKu85wcwAQ9qD6kQsAsW+CG7D/pRcRg888ADDH/AMeuvz85z3+M7QQVfw/gntvqliBHLHAmKof6ydaNloRaqHPBOiiZadRSPp7P
# JHNuz12Plht0bdQmMJDtqjMvtmIdWGDCG7doHBPPMpvg/q07SUiH+8QRTQwx+4n9wAEPPvjjtYgQfw5igsssitBDK7J6puALKNudj01755MEEl
# neQWYxgd96xwxwcVXGaGS9WR2mLONCFKgrFjdUXS9758PonEPOMgvg+w1/YTx//wAEV30MN/ERTXPf/wDPDBB3F9pVvTuOOCSuao0zS0sQkIQs
# Wdd9/wBTZAGJCtlBP3bXS08yw8C791VBnnEQT8yjkEFANTIMpQB21xglrpwzIAPIAlql6x35RYg/7wXffQw+8+DIww9//wA8MMHS60HUvO884L
# ap694IpKxiyzQUm+mc+GYBASgoZunMLO8MNsBw8dsvlTY42vIZpKIiQ4LLB0FrbNO5Txxh+gjSpLKILsf8Vls//wDhB95xDfVDYpPDDD//AP8A
# 889EaMHW8/PMYpKZjALa4rAjyD7WtedksGT776OOFVMNxP8APDzTZgvfL7Jo8vtNt9DzzTnH/RHBK8TWIcgAwY3maKCS3LRtZxRP/wD/AOsX2E
# EPvh/l/wDPDDX/AP8A/wD/AI0iyUffzz387igfwtvitAFLNMzR6ofT7TTTXcew5jH1008zTHIAPCNw902Gssohvvrran42ySFg2wNOAAELEtKj
# ghuJ593iAVceYVfSQR8DL1//AP8ADDD3vf8A/wC9H46oIAAJzW3O4Opb45YDyRjqEtcaH/3882+s/wDWCNIx7jL/AL/zJDMENE9jihnqhgsawz
# R7V9Ih9mJBDDKMp/VoEBIJujq3QX/6wfbQQV83zf8A/wDvPDTzzz//AP6c4bwkggtCIH/S349ikqKBADPsV76bTXcccYRed8lnDDDLdGT7xYPD
# OnvvPLQTcZfSai1yatAg1pKBGItpuW1POJKOgvzxaVfyVfaQQWTOof8A/wD/APyw08+9/wD8+ln3/wDPPTnLSkv3rSyKkY08wOZhzvB999pNRC
# z3++U8848EJlMcQoCdqmqZtNN9tn6nDtTMwmOegooCeu7OkAQkcCeiO/rlV7BV9NDTXgXb3/8A/wD+88sPPP8A/wA2YUQQc/y//wAJh9vcoL5q
# RTzxiJ0uWM8MM1/V0zZrIIUbyxwjAhzDwkLJ1lEc888/+GNcn7TyjATxTgrYb0ShTzAb6oN/vNWXEHX2nEEOs4uHsMNNPOPe888MHGGU0kF0Pf
# 8ACWguDzvO2K0MgAgDR5BRxxx9RA3CRW+iXuW62ay886sB5W+xZzzzxz1N1uI8k4wwEcqeScp8EM8O2KCG/rHrhlNd999JDXMY4nH7/wD+9fYQ
# Sc7fffffYVY36wsiJCw04y9itDAELjrzzzzx2irAwFoQ0Ro0s4j89qg3gWdFLqWQQRecfscHPPODLCAhqthTNAENCvghv+xzz6SdffffQQw5z4
# PKu9TTYRffefD9ffffaRa0/wCpK5WQ+8vcuYrSwxjcABAAwATgtOAv4N9EP8dPc897JXlsAzRDKADRzDSPzDTSxToIJ7L6ewCTziaoLfsM/wDt
# NdJ199xBDDTZIErjT/8AywwVfWzp0fffYUb09/wkvoNfyw7wrjgrv3IghvPPMG050GrRQwwQQSRSQQcWcUiKtjDAABMgtvHPIENOAsgqmw6BHO
# Ihupn/AMsf+0kF7sMOsNK8MNMD5KsMP+8sMPH0bMlX32kFH8PPe4KyH+M+8b76pxqRwpCATzAesOOTF6GV333333mGnOGTjJLLQjDjLKpCMhTz
# 4IJ76o/liQoJbqY5/sPf/wD5m7Ee++u+3/8A8I3C4ww//wD/APDBBl2XB99tJBV//P73Bd0wsGC6zqM8MIA08gMM6yPfAaBN1xxBx999Xr1SM8
# yKGQgMIAAM8rt99992KGORBRoCeyG//LDT/wD/AP0wAT7Lb7v/APgcs7xHLDT/AP8A8MMEFKGtH330EEHHf/PttyBxBsMNULrCAgAADDDCwqJB
# R0E/PPPf+8816uxzygLwDQzzzzzy21mF/wDfrDXvJBOCeiS/rHf/AP8A3mIyBCB8sMP+JTwr/wD/AOww88//AP8ALDRebLBx9JBBBBRV15VrD3
# Pyym0VqG40Mc8McIA0sADdX/8A/wD/AP3zFmTIwcMcoUsQAEc8yI4cyCG+yyyGpBBgeq/Df/5xxxbCIQAA2L//AIBPLB//AP8AvLDDDT/vfPDz
# l3PBVtBBBB9D9pB9vfznPPs1CA8s88488MMAAuvNbzzzzzznNYikAAQsMwAAIw882uc6G+7DDLDDrBBz6unf5xBNNNSkAAAAWL//ABPPHAw0/w
# D8sMMMNf8A/wD7w1U/7wdfTTXa4XfbQccdzw876ZQksMMMsMMPAFARL1fffffTSackPvHMMIPIBDCMNTjMBuow/wD/AP7DWdBVi7X/AARfffau
# CAQAAlq1/wDzzxCgNPf/APPDDDDz/wD/APFe03nXk889nZH332020HHH8Ors3rJIIIbywLx5lhpf/wDzjDDD+Evk+yyyyyy+y2+5JYG+DHbzDT
# /rPeN9959pNFNLD+QEAAAC+D//APPOAJCww/8A/wD/APwww3/+761fTWYX/wD85s8FGFnX330FetOsn7a44LDAY7JvwhDL7ALABDCBCRRHL4I4
# IIIIr2QZ7Kd/sMMsMPPON3+8vcfsHEU1eQgAANaN/wD/ADHIAEDAw/8A/wD/AP8A8sMMfE8NPf8AvDBxhjtnJRxBBR9tJF/v3rpKyyyuOKO2LA
# O+iySyOAAMc8sQRmyyyyGOKBVsiHf7zDDX999tNx9WDd9xxBB3/wD/ACAAALsf/wD/APPCQQVAwwwz/wD++MMNdfcMM/8A/vLBBB6rpRhBBB99
# JBR//iy5BhFLHPLMeue6y++y2OCAAECCijPPLDDPLNMmbzjDLDDX995xhZZId9xlBBHf/wD7wAAFo9//AP8A88sBBBoDDD3/AP8A+88v/v8ArD
# T/AP8A/wD/AAz1VlxQQQTffffQdeYQvvvigEspJ6Rjw0wzz9z9vutvqvWAGsjDDGsnt88wx3/ff8QQcTdXneQcQQQR3/607gAug9//AP8A888o
# BBUiDDHf/wD/AP8Ar+3/ALww1/8A/wD/AP8A/wDiv3LBBBF999NBRaPPPLD3/vPce3//AM8ww0960ww1rb//APPPOMM88r0MMc9/32EEEEXmGa
# UkEMMEM/8A/jDTIGrD3/8A8/PPPAQQZPLDDDDDDAmk/wD+8MMNPf8A/wC/+Tq9/wAsFFHH322XfXHHG88MPPcvXOMM88sPe889P11LOMMc99/8
# OP6UMPfnGEX333lsh0EMMFd//wD7DDDHjWjLbDDD8888sNBAAAAAAAAAFjDX/wD/AMMMMNP/AP8A/wCn0Pf+8EEHHHGMEEEEEHH388vYr088/w
# D/AP7y8876FDzzz/8A/vEMGHOXXnEEE33HEFchcEMfv/8A/wD+4w0//wD/AGrDDDDD888888BBAAAAAAAAQDDT3/8A6ywww1+8848bw0/7ywwR
# SbTTTTTTQQVecfeAddccbf8A/wDDHh8xDDxzzBBF9999iJNN9xxBf/Pr5BBfvf8A/wD/ALDDLX//AP8Aq4sMMMPTzzzzygEEEEAAAAT6oMMP/w
# D/AP8A+8sMMMNcP+MNPe88Ntk3333333200EHHEI0EEFHFHf8AtqjFdtNNNJFd99xBFZtBNN9xlNNXT3P/AP8A/wD7DDDH/wD/AP8A2kQvPHPe
# c888888IBBBBAAAebsLDDHf/AP8A/wD/ACwww1vPrjjnvvmrYQQUYQUcecebTTTenQgwgkogg48FfcccffffeYQTTXfbn+88w8fbfQ83/wD+OM
# MMc/8A/wD+9yPDHPPPPCPPPPKAQwAAAAEvvr6zAww089//AP8A/vDTslRxxV4wyOjPTvPDBBBBBR99999W8QwsAUsAaZ9pBBBxxhBBN/8A/wDs
# fIEEEU//AP8A+ww28wwxzz//AP8A/wD83FJCNg04w/PPPPAAAAQwAAAAHv8A9SsMMMPPN/f/APv6L373/rDDDzl+/wD7zzywwwww0ffUzvfffd
# fdfS2QQQQQQQQTX/8A+sMNqEEEP/8A/wA884wwwww//wD/ALzzzDDoo88AAwy+8888sAAAAABDAAQ2+/n4KDDDDDDDT/nkDTz/AP8A+888OFcd
# P/8A/wD/AP8A/wD7wwVWQQUcYUcQUcYkzf8A/wD/AP8A/wD/AMwwx6ZT7/8A/wDjDDDDT+/nv/8A+88wwww9GHPPCAAAAPPPPLAAAAAAAQwAEE
# Pu+piwwwwwww05Cwwwww9//wD/APvlODDDT/8A/wD+Pf8APH5BBBBBNttNJBtT3/8A/wDPvOMMMMc//wD/AO4wwwwwww//AO7fv+MMMMMNSSzz
# zywAEEHzzzzwwAAAAAAEMMBADb/zyyxxwwwxgg8MMMMMPPf/AP8A7Rwwwwwwwww098/T/wD/AP8A/wD8PPf/AHJzDDDDDDDDDDXB5DDDDDHPPP
# 8A/wD++oCQwwwwwwwxhzzzzzwAAEHzzzzzzwwAAAAAAAAAAB6EAAAAAAAAR64s8sMMMNMNPf8Ah2PLDDDDDDDHP5zzzzzDDDDDDDDRvDDDDDPD
# HX3xDDDLPf8A/wD/AP8A/wD/APHCAAAAAAAAAE88888oAAAA88888888sIAAAAAAABAk8MBAAAAAAk/++++/7DDDDDDz3zX/ADzzxzzyx8Qwww
# wwwwwwwwxw5Zz7/wD8/wDv/wC4z3//AP8A/wD/AP8A/wD/APvMMOsAAAAAAAADzzzzzyAAAADzzzzzzzzzwwAAAAAAAFTzzywwwwxxBb//AP8A
# /wD764888MMNeTDDDDzjjy/9/wD/AP8A/wD/AJz7/wD/AP8Az6dONPPMMNKHW/8A/vvNONf/ALjzDDDsMMMMMMMMc888888AAAAA8888888888
# 88MAAAAAc88888MMYgroAQ+/8A/wD/AP8A/vjziw30wUdfffbTR1//AP8A/wD/AP8A/wD/AP8A7zzznd9999999Z7u3jDDDDDDDDDDDD00QiQM
# MMMM888888sAAAAB88888888888888AAAc88888888gAA8BAA+8+/wD/AP8A/wD/AP59+MMMMMP/AP8AwXP4ww3/AP8A/wD/AP8ADDDD/wD/AP
# 8A/wD/AP8A/wD4wIgwwwwwwwwww3ovIAAAPPPPPPPPPPPPAAAXPP/EACURAAMAAgICAgIDAQEAAAAAAAABESEwMUAQUUFhIFBgcHGRgf/aAAgB
# AwEBPxDor1tSu7V+UNGxohfl7kjosOeHlgoovkQQT2GqFl3clUGvOpDF2mc63nBxtYwPW+AW5o+h4CRCEIQnlbl4SMLVz3FhzUxPnelRZR6nnB
# BnoJRZdEtTXe0JFpbFsXQYnVparnReVOSEIQhCEErrGqug9wJa052VnO19BiRkyZMmTJkyJtOMfQywhprCP9n+z/Z/s/2U002w/DW5uKi97W+N
# 0sI/0f6MmfZn2ZMmSXkXd5epKNVvYt1Go6vHO5q4Ldzs4VZk69XtuYtrEpr5Xe8prhi/Br52NFRIW5PWh6wlrWMdtZexqj/G1uCRV7E+UJ1Xw8
# eIyMjIyMjIyMhk+20UX5exPkW5a3uwdRytnLcsp78Mb40gHGTnPQ9tSG//AAFt4e561uZg5raCUU3JUNUQVFnL0waOb0q/L0SWBYtzVE9y/ClK
# Upz0E9CdV0syd6HDpRzWgnVdyUQtKFydB4e1mE01VQlKuiv+n4TxPKNrBIp0JISLYnQ9iUYvwwYMGBwW3Bh0ORLYhoySSSSSSRoLi+GJ9DLJPo
# k+g+g+g+g+g+gaLgaOg3k2tUaqbJELy0hqz6D6D6D6B+gcgoqLe0QkQREREREW9ogJI+RbnnGqCB+90FEJTdyo9SfPhaWJSMdQJ7kcvYtbQmEN
# VtYnzrSoso9rwqxZV72h/gjKKKKIyMjEx9C1tDuHKM0La3wJTsRQk7Fs5c2vKnK2QQcdBXkWClKUpSl3JTgfDG2rLvZYxpEpVrbglFtao0DXil
# RSlKUqE14aq3pUS1La0cMQR8i1tcduiGyhall3enyhNJfDrz/6K9/j6XhJuTWndyCYnDLLU3EJ77bLKrwy0NnGN7RwPY3fE8QhPK8tVbUotacc
# 3MVJjU/ULQh5fdaHOa4KiCCCCCCBNN9F0lk5i0r8E+diXilKUpSlL4eRqtzRBSlJJJJJIILVgSLaugyE0YZQnVd7Y1p+RCRbmpqTcnV3If8AwI
# QhCE8o4fdWpjRzcxdBrX8iWpfgnz+EJ+EEtzQ/xtkohItTVFtW7nYg0Xa3BvrkkLWvz9lll+OHQeHRZzrWDJsPHaYtqdD1vxUFfLEtifdeOakN
# QlNq2rZzuSoerOtoR2+EJuXcyzqbSVit5e5+9r1s43vK6mxiUcsRAm5a4ZHvWpDYBb+NthSlKUpSlF0Gh5gbKUpSlKQVEyf/AASGt6SzSx5H3l
# jzCEIQhCAkugzlkIiEIiflAJ6rZ9h9h9h9h9h9x9x9xx6LpjroAAACnLFpF5e1uKiQpSlKUpWXxg6hOq7UTVM6UN/nVVasb6LYlrbP+aEiEIQh
# CEOH0GQhCEIQhCCXl7XlsaHjm14RgBJTUsY6Cy7skoiDUxb1va1tFEJNqDRrQiwz7GLU9/psaC5gtb97n0Odayu9axuI4XwhJs4e14EtbGrggp
# tWMbV72v8ABohCeFFFDXiS3pUPVH4UUUUV5OCTHPils5FseXsgqUyFtYs6+cduOeikt0tBMzhCXQeURRRRRRWVlZXBLW/GJTfw/FRUVFRUVEEE
# C7jW9aWPePLFpF0G4hPl9WCklX0GJ+YTxCEGhv1S8TzCfg8VHs3Eug8utAWUYu08Z68IQT+PL2rxCEJ+LVEug0Qk6z8Yne36dl+/wa1rucr2LK
# EshdpidXZXrzz+mb4Ep2GQcFFfwpSlKUpV0Fh916V27BZy+01RyLXxvaonVr4F0YiIiIiIiIiLoL1syc7l1URa2Lfw7r5f6lnOt9xofN8MT1vf
# KcaX+rWH+okgjSzsW+ogggjwfcfcQyfq2qQuT7j7j7j7j7j7vIW/q3vhCEIQhBoar9XwhK5ZCEIQhCC/Wcdfh3oMWpD35OftmLrNDfG9ZzrYnV
# ubiE3P+AP2cra/W3h7Ucv9zUVFKioqKiroLDg9fAve1qjXY0Ep0G0iCCoqKioqKv1PD3tCdWt5c38O7Fl3o8ukJ+vYt/DHpeBLoehPyhPHp0X6
# /Z8b2qWFeivRXor0V6K9FeivQs9GfJXor0V6K9FeivRXor0V6J89Fe/2i9djh9F5xqXroPP7V9hoT+N7whanvYl+2Wx7HjO95ezjdy/27F2F62
# ti2rYxfxBnOzntT+JcPW/XQXioqKioqKioq/ijQtS6LyQhCEIQn73JkyZMmTPSZkyZMmTJkyf70l/DF0VpYuh8/wANYu1xvYv46ti/jy7T2v8A
# spf3lCEIQhCdOEIQhCEJ/T//xAAmEQADAAIBBQEBAQEAAwEAAAAAAREhMDEQQEFRYSBQYHFwgZGh/9oACAECAQE/EOvG1CediHigtmaoabbFrG
# 8Ld4BOBuCyEz6ibyz/AKJ9i64NBYx4U28FFF8rU2JD1oe5ZwcPWsKs5d2pwSA3jUhKIb3JweHfA1YFgpSlKXqlRdrEPUGpq4XeJVRaUqP4Fufw
# xzCdWlFyxrw7DBQSIb1Qd3MT8lGUvW/hIex9gmNR/u9E4qLsEzeRppAPEhOuwSsN9boaqhJtYtTUU2rsEhvJgwYMGDBgwNGqhdg0URv0q/7n3P
# uUDVHqm74SKIezyC2PByGT0P8Ajon5BY8D97nne8IWloJW9Kj51OM6cOiztTyPb8Goxa+XEPCLSxvA9qGptQ3XrmAXrdcgtScYvh0bw9jy4JRD
# 6zWtVFqaEssbut5V3c7XhQWtozJUJ3YlY1Y4WxvDGo4x4yJ1XpHsgj2QQQQQQeV9hYOXAtKVDzC2NHBqbUNa0c7cEZw49jf/ALBbOBIvro8cKM
# jY6QQQiGSSQJJBvHYNXOi0egkUb2MWVuWtvG5OC1BPUvkbq7njEolEsWiiYkwE90FT70Qv1wWD+NycY1tQ/wBwhwuwdcMStKVHijsOB5hbqWcC
# rR7nrqQv08uCb5mSm1DGdIAFNaMm9CZPRSlKylZWVknktd3sVtxDxhaZ1Q6XKGuyCFg5dKVlZWVlYmx/LHr7DhjZSlKX9tiZFlllllliYTL5Q9
# 6GmBe4oroUUUWJ8GNVvZmH1pS/ujRmC8C1NjdUb6UTYxFfiosCDHvSh5YKK+isrK/zxrqKquB7lhU50pixRvG8G9q2AeDo3fwhfhEnRIqGtzFr
# EN60+hNTG1KjVzW/gsE6tqYt6YlX2QuT7H2PsfY+x9j7DUcusb/KF+UzyibHsYtdY1et421FsR7OAtjQNHNbKKLm7DEMiIiIiIiIiIi0L9NB8o
# k2cseE1oe1Ckoc0etKN17YMhkarrn9vpJ724hvU3+0L8oqI5Q9TYsDd1vfJi4g9WCgtywhyORCxCfRPpHyHwHwRPpE+j5D6UW6zHpWRqOftC/S
# Y+USepKhvC7tEcPVy9std3pwkqFi6UvSlKUbHVqotkkMelIsr+0L9IqohqB6GxIuuE7FoKUvJRRRRZZZY00si7BG3Ny+DXSjFlmRJPUggggnRZ
# NyZRg+gUUUWWWYPI12IfYLBSlKUpSlZgjOUe9E1ZR6Wr+LMidV/V/Hi3J+ZaW/AmQorKVlKVlYxZW3neh+tScEqgT3XElEPUnn8Qc6UpS9aNjd
# ELYnCTq8/haHgorHr1Jxj2vdwha38MStqVFzDV7Go/wkI9EEEeiPRHon0PqLbIg1MdVoeXDxbF62rahu7EJk9C2VdPEPYlWxC9i306Fobh5GNX
# tfva9jwhbXjKMa0i/9xvckexZFvarD6LRyHhFuXrah41I53+IWNVXXwOdFu5qrXB2BuI+i0MQVG69/O2VCRCEIQhCD9dg0KBaKOD4oxvG5jTmk
# lTBknRbmrgykEEEEEECUP4XYJw4dS6RRjS4kfI+B8D4HwPgfE+Bz7HBQg4PgfA+J8T5nxR8SHCGNX0fsTq2yoMuCIhCEIiIiJ0mAWNrcRZmEF0
# P6H0Poffr7RtIfYJWN3Wkf/ZjfS9KUpSnKFvSLWUpSlKUpRvz1aObGxIpdacZ4Ans5YuaWd6LRyr2DwmyjrLNSYnne/W5jVa0rGr2w1Q8prbwX
# QXw4Q30WhYY1uXyPWlRwPWs4ONq9n3enHqbOE3JixUJ6lli5fLGuzlbZcDfjYkVDV3YhPItj9bV+FCySSSSSSSJWKG7vaC0SQQSSSSSN3go88F
# A9nGR7MFdlGNMNyHh6+O7vjsKN2o9KVj/UxvcvXSqr0AAEEVG9aOUN73lCKKKKKKKKKHnvG8b20oQsvA1r2CVRD+F2tBR9gmNZKUpSlKUTyJH2
# NL0pSlL+OBZ2tzpSlKUpSmbglJG+wTIXtYMg73awncYE0JM9WmNrdOcFRUUvS9UxvsKB6+2Rwhruk4J57lZUZxjqndbfRd14O4kymHd+jGo53P
# t1Tj1vPdrmjV9y1VEHPxGRkZGRkZGRkm/JXal51spx1bSw+i18i2JXA8KLumguAP8AFKUpSlOVvaCR65WPbz1sKKKKKKKKL1WxPOzFUbvdwwyj
# WmPfw1rC7p716OMamLs6Uv7TP/yGtazvTg3dK5Hv57t5V1PL7F7bKOm8bH73Mr8gXyPkfIh4KuOyz+MmTJnsk4Ux8j5HyPkfI+R8j5EnRbn3a3
# 0pSlZRRQshI8dg+75cG4iKKKKKKKKH76r+S8rY9fCC3pVj1NeRbmxYqPuH3qY1O2TgvkT2s4U2Go9yUN41vqv5LfbrKjOHtTyPY1ULY2JbR7H3
# /JGRkZGRkZGRjxuQlVE9fI8Y2pwSPYtdY1fYJN8FFFFEZGRkZJ3z6UpSlKUo1VvYarXgrv5UFqeThN76cKFKUpSlL/JTGpvagTKUqKioqKUSrG
# 96E8lKiopSlKUXyN3sE8jf9Llb04Kj/s/6I9kez/oj2R7I9np2N8E+yfZPsn2R7I9keyPZPs4TsOR4x/TTGvO7kul5Qt7E86n77BYztf8AIXrd
# xqTE87+WN6lvSo3/AFn72LYsqHG1iwtj3LC/roeO3QnkWxKsb2I42JDf9hvUtyOHrZwt3OxP+Q/5Tyhak8je99IyMjIyMjIyMf8AbpSlKUpRdg
# mNQpSlKUpTkeMdiilKUpSlG/7WDBgwYMGDBjsl9MdGDBgx1Gl47Hkf+MeexelMa7BYX+NQ8b171871kf8AWfccoW57H73cL/Hoe3jatq9/51b3
# sf8Akn/FT/zq/wBfwUpSlKUo+ypSlKUpS9nS/wDgv//EACwQAAIBAQgBAwUBAQEBAAAAAAABESEQMUFRYXGBkfAgQKEwwdHh8bFQYHD/2gAIAQ
# EAAT8Q9SSypxun5DEx9xOk7kEwMUEy/YuY0qfoz6Y9NLUJNtJDGWrveWbFq4I9MXy6jEJCUJJXI6tjQi3khZkfQXB0LZC4FI2ZlvR4MTKaO27g
# quxKbjEmMQjvTGpt7nXcNvIqVIEkKMkLZHAtiXkyXkyXmJeROiOERsRqQRouiFkhFkhRkcE7aHCoiDFNIfzIVJVd9g22eXkeSKPGLyop8ZLzXZ
# LJ2bXZuRK0KeI8uPLiufwcl+IkJafA/EDnIaeRDz+SHmJUSNu5/gRs73j8zfBe2jVn+VfKKWu/0NrQUaDVOhwl1e64K7sg/J+I1LwejFeToNPg
# /A/2H4j/AGf4kj8vwN35/wAT9r/ERv7/AMB/uPwE/wA34DRf4NjwfwH5T7Df5P8ABNKiX4Q+sTX73gYorCqppXgVGL8tnkbE7E9BMTYmyGQRZw
# QeKkDTK+udQV14mIpqV6uEJlQZPAwe4xR0w1Go1qNDGNksm2hQoQR6JJJIYL2LiOWSVYkaYVbNkz09K9lM0kXPcohKX7ihEMZNzInJ4MSjDIZA
# 9H9SbJskmyhCIETVrYpKioWf7P8ALFqS9lChTUjcjVkakakIhZkanItyhCIRFnJz8ieomJsTZLJDwSNquOjFws6IotVeyV3kRzpw1VMUq67msm
# QzRDMhZsjVi5FuKk2JZMlkyXkS8hwK5EPIjQoJIUCFHGLgUKh0QZBwKpQuQ1zaddRvR2KPGJrTspl8nHyKchTkVyJeSFOSFsjropp0bjd/hCzZ
# CzZQlEooQrJgWr4HwoyU4FP859DVzYni5ui/C3b/ADUnNC9FyYNCNNptShnEMr2HwjAzwyX3ZJSSVE5wt7JPFsZv4NZHcQXni0BdpHiMz1jyng
# N5Ww3wDMJFSIqL7RNKm23CSxYkCu+jl6uLnuV1iFAoFAhIh5kPOxnPwUz+CmZKzJRJLKlSpLyK5DlrAY5YYCbkWA0E0QVgThXi19256opeI+DG
# N6nNkbFc0Q80RqiPpNBt4DOfMuE9hU1v9EC1f0ZJJ+ouJQF+FWJC91IpYEei+YWD+wyRar2iHISJAzljJPzcU5rmQXIvq7Em3knVE6okm3kjU5
# tjUjUjUjUjUroKRToJvJDPIdVYuRO9DR+HOb07Mn9OjPVaNVKkYb0Y0Pdlc2JahJ2cIjQh5HDsknT5OPk4+Ty+zoRZIRZCjIrGq5sQiqBmOAJX
# FQV49CHoXQ3ojhHBTKwglgPLiXkyWTE2pLMl5l+NiDrs5XZ0RoNaDWhwUyYo1E1mEyj/AM2XoJ3PGHyr5JO55nfiLhmFjUe1JKvX4Pd+0FVR0i
# D4Qxoj1h6nQ2DfUb6jbMesa5oesev4G2fwPO+CW75KZMaWTG+QFoVVUyb/AARwV7E7IEJCTEnmxJ5lczliRCt5HGZTMpmihQoQQyGV0G3SlXDU
# oenqK5EE4k8238q/gkdIkniVQc5lDV42N+qltSpDItoV48i4l+U3ApFzwvyM2n0QRbBBBBH0kpcCq93Esa1sRJfu04aawEqZJqhIvTvIFeJmLA
# aXoj0cfRgjcjQjQRIVXoLpeBuuHC+zdHec+uSSSTr0dE7E7WQRuRuV1EEJaj3vc1bMiDjalKv225krRlAbDeqzGnoVKkMhiFGhTTsjX5IdhzZU
# h5FciugtxRmLQm6KsYVuGS6EMTl8mqRxqONSE8SGYlrYuOyPDEkEsyEsg3I4GwhZCWQjIJZCorkQPf4G/CG3muiXp0TkG3kJ6I0ERmNpyr01cy
# I9o1qn+c7+WMNKmR4VmgoNUopdIa9tslvNidR5b+R5f+jJ5nwNc/getjcx60N9B6HY2/GN6/JKzJeZLMbZjGMbjAklrXiM200eWQmIQkJCWgoy
# FGRTInQoeXkEEbEbEW0KErUlEolDZVFcx0clUmyecanm4/B12JEthjHZBGh2UKEEFSpX0STYp/0GhQVCqcaP2MJc/U5OfpLQiEvvsJQvbR6oHL
# G4kFVN6uJfcY8qCPoc/RkwqivJBl2fCvuMwbbbPFkksEcE6E6EknR0dFNOyhQlZErIlZE6E6E6InRErIlZFMhRrbGiFOQZ5FPFkoU3Zs5EPowc
# 5NZZ6vfZ7D1YLk0KNSm4dzIebEnmxbhLcjcpr0Ss/gnNYQyJWXwTv0TueXkeSLQQsiFkNSYN6Ua5DSAqqnV6E03RbjfkDaxKiAkFHiJWa6JWhK
# 0J0FNCgkQ8yHmxJ6iT1FIt0RqNsyY3G2g09Ohp6DTIbf6FOT6E34hynLlTYMdQpSXf8ORtdtkoJrk0SKqu5vveL+w0Y8xvqPQGhersN6h6w9T6
# H4gZbcDnMaY6YEkziJLMhn/hWomq1Q1Cq1dP2EIS2EthFoJLQUCeqJ1QnseXWwQh2STbwcEaEEC2IavTvL8uZIw6Ji1zT0aoMlXg2U37kxg20J
# 6E9DiT06J5LonkiehPQloT0JaEtCRMmieCEhFIdFS5IlHosFksEOrl+iCGQ/RX6OoNQagU1zGi1XXJ5jNtt1bEx98+gGC0qK+h4oTbSJypI9EE
# emWT6YHmkm6I1FNmnMm1yv7CUuFeyASPLiviK+qnp5OfgnyCfIJ8glFDkW9kCWolqKcyRILJvBiDqBQ185owWJOzK1bB89kvJibyYm8mVyI0+b
# GwhkQ1IELMhZrojWwlohXXIVSv9GO6POGmYq2iuFGWPAvG1mymZCIELL5Kf0Ro7I0E6IkW7EtWRqImxL1K5spmKNBRkUyOGNaMa3HyN7jerOTn
# 5E9fknbsiPbkp3OuXF/Q568tNPbHpcuxxtWOHiHGYaWY4KeIe7ofiCA4z+RrVdm5dkLTscZIl6dE4I6JeInkxrJwxQThvyeDEkwyGJjCnUW7Fd
# icFMiNCCNuzlHKHuiNURqRqV0K6DnNFc16HyTuSYbkTEoDvVjrsgXCm72S8yXmSySSWSyWTqSySSSSSR3DYCnP+Jkh5cK5EEEemLY9NfROpuNw
# 0uJEaHjf2L2L318OjHnxebL97hjEkI4aeBE4eNlPoTZPohjJCohj1RPPhnwusy2xxbBBDIItnQ4sh6EPQrahRkLYS0I0IZGxDEmJWHaai8qukT
# dLmvsyFeGlKn2N1Wj0E0bwlCrhP4I8gjaxIhlcjixGogjYQ8UNr6NomQkqsazor23IqthTVw9MuO7dR1PdMhWuU3Ekksl6EvQTeaFOaOidESsh
# QJLxiTN9kM2QzIWYksxJZsS1ZGpUnIPINAbY2y9kPMln8EPP4IXkxr2xOLCeuzkZIONGMCvBi6MflSV4yGfybvkeRobeg0xp5oa1RyiNV0Rt0U
# y+CchTIjJIaenY9HybH2RmIfZMi60bcH6AhCW532JLXsheMheMjbsh5IrkiuQ5y+RkMrZNkkk7E7E7DqmnEMmNMZMTKHLZUhkEfVoQpYTqw+BD
# 6slhBBFkEEEenlkfSVGQtQTWKJiKtVtP+BLeqhN+qHLNycRE6k6k6k6k6k6k6k6k6k6k6k6k6k6k6k6kEg5edFmIZKkzsE/N5EISSUIgjX6tCl
# tLVObFObK5srZGgpyFsMtSKklH8hrpKqqIVWzuY0eh+9NOGhyUZck5nZOZ2S83ZLzdkvN2Tmdk5nZqOzUdkvN2S83ZOZ2ajsWY7E2bsexVpUsU
# ec6aYXe1b+EQCyLvvVxAy8L8iHGBAjN8Fc/g5+Dy48uspkTkiWS80TqhbiSFGTFsyRRmjcimZs2NvNks2MbYnRGwmxklzKeCu+yuSmsiarv2HZ
# Mdn8k8nY08yGV16K/wVz6Fc+hDzfQ2zHlDfFHIhZspmzkUyY1uPcbjeUTv+BzUiaahoc1qlVs0NYUnLFuyFmyGbIakFCgx7lczkjc5EIhZkEEF
# MimRKJRWFehCNNuCmaJWZOpyclM7OUTqcnJycnJyc2JIkJJLFjrGuTkf2LruV3uWhxmOdrPuX/AR1LAa1BpZmLvngS5z07nJD9T/AAR/S/wQ/S
# /wQ/S/wQ/W/wAH8r8D+R+B/I/Ah+j8CP8Ab8Ef7fgj/b8EP6fgj+n8CH6/wIfq/ASL0BKl5XCtaahpw08Bck4rc7YIODi3k5JJdsEK2SSSfROh
# sE9BPQTQyHlpK9lwYFNYMZ0v4JzxXJklECziSa1nDHi/AR8D/LAFK3HEkMSnkn2EzxPgSPzPg8a/An+j8Cf6vwIL+sF6zchInDVUmmhOVKuYyu
# K5laH/ALojch6kWSTsddnKORCcCTToWzoT1XRyuiFmJLMUZspqU1KajehOiHsiHkhysBLyVjEGjynD8N2hepIjgly3HS1Z20HeQZ5OyWTsaWKd
# seRIQUzZysSSimY1qumOc0PUNrkPLXZpLs2OyWxT+GNZHQ1mXQ6T0egqTXipesUMMbEJbCTWQk80V0OiFoQiEQIDQyGVIZBUqVOLIIGT2uQnPA
# g2umRLuSi9j8F/wflv+D/UfiNP1/iNP0fgR8j/AAj5H+HlH2I+Z/hH9P4EP0fgQ/T+BH9P4EP0/gR/V+BD9H4DV4nwIwOqndNID6kSlw1BHoj0
# V9i2jV6FpFR8L98lLhFOUu95aiYLvDpnyOTHJs+Tb8m35NvyQy+SGRDIhkbDabTabTaRyYtLFuWzSPDAUrUeOOTlV7HNDgWnFiRbQoUyJWRKKF
# ClihCIWhGxBwiuRXQlidnRGqEnmiHoLgUC2PhFAi5nkqQ8Z7tTaSplXRgQZJEp3nlvwR8f2sWGYQ/QPA/ghYZoItbsSZ+yGftEP7Gn9DzHaGoU
# biZTga0E3IpU4SjEbBpptemr0NCXJi2qrVWaGVVIlOSNGQrBTJlMmSteifIJJeZLzZLzZO9hbBBQKCmnZTTs5Q2ONRw3iRkZCyY0smNJaclWqS
# RMP75exIY72u94LgVmFSxYy17GmvZOR9j1OxwsRTN0To+ini9ARAlZ/BHN9EM/gladELQ0MbZjbNjTz+Bp5j5GYkon2jVXRmhhtxPcrqM7pOSh
# QoUJQ2tRvcdvR0OdCpBDK5lSGUDde3H21CV7buQxKoLuZe2VzYUVIjo5vGv9DXN2Rzdm92eUnhJ4SNM3ZHN2Qzdm52bH2bX2bX2bfkY2SUTfUZ
# FN1WvgHxcVoK+/6/BxbT1zCDri48mNNmmoav8AeQY7giVcjr9rIFOL9ckkk+iLWJwYity8McODENRCepR3cyFkQQRZwcEkknNnBxZTIQiCLJ3E
# xM7OynjFAhJRfoJbVLg3P3d3JHqNRbl0RshS3b0TojZbooTr8ErP4KeI3fBOdE5l0Tk10PYPUm8wnXRiFbqaSsBU2JXdMVNXUcGH5L/e+5EmxE
# 6I4I3I3IIeRs+RJZMJpYfJDxkCRN5sTebE2fwJvESyGNPMoV5G52VKke3Na8ze/hMrAtE1wXAzDJZLbd7H1F8JZOh7/BTN9EZvkRm7Mha9jn5O
# fkpkG0jKzE6t8HJDzRGY3EvU3kha9DjJ9DgMOMkJiaE+VibUUs06NUadhqfAqP0IJpq59nD7I37IRTM5JeY5zHuOSpXI4J0HbBBPPG5CSryJTY
# VtDV8fhfL0KqP7I2MfpqVJZPrpGAxYsDML0JiaDqk7hjE8LeSdfox9VpUZEUt935e8RskMNulMmhQQm5ZLBCy9Ppz60SKcSri9ApU6/YLnwJDK
# G3VEMh5kPMggghEIoUJJ3OzllNShTxiXkkeT6J1EVIYhPUqe/wDwZKput/GqvVoiE1VViorifSEk6k79E7ie9k7Ca0JWhK0HGY3AQloua0HT3R
# mGRqnUUVFIXPJrRqvI9hE001RlC2hkpiIUm9ZMoU1OyNyFqcMnQlkOziQIsWQTeS7E3kuyWTsnwydGN7kWS8kSxEksEkKrbuQtO69UbDZKhKAn
# qXvFj/GODcvken5GmRKKajjUbWpIQpqOzv4I3+CLJeQ51J3Hu7HqQ3OKHsHuuhrVdFaifgYi6o0McdmM0J0EiGQRY3oToN6Dew2S8xvUbWZTMl
# ZkrMknYku65RFHmM2uTFtEpZKmwI8l7at1e41rNblNyG9+x8nDI0IRC+jzZBvCGjCEPXWP3C2oXop65+lP0E4cmASqGOY2GOfu41LvZCN6N3Bc
# WQLYIItoUKempLJEx6EvQqJSDbxKNMoaRZ1uf24HoeGImmpRJ0dHR0QJEehISIWZzZ0UKFNTsQnouyXkhNhTkiOTShViMFqdXn9HoidJzmIK+R
# 7HFkHZOr6OWcsnUTCb1JebOWStSUQyGmTG1kx7fA1tfKtGA9ATWjVcPkps0UlxKsoC9FePtOyHoTggjN8CufwJeaJJ3Kam5kZhxn8E6roTeYp8
# ZE4fJHkikTZOg9mVyZwzgVJ7oHdm8Pl6CmJqhJylLF+ZiRn2svNRNhrYjRdkPJdkskQ9CX4yTwXZXJdkT/RpqQzZDNkJYjkVzD1Mc6jbG2N5F2
# N5Ow3kDnQaIacy6ExUEF4SRuMMNYqrAhaHR0cj3HOY5KnRTIhZEIhEIggoZ/gJHI5zCjPMOWvLLpDoTHnUNjZJUqVOrJ0J9HBBCIIsgc4Md9D5
# T1KFkiY7EUaaYWcnJyc+1witfsXutoGVdq6zwIc2SyW8xJc5fSkkn0ySJiZVNzuriQ4m1vN8FoXEmU71d6oIRQkm3o6OididhbHBBDskTEIrKZ
# ShYt4CUzDSLm/4XLYWpERCIeZXMroJvJCbyJ2KaCSzELMconVEvOwrmiuQ9h7DkbYgsqnKIrVm3cyjCWTRWYLuVdwTKlY2XPc6oiG2F+Q5XNie
# rFuxPyDn4IfiK2NhsK5ECHoQzcQWglZErI4R0dG02EWr0Sl8FyecsV7bdyx+ZVxHgHIcNsh1wHORLyJIeIhlPBSI0/whafA1OQ9CNnyQ8vk8VI
# 8MqN5olanY9mN6McPMeh9jbBDT06HrHQg5KoWpauYYodDGwS0IZEIheMhHl428n2S8mS1Gw2ypXNEPQh5FcjgbSNuEkNc2NyEduxNcN26Lcj4i
# 5dEiojRKENeyW3LG0NjsqT9ZKA5uJW3Dpd8Pdw4mmowPpR7BETSCNxe5OcIll2otq2ac54mJS4FRR9KCCPRJJKJsU4DRJKaeTRXbJCu+2OuzE2
# tq9ClJc7ObJJRQoUJJJJWpTUpmQs7OBbCZJIoEkJD58R/oiOUi4qnHwpxuzGbIxJI1NyOBAloLYTFQloIQimROhLyJeTJ0ZOg4eA0smNIaK6Uu
# bkBXulVPNrVEqlwSTqiuA1TTKi6GIpaYk9SGKciXkuzy8jX5LsWSyWVOUdE6kopkLYjT4EnkQcE6CKR7U+Tk6bLUSlQ7q7lguRtXZHCexN+x+D
# HqfY2DfIPWjehvoSzXZD8ZNg5YDTIhkiFkuimhQUDQa1+B7/A9xjbwS7GyfJLGR7iGolU1mjRfzibSyQMimaFDVwjVEbDWw1sPgqeXnRLJehE2
# kEUJuyasbE6KI2zc4+BOXqyvGbqxoZ0dWUzObZJJG7II9Mi49jo5RTtyl8HyVxKjOCuRUgggj2cD0ZJ2BXdl7iZy1cOVTX0M3YmPqpbT182SSS
# JiL0dVGRD00i5dz5uY/I22L01gVi6O7ch5kPMgjUhEWU0FGhTQ6OjhELIjSxDMg4J0E9BbCgiEpliIUXtuRVbbIVdSZWC47u/kuEmEQtSFqUyZ
# wV1KlbEtxbu2BDkQ9SupLyY29RzmNasa1ZVVTZcpRzFzQtWMtElTzGtGQDWI51IYLnfuV8ydUJiYzUcJS2xeM+54y/J/NX5P5q/J/NX5P5K/J5
# K/J4f5H8H8j+T+R/KX5P4S/J/GX5P4q/J/AX5P4C/J4C/Imchyo1OqTun8lEMEESRRK4ey22WNq7A3y+R6H2hywfaJWvaHDzI3I0I0+Brfoa8g
# 4XQ4xSNiIOoaz6GmfQep9G99E8/gbfwJr8DSGlkNaIbl8DbxDZYP4HCzE1k2aEmIoKQSmTodZihkUysQR5Jy7ORBFr5KFMymZCzGFsCsrvd4+i
# wsM74le2Jhxbl3tu9jGMjQjQjSyUNkkk28klSpUra4ahiQ2hTlcYtM+CeFVc88mOjh/Ugi2PpMdU6oqpVL+j9hx6kpcEMrSWLyWLFTJCodBJcf
# Sizj6SEJlDc5hemCSldGnB8oahkC8bn6J0ZOgnocHBBByS8yWV9PQtkJaCRDVsqEakp1NZruXwirv0FwclbYPLxPyRNeMoUE1mSsxRmUzZKzJR
# KJxG0ekayCLIa0LxyGObiFuuXe5ue4r1PGbBq9DZJNiJi3nYpqokiYwVG9DwpckXOUVZysHQ/YWFzLpDnRgBnyvgeU8NBRXfLQSPA+BeMf4fov
# wEuDy0NP5aC8B9iW9vDQubG1Emj7CqcW3Hciu2aoJJacujweKFKpWVRmLY9T6G1n8ErP4N3+Gj7HmBDfiNxGvwNLN9ELN9FM2NrOwhZ/JCyfZs
# G+T7G+b7Gyz7HKwfY9bseh9je/Y65jW4xQNBdCJS3CWw1qXKJoPNF7HNpsFGSOEcHA0siFkyFqUs6J2J2OjoS2KPu+TGb1C2Ldw6VC0pXv3qLR
# C3NKigbWQ2M5ObKFLPLzy+2F9KZSr0MVA1GL/GBao59XHpggj6rpCCPccngxj0Q04ftcZ8C1Lcy9P2sWFq/boQ1KYXk9dXj3J3bk6kWlNKuTBr
# RqpeFzoypBFsEFPRDyIeRAkimZyTrYhNEImN+gq70bouS1boX08zS5ME0SoKrJ0+S/D5NjORG5G5TIhCglBNZMnRmzoQ/glfwJr+CmpBDsMN6B
# t6DGhVQ+yIQb6UvDK+ULnxxI1JqOSc3UddxNI3Z97zFiuYOyJciokbJ0F+C7I0+Rpajhe2N52ahpOhaXQtHqx2hApYkvXolk+hqZmkm8dGXMIK
# ld/m/sUpVDx0YlmqsxvX5J1+SrxIb/AIV/w2dCauSHoDgNvJErIN5PkU0OioqHuHuuiNURr8jjJ9j3Er+BxkuiGlhtjnKyNpnh+xXFyu3JhjDj
# 2OzkRoRoNaWz6eCfavUR9wMPZbww4lRq2K3R0QiGlmOBwcI4OPTKJRNnJGpDIZUlksl27QVnovWTFCsnhS6MmF7p5UPAjFyPtftEbRIqrYXP4F
# 6SwsvT6cEEEFfV16UTVbooFMKuuG+XwxYZS2HBwcInQnQWzI0IIZDIZBBD8ZDEmLYixDZy4CbFDUWP2r5ZCLF1YqIm2uZvJzk42iWhKyRKyRTK
# ypXNlc2LcqJsU5EMlmNPMaebGtxoehcL9UMNmjurHdOvA5dOlC5ME0aEJTQTUHEVTGupMmK/eL3wKashVRieED8ESs2TrYOcWOSNUVWJBiytiL
# OFmIl5i3EJLTsnVNcSb0YSSDmWBsycMytcHs/uM4GlDHS8RWIg8fZB/uU/ohEM32xqM+2NJZ9saRGhJ4DfIbZfJGrsqYkLM1EZDQ0NMc4jSxY8
# 0azDSzXY+OxxKgl1L+JuyGk+MEJjDjogU0FCeBTNFMymZTNlMzm2uRLE3oPlwUQ4ZTyy5NWbIXFFFk27l3vVjSqvDIbY5IZD9VCnjKeMcWdfRg
# g3gaMFCa/fK8kUq9WV+hBH12hyhactSiGs0PdeV6ea9nAtWRzqrty4sSF6uCdDj0U+hBHohEIZoavQ5WFzbkdGmKZU1wbDdXManJeJGk1cybOT
# kW9kCWxBBBGhDyK5fJDyXZD0EthCalyrqLhRFl39zZXvYlaeM17L2SmSRyJTzKakLJkbktSHmzd8E5l0T4ROc3FcyHmyNxLcXPYmsn2JrJ9k6E
# hxkOMhwNCDnLtn+BXJUqV/Y+GUBuqEK+UEmP7r+Ex6FbKKt4zbbbturdRvV8lc6Ibx9kv6G2UbfwOmPwNh7/CIbH4Ieb6NzEkzNgkyXQtC6EmX
# wKMB7GUZqvWRHxNCgf8AEuZQ28B1GxFK1GnjIWXyQvGJLxkLP5Gl/Q4QbWaGhBkrJjbeZyIzMWY/gjNv4KeJEN/DQ+BpLEPePcNaPoR5fA28vg
# beSG3kiBfSqOeCIlPG4iVZuxhxxtBMlCaavKHBwcejy8SKNf2ETOXciLptmYK5V2SJ2mGlX7EINDQxyVK5lc7Oimh0UOPV0dWVtmyBzmPThkp5
# MUMleJci+5hFHd7p6yZKrWWqxX0II9MEEEEz0GWmCZhts23LdWxaz6KlSpBBHq4OPpoSY6fMf6GQbS67+6qrVC4lKe6OGToydySbUclcyuZUrk
# iuSI0EhISYyiSSWbY0BOdy8WaLRCFJgKF/CfCJWRImToToTZBTUlakrJkMmQKEakeSQJaELU5DjMhZj1IewRiMZqRw05RR24vLmrmmODm0TvNh
# urhWwGEkV7buQhfNCxVVbK4TGsGqkc3Y9TJvMmczslZ9hpmHqY3q+h1xWJZviZidGgsEFzb5FsxPT5G0LxkkWnR22r2o0xy28E31z3+6FohKeh
# oMkwZTJFMkVwQzQash7R7B7Rq8uzh2Tt2VyXYp0E2aFrQ9Q3qPce40tBA01H4IbZdBC05uR4sRls22li5QlQoOVBCGHsmGJIgMQQQ9CGQQMnM4
# SUscWvdw6PVTmldvanZIlPRLlklovsM3MbbctjW41uNEFbH6p0ODj18FcifQkqBqKMQnEUE+h/Ypk0y7Uf0+Tk5+omJ0CtEQQQQQQQQQQQQQQQ
# QQMbSJbYtbcBavFiU0FRR6Y+pJJP0KlRMXn2k01g1iULJ2hU8hrcTamr0JWmJBBBBAkQQQQQ9SHYuBJaCS0FMeIubkeinzvDS3IFPGi2ExlEEW
# NxuI1I1FuLcgi2dh7IrkiXoTr8EM/glZih5iSzIZkLMepDWqFwkaGkT7xHwYppet2uPL/RckpNrBv4fLQyJauu2Q4vojM6JzMpr0YKWFP+EbWT
# G4zGmZHMch6CdLI1RDFohZCF+waMlyQYBrmr3Q8uSfJDeb5jWwqY6qqrgQaknKuqNJfseKiay+Sc3yPX8jYbG2hJ/wnyCmfwRk/gaeDIeYloYk
# 8hKYIbDVDQNcug0yXQ2sl0NrTobQr/gKMXiyruJY3CbyGkbxsQw444mKyDs7OGcM4YloTtYVQ5lCbbcJJVYpeU2kFeyptT5kbNK7UYscjGP0U1
# KWSTsdHR0cormc+iWSSSVtkXHsYlzh6+XIWpK5+4VXAhutEq3oPdgwWSEnBGhGhGhGhDyI0IeRDyIeRGhGhGhGhGhDyJFkSfT6FixilP1OPqwR
# apFJFN3qMbbAzq4/g9GOAvGsGrx11KZ5SeUnlIm/on/RvdnnJ5yeMnjJ4yeMnjJ4yecnjIkVE5l3VWew5Raqytdy792JKiVEckPNkbnZ2NvJkv
# Jk7nPwc/BTP4JSxfRDM3E6ksqS8kToUFAoKHlxHkEbdDow6HrXQ7I1AiZtVHlrslUr1IxUnFmrcscXTi5KbkTOfZE4/Nkk0K5o8UHo+BvR9DQ4
# RPhkN/SbMhqXLmNshFgxIzIjMUCHIeybQ05TQyimdhFYwjD7C/hiy5XiYk0ajFiN9GoNtgNLL5HkPsa5Psej5JZDce43fBGvwKGIi3jUqsa8gY
# 3qhvUNlgG2ZJpsDQsWV93KyB9aWpijgQ4fJH+5D+4vNi8mLyZ5SeE2Lxk8ZF4sWX5id4m6sTcbkxc27hKuBwHbdV8u9jjDY35JPknl/o4sn0dF
# ClkeqEUKW0ZA4EKayuDNvxeSklK5rFYMjkRyNptNptNptNptNptNn00hSQOJ1+xC1bcB5Qg6+uWsa9zGMYhCtY0TlE6oZpowLgMNeqSfXz6KFP
# oQVFIhLmw6E8ygJSoiJ3OtHqhNJQoOBwOBuRuRuRxOJvRvRHNEc0b0cTiLWhziQTyLBaOk7Dher6MV2yniNooRqbiNSLPLjn4J1+Cdzkcuzcxa
# mTuStSmvRTXop4iUXkIheMheMhDLAaNw9xoQnwhp8SXTZCQxy67CdQkFkXwJ8vgT5PpCzJ9Ihk+hlkPI/wBHkf6QndYtghIXBJoJdBISs/ko8W
# QzYks2JfwFpSVCi7JjEt3lxdw7mKpWpk2VUl6KXLHQe4pmynkErL5Q35I93ZOnyNaLsc4JdkZPlmonfob8g2FJLzG2G9A3qht5IbDYWxlCSltq
# 4ZsBckQqxxJKJML/AEoQozFGYksxJZkLNdkLNdkLNELNdkLNdiLNdip4rsp1FTZu5TEjb2o6bvFeV/Ax5RKiWSPKBB2Tbz6oZDIIIsr6K5nJzZ
# BBBGoqUm7iU7mQRNJCeMZHA4HA4HCxLQ4HA4WJWI9cWJLIo1U+TwQ9m25bqydML+QX8B4FYPAjyJHmSPMkeZI86R5UrbvOkeeBfzod/AhItEq2
# SLnsxzk1DTqsiZUiD9lwceuSRPYRtpKJYhIXsuTFjZ2px5J+bxWKpEjCwwPJ+IXjPsLz/wBhPB56Cy3noJODx0FlPHQWW8dDyH7C8p/wXkP+CR
# 5fwLJ+egsDw9BeY/4Lyj/Bj+yHKa61LB3MY3fPXsnDRLXVzcatlk7E7E7FdCXoSX5kbkEaHAkToymvYo8ZTNdnXZLyJeXwJt4uhTkxprMhjobL
# DXhpaMv5dy1Zg1yNyKIHT5G25dCNXRCz+CuZKypFeCGjyVhLePoU5ujcJLMlkUeCIyIS5Lo49DjiQX9E0sF2xLku2JPGJcxiHW4nFrBjINJOlY
# C7kvlCkjSeO5OJ3J8IlkN6DY2VeJcvK52PCSefybvkgv2KZjaJQ4yQ4yG0N+SNvGMUytdeGRO53K6yXbAls2JZLMTrEX/RFzfFEFCeGgulCeWh
# lbzyIPh9C8p/wTl4PR4b9h+B/wCDRd5uh5T9jxD/AII1cHjgS8UV0UveqIRHE7MXXctQenHZjNBXoNbHVsEDWo9ySX6OCdCSSSSbaFPTBPBchk
# htIWLYlOpQuuc/sPL9L8Gj6Ro+hp+hp+h50jxpHjSPCkeFI8KR4EjyJfSdCSVWVUl17Vk1KmJkk2kkkk2kkkkiZGMQnOKIYZPgY5lUp54ckJTd
# zEGiPpVK/RoUKEbkb2SSIvRoRLFFOfAXP+CwpzFhanR0VExMp6qEnAtkLZEC2g8YwYhFTrAIdKfKHUqYogsCm47J3OWLcQ8xXMQ8yNRLeybPLi
# Bp5EaFChGvwRt0JNBJp2QhwHJ4DQcDe4w9jpazvLb1Y9bmJW9m6Tzki1JN+cl/MN5vY3/UbjaxNZPsWpiWZm52NZH2UO5lMhNmwNvTsb0+SfDJ
# ZuxKcH2LxIgl1yTeh2UnU7sk1ThkLKkGDyTRqvIyo1D1G2aHtOFmWvQ1q6HuEZ/g1CWJGr7IX9DSzY0s2OBxl8D2G3kMPUJd6EuvwOil8iQJXI
# qU1cv9HkO1DD2TjEiZJO5KzZKzEmZtEWMSSqXsb/dF5UHm33VxNtNDeEHI2xzkVyZXIqVIIRQp6uyn0q9jgJLLt7TQx+xcUQ6/49Eeun05nsNy
# Y3T8hhCQiSSSSSSSSSSSSWVKibGG4tiZVUPPC+GOKrnfnqNKh3oQaI9XFtChT6fJzZUVoQrCa/EVyy+TZemSEl6ejk5FZImyWSStSGokEgkE0N
# U4XrNEpKjeTXJqnUSBcEl18k0ahl/ZT/I9iuRXJdFdCX4idyVqStSUJBJoTsdEMhkMh5o3ITzIliWhImNgLYbG9xtSQFGp3fl6vRCZLb8sdXLa
# WQsw1OLGmbPCBZBDJkNR8jZewJWSKZCay+SVl8krL5HoXZPISydM8IYky+DzQ3fBudCbMMzGManVVa8MUOUE00r8F8P4YvQB7DwGqojJ8DW/Q0
# 5vZXN2eKjuvTHsmPZ0VwSK4JHAjERn/o93Y3kbDers4OTgNpfoJTDewxf6I1K93Elx3u4VFI/SmNZMMK70MkTNgQ1gPJh8tqUCUTX483oc04V0
# YCM5ja1JXiJ8gllRrYh6EPQqQRudkfX29XDQ4lsMX0JCaJZJ93eS7Y+1VSVpBVO5Swkv6Mkk+pDExNEUJtXZixQx3kzmXcq4cDQ/q1K28eibUI
# RHcqJi1adY4VwhIUCQiNyNyLUVKkEWUKWoT2GWgmHBne5RFzIEJnAe7fDIXODHzXg7oaZLJZOpOpXM5XR10eXElNSmpK1JWpKJWRKyRDQhoToc
# Hl5e7/kpn8jjNkNRHxCV7bokOKTunHvbK5bExovyIY1v8DTP/C7EmMR6mNvMbYl5vo5ZGvY3fJDzQp0FwhbropmiFmhrVEaonY2E6Mca/I41GW
# TETwY6ZpkoUFFYfc06NiVl7kPuruCNpHKf+Dhq9shPMqxfQ3w/wfihhDyY08xDyOPgpn8ErP4G1mPW+Btz+B7hpCIxGaLmx1ZtzVsosCdDblcN
# +pDD2wxKzE9SdSVmSs0J6oT1Q7Qehl4RssjXMQjZlqG6/oSKrDusk3HJWyhTMaWZy7ezuyLalSvpkmyiHViFTKEzr+z/AAw/I/RBHsMQpP6UNy
# 7EoXq5+ohigO5lMJuZGT7iL4S5dDG3Ag/qVK+iCPRBAlsZJCvElNeSvburxNtcs5beLFrPo5KZlM2cs5dkkkk6MncnexCEJdBpyhJW4fcyjOBp
# n1QvhunRiwuF6zQ0UDTUpkPIhkMaep2S87G5E6oTzCc4nOujcjkg4KZFMmRuQ9TAEg5yG3kbghQcu1xf9qpu9Con2poPobYr4IY/4R8R5QRIZf
# JC8ZK1HVRvsl5/JXNFRwuirwVmOZCYsW4VWPZsIUYIohDMRzEHiOA5qMQ17mxXfsTlJa9U+7fuhhPArVgNGXFR6mPUxusR5g35GycSc6JyujY6
# JZjzkdOyOnYlguyDAYJBP8hmy/73fZSF7/wuW4/UhWXsbihKJRKKFBNZiBTV5G5MeklAzK/3uYlWGtRraTRWzkjUgaIRCIRFsEakakakalMyFm
# UIRCsbSUu5DHPMkdwnm9Zbu4emqW6JO7JDbZt3uyLH9KfWlLgXFREsc9scMrFx9mhMYgCOvnEhqokrwJvQ/ZHDUjQ9zkj6c21K28FSokxK6bo5
# HFzXM2ISuSFRQSTZX0x6K6ldTsTJE9BPQbQpBk1uZffmfNW/vKq1RG5hrBySp4FfuQ1sQVKkakLMpmSlizczcxMoJLJkaMjRjW43ozYzmIty8C
# iy6G1l8WELKjSuTFtEqjKJH1bl73bqXpW5VoiTKCjMjUlrFkhtA2yY8o0CWJEI9zo3OhN5ujl9FM2JWbCYT0JBt5iua6OQWhCWRdiUMOxNrFLk
# anKRPcRMnjQ8xs3tqV3kNb6DVG8ZmZIcMx/so/3kf76PN9x5vuf2J/Sn9SL9pNV3P6U/vT+lH++j/aRkZfoahYlXdwYyY3ciTYb9atIkRkJopq
# UyIRG/Rx8FfES8Q7zHhpyiMVKj0ePAyRcGJ3Pur5K6lR64i2GyRsmzs7IIZUk69XFtCSdDD8jm6JtuiRR5Tq/Dgiloj2xYREJff+A6sSlwJe0T
# GMbo7yVuKdOa5uZBVQtZTevuKo2Ig/a1OCZ6B7FhJed4CEpIuJFsWcnKOUcnPo7JWpOhOhx8iFyMSGU1ROVg1cxNVkNVyv8Aa9ckpMhkpiMUYZ
# OyYsSvEU16OyCChQockEIhEIhZkMhBYropmhtCNBGhD1rS6kuvLLpDqOaawfwLIvkrl8kPL5LrG74KPH4I0+LBvT5JNYWp0LzQoeIkv7IX9EZv
# k3OxJZiE8QtQjIzYxxqSJvNibUWh9EAlEpLRKP5F+fD0pXvs9y48tvWcB2Mf0cQoqABNEaL0okRpBK05sqR5HRQP1oVjaRyIFDk5GVzK5nIrDl
# KdxSDnSv5aohml4i5rBkDad6FDSskl+qpXIrkV+ktzKtLvYtVOmzg6vFk2cvv+4/apLGTnuuLNjm225bq7Eiv0o+omMUYd6JqyiHmlbmJIhtDQ
# uTEQf1V6q2I2SSqxSWotEl7HJFBsi5CS4IIIItkk7tqVK5MrkQQUKWIW4nr8jEs6qVYCJaWk+sf83ox/l+9g1ecaOjG4wtkkl2RqRqiHmiMxuZ
# UrkcE6E6EvIrkyuo1LraVBrC+glz8TdkJrN9nLsl5/4Sz4US5xFcyHn8G4jizQ/wBNL4IeIhBQv4KCmRC8YkzFrQsJNZmZ3ELFIgxhb6IWE9Eb
# 9FVn8lc+zK5vsZAmu1W4iWpWgYdhJJS2dCXkSSTbKKWLb0E5bYf0EK1cYTs5OTkoQR5Am1gMyGZETkt2axQmVnMYtv3N8FSC3Nps+B7HFlfTBB
# B5d6IIIODgoU1XIiJAgrlIjwF5MOaYE6k+0ukr2JmL+47EpftYsQxHNELeVQ6MY9ogMWD7iEvbhBr0SST6YtrZHpjUo0HrWo1Hhg5XiwtWJCvJ
# 1JJJJs8uPLjy4qVODgkncnUnWySSRMYZjNGNcCaqks8Oa56wXRdgRDdygjRje9hBahPUW6NysQRsdFNLI1NzNw9yXmMx2VQosrKnDTlNCaAuJL
# oxRn8iiCVmUzY4zJNhITkVjUEZo/YtYKGIXHYm07E2SFlLoT5JBPR0OukKBNZE6iSDfIbDbzDZhSm4ErxrVuLkngiRyTNsb3JJsTqySSpLK2zo
# SSN7k7k7lEXIeSuQ/WrFYYcZjMTZks7Ek+hPQchmPJPUtW5vHY0LKco3ZrdOhNMKOChIyERZWzkjUj1zZc97uElikeg9F4JCoN7vrhZJJPslly
# NyYnT8huxIXuEMPT+BdGUTmX9Xj70V6eawY0qHehB/S59NPQ9SEd2JazYch/stlsSX6ujonYkknQl5FSpwToToSSSS/Gc/ItxPUQvCk+xuUzc9
# cq/garXyDao3XzJFN3qB8WSTVJvkf+HjH2PGPseMfY8Y+wvCP8PEPseGfY8c+x459jwD7HkH2PIPseWfYfjn+D8S/wAIHhdDg0Ur22UfBidjkI
# qhgPR4MXPQpzfRL/g1PgTegnqjciZMS83RObdCay+C5crBPULfsLgW76E1/AmsuhKzdC0MjWRqIXjOuxtrIahhAjq1bDDIHY2OySSSUSifTxbD
# IcFy3u4ShTix/QSEIXpBWcM4ZGjKalCgoGGoPcZpktkxolX2nKXQlRlaloC7iDIt5I1I1I1IOStj9EEbkFXwwEGccAXsY2KgLkuQ5zXv2qqyZp
# XZsqyuVErEr7lMTImmnUvV1es80Riut541umPB1UjRFsIizk59NChS2B0JJTgFSpTyy8aXCQoEoX0KFChCzIWZGtskolFNCmhTQoUFGZusLZ4t
# ascUKlWXMV/6DVWhE5VzKtZGqsKnCkr6yadZH9rGP09Yz/WBCVisU25Dl9UzugNeDhR53oOn/m/J/Ffkl/G/I3XK4/kf6INSIvdSAyZDqSJeSy
# 4crgZybQx8hNBy71gxN5LsTeXyS8vk67IFuIepuZGrNz7Nz7EvDIELXoSyLoWh0QVwRJshSwdCejoUZJEIjT5Ht8jb8ZLxiHqiWYx7q6jS7y6l
# PpkkpmyhQplZBBBFvIybD7Dqx+tWKxCYxWIJHipD8ZD8ZUZJJIrHC00KlRJaP7g9EqsRMC/h3k3k7hRpDSIRBFkkk2RoRp64YL3eJiRimkLySt
# 5JDMK/11KlfpS8yXmSQORqSvqew77Eo90hikO5iUsSV8XjyQgLpbGa4KG24EH9etl6XIouqieObgRs2ct4vExrKldCpJJJPoVlSpDIehLQgjSx
# AhYSFOYzEhtDTlMlYPq1zzbRr/RLernI797U6EhL0NUJc6jpF1zcalEmwJNBK8UJM0LUILb0bEbENckNMhoI2hph/g/EWD1dtzZxOC4czbdXeP
# cjUcESKDMXJmiikMpTgSa/gtAlkjwk59izMRqKYP4EtHRGgh5kPIlrBi0fItDFW5hJiv8AQnouxPKOxb/Jy+x7h7hlk+jQ+Dn4piObgrIzfrcE
# 6InYl6FdLalcyWJk0LFVJxMFNs5rhj+grUIVjeQzYoKHPoexwToJjDkDhujH+VET8vOGIWh8WSDRBUrZO5UrbHqQjbuQzc3exMbat5hyY51rSO
# rHbNnNkk+jg4+i3YmPu5ExhyhIMIHCJNMi9cqo5lIaZMJGvV1ZJz60pGw6S/7i3cW9nyEuSKeiCCLZJRJJJJJJJJOhwVK+hLUoKBFUu3oxz8Sb
# SuVV2pTcaxI0OGmqodrS9sIUlyWZjLjsTSy7I6C22VuE9ydWTuSEshsJ0E9hvVDeqG1kIVSqh2EiYlYciW1XVtyIZCWnyJPMJPMQ8xGYdeCMTS
# 4EtBDNELNdkLTsWoWpm5kRiyupXIU5fJGRdiTyXZdgShvV0PmfyOEnKiakUty2xswboV0K6W1KndtPRJOhwcCSSWIiZKsM7evw5EabTTTV6dr9
# CtViFZbcbRi2YkQbBrQaWRwdnZQUDIQq0FpTA1jXiauGsxfxZQCcO8Xca3GmQyCLKlbO7eTkjUgnccLxqEjbISWJAi6MxcNlcXbcoiSSfVz9d1
# Ep96mMQbwxFS4UUS2GURBm0sG/u8w3czcPc5J1XZTTs5RTMpmjlE6onVErMlZiazRK0JWgpuhaFz0XGbFfNxEpKUkEEEEWVKnJGpFsolFChT1c
# lcyuYnqydxPc5DaKcmkblNXMT6TIVhX8XuySVWjZmYBLJ1JWaFqC1hakLV8k6vsnySfJJfjJrLslp2TyXZM4Lsif6NibQWVK52XqGOShsouYE6
# IZsSWZCzIWCYlqI0fRsEtESyRL+E82TwYlmEliYX8mxoxkvN8Cbz+Am82SzfZLz+R6xGojaS/JI9BsdKBTI4OPRwT9KCTG6w7aTTaxEVIh0K8K
# 39kepWqxCCWG3E1qSteiVr0Tudj5JebJebJ1ZOrJWoyHMHIlpVuf8L0QqpRqi5lYnCa1GU3rsbWa7JWa7JWa7JzLslZrslZolZolZonVErNErN
# ErNdkrNdkrNdiGOmgqsQummmdvCENuzPuU0KFCn15J9Se+QxjnVXEvaiLQ8YY1ehtDsP6VLKWysFy2QhaE6ZBchJZUrmc2ySTocWySibaZFMji
# yNiNTk5OSSR7iSSdyOhS5iVDWlNzVyakqaJJQkJfI0jk5E9RMJrMJrMTqJHPweXFdeiX4iWYlNB4nFCbzObeSdRPUSVOKJVmTOD/AGJvNCnNdF
# cx4qKNOyVmLf4Enm+rKaFWCKZIhPBGxEaDbWBsOpES5Mhr0bBvEfo1oQlCvHAlvc3XYbQA4TE25zU2AwHnDW9ngZrPg1vwak1JrTWGoNUagdSV
# LFk4uNhKbDEenCJOL2HBiyIYQP0K1WISYjEE1EtRJWQQOSuZXP4OUcq1MYTyG+15X4L/AEQ4n/i6jNrqbctiEEEEEeqCLWpEsTAWmpmvHF+fJk
# 7DYfqn638Q/iH8QilNqYdLrGle+QmO5kwOEF8mKRgvFQf6L+T+U/J/Hfk/mvyfwX5P4j8n8Z+T+C/Jn9X8n8/+T+X/ACfwX5F+sfk/gPyfwn5P
# 578lDoTLUsJqJubhjBoeotKfooUsoSiVZTx+qCChS3k5KaFCUSSdCEpEpr3m7hoBC834S5FqvHsG9GVyfRx8CC3CTCnUh5kalVh8lcvkr4zn5G
# 9RLNlQmnDoPTzS45J1J1J1ExcDV1umMKlGkMxNZPsjFz7IZfImskbBsQpZFWZTN2ibE3kiXkh7D8qN7kNRJqch6mJYzhJS2xpeNEObkY97f5Kx
# djs9iXklVgVyGtBsTJEtCHkcuzkVyZLJKZopn8E6/B5cSTqcUuItppSVf9kufAx2r0oQQSwTCTI2ItqV0HOhUgixhLsWB+ahPYKNSPwS2qxt/b
# j9Ph/ro/nBm9UfwIf64H+gfk/hfyPD6v5H+ifkf6l+T+A/J/Efk/ivyfxX5GhS+n+TP4M7m2oOG7NO5zesGNQ4f1J0+jJJJIiUUMc1sPkaH79V
# cCm4bhFLeSHOhFxMkMSNYGgjQXRpdDS6Gkujb6No2jSRoI0ELKVoQsgLLC0RwkrTIUpXCksfuqj1Ehl53q+ySbeDgj08nJLzJeZUrbK0KWcHA5
# yOETtYkRrao0FYCjuL8lyNOqTQbyRqjhmS16E34iHmJPMqJpghNkjYiVkiRsSyZyEg0EQV9xEq2CBF0X4EDKKOjUh+I7OGcMnQTZfAs3+EM2Vh
# NsKq8TT+EvEbPgbnB9Dj+BpZCFl2KZPsnM/knM/kozX1D4DQ9V282SFyJNLRMkIvGJCWqIehDY55jUYRnsIzFFiyVrZBGiI0+SPJPLzy+xyGoo
# LSL5nEo0Nm5d+3MZBFqVkCQglgglEhDMhZkLOxj3Y1qRqNakanIinIILwI1Y/GU4fHb+ESEKlJHk9B5fUeSNEaI0Rp9DT6Gn0NPoafQ0+hp9DT
# 6Dyg5KEthZRJNcTqycH5nuHwK1+xWNK98kKWQa5ulYIoRQralfRz6JJtQ9KRTDMmtEP4xY7q8rit5Rc65N0V93OjI0I0It4tp6pJ0J0JsiyhTQ
# UaHRyc2JDUJIckhS8aXseSpqVjk4JDdBQ2iUTuLkS3FscHBOxOqJ0CTM1jWRqErMnUbnIk4VVUVKlSpwLYSHODFaLbrAWyxJOxKyRKyEphQ8BJ
# ZC0EbkaMmMGUZj3m34Hkg3fg3OhTVUXyPYpbcscrCO53ujAhHoJoJPL4EtPga0GtPkflbJ1+CufwQ9CqyE2SE2RV4Mh5Mh5EZBoQ9SN+ymbE1q
# LTk6O4Wgqt5viNcketCCaCCCSKErN9CjP4PLrI1OTn4H5Q8uOjqymLIQsvQhhC2lrwrnIhF479ENjZJJJNklSSfTNiQy8JaV+Bi9InRpwSII+j
# yc+uPVMScoRurYJwyfeJLIjTTlrPJDKybcsWXP15JJE0KTbOjqhMo5LX974FhyVhev8ALOyCLZ2JWaJWZKzKZnJyRqRqRqRqcnJOpKtaEIEhBU
# vC4XSppR4/reSjblsaw5ODg4OBPQQmSS8iRsGxdCayE9GToyuo0xj1SVVG5z6FA0kgUBTDqs1iSFkSnoJaI2HLsSjPslrB9kshNkLQeaD8wS0H
# INPQbaNnyRyZHUaaiNwdWTOLFuTiOl+SGiKWm4lkbBbEPAjIhrIh7InQ4Zw+ymTKeIpl8HHwbCuRUl6EvQc6dlc12Q/GRv2XMorPnkQoIavIh/
# DQ/ShBBLCYpFJXMl5kvNnNjsk5s6KJS4JJ4XIfxf4RdW6GSI6GDRLzMa1lWPeypUrmcnPoqSytsWNShJRBYvVMMnJMrqr3Dw4zFKwK/iMfD3kK
# SiWxaau+79BLAUJfT49SYmMZNUauEtm1eXPNckyRwyZNhw6DktXoUCauZJPqkk4tkkmzo5RUqSxuzkQg1SYjL0qIktUtx4vkkOpXmJvZOhOgTe
# CCeQ2EPIS0PLySUSsimRCZDxkeSRv2ROPyPxJQ916uJuNxGpzYj8gfDQzn8olmJZieQT5k9SY29iCxdiXJ9m19k3/SW8+x7jcZDXxD1Po3Oh7G
# nVQPSvqyWKWSSluiRygfMbPg8UNwozHyQxtkzYyEryUHlGgycj7JWCZLEvXsbeb7G9WSs2X4ka/BDWK6G2sUSEzwYqpMO+pDOmSncXcO4aWYaa
# d6aItQkJqIIJuLk5ZfixaiRGpGpTNFNCmhGxGxBDKYvd+wmLFPQpSKv3a98CMEvbjGcHHo49HfqixMRyhkNOU9RMYwLl+15sD9xdNOqEtq6vrJ
# 2JyvbUKWyPREHsvuc+BJcsXG2v0ebaFLZQmhcj9hLalza+3JfIxOqhqjTK8+Ppy9SXqJkk6Ek6E6FciuSK5I4RxYhJGwnvubCT0pTq3Yn9hjzY
# bPge3wSvEJiUbhN5oTeYmJrWyNiHoQ/EQJZfJsXYlt2QJbdHK6Gh0h6CtzRKZJLyK5HBwQmogQaDJTELKt6m55FQl5CawRIWpleLIZ/I48Zq/0
# jwzh2PUhoPKRNXezcEuauUEjsgAsC5iTcu9khHmhal2eEiVg29BscI4RXQksiWaJZol5rs3fJXx2ciazJQoJzEiVkSGu4wu+SiSuhTg+VbAkJC
# aIR5IR5IXAuDo6sZBByPeyCCBTWUQxrXtk/ZJWf7r+JIjHIjCcFshm227xyNsm2LZJJsqV9TUoawYprIqGTwYxO5GV+hQp9ZoZBGzVyeDHORDV
# GND9xJeOaFLFrb4kiVyLvTBBH1kNMIaq4zgxLJNpCi71zf2OaF6uIdqCXkToToTbyck6kklMji2dDg4sb2J2JFYelQ4xEKg0JZuS8niQUkuSuQ
# 7bwHeg29BlChTNdijNdlM12crsT1XZOp2dnDJ0ZOjKkCQnGfZOjFL+D8oSJKrqUW8nJyckinFCbcnXNE2K/ofWkr3jGMY1lK1LRsWTd4lOJ8FS
# +SYQ3cSGubEEWSFoXQtHwQ/ERArkOcmOdSubNzJzMl5nJCzRDQSRTXsnVm4nX5JZLyJyEskT5JFPuoymbvXdkmqdRJ10bVzya0aqQQJCCCIgKM
# imRwjhHR0V8VknDKnFlCXAK/caSbSF7bwKszIeIrtkp2LjWQh7D9EWcnPo49NStqYi4kO1YdVYP7Ebkj2Ev1vKggFyPsdjSvcYhczw1p+wkIWF
# 9CSSfXUr6YbBc9iK4tLxF5I2JGqKG7mSTqVK2cHAtrO7eDg4OCSTk6FwLgQsuBiKVVZCNFrQWC+45jljPUbUe5yLcT1ROx1ZG52SiBOYpmUzJ1
# J1/wBJeYn5IpKlcxzmQGnDTvHte7DYgje2RumJJNtPRJJNvNkklCJZJkHDGjEza+iGT6Fs+hLQjQh5DnIa0I2I1RGq7OuyVkididUcoroS8kTo
# JEaOxIh+IjwiGQ9SuthjU3sQNZazMB8OmzsSEhBdBNBJ5EM4OCdCdCdCdCbYPLrFvom5biOpuxSqGlK+XwSu8DzLtjlu/Vj3GUIRTI4ODg4OPR
# JNk2cnNrGoZF3momaxEsRyyls1gNQ4ft04ci06qWUNaDHXlg80ND+vJJPqSlwhTdUKlskMc92CyWCEl+uv05JJOrOhcC5VVychNOlKSq/CnwLD
# L/vVGQVKlSfT2dndsEEDRFisRbJwF1UZLNghq5slmqzWY3uPZkaWLjsWy7I0IjMnRmxi0CYvEHihOvwc/BOvweKE6fBOi6EtiNSNUNLNdCYWZd
# eiDgr6Ek+qpUlkvQkkkmxVZyISm4WrZIkriuTJErCRHkEPP4IzEs/gbYsosiRuEzgzhEPIeEj1rs3fJBTQhaEIhEeQeXEoTWpKOWVzCbZNNyhk
# ZIoZcyjRUgjMxburuBIQS0SI1IIoUKErIpl8FMrK52K6CLvyELElNMlm3olUkFfwubq3UY3BgskNDRBDIeh0Vsr6uzuzk5OvRUhJRIs+ZWK+4q
# alfUkn6b4FK1lqrHpHtkhSQieDCEoQkL1wR9ChSypX0SIN4hK0z2fL0MI+wtzI94YlM7OTk5OfRJUrbQpZO9q3GISrIyml6K9lFBU6xx9XEpuW
# LGWXyNrL5OPk4ZJOpyRqchNmJs0S0IeSIeSFOQU5BPREm75Fpdk6OxN5oTs8vH5UrazFUe9k2Or9MEEEEWVyOPSrmyiu8asEJrYl4hN+IliHsP
# YfA+CmZSwgNsyWZDzZyyubIeYh5sh62SSypU4fRDyZ30Ss30IUjQ9BEoctGqfdvWqEIIECSIRBUc20KZDjIpkRpYigrI4JHoh1QlmfEyotERpj
# V2Deg3oN+no6t59XP0EqNJhtKESioJSyzQ5o9xC0l6FLzJaaCcMTle0SWKcrRzeCGxdLblsWttCCPVPrkn6EMjo7tyXSW5nfYL0LiTqTqrvpyT
# 6H6EhraTNN4oZlMnKPE+EUjpVUjgwNvIl5EhNCmRQocHDsORTUpmRsSzRDzQk9BJ6Es0bkQvGLUKMzYroOcyda+9PUdHDvRNjfogj6q0G4uvHM
# 5t5m7xHjELEUCRfi+iFn0IWb6GtfgaI0IWXwQvEU8RK16J36G9CVkTp8krxk2Q8l2Sy+TYRoQypXMrmVzRyi+mFo1E1UOqU8icuXfaJCXkkbdn
# RyVzK5lSpXQqS7IHCTbcJXjG8EhE+Jl6/l3LcjJGS1y6IGvZLbljaG0Mf0O/rNShqVAtmYVb5fsSLVWzZwceyeGST3uu8ah1Hw9oyiSlskTUXn
# iEsBKF9CCCCPp0J9CcNNXjXKGzGouIobj7D+IGamr0NA1cyLJtgoRbBBBA9iCBIkZeLNe8NR3cyPNZ8sqXUddxrMbepL1Fydk7ksgmyEtSXqTu
# dkaELJErJCTTs8VJeopzZXxEvJ9CnL4Fo+CH4jf/BR4jcUzGqXsoi69ucj3Ll/0JJJtqVK2JD2SJbokPdyJlRR/g/hoqJJHTSaThicYMT1EvJi
# nKydf9J1XZLydkvNdlTs7HGbHGo0tSEQvQkhLYga9HJGqGoTbahD2poTQcPE6v0BCvwOrGdnZ2Use6OfgjX4EQqDvqzGYp6mk5nwm9yvDxNxsb
# Y5OiSSSfocWx6pJszEk5Q0WKt2/PkSHdR2TZNk+yZnVFJoEyZcxpVkEEEEEEEEEEEWRbM5wQ5+J24szCY/Tn0T6YI9HJzaiN5DHItPmYGGzVBy
# Q2Iad6ZG5XO4j09nZ3ZBGhGhGhG5yI1IEqjEhBlxMZs3klpuHdBxFUxSsdzWTGUyKZELJEaIhZITWgnmQms0StCdimSNiKZLohaCSEkKBRqSlm
# crKZ4HBXIrkS8mToKfQNDnMqoZes5ObePRySsyhT0Vsgk0uTy1HTxWmDctkp0JyTDTa9NXoic7ncJPUW4W4ri/gpm+jd8FPEU0HHiJRKGxvRDa
# yRVgNAQshGiI2I1OTsncknQkne0iGV+ImcsLiZ9DYbTYJELP4IWbIWpSySTo6IIskWuQ22t3t1KDcu135ur0QwYybebY05jjUcDgaGOyfVyc2y
# TZJOvqY1gJf/imTHM1VQ17dock05e9MmMbeJlLIIIIIIIII9AixBBA1tJ2cEtglNPpSST9DgnQnQkknS2pUlizUsdfDFKvegS5OFdxpp0Il44k
# aGz6f5P0BVFByqrJfzcXbE6IwWCHCbiKyeG9GS80TqhxkKZoUCgT1J1ROxXOxLJElqJLUSWokdHRK0IGhMl5iXkyXkyWpyEjwYqIQlBgrY7III
# 0KZWxZBCIVvJyNaFiRKBqKunXHRlFxNAlcqmxK7plSTV6HLeOI20TWLKs+ydX2c/I92VzfZyymZTP4sc6lcmN5B5BvEiOJAlWKCFmUzJRsJeSF
# XSSWMV4dCVJXJFZtWE7FHonQnQ4ZUqQQU3de3Hv1iV7buQm7Ru5l7ZXLYlWngBtDaHA4GiCCDk5O7alfTSyfRBFqCUL0eA9cDL+VqvJYsk06lE
# 5W9fbyvfve9e89ztSGRyZepYMnkJCLDYbCMhGQi0bLGw2Gw2DtVIuBCuv2EqCQvqcHBx9GCCPSiKwY7EZ1V38ODEzRKRjqtHeV+YWUuhZS6NNd
# GkujSXRpro0V0aK6NHoaPQ0eh/EP4B/ENFdGkuimoIkZbi0/wDmVGGKgrmIheU9bKlcvg4+DrokTRKyKZE2KchTkS8l2V0JehLzRyrJeRLK+MU
# +MjY5+CJx+CIUv/B5Gw0EplKJ3O/1fwmRjqrsGP0cFbK5lcytskuyBiVr3qNHwlMVmhk5M8U6k6pwyPAzkPJrRqvJT3c7xrQaIWRGiI0Q+Doro
# RqjlD3GydENvJDnQ6JJOSuZXMlldTsrqVI1I1lKtxApK+4ohmOaEJOQlZdCT+gv5DwI8CPAjyI8yPEjR6Gj0NHoaHQ0Oh4kJL/SLqppen4Xyyn
# N/QYxkEEW8EaeubeyCCCPoNQxyUqsVmhLGrmjxX7laHJLzZLzZOrJ1ZLzZLzZLzfZLzZLzZLzZLzZLzf0kSmUSaqJTo1mhAojqRNkbP7o/sj+6
# P778n9d+T+u/J/XH9Yf1h/VH9Ef0X5P6L8n9qf2v5P7X8kP70RGiLEuR0JG19SXoVK2QR659PJXMUiKMNpXCLEE40wXt1VCAoSmnaaF+1H9ML9
# 2F+zC/aD+3P74/pz+8P6w/vz+jIfsjRf2xqvVyGm9XP8iRkUnKiBdLGSIG2zdsNiTIcqqLmtBM0mnKd1SXp2TtZTIhZFMidEX4Kzs7I0Z2ISF5
# QT1+C/FdDSzXRC8RTxHlxyLRiT0GlxQkwY0kl7buQwQbzl/fwrlyUdLijIfkeX+TzmaY0RovRydR2ans8bPOyT9zS9ml7NGJMl0IsjYPkKWq7M
# iV+hn/AHhR6MZtRWUPjczqGhrP/SHjORG5D1OWUzIzM1GPUGtxjnIrkS8iWT4dip2dk7k72LpM3Jmxtas1bJ4SRWNJKW8WuS1LmdyE652zl8nY
# r+W34hPVGeOQvJf8F4j/AIeZ/Y8D+x4P9h+e/wCHkP2HJHlbHh32PDvseffY82+w2MVQ1ms0mM0+lNfJuWxvGFkhuzo6I1OTkgggjQg79EEeiC
# NDg49bpKWSBGkTaZc3Db5O5ZZIbbcu9+1QkSMWylCfDO4fpw28MFkSz9ks3ZLP2Sz9mp7NT2a3s1vbNZ2a3s1vZrezW9mt7Nb2ansYRPsRoVXe
# osH9rG8L6VCnqr9Do6tkkk3FRh1NKlskNLUWCySuRCqXK7shfu4m/fP6c/txL/PP64X7oL90Fb4JJ/Zj/aT9iDn5Ax+WN1KMNttw8GUAWnDsG7
# Y3DklHdalsdEiQWolZkrTqydDYLQJ6WRkQyGeKHIjVnJBwI2JjETeaGyU0GNcqcB6ApZpbvhXg+WRZN5k/I3q7GtQ0Ieh10ddEJ5dECGRC0oSi
# TYToT5Anq+hRmxMzKq5TlCU7pNhNplGDoiKZxLuVc9UOWipjsOVUhvYbJWvRKwnonfob8gexFiNRvUnUkcnJOqJ1XZO3Z5eRocWws2UFpprXU3
# BihI2cJmx5MycvMvfFxWGrkKfmCGDzFfyj97n7HFZMczpu8z5G3if6PzH3HLwPkkF/aWEP9kGhEXSOFkTD1Q9TEuLypSNkkkkkk2TZQp6oIOrJ
# JJOTn0TY9BcCXIzewXBTFcvaoQkl/wByrI1KfJwXFgN+sCbE2k2kiZNNCWlqFCZrEfIyr2zWD+jEMgggrmVzK/QkklemliJKcxOGDQyX3N4YmI
# bjeLWzezxWzz9HjmNcxpmIzNUnUPApUy9SwZel69DUqGICXsIN00dC4FIp8RL8RLJep2Kc32V17FOvZ32d9lfGKdCuhXTqw5CuvRL16ExVz7Km
# MbmJoBuizb0SrwIZSlzd6V7at1JhrsFoNM2czeyDKZkLQg8VIELJWk6E2cnlx10S8l0JvJDbDLQVsRoyrRrnw2tUPKjolU8LhyObOSua7K5rsc
# +Mb0HGQ9hvQnQnQnT4JeQnQcIpkimg9yWS9SXkYUU1oioNURCKCXjqe3BCY8gvyTOSRhkIEljYSsSNnZJLyJeMkJsb+w0/0DouPBlmuGSTj2FP
# Rz6eSbakC1YtKjuruweryM2q6/2yEiYYFZozwL7j3tuW3WxuyfXJPpkkhcsbiURXupiX3GTKMvpVKlSvqn009KgpicLN4ITZMtuW82Lkkkkkkk
# kkkkkkmw7QUOULTm9qNZopF+B5r0yKF6ENurm5QocEvJkvITeROxOw0syNRJ5sUibJeZLzJYlmbmTuToToKMh0lEVYqBXsk0tMXGq+VNkQqDvq
# 7hvccanLI1Ylq+yN+7JODgqV1ORLUSI0ZwziyNUQ810LgbyCpqMKUCc5NFTa1LvydVoxmmkvGgRKuo9nY28ididiUTZCGkQHGg3oidES8iXl8l
# cvkjJ8kPL5IeXzYoG0TbcJVbHtwOiaEAim+2JeCxYulKB/J8sncDYnaMxN5EvIlks2GwkknUmzgnQU9dCs2zo/e4S+U00Ssjg4JJJsjUj109U2
# TpZQpYxHEthBUeaomNxj3vDD2qETMatxNYSzeAtQ+cXNixuXIx+xmB7MQjFBXxGaE5SJyp9HBx7GbKnNrKJJtskRLK/J+CISIOCdCdCfTJJNlM
# htDYw2NmEJylbYooywJ9Dqe6EqWTcQhArmVzIIKZ/BGolqyNyHqQ/GV0K5ormQ82S1Nj7I0+SFkuyNA1TdyEJkRgYN/Lu5JaVCSXciiQekVY28
# idCdyGvZDXsncnRkrJkrIlF683G4l5lczkpmQKdRT4xJinJDDEVOV+Q9BVBdE3tnc9xgF0xeijQ6go7tx6BiHmQ8yHmyHmypOxKJWvZTXuymZT
# MlZk7E7ErQlWKMhSS+ddhM5cWAqa9OZ+0nC7BEjGxWkNBRmJksrp2OfGeX+jglZEk7CY5DI2wYhLeo5ZuRYeJBBBHooUsnQnQn6kkkmEiKSqT4
# LH7CNQvd/tkIaySVWJqPen7r+1iP2l8XMS8vqfL9hGm01DV6K0P6NPVJJJJJJJJPokc4Iu4zjHF8GIFbXMqVtr6JsoMY2NjdkTSXog88Wmgmkl
# ejfFcX5kM4QtiNCNPkjT5I8kjUhCFmQs2U1KZMlZhJkyGRKKZsjVks2J82I7kxiUXqx7oUGcvwqr1ZTd17cbGTsSSsiGVjcS8xt6E7ECVkQyRt
# NhOxGxDzQk9CNiEU8Qo8Q1i+WYb0wLxS0hK6PwqboTNYyVmXOI930T5BJKJXjsgjyCfIJXiJRyVIYps7GnqQGudRCkteSyOEiukL0yYcj3HR1Q
# wYcETMaxCsJiF6GOySWVK2tJidzFOb6nJ8CC2mRbJJNnBwcexkcFJOCE69wxMibMkuGMbd/wBePWiRkpO6cclixGCVBkicRsn2k6vcoQqGTR+x
# cxqnp4tj08kfS4FWgxC8vLUoU4OHPkSii9HJyVz9Uk7nYxjGMdjQxJmd9dDIm2sknQkgkrmNnPB3QkyGQ8iHkcCjIoNHlwtvgUZfBTL4JWRTIh
# ZEaHCFBKSloUxkKNwGZ08hvRFJ02ty3e2OchyOcyXmSyWcHDJWRDIlkS2JPXsTTj2cuyIJIZErIlZFMmKMmcMrqJPUTQQhVul6zRMZAmq57pw+
# BtMwoXXiTRqGX+6O8b1Y2S8l2ToiXoVzIeZXM5+DkoNEeQV8RXxEvInSxblCPM3IFOLJnLuQyW9+Nz7F49zOrGHYrDCdhHJyPcnySfJJenZLzJ
# 1Jt4FySwXq/Yim3KtzA+LhcbI9fBOhOhOlkkkkkk+uZwsBKE7n/BXN4tuGF/tkINUkJSlEdYO77AbH7V0gwrgQ9MnwLBqQyB6P3KYsp5uDr9iJ
# TixEu2d/ROhOhsJJJZUYxjHaxpWqFglxpuKx6KANQmFGs0QDE06oroV0JJ3J3JK5lcyp5eLjshaENCBwLZibyHNxAz6sQxYYqnK0417ZXLYTQu
# UQ0MqVys4ROxOx5cddHXQiUcCWaJ0dEvxEvxE7Ca0JWaEJPUh5Mh6icYMWh9Gj8D0nBnL/AAhkNEhMy/d8MUlGQmBqqGlkyFkyGpDUhakaDJ2s
# eKE+QS9OiuSHt8jizkmZVU3D6+7J2kKZSKTHuX3GhOSW2zeJIxptQhCExWysyVmydWd28E6E6E6El+AxCqcSzL0KrE1STemNNMkn6MEHBx6ZJJ
# sZEEuRR3clyPFUhMuW/RX6PH0EKwaVULgy5HXwbsft6EiOW5jVgfAyBqvqSSSST60bcCKt4XLaGIxhksEKyup2dnZBCIRGtlSvpY7D9CcOR1VZ
# BiTdsEejDckyb3qorkyuRXI8vPLyhQ5KCRuI1OTn5Fv8nIbhXsVPLl3ENnNtT8MKi1Y2E/wDTOWcsl5sl6lSNTcQ80NMh6EPQ4HAh6EPToh5oU
# 5lbJ0skl5/JXN9inP5FOYpFObHqRk05VBqRRKbQjo20aHFTlJi+G6dOBqEJhKuY1uRuQcDK6lSWSyvisknySV4ymQoLgyEb4xJMuhM2NJmZSvE
# wJmxh2oVohEq2pWyTo6OrKkk6FxqquJFsfUWK+4sqRxodWSSSSySSSSSSSfTJJNkkpJrCQ1il4rHJwXFcifaoSWXsqK8ikvwc8uBpDY/bpw00K
# RBtqJmsUSyVermisempX2KQpIu8+TBC0MbOzs7O7J1JJt59D2HsMYx2ux8BeAvVFIxXoalQxNBtDaUzXDXDV6GuGv0Nfoa/Q1w1w1Q1Q1Q1A1A
# 1g1SaHrEoUDhkpxK5F7bKpIoz84Md268jyyv1G2vdiGZAlE6MlkskaA0ESybHGZQghkPUjRkaMncmxL17F5Ujch6kPNlc2LkTVv8WIjE52ze/u
# r5Q2DHOiZqbarUtirWLWLWDUDWDVDXLXDXDVBqZwahwiVOCIwwIl0PwFNVyiJmN2qxWEK1Mlku12ySSSSJjsOGnKeo8IqtGbFCQzo6skkkkkkk
# mySSSSfRJEozIuKwmf6D0nVv2whEwpillWeDq8Y5ty2MfuYHLEm0rJRvWK+40UtF30pJJ1ObJJJJJJFllRhXVngRNrpbct5s4J0J9NChQjQhEE
# WyMY0ND9NzImr2aLrq1VqhWyNJ3pM0BpOjQGk6NJ0aTo0nRpOjSdGk6NJ0aTo0nRpuj+YL9YII0kmhVUWyNaqW7gWqDWskrP4KZ/Aw9hGgpoLg
# nbonboe5yRv0Q/EQ9ejvo4fRXJkPIgh5kZiuYpzRGpyTY2fAvEE9ehNkxNkxc4hNKKqxIfSstOGwaN1HkjRWJpujRdGi6NEaI0RpujSGmNMaQ0
# gsoZAJUJUHKnF59hmEJoi/m8kYw/QhCCSElmUKC9cv1zSKxwyp4YPwK6p0aJJGxQuzI8P1TGc9f70/vbCtPqc7uwD+1s87qC9uBeUkIRNU4Wub
# 5Jp9eiCPYIQssctpS5hLNiKPmmnm8WNy5H7tilQj+RK1ipZsUJykaVPokkn6zKIpbIavS3eLEhAvRNlPRyR62MYx2ux4cDkaj8ChLj0SceupLz
# OTmzr0bx1mohI6sIU0M3MjWypwzhlcmVKkm5ErNE6onUknUnUl5lSTkjVnZL1K5lc2VzdsrL5EwLsOB8CfTJJJNvfoSENgKQUTPgLke0dk36UQ
# FAoFwQRZJOqJ1ROqGzk5K5lc/Vh+TSnswfIsMZI8Fadvf2HNWkkknCKJGt6Y870zW9M8KZrOmPP/ACPM/I8z8jz3yPPfJ5zH++Y/2THnO2Nc3b
# IZ/kbfN7h9JqaCxY2Pl9KCPpoSGoSvYmoVw9nF/YlDH7vbHeIwYVbZYPwOYkhpw0ROHj9abJJJHrJOK/ic2Lj6Z0OLeTk5tlEooQQRuNDQ0NDR
# HpZRq9CQUl8GISbJJ+l2dnBxZSxUViSpyKuUubk2Q9CHoQ8yub6K69HlxTxELxFMkRouiNuiNfgiMSFmUJVnR0cI4JjAnySSUSiVl8DRKXCSGs
# 6CY0v1Vtkm2CBCEjHemmbTBcjCvEosMlwiZjDfoSEhIQhWc2T5FsEWSSTZwTocWNJqHiTH2QzHubDEdB1EJVCvgNjI9F7cjUiydCWSybH9BpCJ
# DcuXbBBBH0p9KETMnJtxOOSxZMNUSiZInEfvZYN1RRlLoLPB8jvIAqSzvUqH92f3ds139mf35/en9of2x/bH9OIyXoaCCijQPlEmnGLqXDRKJk
# heriyCLerJtgi1jGMdrsaGIkb3XNGM2UPz9OSSSSfQrxyiwvs4EdDgWnApuJ0ZsZyJJOiduiX4hsS8yuZyTqySWVzK5nKOjo5RTNELNELNEbWV
# IZAoXurETC+hz9EhO5iRKViHNh4IYxt1Yw/SkIIQhFBQSSSScnJTMpmck+R6HJWyRTiijt0u/wBCVtCjwK/4PuYMzqNzfbX1MdnBwcehjUMXs5
# QmhQQSwxEoWiJemBfewGx+9rEFWmU8GZekNfmK5eQ93SUzykn/AESy+TZ8nhJD+jwk8JPCSQ8JPGSH9Ef7I/0b3YxsDem780LxCJtMuLhWT9KC
# CF62MYxofpaURCX3fkVjHEp9aCCBysgjrd7TasrUvl4DJZLKlcyXmSzJepJNlcyNxCIJJtgSIednY9iuXwS9CdhLmShDGN3uy56erZJJJ9CsTE
# hU7KlHiXdXjmKThtt5vFkjGx+hCEJCQipUrodWSinpjYjayCPSg9NQjGaQIdasqxL+rhlF0URUaIIODiypUc2R6J9DUq2fYTYrEqvF1ZLkvAG5
# dj91JJJJJR+BF4ON/wBBIR9CSSSSdbJ9FbOn+hjSIvnxXPoj1delWVte5yMY0NDGvSnDkdXO4hjTYxvEdeiOvRHU3DcNw0maTNJm8bxvG4bhuG
# 50S0lcKCSyItSHOYiU+4ilkrJErQlZohmiGhOhIqJeT7JevZO5TMpmUzJJ1+Cdfgnwjk5OX0V16K+IqUXde3ETjlyJWlVJuG50bnRudG50bnRu
# dG50bnRudG50bnRudG8LUNQUEl0IPolLfmCRjD9CQhCEKBQUOSmZKzRK0J2G9ES8kSzo69LZUljY2zEoNTxx8F8j4zBJNtSfR2SSST9BI9E/X1
# AWYGYBpCVSVu7JikKpkyhj99mG4hi/8F7Kg9COMafkTAJXRcvd/pX15JGMaGkNDtdjoiQ5Wl8mttQhrhrvosYgEMY9Q3FeXYcvf40MSzxoSRjI
# k8CupUu/RIoGJTC9DQNVTUqp5eRqdFciuRyOGdnLOWRq/RwcFMhvYb2J1ROpNpTHi6IvsZqrVjkoJV7Uai8V9h+K+w/H/Yfl/t9T/YxrGMQhig
# LKFwDDDhtjDfpQhCQl6KEIghFCg9mPm3r1vkvESJyWLeyFkpVEsFe926jGNicWQUKFPR2TuVK2QQR6XWnrn6ksljCCd6dGtBUCqobzwP7WUx+9
# vEzuQ225eP0ufVyc2wLmlzEVpUfgMUZD4a1FbwcEEEEWySSSSyWVHaxjQ0NelyhIaSSTAkrmSzNQ1DUNY1jWNY1jWNQ1hZws1dGaXQu6pWKg/w
# AJRyfDL2tobWOT9KYiq7wpoSToToSJkvNk6snV9nPyJrP5JRKJ2K6HRTIhFNOxvVdk6rsnVG5G5dFcVyohFfxwJJr3TfizAXmr8Gr8DzB5xqGs
# ahqGsaxrGsanwSJk8xNvcSUk2e4nKtixCEmKRCWhQoI6trZJJPqdjY2Nk5ETFPLy/guEbzDGySbJJJRwcEk2wUKeibGJiL2SEyJwUYdcmeJE9e
# arZoWQ/eSIoUdi+vPonQkllvX+D0kOLXWH2fQnQnQnQnSxeiSSSbWNDQ0O1oRWN7oh/VgQkIJEinhcR61R/ivgojvXodRNrao06C0IrybYWpTU
# leMp4ymXyUyKEolE6krUpqUyKZELIhZEeSR5I6f0oq//ABbDVcZ5LMdnFCoWxe5IIH9ZUHVVkGI2th6EIQhCgjcoU9EbEaI4tqV9DtbGyYlIiY
# Jhu7hL5QrkXJYImGctjgfpleqpX0TvbBBBA1DtoU+uhhqEdUQPek/uoaDqpH7tDR/gVSfY8lMyhQcpMB5KQ9U14x7VKuYXP1SibK2yTZzZS2dj
# oe4xjGh2JCkMsLlRfWQhCEJyTTqhKhSyjMTvQp6dusZsKGqehZU5HnwyhKJ3J3J3JWZCzKZkrMmwpl8ELTopZXIrkSSTr8HPwNCbbULQa1sSpr
# hlTwOkPh2JEEDQxj+pkKU1dUNKtQtxC3FGZySS7II1I1ObJJ+hJI2NinOG3J/YXyU8/wAhJP1I9NPUxJQmSST9Dn6CZAxiEcOZbJiXC4qxk8UR
# DhjH7pLDEyK5CX041I+nE5uJuJuGmh/Iri8TJJ+rNvBBBCGhoaGiClQeUUH9ZCEEEhlUOj/0kL0mtmjHcWSSSJDI6WoUYt0ckolZEkrXslE6E6
# fJPkk+SbPk8pNrNhOltMzkwr1YkNwm26ImbhV7D22whCQ0ND2Ht9WScn2i7L1VsIQkJCQkJaIjT01JZW2SSXkToTY7GMbFTC00ndhPuLJptt7z
# zHyNWc2STZQpZycnJyc+rj1JD9mhMbnVCnuX24exr01DTL0P6c+mSSbJtmxCopxdwvZcepOHKvHpx5LhSV0NrNcP0z9WbODgY0NDQ1CJNvMZNt
# tkEEEEEEEEEEEECQkJCQkQhqxQOhl+opaitGTxRANE2pKIZu50YnJwQVsklEolEopZwRoRoRoQ8rG59jprP5G2zbct32YPkiFL3XdkM24yEEEM
# aGhoaIII9MEEEEGQc7Cr+BlEhIQhbCs6J2JsnT0QR6WS7G9RsgvMhYtjQU5NTvfYlmrlF6Ztkn69SpU6GpV30o+kiJyUxvAZcijswfIgMf0pJJ
# JJJtkkkkmxJcDcsX0ZJ9Mkk/Qp7vCkcScrwy83DTTadGr0/TJJPr7J3J3Ozu2BoaIHlwHC3N2QlSCCCCCCCCCCCCBISEhISGhsY2R3iSYqXHk8
# Bm1TTmIyfo5FhyVW63Njk5snYnYl6EvJFdCuhOg2bCRLK6ldeyvjKlDRFiabKjrJXasvHixWkEDQ0NDRBBFkEEEEEEEEDtQ04aP0DXiVKRCQkJ
# EIoUJ1OShHpoUKEk6j3sY2Nl26TwOCi3W9t65JJJ+rT1MSs+0TIqDGsLhz4HNMPkwGP0JiTCAQCAQ/oeFjS9jS9rC8LWV5GPIx5GNJ2NB2NB2H
# uRch0iBFyjMXpoU+pBBz6qjUVjEExNHhWH739+iPXBBBBUkklksqVOCNBpHBXTlPyDu93uyCCCCCCCCNCNCCCCBISFscIa0XY7CEyiaoikvu34
# M3DG2g0moGIS9ClSQ7jhlcjo6OimSKZErI4K5WyiFidy5HV0VrtGdHJBJXXyY6sSFYRA0NDQ0QQRaQR6gRoUMRQNy8ngxGxcNOGtbCQvRJNs6W
# 1KkMi2SXax+MSnIL30SEkejRPyPbeMdnl9k2yyX7VlxJP0p9aGgjuyESqqKPP9BgMdqYjkJEsiWSJZIlkSyJZEsieRPInkSyJ5fJPJdk8kTyRi
# lKoTQc5qlVPNYCqL2Ek2wR6oXBiXWpJk8ODFWQ+GSST66FPV3bUqVEqi24W4mSdObxYkuxBBBBG5G5BBBBBBGgloJaC2RTIlDaG0NhsJlIo4SV
# Q9hjrjPNZ+lcRS2Rgoa/sa8a8aoaoa7pms6ZrOmajpnmY13TNd0zVdM1/YX9YX9Ypp6LLnvdxNvkfcxoUCQkIJCsaGhhiCCNyCCCNGRoyCCCCC
# CTUZDlYR9hjbivFJBBXSySSbODj6bGVsJMvPBXN5I0mFWPb6c2P2SY/Rj6aImNTSvdSWaxQq/VSaF1BjL2L2UTljcXEsZa4kIXuaFCmgpqcSrt
# iCgaFqYHxd9eSSSSSRFzXu4c18bQWL+w8KLODg4I0I0IIIIII0IIII3I3Ejy8nyRtjdhjMLoqS/MiWDvXoY5u9QTzRPNE80TzRPNE80TzRPNE8
# 0TzRLNEs0SzRLNEs0aiEDThrAkrHcv8QpuihKJaEyxWEJaCSyIWRCIQ0hociCCCEQIEEEaEaEEEakk5kQZO2qGMGMGlK7IwYiCCCPVJJPqdjY2
# VhhO6lcuXQRFJbolhkhuW26tkon0x6pJJJ9gx0dlPZJjE006ogzU3cVZDGJC9khtFiUJhcXRmhMn3VRykdUJZPRNZid6I8cu6Ln6Z+pJNlyHrl
# F5vJLxMiSShMkOrkggoUKFLJ0J0tgggjUhZkLO2UMZwGMZC0kbEa662zIUNSrZskkmyn1LhGoXsoGo9ENgISEEhJiTIZLQh5EW1IehGxBBGhGl
# nl55fZBBB+AV9JtEr5eiWDvQnbJJNskk+tskY0KWOTFOVKudskkkk+jq3r2TaSkaoJC9omRMepTFZTyYpC4vVliQkOCJZHtF1LmNGt7q+TLnDo
# xfTgj1z9GCW53bk8lZs5rH7vRx6I9NbalSoiFQxvIpl8JgX3MIkklEokkm2SWVK6EEeiNSGQORsb0Ng9hjw4wY5WBXfkQVcWv2TaSXgJLcKv8A
# Axtte7EIJCQkIhWcHHycFCmp2d2ySTbLK2cl2I1oUp3Z6CFVUcWK4E00mimpTUpqQihJPpgj0OxlaHIsIYjge1nBxZJP14I9UEWYDkWWPA2mw2
# Gw2m02m02Gw2Gz6EiZCPDaUzlgY5JqGnDIhe2lWqJoRCo0P9iF7SfWnBOW5UjNpEiJO9eiSbYII+g3Bt3IWz/QMkOY6W2SUt6OrJfpg5OSSSSd
# Dg4smx2GMZSTmqKioK9oyIdjvtn6yvJHAaiXfcNyxISEhbCsjUhCsmzy4oUJRK1JJJs4JWRPpig7mJH6z08lyQNshbHDPLyV4ydTn0xZFnPokm
# JYJw5RUB28HBxa1bJNk6nJz64trbAkq1jSlkEEEKxBCIEIhEIhfRkTshKFr+hZExj9pEMjO64emo29ScWL1x9WEUzKZnNqqysET0x9CPQkO0TN
# /wCsaX6VXWP6EjJJJKlfTJJPo6J2t4OLJQ4HA4IDQxORBGxZuTwZN1KsP1z9Ro544CROBdqxvtiFaIVs292SSNkkklCUUKFCCLGSSOo02mXi2i
# hNSuXu8iGSvROpLz+myiK5C42xQwY97K2VK+upX2EzhXIQftpExqirxVBoPbeyeazGP1T9CbJ9MilwQaZOpZi9xJJIioi7ATauZrM1BqDVGqNU
# ao1RqjVGuNca41xrDWEk3coLxGjXm4N6X6ZZJJPq5tkkkmyhQpqUKDgcCDQx5UEGmR9jN5XspJ2EQomgOrEhISEhIRBBFvZ2StSVqSsidCSSSS
# STg4t6J2OCZMFESTE5sGNQoZD3EItCWRqTUmtNaa015rjXmvNcao1RrjXGuG3EJSxKei9L0OyCCCPXzZQp64I9G4CUuyfbyZyVI5eUrCeMZDft
# k4aaFqIJp0a0JVKtVs0IXuEiBRNWNgKSUtSpRWC8n5jV8Gp4vyHi/IJ/g/08f5BeU+55vzC8V9xeT+5reXUl8v8Ap5/ynj/KeD8o3OVcNqhvAx
# JogJS+WJmueKJRKJRKKWSSSVKlbKFPTXI4siySdBjEGMmUid3KNNQ1mTThCzcGt0Gt0GsGqhqoaoaoaqGqGshrdBrdBrdBqdBqdBq9Br9A50it
# 2xVQSEJCFsJ6E/QqVK2dHCOLI1OTmymZTM8vJJsbu0Gli2SF0KtV8Bq8P+mr4dTz/lPL+U0vLqaHl1NLy6ml5dTQ8uo1+X/TzfnPD+U8P5zwfl
# PB+YeV4tTyfmKlVJUf+BOUvRWMMR1+tJJP09gwEoQ3CEm0SJeMlp2T07Njs2Oza7Nrs2uzaGz2bXZtd/SVRWT7iBw7mSCZ+pYoQvY0KWU9FyJm
# 2LKtwpYdwst9Gi+jRfRomj8Gh8Gg+jQfQsp9Cyn0aT6N7o8CPEjwI8iHhK4ai9vurys422GD5Rs7v9ck2TqTqTuTuV1O7Js49VbXyMY7CTXeMh
# C4+VtQ1IakNSGpAhqQ1IkdSJDUgQsoO4gVvVPyEVCQkJCkUlcypUrZFkk6k6k6knHrgh6EPQiyoym6u4Ska1Qp6Ku+x2RKK6I0OhodDR6Gn0Hl
# vo3OjwI0uhpPo0H0aD6NDobnRv8ARudD1OiK5am9DQ4fpkUO9DRH0uzv6c2RKFexLLw7ZJJRKJRKJRAlEolfSSBe0n1sojqmIXnezxQvbowENL
# EhfQrp9GTGrYfXCJpf+j/BKlUXq3j0ySSTbPpknUkkkkklDY9jYUoeENmTNGzFmT0wR9NUYyTrVqNaDXN3mhoYhWFZQpZBCIIIIIRQoUKFCCCP
# TyclFiiv4YDZ6SuUXsp9NkC5DnNeySSSSSmhQlEk6nJz6WIXC5jSvQ0k0JpJRBBC9NfYNpJtjVBDCot/bpVF7zZHeJTsZmTGmzTUNUaEyfZSSX
# jcJG7ZI59mm001ehZstXp45olV3n0y4dBinkJyk06O2NSNTn1ySTZJJJJNs6nJyQMY8uRirivbyRKmISiWSHVz6otiyLI9ED4FxrG3sGlRkJCQ
# lqJLNlNSg49UEEEEbkbnZO5OhJ0V0K5o5RyRqiFQvd4hC2hLWb90v6FtxuV5QpbP1ZgSZPErE+fTA5cDsqVKlfZfkCY2Krlj9uqC97IoxRHS40
# 35i+jJNtChQp6UhpcYIvCUKCPpzZPqoDuZXybRz/LkvkX9mJ49PJyc+qCCn0JJJ0J8g8uHwGpBFN/gLBfcasezQ1C3oQm5f0cDQ00MmpkT1tUk
# 7ndsMj0QyHmRrbJO5PqZI28Bm5vEfVyn7Tk/uNirdPI3NXZwcEkk2TbJNskkkjYEqhhePSPRcVgZJJP0IVs+uBJe7GwLlHt0he+gGMyaqXDHXy
# XyL2aQ8NRhIU5kk+nr1z6uTka0kZOvFtoQ6F7e7yrSr0RTVk+qhQpmQiLJJsrZJPqbhF42KcqeQeCHVE2xoa+vFqHhxgyknlRyUNpjV+BBHo5J
# eZUrqV1sk8vOPVHrnccLxyEjbOEliIYqkyxy7JUKWnRHJXM5J9UEerskkllyo6En0bQx/Un6MzhXIQbgzf8AYxHBRl1XX9BezRM5wEvrE/Rr+G
# JHclR8ALsh7TRXFzOfqco6I2+hJOxwh5oTQqXMQsWLhE1Nn+lxM9EMY0QQQQR9KCBISKRptYhPGqx83u8a5oaEkHJyckkkkvMl5k2UKFClkakE
# eqXeOBVupAVUPA8c3Cr0NF7En5OSCCCPpR66GVxXofD0s1EMkn2O4MSl2OrgeXt0L2s/TThzNRCH2hUQ96nskQKMxsBYX1ZJJJ+hJJev8GpVFa
# y8EJDN3V5Hp6OrJJJ9ck+loREkhJzKFq/NwQLVjGMfqggj1QRYpFJWsMTCNQ3mw4MRNDoa1JUYMkklHBwjhHXroU+lS1chKcwF+Rmyrn5cmNbK
# mBycnNnNs/VpY0oq6udUJyp9FQLyCPrcHFsKg2KinP3KcP8A4CG6mNytn0SSSST9C5DXsWX6Z+tJPpchMBMyG2aa8clylXOLmV3DEkmyltChQ5
# J9EeiUStSVkydCSRiJpZC/IsqBe5m+WVgY0NEEEEEEEEEEEEEEEECQkJCJ5MCGFFa68ENKJNSJJJJJ9Ekk6kkk+qSbKer2JEKqDzcXld2RKON5
# I3qTqSySfXUrn66FCgnDEPWOA0OH6aUMfsYFCxErL2P3TYe/WRtCu9Ekk+uSSSSRD4DqxIUfT5OfVx9CNyxuJxJSh/Iri8TElkvRP059M28HA0
# IiUYsc5qL2cb5KHyGMZGxBBBBBDIIIIII9EEECQkM2TWAloSLzTXobO4mcXMkT6eDokkkkkm2CPRySTF5LvokyUiNgX/gTKENEXIYxu9jtkkmy
# PVJJOhOhOhJNs6EjYELhc7xpXoThyQJF7NQag1hrDWGszWZrM1GajNRmozUZqM1GSzZe7Gy5e7uFX3qHoYv/ACxZ5LP6jX6jX6jX6j+ZP5n0ZS
# H+RP4M/gz+DP4M/gz+DEWQziWmowuNs/Vkkn6KcOUNvuSJqqW3nwYxTWAhE1c/RJPomzg4OPoNy5YtbIqOSDXFcIwWCHVtvGyCCCCCCCCCCCCC
# CPRBHpicsbiaVNoerjXF4+BIoys6K6HVk+uSSfVCoY3iJ9TS1Xu8DJIXRX1x+hJJJJJJx6IIIII9EjSYncyHE/TN1SSktONj+VH+jH84fxh/EH
# 8QfzB/Bn8ma3SfyJ/Bn8WfzZ/Mn8CNjOOkrFVy/et71RjchpNlRGoZDIhkyGRDJm4bhoM0maTNJmkzSZpMhkyGT6IZfA+6fk8GJShHDQvqx9em
# OYZKpKrll5uHJuU01RohcuCSSdDg4sqV9XNk+h8ChBHXYdJYfcSPIvXBBBBBFsEEEevmxSigCyRDXCIcs+DE4hoUNUgjYjYj6sWoY3gNtjd7EJ
# pwMn4E/wCDJc3zyNsknQnQknQ49M/Tn0p4Eyherx8LVwKi3dOR6Cqu5f5YNYaTNBmgzcNzo0H0aT6NJ9EcmRyZHJkNSOpHUmaCw4Lqe+Tle7SG
# hfIvFT2Ui0EGqudVYP2sEeno6OhjSqliCETUNCsM/N/ZeEKff1PLvU3CwGhNsU3NWHwIa21LJ5JJJ0JtoU19E+uPpX5czEY0rw/e4hsQ004aeD
# GrHq5t69NfTO4XIayYhJYsgXd5Dvb+ri77ld9GfocnP0ZJJlCfaE5Qqug1W6jXLgoiuXsklTih+0oU+inD90iYUvAbl1F7NpJoQnLqqEzQ2ZlX
# tmhew5+hJJJI2bscqopMsnwxe0PhlEdz9k9YHK1S24SzZNWVW3Z+DZESUKfQghEeiSfT0dEbFPQ16kRkb8Kwz8icjJJKHfrl5EvKzr01bHAvZd
# DbfePhfJQE6+hz7huxMTcQ2ApmulCvH9BqTbbeJPtFh+/b3KQ0uFcrF7SFy4FxJO8WqxQhe5mySRSwuIhVSWpgfFwkMUkSOTSZpM0nbBojRGgz
# QfRoPo0H0aLNFmizRYnUSaGhGphuYvgclE1ZUr6+PbRDFTdPYyfBe3EMS1u40GaA0BojRGgzRZps0RoDRGiNEaDNFmiJcq4i0liXclixGhXCc+
# byXfXuOPRSySRKcshDtOhCebxZUsMPaJKgj3yp7hDdTF3e3mCBp1UJRmujNCF7tjJrASlpMoY7070Kfrcoc0tNxuNxuNxuNxvN5vN5vN5vN5Ja
# ScSuWo20okwzgSJJJ+jPqkknUqT6uTn0LShkspHT6Qqa4D4EcKm83m83m83m83m83m83m83m83igPfiITVd/L/wQ1InnFklClkWx6J9k2SSjf5
# qxf2I1DH6E/WTH37Ye3Q0tMLEvbbQxI0dXV8v2Kpw6NCF9OhT19/QgSJkmpwhKbUYSa8e4vJ/c8/8Ak8/+Tz/5PP8A5PG/n0vBjKt+tvi/zY+G
# 8spg8LwodzS+LNwVtSv0JJtkknf1VK+vYEX4xCMKwqZqSP0a7nXkvyeC/J4r8nmPyeY/J4T8nlPzbvvlPyea/J5/8lIpkrbAaEw04YnDt5sncn
# cn6tSv0mVpi82SxHm2lChMkSNt4k+1alDUOPfqvtUPCjF2L3E61QuCsmn9hC9jJUn1SSJk4zhDpRccL8ksG1yajs1HZLN2Szdk8/ZP9hrezW9m
# o7P6BqOzUdmo7P6h/UEppyfIiRIOqa8cwcq/MLmVjDG2LaFCfTx9GSSfXA1YySai3o43zcNVE4Z/YP7B/YP7B/YNZ2f2D+wf2D+wf0D+gf0D+w
# azslm7Jr3USpP91YP7Ey1E6ElChKJRPrkn60jY2VxSroWCJXDD3C0n37e1urghuXLsXuHlI6Hd8PTJl4k0C9jPrkbIlGLKryVohsPTJJPpkkn0
# QuWNxPJKVv5BcX2TKHerJJJtj6UWyST6YtqBCOhFokvJmKQoRglchuXLxt5ZO5OpJJKKeiSbU4cipGpZQmaJK9ebNCdSSfdsU7PNTwQyXfH7pI
# fv1VezQ+Hdi9pJJPopS4IpMrUsGIXuGXrRKtkiQ3ELBZL1TZwcEkk2zqSTZMMY0FMyFoRR2c1wJylCaalY+8pQGxi3Sp5yWH3ErjL0SSST65JJ
# tesEsmdqWK+40qLUe5bKtpJS3chD0pVXz/Q2xe6SV79OH7JEwptXuk2nKIGoSnRrNEylWq2aF7SSbWwI/UfYhsPTz9apsjKCpaTLJzcNNmmoao
# 0ytLj0V9NSGV9g4KRuXLFMzWa6EPNptkzr7VrJL0KQuK+jNCeJKJJ9MfXoUsYyAhk15uCBav3iQ/fpkolEolZkrMlZkolZkolZkrMlZkrMlZkr
# MlZiGlxgrF7yJxgyf+/M0L27cKSdzTd4Ic223V28+ifTQoUJRPqhX1QhUaUmX7FxAn68EeqSbZHGQjUiWcJLFiKv1U65fwbYvo0soUKempUkie
# ghg1NT5Cabaj9aCPYSSNl8C0ChU0wvyOk941K/6Chq/wCBdpehCUxWSyeKF7aSEqNQJdeebG5frn6tSoybsQNU4bLJ8C14ZDIKrn9Stkkkk2de
# iCBoDJsmV24vgelEuXbPtHlaopMSml/skUic2SST7NjKqu40ZuTAc++TH/or320CK5V5kxps01DVGT7OSBEw9927MansuPVOpcEClytXA+LrJF
# qvrySdWSTbJM0L8Fr8tRyEQrgz5GMfo79mnDGabvh6ajL1JwxP6Ek/VYyJai1bJEpwhXJZLBDcuX79qP8AwMk/VkUYoikvu35+1YpMRFFcIQ3L
# +jPqkn1yNDTQtFQUZixRKq5ermncSJJ9XBwcfVkiUZ2Jk3ELT9xWLf6skkk/RfAglytSwY8rUVvPrkkknT6LHr+zckTOJovryT7C5/z1/wABoc
# kl0BDETEnKTvWPs3hFZf4UZPocnP0ZJ9UkDlcyTVXmqsV97GmjII9Ekk/VuGlyUShEug9z0yWSwQ3Ll/Tn6yISErFZooKq1WzQnj7ZKooWh4sE
# JcyTb68+ylDv/wCaxP8A4LQrJ9i2X5cq9hzbb93IxNqGfIhSoqpZPFCcOUJypJskkkn6M2zZgDFA8RREzhXL3bYEnqPuQ+AvVP0p9DcIzCf/AA
# HQvf8AzUSK1er7E6f8BuX7N8BQcTr+A/XPqn0SST6ZJt2BiXLO+WD8DGIhpw0QOPZtwpG8RU1zdLPAvuOq1WxOPXP1aeifQ9NI4aEIzzZ4oTmp
# Nk2SST6psm2bHlwK4b/gNgL/AJqGiuGJQMMBU9+2Hs24UkjXFzVjYt1f0ZJ9pOorKIhFX2Z82SL2Ty4yFFyyEhWCnePPEzaPoz7CfQnDIOa648
# mKWbUETxZCX0mMJSlKQh/AP4h/FP4p/PP55/FHGKEjTV6dqcr3zcIv/wCarGwGqeKqrG966Kxp9k5UlWNJErp8mNy/fSJKxspj8i/Ibsien0Z9
# MEWNAZLF79jIFGev1aeyYSKS+7dmJyhYMKz0WCGuLTuRzdkc3ZH+jyOwQMcxER8OyREREREQ6aSY0xN6xtTh++aXY/cr2atbHEicq5++Yd3qqS
# ypUqVKlSWSyWSxcgsz3un5Df8AwM5sRq3cPX9BkvUl6kvUl6kvUl6kvNkvUl6kvUl6kvUl5sl6kvUl6ibmo1TSb3ksWMPAmE0JHNk/Vkn66oMr
# neoyd9XqyJm2dWST6Z+m0v0N7xoF/wBFOGJQbY3bjUDe7dFYxLScPZD+5D+pH9bI/rZH9LI/1I/1IfoZD9TI/qZH9T/BH9T/AAR/U/wR/U/wR/
# U/wR/U/wADnKKvqoOldRQqESt//Abio3laLh8yUhOVeiH6PwP4X4H8L8D+F+B/K/A/lfgR/R+BH9D/AAQ/W/wQ/X+BD9H4H8L8CP6vwIfq/Aj+
# v8CP6vwGiX2vwFQRN4BOhun0p9vKYReGWqtr+iR6L2To/Qqe8bl2wRqRqRqjYNo2DYNk2TZNkhlIZP8AhsLKS7OxOfdNyxiVFA2Gw2Gw2Gw2Gw
# 2Gz5NvybTabTabSsXsoTNEteV7ZoaX/AbljcVCk0qUwjyk8pPKTyk8pPKTyk8pPCTwk8pPKTyk8pPKReDMGI5IRMrUsGJjSvftCJTRk3EC1f1J
# 9dS9Le6bC2+2SSSSbGz/AJAFRjK53O8kNPAT9y1l7EoXsoHGZI6vUsUMake2n6DQhoNKFNA+FtfqyJwxTKEp0azROpVqtmhOHbPu2LV40Iiiuu
# FrmxpT7RqPSvcNl9j/AOm2AtTFf5Y3uGNiY+0amkvQpGfrR4oVGJyvqz7BvE0JrsJW24Rf7KBxmTev1LFCGw96+BIssHQsWUI9q6+lOvuGFYv+
# pA0y4LnVCp7duy9+1aGJK7vq2TEabTUNXj4e8bAbAUHEr+A0v6vHrYmkvQpKYrrR4oTxE59hNs/QbhESm4V7ZIlbdyVEskNtuX7ZPSnPpn2LcL
# /sNUapYqqsT9rNjE9tMtUQUmNN5cxpXum4GxMri4s2Oq26v6VPptDETXeZsmQ2adGhvdtUhtXoWCGlwvcOnoXtm5dq/wCs2OJUhc/9sXtG7Ep9
# unDkRW4oY9t4hofum6iTUiW3CESri882NL+lP1JljKIKW+7fmITle5aESKsd6vBDKte/cp6U/aNT0T/1k4YoabY/6NQxP2bsYlHuHwE73qrHle
# yn1NwhuCSa90+5j0j26cOR1VXKGNdhCce5rAqzcNJK4VbNkz090/cOv/bYSV0difsmMT3UpXs0UlVaraCcP3DcsapO8kKbpRKLYblz7h8CgtXV
# WN6Z9k0EJvhTdmRLV+7fpXsm/wC4mN07yZHsppZey73Tw4HL1n3IY+Htmxs8FhDYe6gahui6L1dgnD9s2OUl7HVLghDS594/S3T/AMcmM3fh7N
# ie8umr0LlI+yy5icqfasq+YY9ttj7t4Y5WFX8LG9q2BWWjojA96/8Ayb9pe/etDIq2uuaMYzTvV48OPaNjyKHHfuGl+6kkdRp1RUSXXtHYq+zd
# EXxcq2hI30Q/fP8A9Kxe+eVBFJeqflY0r2TGRS2F2rG7fvU4ZBG93wY02J0aE/ZsQWo+xDy4/wDgiXv04ZFfVlD2GvbAaH7JiTUl7IJJLg3L98
# 1IIpL1T8rE59i3CsQn/wAB+1f/AI9f8BsBfBpYhssbTYbTabTabTabTabTabTaM1hQhsPfpwx1ipZQxrWJg2m02m02m02G02Gw2m02mw2GwbkX
# /Cv/APRon/gyExJSgggggggggggggggggg0TQsRh6Yf8FIrxKrkaovIIIIIIIIIIIIIIIIsVqfvm/wDJySSSSTbNkkkksTeZLMkLD0w/4TKGbA
# UN815rzXmvNea815qjVWpas1ZqzVmvEnat9qrGp/wG5ZDrsTUM0XI15qzV+ltvVmvNeaux601prOzV9lYDxDGJ+ifeOlqo1ZLMlmSzJZkvMlkv
# Mkkkkkkkkn/yKIhGOFi/4CUBvrD2UTTRc96qE4fv27F8ig2HsULUx/wK1e8brYkutw3j/wCiTFxWP/AYm4xv2TQxqXEq2Gw9+qR3KsvG/ZpxUu
# i53ehe6btuUD/5P//Z
# BG_B64_END
