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
def inject_css():
    _h_css = "".join(".tbl-h-%d { max-height:%dpx; }" % (h, h) for h in range(120, 1001, 20))
    _pw_css = "".join(".pw-%d { width:%d%%; }" % (n, n) for n in range(0, 101))
    st.markdown(f"""
    <style>
    section[data-testid="stSidebar"] {{ background:#0B0B0F; border-right:1px solid #1d1d24; }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius:18px !important; border:1px solid #23232b !important; background:#111116;
    }}
    /* Tab menu bergaya pill */
    div[data-baseweb="tab-list"] {{ gap:6px; row-gap:8px; flex-wrap:wrap !important; overflow:visible !important; height:auto !important; }}
    button[data-baseweb="tab"] {{
        background:#15151b; border:1px solid #23232b; border-radius:999px !important;
        padding:8px 16px !important; margin-right:2px;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        background:rgba(169,166,247,0.18); border-color:{ACCENT2}; color:#fff;
    }}
    div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {{ display:none; }}

    .app-title {{
        text-align:center; text-transform:uppercase; letter-spacing:2px;
        font-size:3.2rem; font-weight:800; margin-bottom:0.1rem; line-height:1.1;
        color: {ACCENT};
        text-shadow:
            1px 1px 0 #d48ace, 2px 2px 0 #b874b2, 3px 3px 0 #9c5f96,
            4px 4px 0 #804b7b, 5px 5px 10px rgba(0,0,0,0.6);
    }}
    .app-watermark {{ text-align:center; color:#8b8b98; font-size:0.85rem; letter-spacing:0.6px; margin:2px 0 1.2rem; }}
    .app-subtitle {{ text-align:center; color:#9CA3AF; font-size:0.9rem; margin-bottom:1.2rem;}}
    .kpi-box {{
        border:1px solid #23232b; border-radius:18px; padding:16px 18px;
        background-color:#111116; height:100%; min-height:108px;
    }}
    .kpi-icon {{
        width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center;
        font-size:1.05rem; background:rgba(243,166,233,0.16); margin-bottom:4px;
    }}
    .kpi-label {{ font-size:0.8rem; color:#9CA3AF; margin-top:2px; }}
    .kpi-value {{ font-size:1.5rem; font-weight:700; color:#F3F4F6; word-break:break-word; line-height:1.25;}}
    .kpi-sub {{ font-size:0.75rem; color:#9CA3AF; margin-top:4px; }}
    .kpi-cmp-up {{ color:#34D399; font-size:0.78rem; margin-top:2px; }}
    .kpi-cmp-down {{ color:#F87171; font-size:0.78rem; margin-top:2px; }}
    .big-nominal {{
        text-align:center; font-size:2.4rem; font-weight:800; color:{ACCENT};
        padding:10px 0 2px 0;
    }}
    /* Kotak Capaian by Divisi (menu By Salesman) */
    .dv-box {{ border:1px solid #2a2a33; border-radius:12px; padding:8px 10px; background:#14141a; min-height:66px; }}
    .dv-label {{ font-size:0.62rem; color:#8b8b98; text-transform:uppercase; letter-spacing:0.4px; }}
    .dv-value {{ font-size:0.92rem; font-weight:700; color:#f3f4f6; word-break:break-word; line-height:1.2; margin-top:2px; }}
    .dv-sub {{ font-size:0.62rem; color:#8b8b98; margin-top:2px; }}
    .dv-gap-bad {{ border:2px solid #ef4444; }}
    .dv-gap-bad .dv-value {{ color:#fca5a5; }}
    .dv-gap-ok {{ border:2px solid #22c55e; }}
    .dv-gap-ok .dv-value {{ color:#86efac; }}

    /* Tabel seragam: semua kolom rata tengah, header sticky, bisa scroll ke kanan & bawah */
    .tbl-wrap {{ overflow:auto; border:1px solid #23232b; border-radius:14px; background:#111116; margin-bottom:6px; }}
    table.tbl {{ border-collapse:separate; border-spacing:0; width:max-content; min-width:100%; font-size:0.84rem; }}
    table.tbl th, table.tbl td {{ text-align:center; padding:8px 16px; white-space:nowrap; border-bottom:1px solid #1c1c23; }}
    table.tbl thead th {{ position:sticky; top:0; z-index:2; background:#1b1b24; color:#C9C9D6; font-weight:600;
                          font-size:0.78rem; letter-spacing:0.3px; border-bottom:1px solid #2c2c37; }}
    table.tbl tbody tr:nth-child(even) {{ background:#14141a; }}
    table.tbl tbody tr:hover {{ background:#1d1d27; }}
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
    .dv-panel {{ border:1px solid #23232b; border-radius:14px; background:#111116; padding:10px 12px; margin-bottom:10px; }}
    .dv-title {{ font-weight:700; font-size:0.95rem; margin-bottom:8px; color:#F0F0F7; }}
    .dv-grid {{ display:grid; grid-template-columns:1.4fr 1.4fr 0.75fr 1.5fr; gap:8px; }}
    .dv-panel, .sc-card {{ container-type:inline-size; }}
    .dv-grid .dv-box {{ padding:7px 8px; min-height:auto; }}
    .dv-grid .dv-value {{ white-space:nowrap; font-size:0.78rem; font-size:clamp(0.6rem, 2.5cqw, 0.88rem); }}
    .dv-bar {{ height:4px; border-radius:4px; background:#23232b; margin-top:9px; overflow:hidden; }}
    .dv-bar span {{ display:block; height:100%; background:{ACCENT}; border-radius:4px; }}
    .dv-bar.ok span {{ background:#22c55e; }}
    .sc-wrap {{ padding-right:2px; }}
    .sc-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(460px, 1fr)); gap:10px; }}
    .sc-card {{ border:1px solid #23232b; border-radius:14px; background:#111116; padding:9px 11px; }}
    .sc-head {{ display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:7px; }}
    .sc-name {{ font-weight:700; font-size:0.88rem; color:#F0F0F7; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .sc-tag {{ font-size:0.62rem; color:#B9B6F5; border:1px solid #3a3a55; border-radius:999px; padding:1px 8px; white-space:nowrap; }}
    .sc-card .dv-box {{ min-height:auto; padding:5px 8px; }}
    .sc-row {{ display:grid; grid-template-columns:92px 1.4fr 1.4fr 0.75fr 1.5fr; gap:6px; align-items:stretch; margin-bottom:5px; }}
    .sc-lab {{ display:flex; align-items:center; font-size:0.66rem; font-weight:700; color:#B9B6F5; letter-spacing:0.3px; white-space:nowrap; }}
    .sc-cell {{ border:1px solid #23232b; border-radius:8px; background:#14141a; padding:5px 6px; text-align:center;
                white-space:nowrap; font-weight:600; color:#E6E6EE; font-size:0.74rem; font-size:clamp(0.54rem, 2.05cqw, 0.8rem); }}
    .sc-cell.gap-bad {{ border:1.5px solid #ef4444; color:#fca5a5; }}
    .sc-cell.gap-ok {{ border:1.5px solid #22c55e; color:#86efac; }}
    .sc-row.sc-total .dv-box {{ min-height:auto; padding:5px 7px; }}
    .sc-sep {{ height:1px; background:#1f1f27; margin:6px 0 6px; }}
    .sc-row.sc-divisi {{ margin-bottom:4px; }}

    /* Kartu KPI Gap Harian: hijau kalau tercapai, merah kalau belum */
    .kpi-box.kpi-bad {{ border:2px solid #ef4444; }}
    .kpi-box.kpi-bad .kpi-value {{ color:#fca5a5; }}
    .kpi-box.kpi-ok {{ border:2px solid #22c55e; }}
    .kpi-box.kpi-ok .kpi-value {{ color:#86efac; }}

    /* Mobile-friendly — layar sempit (HP) */
    @media (max-width: 640px) {{
        .app-title {{ font-size:1.7rem; letter-spacing:1px;
            text-shadow: 1px 1px 0 #d48ace, 2px 2px 0 #b874b2, 3px 3px 5px rgba(0,0,0,0.5); }}
        .app-watermark {{ font-size:0.7rem; margin-bottom:0.7rem; }}
        .kpi-box {{ padding:10px 12px; min-height:auto; }}
        .kpi-value {{ font-size:1.1rem; }}
        .kpi-label {{ font-size:0.7rem; }}
        .kpi-sub {{ font-size:0.65rem; }}
        .big-nominal {{ font-size:1.6rem; }}
        .block-container {{ padding-left:0.6rem; padding-right:0.6rem; padding-top:1rem; }}
        button[data-baseweb="tab"] {{ padding:6px 10px !important; font-size:0.8rem !important; }}
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


def kpi_card(icon: str, label: str, value: str, sub: str = "", cmp_html: str = "", state: str = ""):
    """state: '' (netral) | 'ok' (hijau) | 'bad' (merah)."""
    st.markdown(f"""
    <div class="kpi-box {('kpi-' + state) if state else ''}">
        <div class="kpi-icon">{icon}</div>
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
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
            f'<div class="dv-value">{value}</div>' + (f'<div class="dv-sub">{sub}</div>' if sub else "") + "</div>")


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
                       f'<div class="sc-cell">{fmt_rp(d_tgt)}</div><div class="sc-cell">{fmt_rp(d_cap)}</div>'
                       f'<div class="sc-cell">{fmt_pct(d_pct)}</div><div class="sc-cell{g_cls}">{d_gtxt}</div></div>')
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

(tab_overview, tab_sales, tab_salcard, tab_wilayah, tab_subbrand, tab_mhs, tab_insentif, tab_lato,
 tab_ltdnpl, tab_paretto, tab_stock, tab_ss, tab_readme) = st.tabs(
    ["📊 Overview", "🧑‍💼 By Salesman", "📇 Capaian Salesman", "🗺️ By Wilayah", "🏷️ By Subbrand & Divisi",
     "📦 MHS", "🎯 Insentif", "📋 LATO", "🆕 LTD NPL", "📐 Paretto", "🗃️ Stock",
     "📈 Performance SS", "📖 Read Me"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
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
with tab_sales:
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
with tab_salcard:
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
with tab_wilayah:
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
with tab_subbrand:
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
with tab_mhs:
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
with tab_insentif:
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
with tab_lato:
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
with tab_ltdnpl:
    with st.container(border=True):
        st.markdown("#### 🆕 LTD NPL")
        st.info("Menu ini akan dikembangkan lebih lanjut setelah definisi rumus LTD NPL dikonfirmasi.")

# ---------------------------------------------------------------- Paretto
with tab_paretto:
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
with tab_stock:
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

    if len(stock_files) < 2:
        st.info("Upload minimal 2 file stok (tanggal berbeda) untuk mulai membandingkan.")
    else:
        raws = []
        for sf in stock_files:
            try:
                raws.append((sf.name, stock_read_raw(sf.getvalue(), sf.name)))
            except Exception as e:  # noqa: BLE001
                st.error(f"File '{sf.name}' gagal dibaca ({type(e).__name__}: {str(e)[:160]}).")

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
with tab_ss:
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
with tab_readme:
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
