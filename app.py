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

ACCENT = "#F5B301"
PALETTE = ["#F5B301", "#38BDF8", "#34D399", "#F472B6", "#A78BFA", "#FB923C", "#94A3B8", "#F87171", "#4ADE80", "#60A5FA", "#FBBF24"]


# =====================================================================
# 1. STYLE
# =====================================================================
def inject_css():
    st.markdown(f"""
    <style>
    .app-title {{
        text-align:center; text-transform:uppercase; letter-spacing:2px;
        font-size:3.2rem; font-weight:800; margin-bottom:0.1rem; line-height:1.1;
        color: {ACCENT};
        text-shadow:
            1px 1px 0 #c98f02, 2px 2px 0 #b17f02, 3px 3px 0 #996f02,
            4px 4px 0 #815f01, 5px 5px 8px rgba(0,0,0,0.55);
    }}
    .app-subtitle {{ text-align:center; color:#9CA3AF; font-size:0.9rem; margin-bottom:1.2rem;}}
    .kpi-box {{
        border:1px solid #333944; border-radius:12px; padding:16px 18px;
        background-color:#1C1F26; height:100%; min-height:108px;
    }}
    .kpi-icon {{ font-size:1.3rem; }}
    .kpi-label {{ font-size:0.8rem; color:#9CA3AF; margin-top:2px; }}
    .kpi-value {{ font-size:1.5rem; font-weight:700; color:#F3F4F6; word-break:break-word; line-height:1.25;}}
    .kpi-sub {{ font-size:0.75rem; color:#9CA3AF; margin-top:4px; }}
    .kpi-cmp-up {{ color:#34D399; font-size:0.78rem; margin-top:2px; }}
    .kpi-cmp-down {{ color:#F87171; font-size:0.78rem; margin-top:2px; }}
    .big-nominal {{
        text-align:center; font-size:2.4rem; font-weight:800; color:{ACCENT};
        padding:10px 0 2px 0;
    }}

    /* Poin 6: mobile-friendly — layar sempit (HP) */
    @media (max-width: 640px) {{
        .app-title {{ font-size:1.7rem; letter-spacing:1px;
            text-shadow: 1px 1px 0 #c98f02, 2px 2px 0 #b17f02, 3px 3px 5px rgba(0,0,0,0.5); }}
        .app-subtitle {{ font-size:0.75rem; margin-bottom:0.7rem; }}
        .kpi-box {{ padding:10px 12px; min-height:auto; }}
        .kpi-value {{ font-size:1.1rem; }}
        .kpi-label {{ font-size:0.7rem; }}
        .kpi-sub {{ font-size:0.65rem; }}
        .big-nominal {{ font-size:1.6rem; }}
        div[data-testid="stDataFrame"] {{ font-size:0.75rem; }}
        .block-container {{ padding-left:0.6rem; padding-right:0.6rem; padding-top:1rem; }}
        button[data-baseweb="tab"] {{ padding:6px 10px !important; font-size:0.8rem !important; }}
    }}
    /* Tabel lebar/panjang tetap bisa di-scroll horizontal di HP, bukan kepotong */
    div[data-testid="stDataFrame"] {{ overflow-x:auto; }}
    </style>
    """, unsafe_allow_html=True)


def kpi_card(icon: str, label: str, value: str, sub: str = "", cmp_html: str = ""):
    st.markdown(f"""
    <div class="kpi-box">
        <div class="kpi-icon">{icon}</div>
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
        {cmp_html}
    </div>
    """, unsafe_allow_html=True)


def fmt_rp(n) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)) or pd.isna(n):
        return "-"
    try:
        return "Rp {:,.0f}".format(float(n))
    except (ValueError, TypeError):
        return "-"


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
            out[c] = out[c].apply(fmt_rp)
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
    app_password = st.secrets.get("APP_PASSWORD") if hasattr(st, "secrets") else None
    if not app_password:
        return True
    if st.session_state.get("app_authenticated"):
        return True
    st.markdown('<div class="app-title">Dashboard Operational Area MV42</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Masukkan password untuk mengakses dashboard</div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        pw = st.text_input("Password", type="password", label_visibility="collapsed")
        if st.button("Masuk", use_container_width=True):
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
st.markdown(
    f'<div class="app-subtitle">Tahun {tahun_aktif} &middot; Periode {", ".join(map(str, periode_sel)) or "-"} '
    f'&middot; {len(salesman_terpilih)} salesman terpilih'
    f'{" &middot; komparasi vs " + str(tahun_aktif - 1) + " aktif" if bandingkan else ""}</div>',
    unsafe_allow_html=True,
)

pencapaian, bruto_f, bruto_r, pct_retur = hitung_pencapaian(df_filtered)
oa_total = hitung_oa(df_filtered)

kode_sales_scope = df_filtered[COL["kode_sales"]].unique().tolist()
target_total = 0
if not target_all.empty:
    tgt_df = target_all[target_all[TARGET_ALL_COL["kode_sales"]].isin(kode_sales_scope)]
    if periode_sel:
        tgt_df = tgt_df[tgt_df[TARGET_ALL_COL["periode"]].isna() | tgt_df[TARGET_ALL_COL["periode"]].isin(periode_sel)]
    target_total = tgt_df[TARGET_ALL_COL["target"]].sum()

gap_harian_total = ((target_total - pencapaian) / hke) if hke else 0
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
    kpi_card("📉", "Gap Harian", fmt_rp(gap_harian_total), f"HKE yang dipakai: {hke}")
with k4:
    kpi_card("🏪", "OA (Outlet Aktif)", f"{oa_total} outlet",
              f"{oa_pct:.1f}% dari CB Standpro Area ({cb_standpro_area})",
              compare_badge(oa_total, oa_prev) if bandingkan else "")

st.divider()

# =====================================================================
# 6. TABS
# =====================================================================
ringkasan_sales = ringkasan_by_salesman(df_filtered, target_all, periode_sel, hke)
mhs_resume_all = hitung_mhs_resume(df_filtered)
mhs_by_sales_all = hitung_mhs_by_salesman(mhs_resume_all, df_filtered, outlet_count_dmp)

(tab_overview, tab_sales, tab_wilayah, tab_subbrand, tab_mhs, tab_insentif, tab_lato,
 tab_ltdnpl, tab_paretto, tab_ss, tab_readme) = st.tabs(
    ["📊 Overview", "🧑‍💼 By Salesman", "🗺️ By Wilayah", "🏷️ By Subbrand & Divisi",
     "📦 MHS", "🎯 Insentif", "📋 LATO", "🆕 LTD NPL", "📐 Paretto", "📈 Performance SS", "📖 Read Me"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
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
            st.dataframe(format_cols(tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]],
                             "Download Excel (Klasifikasi Outlet)", "overview_klasifikasi_outlet.xlsx", "dl_ov1")
        with colB:
            pie_tipe = top_categories_for_pie(tbl_tipe[["Tipe Outlet", "Omzet"]], "Tipe Outlet", "Omzet", 6, False)
            st.plotly_chart(pie_chart(pie_tipe, "Tipe Outlet", "Omzet", "Omzet per Tipe Outlet"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🏆 Top Contributor (6 Terbesar)")
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            st.markdown("**👤 Salesman**")
            st.dataframe(format_cols(ringkasan_sales[["Salesman", "Net Sales"]], rp_cols=["Net Sales"]),
                         hide_index=True, use_container_width=True, height=240)
            pie_sales = top_categories_for_pie(ringkasan_sales[["Salesman", "Net Sales"]], "Salesman", "Net Sales", 6, False)
            st.plotly_chart(pie_chart(pie_sales, "Salesman", "Net Sales"), use_container_width=True)
        with oc2:
            st.markdown("**📍 Wilayah (Kabupaten)**")
            net_wil = net_by_group(df_filtered, [COL["kabupaten"]], "Omzet").sort_values("Omzet", ascending=False)
            st.dataframe(format_cols(net_wil[[COL["kabupaten"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=240)
            pie_wil = top_categories_for_pie(net_wil[[COL["kabupaten"], "Omzet"]], COL["kabupaten"], "Omzet", 6, False)
            st.plotly_chart(pie_chart(pie_wil, COL["kabupaten"], "Omzet"), use_container_width=True)
        with oc3:
            st.markdown("**🏷️ Subbrand**")
            net_sb = net_by_group(df_filtered, [COL["subbrand_name"]], "Omzet").sort_values("Omzet", ascending=False)
            st.dataframe(format_cols(net_sb[[COL["subbrand_name"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=240)
            pie_sb = top_categories_for_pie(net_sb[[COL["subbrand_name"], "Omzet"]], COL["subbrand_name"], "Omzet", 6, False)
            st.plotly_chart(pie_chart(pie_sb, COL["subbrand_name"], "Omzet"), use_container_width=True)

# ---------------------------------------------------------------- By Salesman
with tab_sales:
    with st.container(border=True):
        st.markdown("#### 🧑‍💼 Kinerja per Salesman")
        st.caption("% OA dihitung dari standar CB per Team (Read Me). EC = akumulasi jumlah outlet unik "
                   "bertransaksi (F saja) per hari, dijumlahkan sepanjang periode. Target/Gap kosong "
                   "ditampilkan '-' kalau file Target belum diupload.")
        salesman_filter_sales = st.multiselect("Filter salesman khusus menu ini", salesman_terpilih,
                                                default=salesman_terpilih, key="sales_salesman_filter")
        ringkasan_view = ringkasan_sales[ringkasan_sales["Salesman"].isin(salesman_filter_sales)] if salesman_filter_sales else ringkasan_sales.iloc[0:0]
        show = format_cols(ringkasan_view, rp_cols=["Net Sales", "Bruto F", "Bruto R", "Target", "Gap Harian"],
                            pct_cols=["% Capaian", "% OA"])
        kolom_tampil = ["Kode Sales", "Salesman", "Team", "Target", "Net Sales", "% Capaian",
                        "OA", "% OA", "EC", "Gap Harian", "Avg SKU"]
        st.dataframe(show[kolom_tampil], hide_index=True, use_container_width=True, height=380)
        download_button(ringkasan_view, "Download Excel (By Salesman)", "by_salesman.xlsx", "dl_sales")

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🗂️ Capaian by Divisi")
        st.caption("Divisi 5-Coffee, 6-Cereal, 8-Instant Food, 16-Homecare. Target diambil dari sheet "
                   "'Target Divisi' pada file Target.")
        df_div_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_filter_sales)] if salesman_filter_sales else df_filtered.iloc[0:0]
        net_by_sales_div = net_by_group(df_div_scope, [COL["kode_sales"], COL["salesman"], "_divisi_norm"], "Net Sales")
        net_by_sales_div = net_by_sales_div[net_by_sales_div["_divisi_norm"].isin(DIVISI_LABEL.keys())]
        net_by_sales_div["Divisi"] = net_by_sales_div["_divisi_norm"].map(DIVISI_LABEL)

        if not target_divisi.empty:
            tgt_div = target_divisi.copy()
            if periode_sel:
                tgt_div = tgt_div[tgt_div[TARGET_DIVISI_COL["periode"]].isna() | tgt_div[TARGET_DIVISI_COL["periode"]].isin(periode_sel)]
            tgt_div = tgt_div.groupby([TARGET_DIVISI_COL["kode_sales"], "_divisi_norm"])[TARGET_DIVISI_COL["target"]].sum().reset_index()
            net_by_sales_div = net_by_sales_div.merge(
                tgt_div, left_on=[COL["kode_sales"], "_divisi_norm"],
                right_on=[TARGET_DIVISI_COL["kode_sales"], "_divisi_norm"], how="left")
            net_by_sales_div = net_by_sales_div.rename(columns={TARGET_DIVISI_COL["target"]: "Target"})
        else:
            net_by_sales_div["Target"] = np.nan

        net_by_sales_div["% Capaian"] = (net_by_sales_div["Net Sales"] / net_by_sales_div["Target"] * 100).round(1)
        net_by_sales_div["Gap Harian"] = ((net_by_sales_div["Target"] - net_by_sales_div["Net Sales"]) / hke).round(0) if hke else np.nan
        tbl_div_long = net_by_sales_div.rename(columns={COL["salesman"]: "Salesman"})[
            ["Salesman", "Divisi", "Target", "Net Sales", "% Capaian", "Gap Harian"]
        ]

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

        st.dataframe(format_cols(tbl_div_wide, rp_cols=rp_cols_wide, pct_cols=pct_cols_wide),
                     hide_index=True, use_container_width=True, height=280)
        download_button(tbl_div_long, "Download Excel (Capaian by Divisi)", "by_salesman_divisi.xlsx", "dl_sales_div")

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
                st.dataframe(format_cols(agg[[col, "Omzet"]], rp_cols=["Omzet"]),
                             hide_index=True, use_container_width=True, height=380)
                download_button(agg, f"Download Excel ({label})", f"wilayah_{label.lower()}.xlsx", f"dl_wil_{label}")
            with colR:
                n_pie, other_pie = pie_config[label]
                pie_data = top_categories_for_pie(agg[[col, "Omzet"]], col, "Omzet", n_pie, other_pie)
                st.plotly_chart(pie_chart(pie_data, col, "Omzet", f"Kontribusi Omzet by {label}"), use_container_width=True)
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
            st.dataframe(format_cols(agg_pasar[[COL["kode_pasar"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(agg_pasar, "Download Excel (Pasar)", "wilayah_pasar.xlsx", "dl_pasar")
        with colR:
            if agg_pasar.empty:
                st.info("Tidak ada data pasar dengan nama resmi (selain N/A) pada filter saat ini.")
            else:
                pie_pasar = top_categories_for_pie(agg_pasar[[COL["kode_pasar"], "Omzet"]], COL["kode_pasar"], "Omzet", 15, False)
                st.plotly_chart(pie_chart(pie_pasar, COL["kode_pasar"], "Omzet", "Kontribusi Omzet by Pasar"), use_container_width=True)

# ---------------------------------------------------------------- By Subbrand & Divisi
with tab_subbrand:
    with st.container(border=True):
        st.markdown("#### 🏷️ Kontribusi per Subbrand")
        agg_sb = net_by_group(df_filtered, [COL["subbrand_name"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.1, 1])
        with colL:
            st.dataframe(format_cols(agg_sb[[COL["subbrand_name"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(agg_sb, "Download Excel (Subbrand)", "subbrand.xlsx", "dl_sb")
        with colR:
            pie_sb2 = top_categories_for_pie(agg_sb[[COL["subbrand_name"], "Omzet"]], COL["subbrand_name"], "Omzet", 10, True)
            st.plotly_chart(pie_chart(pie_sb2, COL["subbrand_name"], "Omzet", "Kontribusi per Subbrand"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🗂️ Kontribusi per Divisi")
        st.caption("Divisi ditampilkan sebagai kode mentah untuk kode selain 5/6/8/16 (belum ada tabel nama Divisi lengkap).")
        agg_dv = net_by_group(df_filtered, [COL["divisi"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.1, 1])
        with colL:
            st.dataframe(format_cols(agg_dv[[COL["divisi"], "Omzet"]], rp_cols=["Omzet"]),
                         hide_index=True, use_container_width=True, height=380)
            download_button(agg_dv, "Download Excel (Divisi)", "divisi.xlsx", "dl_dv")
        with colR:
            pie_dv = top_categories_for_pie(agg_dv[[COL["divisi"], "Omzet"]], COL["divisi"], "Omzet", 10, True)
            st.plotly_chart(pie_chart(pie_dv, COL["divisi"], "Omzet", "Kontribusi per Divisi"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 👤 Breakdown Subbrand per Salesman")
        st.caption("Pilih satu salesman untuk melihat kontribusi Omzet, EC, dan OA di setiap subbrand-nya.")
        salesman_for_breakdown = st.selectbox("Pilih salesman", salesman_terpilih, key="divisi_salesman_breakdown")
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
        st.dataframe(format_cols(tbl_breakdown, rp_cols=["Omzet"]), hide_index=True, use_container_width=True, height=340)
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
            salesman_mhs = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih, key="mhs_salesman_filter")
        with colf2:
            rayon_opts = sorted(df_filtered["Rayon"].dropna().unique().tolist())
            rayon_mhs = st.multiselect("Filter Rayon", rayon_opts, default=rayon_opts, key="mhs_rayon_filter")

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
            st.dataframe(tampil_with_rayon[kolom_mhs], hide_index=True, use_container_width=True, height=380)
            download_button(tampil_with_rayon, "Download Excel (MHS Resume)", "mhs_resume.xlsx", "dl_mhs")
        with colR:
            n_lolos = int(tampil["Lolos MHS"].sum()) if not tampil.empty else 0
            n_belum = int((~tampil["Lolos MHS"]).sum()) if not tampil.empty else 0
            pie_mhs = pd.DataFrame({"Status": ["✅ Lolos MHS", "⚠️ Belum Lolos"], "Jumlah": [n_lolos, n_belum]})
            st.plotly_chart(pie_chart(pie_mhs, "Status", "Jumlah", "Status Kelolosan MHS"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📈 % MHS Keseluruhan (vs Jumlah Outlet DMP)")
        mhs_by_sales = hitung_mhs_by_salesman(tampil, df_mhs_scope, outlet_count_dmp)
        total_lolos = mhs_by_sales["Outlet Lolos MHS"].sum() if not mhs_by_sales.empty else 0
        total_cb = mhs_by_sales["Jumlah Outlet (DMP)"].dropna().sum() if not mhs_by_sales.empty else 0
        pct_mhs_overall = (total_lolos / total_cb * 100) if total_cb else 0
        colg, colt = st.columns([1, 1.4])
        with colg:
            st.plotly_chart(gauge_chart(pct_mhs_overall, "% MHS Keseluruhan"), use_container_width=True)
        with colt:
            st.dataframe(format_cols(mhs_by_sales, pct_cols=["% MHS"]), hide_index=True,
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
                st.dataframe(sku_outlet, hide_index=True, use_container_width=True, height=300)
            with cR:
                st.markdown(f"**⚠️ SKU belum masuk** (vs SKU lain yang laku di kategori '{kategori_sel}')")
                sudah_norm = f_only_mhs.loc[f_only_mhs[COL["outlet"]] == no_outlet_sel, "_produk_norm"]
                belum_masuk = semua_sku_tipe[~semua_sku_tipe["_produk_norm"].isin(sudah_norm)][[COL["pcode"], COL["nama_produk"]]]
                st.dataframe(belum_masuk, hide_index=True, use_container_width=True, height=300)

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
        st.dataframe(summary_outlet, hide_index=True, use_container_width=True, height=380)
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
                                                  default=salesman_insentif_opts, key="insentif_salesman_filter")

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
            st.dataframe(show_ins[["Kode Sales", "Salesman", "Team", "% Capaian Sales", "Insentif Sales",
                                    "Insentif Kategori (4 Divisi)", "% MHS", "Insentif MHS", "% OA", "Insentif OA",
                                    "Total Insentif"]], hide_index=True, use_container_width=True, height=340)
            with st.expander("Lihat rincian per Divisi (Coffee/Cereal/Instant Food/Homecare)"):
                st.dataframe(tbl_insentif[["Salesman", "Detail Kategori"]], hide_index=True, use_container_width=True)
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
                                                key="lato_salesman_filter")
            with cf2:
                rayon_lato_opts = sorted(dmp_master.loc[dmp_master["Salesman"].isin(salesman_lato), "Rayon"].dropna().unique().tolist())
                rayon_lato = st.multiselect("Filter Rayon", rayon_lato_opts, default=rayon_lato_opts, key="lato_rayon_filter")

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

            def _highlight_belum(row):
                if is_belum.loc[row.name]:
                    return ["background-color: #7f1d1d; color: #FCA5A5"] * len(row)
                return [""] * len(row)

            styled = tbl_lato_display.style.apply(_highlight_belum, axis=1)
            st.dataframe(styled, hide_index=True, use_container_width=True, height=460)
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
                                              key="pareto_salesman_filter")
        with cf2:
            rayon_pareto_opts = sorted(df_filtered.loc[df_filtered[COL["salesman"]].isin(salesman_pareto), "Rayon"]
                                        .dropna().unique().tolist())
            rayon_pareto = st.multiselect("Filter Rayon", rayon_pareto_opts, default=rayon_pareto_opts,
                                           key="pareto_rayon_filter")

        df_pareto_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_pareto)] if salesman_pareto else df_filtered.iloc[0:0]
        if rayon_pareto_opts:
            df_pareto_scope = df_pareto_scope[df_pareto_scope["Rayon"].isin(rayon_pareto)] if rayon_pareto else df_pareto_scope.iloc[0:0]

        agg_pareto = net_by_group(df_pareto_scope, [COL["outlet"], COL["nama_outlet"], COL["salesman"], "Rayon"], "Omzet")
        agg_pareto = agg_pareto.sort_values("Omzet", ascending=False).head(40).reset_index(drop=True)
        agg_pareto.insert(0, "Rank", range(1, len(agg_pareto) + 1))
        agg_pareto = agg_pareto.rename(columns={COL["outlet"]: "No Outlet", COL["nama_outlet"]: "Nama Outlet",
                                                 COL["salesman"]: "Salesman"})

        st.dataframe(format_cols(agg_pareto[["Rank", "No Outlet", "Nama Outlet", "Salesman", "Rayon", "Omzet"]],
                                 rp_cols=["Omzet"]), hide_index=True, use_container_width=True, height=460)
        fig_pareto = bar_chart(agg_pareto.head(20), "Nama Outlet", "Omzet", "Top 20 dari 40 Toko (visual)")
        st.plotly_chart(fig_pareto, use_container_width=True)
        download_button(agg_pareto[["Rank", "No Outlet", "Nama Outlet", "Salesman", "Rayon", "Omzet"]],
                         "Download Excel (Paretto)", "paretto.xlsx", "dl_pareto")

# ---------------------------------------------------------------- Performance SS
with tab_ss:
    with st.container(border=True):
        st.markdown("#### 📈 Performance SS")
        st.caption("Rekap gabungan dari salesman yang difilter di bawah ini — anggap ini sebagai tim yang "
                   "dihandle satu Sales Supervisor. Insentif dihitung pakai skema Sales Supervisor (IBN) M245, "
                   "bukan skema per-salesman.")
        salesman_filter_ss = st.multiselect("Filter salesman", salesman_terpilih, default=salesman_terpilih,
                                             key="ss_salesman_filter")
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
            st.dataframe(format_cols(net_divisi_ss[["Divisi", "Omzet"]].sort_values("Omzet", ascending=False),
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

        pct_sales_ss = (pencapaian_ss / target_total_ss * 100) if target_total_ss else np.nan
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
        st.dataframe(format_cols(tbl_ss, rp_cols=["Insentif Sales", "Insentif Kategori (4 Divisi)", "Insentif MHS",
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
        st.dataframe(df_prod_std, hide_index=True, use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📖 Target SKU per Klasifikasi Channel (acuan SKU Sold) — Memorandum 27 Agustus 2026")
        st.caption("Klasifikasi diambil dari kolom NAMACLASS di file DMP (Supermarket dari NAMACHANNEL). "
                   "Outlet yang tidak masuk 9 kategori ini tidak dihitung ke SKU Sold.")
        df_sku_std = pd.DataFrame(
            [{"Kategori Channel": k, "Target SKU": v} for k, v in TARGET_SKU_BY_CLASS.items()]
        ).sort_values("Target SKU")
        st.dataframe(df_sku_std, hide_index=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📖 Mapping Divisi")
        st.dataframe(pd.DataFrame([{"Kode Divisi": k, "Nama": v} for k, v in DIVISI_LABEL.items()]), hide_index=True)

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
            st.dataframe(df_show, hide_index=True, use_container_width=True)
        st.caption("Tabel ini acuan statis dari spesifikasi awal.")
