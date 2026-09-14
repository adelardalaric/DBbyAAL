"""
Dashboard Operational Area MV42
================================
Cara jalankan lokal   : streamlit run app.py
Cara deploy           : push repo ini ke GitHub -> deploy di share.streamlit.io,
                         pilih app.py sebagai entrypoint.

CATATAN ASUMSI (baca sebelum pakai data asli):
1. Menu "LTD NPL" dan "Komparasi Tahun (YoY)" masih placeholder — menu/tab
   sudah ada tapi logic-nya belum dibuat, sesuai instruksi "tambahkan menunya
   saja dahulu".
2. Standar CB/EC/IPT baru ada untuk TO-Retail & TO-Grosir. Salesman dengan
   team lain (Motoris, MUH, dst) tampil dengan % OA dan % MHS kosong.
3. File Target (.xls) diasumsikan 3 kolom: "Kode Sales", "Periode", "Target".
4. Pie chart di menu By Wilayah / By Subbrand & Divisi / Pasar dibatasi top 10
   + irisan "Lainnya" (supaya tetap terbaca kalau kategori sangat banyak,
   misal Kecamatan/Kelurahan). Untuk menu Overview, pie chart PERSIS 6 irisan
   terbesar saja (tanpa "Lainnya"), sesuai instruksi.
5. Menu MHS "SKU belum masuk" dibandingkan terhadap SKU yang pernah laku di
   outlet lain dengan Tipe Outlet yang sama (proxy) — belum ada file master
   SKU. Ganti fungsi `universe_sku_per_tipe_outlet()` begitu tersedia.
6. Semua angka penjualan (Bruto, Net Sales, Omzet, Target) diformat "Rp
   123,456,789" sebagai TEKS di tabel (bukan kolom numerik native) supaya
   formatnya konsisten dan tidak terpotong.
7. Judul di prompt kamu tertulis "MV42" (sebelumnya sketsa awal "MU42") —
   saya pakai "MV42" sesuai instruksi terakhir. Kasih tahu saya kalau ini typo.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from io import BytesIO

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
TARGET_COL = {"kode_sales": "Kode Sales", "periode": "Periode", "target": "Target"}

STANDAR_TEAM = {
    "TO-Retail": {"CB": 300, "EC": 20, "IPT": 6},
    "TO-Grosir": {"CB": 90, "EC": 12, "IPT": 10},
}
TARGET_SKU_MHS = {"111": 7, "113": 10, "114": 15, "115": 15, "105": 20, "109": 20, "110": 20}
TIPE_OUTLET_LABEL = {
    "111": "111 - Retail Small", "113": "113 - Retail Large", "114": "114 - Semi Grosir",
    "118": "118 - Kantin", "146": "146 - MUH", "115": "115 - Grosir",
    "999": "999 - Aneka Pembeli", "116": "116 - Big Grosir", "105": "105 - GMM Retail",
    "109": "109 - GMM Semi Grosir", "110": "110 - GMM Grosir",
}

ACCENT = "#F5B301"
PALETTE = ["#F5B301", "#38BDF8", "#34D399", "#F472B6", "#A78BFA", "#FB923C", "#94A3B8"]


# =====================================================================
# 1. STYLE — kotak KPI, header judul, dsb
# =====================================================================
def inject_css():
    st.markdown(f"""
    <style>
    .app-title {{
        text-align:center; text-transform:uppercase; letter-spacing:1.5px;
        font-size:2rem; font-weight:800; margin-bottom:0.1rem;
        background: linear-gradient(90deg, {ACCENT}, #38BDF8);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;
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
    </style>
    """, unsafe_allow_html=True)


def kpi_card(icon: str, label: str, value: str, sub: str = ""):
    st.markdown(f"""
    <div class="kpi-box">
        <div class="kpi-icon">{icon}</div>
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


def fmt_rp(n) -> str:
    try:
        return "Rp {:,.0f}".format(float(n))
    except (ValueError, TypeError):
        return "Rp 0"


# =====================================================================
# 2. LOAD DATA
# =====================================================================
@st.cache_data(show_spinner="Memproses file LBP...")
def load_lbp(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".txt") or name.endswith(".csv"):
        # index_col=False WAJIB: file LBP punya trailing "|" di akhir tiap baris,
        # tanpa ini pandas salah mengira kolom pertama adalah index dan semua
        # kolom lain geser satu posisi.
        df = pd.read_csv(file, sep="|", dtype=str, engine="python", index_col=False)
    else:
        df = pd.read_excel(file, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    for c in [COL["qty"], COL["bruto"], COL["week"], COL["periode"]]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df[COL["tanggal"]] = pd.to_datetime(df[COL["tanggal"]], format="%d/%m/%Y", errors="coerce")
    df[COL["tipe_outlet"]] = df[COL["tipe_outlet"]].astype(str).str.strip()
    df[COL["transtype"]] = df[COL["transtype"]].astype(str).str.strip().str.upper()

    def classify_team(x):
        x = str(x).upper()
        if "TO RETAIL" in x:
            return "TO-Retail"
        if "TO GROSIR" in x:
            return "TO-Grosir"
        return "Lainnya"

    df["team_simple"] = df[COL["salesforce"]].apply(classify_team)
    return df


@st.cache_data(show_spinner="Memproses file target...")
def load_target(file) -> pd.DataFrame:
    df = pd.read_excel(file, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df[TARGET_COL["target"]] = pd.to_numeric(df[TARGET_COL["target"]], errors="coerce").fillna(0)
    df[TARGET_COL["periode"]] = pd.to_numeric(df[TARGET_COL["periode"]], errors="coerce").fillna(0).astype(int)
    return df


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    return buf.getvalue()


def download_button(df: pd.DataFrame, label: str, filename: str, key: str):
    st.download_button(label, data=to_excel_bytes(df), file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=key)


# =====================================================================
# 3. PERHITUNGAN NETO (Bruto F - Bruto R) — vektor, bukan .apply scalar,
#    supaya jelas dan tidak ada celah kesalahan.
# =====================================================================
def net_by_group(df: pd.DataFrame, group_cols, value_col_name="Omzet") -> pd.DataFrame:
    # PENTING: di file LBP, "Harga Bruto" untuk baris TRANSTYPE == "R" SUDAH tersimpan
    # NEGATIF (mis. -490000), bukan angka positif. Jadi neto yang benar adalah F + R
    # (R sudah membawa tanda minus) — kalau dipaksa F - R, retur malah DITAMBAHKAN lagi
    # ke pencapaian, bukan dikurangi. Ini akar masalah "pencapaian belum dikurangi".
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
    bruto_r_raw = df.loc[df[COL["transtype"]] == "R", COL["bruto"]].sum()  # sudah negatif di sumber data
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


def pie_chart(df_agg: pd.DataFrame, name_col: str, val_col: str):
    fig = px.pie(df_agg, names=name_col, values=val_col, hole=0.45, color_discrete_sequence=PALETTE)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
    return fig


def ringkasan_by_salesman(df: pd.DataFrame, df_target: pd.DataFrame, periode_sel, hka: float) -> pd.DataFrame:
    f_only = df[df[COL["transtype"]] == "F"]

    net = net_by_group(df, [COL["kode_sales"], COL["salesman"], "team_simple"], "Net Sales")
    oa = f_only.groupby([COL["kode_sales"], COL["salesman"]])[COL["outlet"]].nunique().reset_index(name="OA")
    ec = (
        f_only.groupby([COL["kode_sales"], COL["salesman"], f_only[COL["tanggal"]].dt.date])[COL["outlet"]]
        .nunique().groupby(level=[0, 1]).sum().reset_index(name="EC")
    )
    avg_sku = (
        f_only.groupby([COL["kode_sales"], COL["salesman"], COL["outlet"]])[COL["pcode"]]
        .nunique().groupby(level=[0, 1]).mean().reset_index(name="Avg SKU")
    )

    out = net.merge(oa, on=[COL["kode_sales"], COL["salesman"]], how="left")
    out = out.merge(ec, on=[COL["kode_sales"], COL["salesman"]], how="left")
    out = out.merge(avg_sku, on=[COL["kode_sales"], COL["salesman"]], how="left")
    out[["OA", "EC", "Avg SKU"]] = out[["OA", "EC", "Avg SKU"]].fillna(0)
    out["Avg SKU"] = out["Avg SKU"].round(1)

    out["CB Standar"] = out["team_simple"].map(lambda tm: STANDAR_TEAM.get(tm, {}).get("CB"))
    out["% OA"] = np.where(out["CB Standar"].notna(), (out["OA"] / out["CB Standar"] * 100).round(1), np.nan)

    if not df_target.empty:
        tgt = df_target.copy()
        if periode_sel:
            tgt = tgt[tgt[TARGET_COL["periode"]].isin(periode_sel)]
        tgt = tgt.groupby(TARGET_COL["kode_sales"])[TARGET_COL["target"]].sum().reset_index()
        out = out.merge(tgt, left_on=COL["kode_sales"], right_on=TARGET_COL["kode_sales"], how="left")
        out = out.rename(columns={TARGET_COL["target"]: "Target"})
    else:
        out["Target"] = np.nan

    out["% Capaian"] = (out["Net Sales"] / out["Target"] * 100).round(1)
    out["Gap Harian"] = ((out["Target"] - out["Net Sales"]) / hka).round(0) if hka else np.nan

    out = out.rename(columns={COL["kode_sales"]: "Kode Sales", COL["salesman"]: "Salesman", "team_simple": "Team"})
    return out.sort_values("Net Sales", ascending=False)


def format_currency_cols(df: pd.DataFrame, cols) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = out[c].apply(fmt_rp)
    return out


def universe_sku_per_tipe_outlet(df_f: pd.DataFrame) -> dict:
    """Proxy 'master SKU': semua Pcode+Nama Produk yang pernah laku di tiap Tipe Outlet
    (dalam data yang sedang difilter). Ganti dengan file master SKU asli kalau sudah ada."""
    universe = {}
    for tipe, g in df_f.groupby(COL["tipe_outlet"]):
        universe[tipe] = g.drop_duplicates(subset=[COL["pcode"]])[[COL["pcode"], COL["nama_produk"]]]
    return universe


# =====================================================================
# 4. LOAD & SIDEBAR (Option: upload, pilih salesman, periode/week/HKA/CB)
# =====================================================================
inject_css()

with st.sidebar:
    st.markdown("### ⚙️ Option")
    target_file = st.file_uploader("Upload File Target (.xls)", type=["xls", "xlsx"])
    lbp_file = st.file_uploader("Upload File LBP (.txt / .xls)", type=["txt", "csv", "xls", "xlsx"])

if lbp_file is None:
    st.info("Upload file LBP di sidebar (⚙️ Option) untuk mulai melihat dashboard.")
    st.stop()

df_lbp = load_lbp(lbp_file)
df_target = load_target(target_file) if target_file is not None else pd.DataFrame(
    columns=[TARGET_COL["kode_sales"], TARGET_COL["periode"], TARGET_COL["target"]])

with st.sidebar:
    st.divider()
    st.markdown("### 👥 Pilih Salesman")
    salesman_opts = sorted(df_lbp[COL["salesman"]].dropna().unique().tolist())
    pilih_semua = st.checkbox("Pilih Semua Salesman", value=True)
    salesman_terpilih = st.multiselect("Salesman Terpilih", salesman_opts,
                                        default=salesman_opts if pilih_semua else [])

df_sales_scope = df_lbp[df_lbp[COL["salesman"]].isin(salesman_terpilih)] if salesman_terpilih else df_lbp.iloc[0:0]

with st.sidebar:
    st.divider()
    st.markdown("### 📅 Periode, Week & HKA")
    periode_opts = sorted(df_sales_scope[COL["periode"]].dropna().unique().astype(int).tolist())
    week_opts = sorted(df_sales_scope[COL["week"]].dropna().unique().astype(int).tolist())
    periode_sel = st.multiselect("Filter Periode", periode_opts, default=periode_opts)
    week_sel = st.multiselect("Filter Week", week_opts, default=week_opts)
    hka = st.number_input("HKA (Hari Kerja Aktif)", min_value=0, value=24, step=1)

df_filtered = df_sales_scope.copy()
if periode_sel:
    df_filtered = df_filtered[df_filtered[COL["periode"]].isin(periode_sel)]
if week_sel:
    df_filtered = df_filtered[df_filtered[COL["week"]].isin(week_sel)]

team_per_salesman = df_filtered.drop_duplicates(subset=[COL["kode_sales"]])[[COL["kode_sales"], "team_simple"]]
saran_cb = int(team_per_salesman["team_simple"].map(lambda tm: STANDAR_TEAM.get(tm, {}).get("CB", 0)).sum())

with st.sidebar:
    cb_standpro_area = st.number_input("CB Standpro Area (saran otomatis, bisa ditimpa)",
                                        min_value=0, value=saran_cb, step=1)

# =====================================================================
# 5. HEADER & TOP BAR (kotak KPI)
# =====================================================================
st.markdown('<div class="app-title">Dashboard Operational Area MV42</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="app-subtitle">Periode {", ".join(map(str, periode_sel)) or "-"} '
    f'&middot; Week {", ".join(map(str, week_sel)) or "-"} &middot; '
    f'{len(salesman_terpilih)} salesman terpilih</div>',
    unsafe_allow_html=True,
)

pencapaian, bruto_f, bruto_r, pct_retur = hitung_pencapaian(df_filtered)
oa_total = hitung_oa(df_filtered)

kode_sales_scope = df_filtered[COL["kode_sales"]].unique().tolist()
target_total = 0
if not df_target.empty:
    tgt_df = df_target[df_target[TARGET_COL["kode_sales"]].isin(kode_sales_scope)]
    if periode_sel:
        tgt_df = tgt_df[tgt_df[TARGET_COL["periode"]].isin(periode_sel)]
    target_total = tgt_df[TARGET_COL["target"]].sum()

gap_harian_total = ((target_total - pencapaian) / hka) if hka else 0
oa_pct = (oa_total / cb_standpro_area * 100) if cb_standpro_area else 0

k1, k2, k3, k4 = st.columns(4)
with k1:
    kpi_card("🎯", "Target", fmt_rp(target_total))
with k2:
    kpi_card("💰", "Pencapaian (Neto F-R)", fmt_rp(pencapaian),
              f"Bruto F {fmt_rp(bruto_f)} &middot; Retur {pct_retur:.2f}% ({fmt_rp(bruto_r)})")
with k3:
    kpi_card("📉", "Gap Harian", fmt_rp(gap_harian_total), f"HKA yang dipakai: {hka}")
with k4:
    kpi_card("🏪", "OA (Outlet Aktif)", f"{oa_total} outlet",
              f"{oa_pct:.1f}% dari CB Standpro Area ({cb_standpro_area})")

st.divider()

# =====================================================================
# 6. TABS
# =====================================================================
ringkasan_sales = ringkasan_by_salesman(df_filtered, df_target, periode_sel, hka)

tab_overview, tab_sales, tab_wilayah, tab_subbrand, tab_mhs, tab_ltdnpl, tab_insentif, tab_yoy, tab_readme = st.tabs(
    ["📊 Overview", "🧑‍💼 By Salesman", "🗺️ By Wilayah", "🏷️ By Subbrand & Divisi",
     "📦 MHS", "🆕 LTD NPL", "🎯 Insentif", "📅 Komparasi Tahun", "📖 Read Me"]
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

        colA, colB = st.columns([1.3, 1])
        with colA:
            tbl_show = format_currency_cols(tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]], ["Omzet"])
            st.dataframe(tbl_show, hide_index=True, use_container_width=True, height=320)
            download_button(tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]],
                             "Download Excel (Klasifikasi Outlet)", "overview_klasifikasi_outlet.xlsx", "dl_ov1")
        with colB:
            pie_tipe = top_categories_for_pie(tbl_tipe[["Tipe Outlet", "Omzet"]], "Tipe Outlet", "Omzet", 6, False)
            st.plotly_chart(pie_chart(pie_tipe, "Tipe Outlet", "Omzet"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🏆 Top Contributor (6 Terbesar)")
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            st.markdown("**👤 Salesman**")
            top_sales_all = format_currency_cols(ringkasan_sales[["Salesman", "Net Sales"]], ["Net Sales"])
            st.dataframe(top_sales_all, hide_index=True, use_container_width=True, height=220)
            pie_sales = top_categories_for_pie(ringkasan_sales[["Salesman", "Net Sales"]], "Salesman", "Net Sales", 6, False)
            st.plotly_chart(pie_chart(pie_sales, "Salesman", "Net Sales"), use_container_width=True)
        with oc2:
            st.markdown("**📍 Wilayah (Kabupaten)**")
            net_wil = net_by_group(df_filtered, [COL["kabupaten"]], "Omzet").sort_values("Omzet", ascending=False)
            st.dataframe(format_currency_cols(net_wil[[COL["kabupaten"], "Omzet"]], ["Omzet"]),
                         hide_index=True, use_container_width=True, height=220)
            pie_wil = top_categories_for_pie(net_wil[[COL["kabupaten"], "Omzet"]], COL["kabupaten"], "Omzet", 6, False)
            st.plotly_chart(pie_chart(pie_wil, COL["kabupaten"], "Omzet"), use_container_width=True)
        with oc3:
            st.markdown("**🏷️ Subbrand**")
            net_sb = net_by_group(df_filtered, [COL["subbrand_name"]], "Omzet").sort_values("Omzet", ascending=False)
            st.dataframe(format_currency_cols(net_sb[[COL["subbrand_name"], "Omzet"]], ["Omzet"]),
                         hide_index=True, use_container_width=True, height=220)
            pie_sb = top_categories_for_pie(net_sb[[COL["subbrand_name"], "Omzet"]], COL["subbrand_name"], "Omzet", 6, False)
            st.plotly_chart(pie_chart(pie_sb, COL["subbrand_name"], "Omzet"), use_container_width=True)

# ---------------------------------------------------------------- By Salesman
with tab_sales:
    with st.container(border=True):
        st.markdown("#### 🧑‍💼 Kinerja per Salesman")
        st.caption("% OA dihitung dari standar CB per Team (Read Me). EC = akumulasi jumlah outlet unik "
                   "bertransaksi (F saja) per hari, dijumlahkan sepanjang periode. Team di luar "
                   "TO-Retail/TO-Grosir tampil '-' pada % OA.")
        show = format_currency_cols(ringkasan_sales, ["Net Sales", "Bruto F", "Bruto R", "Target", "Gap Harian"])
        kolom_tampil = ["Kode Sales", "Salesman", "Team", "Target", "Net Sales", "% Capaian",
                        "OA", "% OA", "EC", "Gap Harian", "Avg SKU"]
        st.dataframe(show[kolom_tampil], hide_index=True, use_container_width=True, height=420)
        download_button(ringkasan_sales, "Download Excel (By Salesman)", "by_salesman.xlsx", "dl_sales")

# ---------------------------------------------------------------- By Wilayah
with tab_wilayah:
    icon_level = {"Kabupaten": "🏙️", "Kecamatan": "🏘️", "Kelurahan": "🏠"}
    for label, col in [("Kabupaten", COL["kabupaten"]), ("Kecamatan", COL["kecamatan"]),
                        ("Kelurahan", COL["kelurahan"])]:
        with st.container(border=True):
            st.markdown(f"#### {icon_level[label]} Penjualan by {label}")
            agg = net_by_group(df_filtered, [col], "Omzet").sort_values("Omzet", ascending=False)
            colL, colR = st.columns([1.3, 1])
            with colL:
                st.dataframe(format_currency_cols(agg[[col, "Omzet"]], ["Omzet"]),
                             hide_index=True, use_container_width=True, height=320)
                download_button(agg, f"Download Excel ({label})", f"wilayah_{label.lower()}.xlsx", f"dl_wil_{label}")
            with colR:
                pie_data = top_categories_for_pie(agg[[col, "Omzet"]], col, "Omzet", 10, True)
                st.plotly_chart(pie_chart(pie_data, col, "Omzet"), use_container_width=True)
        st.write("")

    with st.container(border=True):
        st.markdown("#### 🏬 Penjualan by Pasar")
        st.caption("Kode Pasar dengan keterangan 'N/A' (belum ada nama pasar resmi) dikecualikan.")
        dfp = df_filtered.copy()
        dfp["_pasar_desc"] = dfp[COL["kode_pasar"]].astype(str).str.split("-", n=1).str[-1].str.strip().str.upper()
        dfp = dfp[dfp["_pasar_desc"] != "N/A"]
        agg_pasar = net_by_group(dfp, [COL["kode_pasar"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.3, 1])
        with colL:
            st.dataframe(format_currency_cols(agg_pasar[[COL["kode_pasar"], "Omzet"]], ["Omzet"]),
                         hide_index=True, use_container_width=True, height=320)
            download_button(agg_pasar, "Download Excel (Pasar)", "wilayah_pasar.xlsx", "dl_pasar")
        with colR:
            if agg_pasar.empty:
                st.info("Tidak ada data pasar dengan nama resmi (selain N/A) pada filter saat ini.")
            else:
                pie_pasar = top_categories_for_pie(agg_pasar[[COL["kode_pasar"], "Omzet"]], COL["kode_pasar"], "Omzet", 10, True)
                st.plotly_chart(pie_chart(pie_pasar, COL["kode_pasar"], "Omzet"), use_container_width=True)

# ---------------------------------------------------------------- By Subbrand & Divisi
with tab_subbrand:
    with st.container(border=True):
        st.markdown("#### 🏷️ Kontribusi per Subbrand")
        agg_sb = net_by_group(df_filtered, [COL["subbrand_name"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.3, 1])
        with colL:
            st.dataframe(format_currency_cols(agg_sb[[COL["subbrand_name"], "Omzet"]], ["Omzet"]),
                         hide_index=True, use_container_width=True, height=340)
            download_button(agg_sb, "Download Excel (Subbrand)", "subbrand.xlsx", "dl_sb")
        with colR:
            pie_sb2 = top_categories_for_pie(agg_sb[[COL["subbrand_name"], "Omzet"]], COL["subbrand_name"], "Omzet", 10, True)
            st.plotly_chart(pie_chart(pie_sb2, COL["subbrand_name"], "Omzet"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🗂️ Kontribusi per Divisi")
        st.caption("Divisi ditampilkan sebagai kode mentah karena belum ada tabel nama Divisi.")
        agg_dv = net_by_group(df_filtered, [COL["divisi"]], "Omzet").sort_values("Omzet", ascending=False)
        colL, colR = st.columns([1.3, 1])
        with colL:
            st.dataframe(format_currency_cols(agg_dv[[COL["divisi"], "Omzet"]], ["Omzet"]),
                         hide_index=True, use_container_width=True, height=340)
            download_button(agg_dv, "Download Excel (Divisi)", "divisi.xlsx", "dl_dv")
        with colR:
            pie_dv = top_categories_for_pie(agg_dv[[COL["divisi"], "Omzet"]], COL["divisi"], "Omzet", 10, True)
            st.plotly_chart(pie_chart(pie_dv, COL["divisi"], "Omzet"), use_container_width=True)

# ---------------------------------------------------------------- MHS
with tab_mhs:
    with st.container(border=True):
        st.markdown("#### 📦 MHS — SKU Masuk vs Target SKU")
        salesman_mhs = st.multiselect("Filter salesman khusus menu ini", salesman_terpilih,
                                       default=salesman_terpilih, key="mhs_salesman_filter")
        df_mhs_scope = df_filtered[df_filtered[COL["salesman"]].isin(salesman_mhs)] if salesman_mhs else df_filtered.iloc[0:0]
        f_only_mhs = df_mhs_scope[df_mhs_scope[COL["transtype"]] == "F"]

        sku_terjual = f_only_mhs.groupby([COL["outlet"], COL["nama_outlet"], COL["kode_sales"], COL["salesman"],
                                           COL["channel"], COL["tipe_outlet"]])[COL["pcode"]] \
            .nunique().reset_index(name="SKU Terjual")
        sku_terjual["Target SKU"] = sku_terjual[COL["tipe_outlet"]].map(TARGET_SKU_MHS)
        sku_terjual["Kekurangan SKU"] = (sku_terjual["Target SKU"] - sku_terjual["SKU Terjual"]).clip(lower=0)
        sku_terjual["Lolos MHS"] = sku_terjual["SKU Terjual"] >= sku_terjual["Target SKU"]
        tampil = sku_terjual.dropna(subset=["Target SKU"]).rename(
            columns={COL["outlet"]: "No Outlet", COL["nama_outlet"]: "Nama Outlet",
                     COL["salesman"]: "Salesman", COL["channel"]: "Channel"})

        colL, colR = st.columns([1.5, 1])
        with colL:
            st.dataframe(tampil[["No Outlet", "Nama Outlet", "Salesman", "Channel", "Target SKU",
                                  "SKU Terjual", "Kekurangan SKU"]], hide_index=True, use_container_width=True, height=340)
            download_button(tampil, "Download Excel (MHS Resume)", "mhs_resume.xlsx", "dl_mhs")
        with colR:
            n_lolos = int(tampil["Lolos MHS"].sum())
            n_belum = int((~tampil["Lolos MHS"]).sum())
            pie_mhs = pd.DataFrame({"Status": ["✅ Lolos MHS", "⚠️ Belum Lolos"], "Jumlah": [n_lolos, n_belum]})
            st.plotly_chart(pie_chart(pie_mhs, "Status", "Jumlah"), use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📈 % MHS per Salesman (vs CB Standpro Read Me)")
        st.caption("Pembanding % MHS memakai standar CB Team dari menu Read Me, disesuaikan Salesforce "
                   "masing-masing sales — sama seperti pembanding % OA.")
        mhs_by_sales = tampil.groupby("Salesman").agg(
            Total_Outlet=("Lolos MHS", "count"), Outlet_Lolos=("Lolos MHS", "sum")
        ).reset_index()
        team_map = df_mhs_scope.drop_duplicates(subset=[COL["salesman"]])[[COL["salesman"], "team_simple"]]
        mhs_by_sales = mhs_by_sales.merge(team_map, left_on="Salesman", right_on=COL["salesman"], how="left")
        mhs_by_sales["CB Standar"] = mhs_by_sales["team_simple"].map(lambda tm: STANDAR_TEAM.get(tm, {}).get("CB"))
        mhs_by_sales["% MHS"] = np.where(mhs_by_sales["CB Standar"].notna(),
                                          (mhs_by_sales["Outlet_Lolos"] / mhs_by_sales["CB Standar"] * 100).round(1), np.nan)
        tabel_mhs_sales = mhs_by_sales.rename(columns={"Outlet_Lolos": "Outlet Lolos MHS",
                                                         "Total_Outlet": "Total Outlet Bertransaksi"})
        st.dataframe(tabel_mhs_sales[["Salesman", "team_simple", "CB Standar", "Total Outlet Bertransaksi",
                                       "Outlet Lolos MHS", "% MHS"]].rename(columns={"team_simple": "Team"}),
                     hide_index=True, use_container_width=True, height=280)
        fig_mhs_bar = px.bar(tabel_mhs_sales.dropna(subset=["% MHS"]), x="Salesman", y="% MHS",
                              color_discrete_sequence=[ACCENT])
        st.plotly_chart(fig_mhs_bar, use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 🔍 Detail SKU per Outlet")
        if tampil.empty:
            st.info("Tidak ada outlet pada filter saat ini.")
        else:
            outlet_pilihan = st.selectbox("Pilih outlet", tampil["No Outlet"] + " - " + tampil["Nama Outlet"])
            no_outlet_sel = outlet_pilihan.split(" - ")[0]
            tipe_outlet_sel = f_only_mhs.loc[f_only_mhs[COL["outlet"]] == no_outlet_sel, COL["tipe_outlet"]].iloc[0]
            universe = universe_sku_per_tipe_outlet(f_only_mhs)
            semua_sku_tipe = universe.get(tipe_outlet_sel, pd.DataFrame(columns=[COL["pcode"], COL["nama_produk"]]))
            sku_outlet = f_only_mhs.loc[f_only_mhs[COL["outlet"]] == no_outlet_sel,
                                         [COL["pcode"], COL["nama_produk"], COL["qty"], COL["bruto"]]].drop_duplicates()

            cL, cR = st.columns(2)
            with cL:
                st.markdown("**✅ SKU sudah masuk**")
                st.dataframe(sku_outlet, hide_index=True, use_container_width=True, height=280)
            with cR:
                st.markdown("**⚠️ SKU belum masuk** (vs SKU lain yang laku di Tipe Outlet sejenis)")
                belum_masuk = semua_sku_tipe[~semua_sku_tipe[COL["pcode"]].isin(sku_outlet[COL["pcode"]])]
                st.dataframe(belum_masuk, hide_index=True, use_container_width=True, height=280)

# ---------------------------------------------------------------- LTD NPL
with tab_ltdnpl:
    with st.container(border=True):
        st.markdown("#### 🆕 LTD NPL")
        st.info("Menu ini akan dikembangkan lebih lanjut setelah definisi rumus LTD NPL dikonfirmasi.")

# ---------------------------------------------------------------- Insentif
with tab_insentif:
    with st.container(border=True):
        st.markdown("#### 🎯 Insentif")
        st.info("Menu Insentif akan dikembangkan lebih lanjut.")

# ---------------------------------------------------------------- Komparasi Tahun
with tab_yoy:
    with st.container(border=True):
        st.markdown("#### 📅 Komparasi Tahun (2026 vs 2025)")
        st.info("Menu ini akan dikembangkan lebih lanjut — nantinya kamu bisa upload file LBP tahun "
                "pembanding (misal 2025) di sini untuk dibandingkan langsung dengan data tahun berjalan.")

# ---------------------------------------------------------------- Read Me
with tab_readme:
    with st.container(border=True):
        st.markdown("#### 📖 Standar Team (CB / EC / IPT)")
        st.dataframe(pd.DataFrame(STANDAR_TEAM).T.rename_axis("Team").reset_index(), hide_index=True)

    st.write("")
    with st.container(border=True):
        st.markdown("#### 📖 Target SKU per Tipe Outlet (acuan MHS)")
        df_sku_std = pd.DataFrame(
            [{"Tipe Outlet": TIPE_OUTLET_LABEL.get(k, k), "Target SKU": v} for k, v in TARGET_SKU_MHS.items()]
        )
        st.dataframe(df_sku_std, hide_index=True)
        st.caption("Tabel ini acuan statis dari spesifikasi awal.")
