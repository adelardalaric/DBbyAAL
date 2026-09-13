"""
Dashboard Operational Area MU42
================================
Cara jalankan lokal   : streamlit run app.py
Cara deploy           : push repo ini ke GitHub -> deploy di share.streamlit.io,
                         pilih app.py sebagai entrypoint.

CATATAN ASUMSI (baca ini sebelum pakai data asli):
1. Menu "LTD NPL" SENGAJA DI-SKIP dulu sesuai instruksi terakhir.
2. Standar CB/EC/IPT baru tersedia untuk TO-Retail & TO-Grosir. Salesman dengan
   team lain (Motoris, MUH, dst — dibaca dari kolom "Salesforce") akan tampil
   dengan %OA = "-" karena belum ada standar CB-nya.
3. File Target (.xls) diasumsikan punya 3 kolom: "Kode Sales", "Periode", "Target".
   Ganti nama kolom di TARGET_COL di bawah kalau strukturnya beda.
4. "CB Standpro Area" di top bar adalah SARAN otomatis (jumlah standar CB dari
   seluruh salesman yang sedang difilter), tapi tetap bisa kamu timpa manual.
5. Menu MHS "SKU yang belum masuk" dibandingkan terhadap SEMUA SKU yang pernah
   laku di outlet-outlet dengan Tipe Outlet yang sama (dalam data yang sedang
   difilter) — karena belum ada file master SKU per channel yang diupload.
   Ganti fungsi `universe_sku_per_tipe_outlet()` begitu ada file master SKU.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from io import BytesIO

st.set_page_config(page_title="Dashboard Operational Area MU42", layout="wide")

# =====================================================================
# 0. KONFIGURASI — SESUAIKAN DI SINI KALAU STRUKTUR FILE BERBEDA
# =====================================================================
COL = {
    "outlet": "No Outlet",
    "nama_outlet": "Nama Outlet",
    "tipe_outlet": "Tipe Outlet",
    "tanggal": "Tanggal Faktur",
    "faktur": "Faktur",
    "transtype": "TRANSTYPE",
    "kode_sales": "Kode Sales",
    "pcode": "Pcode",
    "nama_produk": "Nama Produk",
    "qty": "QTYPCS",
    "bruto": "Harga Bruto",
    "channel": "Channel",
    "kabupaten": "Kabupaten",
    "kecamatan": "Kecamatan",
    "kelurahan": "Kelurahan",
    "divisi": "Divisi",
    "week": "WEEK",
    "periode": "Periode",
    "kode_pasar": "Kode Pasar",
    "salesman": "Salesman",
    "salesforce": "Salesforce",  # kolom berisi "TO RETAIL" / "TO GROSIR" / dst
    "subbrand_name": "SUBBRANDNAME",
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


# =====================================================================
# 1. LOAD DATA
# =====================================================================
@st.cache_data(show_spinner="Memproses file LBP...")
def load_lbp(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".txt") or name.endswith(".csv"):
        # index_col=False WAJIB: file LBP punya trailing "|" di akhir tiap baris,
        # tanpa ini pandas salah mengira kolom pertama adalah index dan semua
        # kolom lain bakal geser satu posisi.
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
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=key)


# =====================================================================
# 2. FUNGSI PERHITUNGAN INTI
# =====================================================================
def net_value(df: pd.DataFrame) -> float:
    bruto_f = df.loc[df[COL["transtype"]] == "F", COL["bruto"]].sum()
    bruto_r = df.loc[df[COL["transtype"]] == "R", COL["bruto"]].sum()
    return bruto_f - bruto_r


def hitung_pencapaian(df: pd.DataFrame):
    bruto_f = df.loc[df[COL["transtype"]] == "F", COL["bruto"]].sum()
    bruto_r = df.loc[df[COL["transtype"]] == "R", COL["bruto"]].sum()
    pencapaian = bruto_f - bruto_r
    pct_retur = (bruto_r / bruto_f * 100) if bruto_f else 0
    return pencapaian, bruto_f, bruto_r, pct_retur


def hitung_oa(df: pd.DataFrame) -> int:
    return df.loc[df[COL["transtype"]] == "F", COL["outlet"]].nunique()


def ringkasan_by_salesman(df: pd.DataFrame, df_target: pd.DataFrame, periode_sel, hka: float) -> pd.DataFrame:
    f_only = df[df[COL["transtype"]] == "F"]

    net = (
        df.groupby([COL["kode_sales"], COL["salesman"], "team_simple"])
        .apply(net_value)
        .reset_index(name="Net Sales (Rp)")
    )

    oa = f_only.groupby([COL["kode_sales"], COL["salesman"]])[COL["outlet"]].nunique().reset_index(name="OA")

    ec = (
        f_only.groupby([COL["kode_sales"], COL["salesman"], f_only[COL["tanggal"]].dt.date])[COL["outlet"]]
        .nunique()
        .groupby(level=[0, 1]).sum()
        .reset_index(name="EC")
    )

    avg_sku = (
        f_only.groupby([COL["kode_sales"], COL["salesman"], COL["outlet"]])[COL["pcode"]]
        .nunique()
        .groupby(level=[0, 1]).mean()
        .reset_index(name="Avg SKU")
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
        out = out.rename(columns={TARGET_COL["target"]: "Target (Rp)"})
    else:
        out["Target (Rp)"] = np.nan

    out["% Capaian"] = (out["Net Sales (Rp)"] / out["Target (Rp)"] * 100).round(1)
    out["Gap Harian"] = ((out["Target (Rp)"] - out["Net Sales (Rp)"]) / hka).round(0) if hka else np.nan

    out = out.rename(columns={COL["kode_sales"]: "Kode Sales", COL["salesman"]: "Salesman",
                               "team_simple": "Team"})
    kolom_akhir = ["Kode Sales", "Salesman", "Team", "Target (Rp)", "Net Sales (Rp)", "% Capaian",
                   "OA", "% OA", "EC", "Gap Harian", "Avg SKU"]
    return out[kolom_akhir].sort_values("Net Sales (Rp)", ascending=False)


def top_n(df: pd.DataFrame, group_col: str, n: int = 10) -> pd.DataFrame:
    out = df.groupby(group_col).apply(net_value).reset_index(name="Omzet")
    return out.sort_values("Omzet", ascending=False).reset_index(drop=True).head(n), \
        out.sort_values("Omzet", ascending=False).reset_index(drop=True)


def universe_sku_per_tipe_outlet(df_f: pd.DataFrame) -> dict:
    """Proxy 'master SKU': semua Pcode+Nama Produk yang pernah laku di tiap Tipe Outlet
    (dalam data yang sedang difilter). Ganti dengan file master SKU asli kalau sudah ada."""
    universe = {}
    for tipe, g in df_f.groupby(COL["tipe_outlet"]):
        universe[tipe] = g.drop_duplicates(subset=[COL["pcode"]])[[COL["pcode"], COL["nama_produk"]]]
    return universe


# =====================================================================
# 3. SIDEBAR — UPLOAD & FILTER SALESMAN
# =====================================================================
with st.sidebar:
    st.markdown("### ⚙️ Option")
    target_file = st.file_uploader("Upload File Target (.xls)", type=["xls", "xlsx"])
    lbp_file = st.file_uploader("Upload File LBP (.txt / .xls)", type=["txt", "csv", "xls", "xlsx"])

if lbp_file is None:
    st.info("Upload file LBP di sidebar untuk mulai melihat dashboard.")
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

# =====================================================================
# 4. TOP BAR — TARGET / PENCAPAIAN / GAP HARIAN / OA / HKA / PERIODE / WEEK
# =====================================================================
st.markdown("## Dashboard Operational Area MU42")

periode_opts = sorted(df_sales_scope[COL["periode"]].dropna().unique().astype(int).tolist())
week_opts = sorted(df_sales_scope[COL["week"]].dropna().unique().astype(int).tolist())

c_t, c_p, c_g, c_oa, c_side = st.columns([1.1, 1.1, 1, 1, 1.3])

with c_side:
    hka = st.number_input("HKA (Hari Kerja Aktif)", min_value=0, value=24, step=1)
    periode_sel = st.multiselect("Filter Periode", periode_opts, default=periode_opts)
    week_sel = st.multiselect("Filter Week", week_opts, default=week_opts)

df_filtered = df_sales_scope.copy()
if periode_sel:
    df_filtered = df_filtered[df_filtered[COL["periode"]].isin(periode_sel)]
if week_sel:
    df_filtered = df_filtered[df_filtered[COL["week"]].isin(week_sel)]

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

team_per_salesman = df_filtered.drop_duplicates(subset=[COL["kode_sales"]])[[COL["kode_sales"], "team_simple"]]
saran_cb = int(team_per_salesman["team_simple"].map(lambda tm: STANDAR_TEAM.get(tm, {}).get("CB", 0)).sum())

with c_side:
    cb_standpro_area = st.number_input("CB Standpro Area (saran otomatis, bisa ditimpa)",
                                        min_value=0, value=saran_cb, step=1)

oa_pct = (oa_total / cb_standpro_area * 100) if cb_standpro_area else 0

with c_t:
    st.metric("Target", f"Rp {target_total:,.0f}")
with c_p:
    st.metric("Pencapaian", f"Rp {pencapaian:,.0f}")
    st.caption(f"Retur: {pct_retur:.2f}% (Rp {bruto_r:,.0f})")
with c_g:
    st.metric("Gap Harian", f"Rp {gap_harian_total:,.0f}")
with c_oa:
    st.metric("OA", f"{oa_total} outlet")
    st.caption(f"{oa_pct:.1f}% dari CB Standpro Area ({cb_standpro_area})")

st.divider()

# =====================================================================
# 5. TABS MENU
# =====================================================================
ringkasan_sales = ringkasan_by_salesman(df_filtered, df_target, periode_sel, hka)

tab_overview, tab_sales, tab_wilayah, tab_subbrand, tab_mhs, tab_insentif, tab_readme = st.tabs(
    ["Overview", "By Salesman", "By Wilayah", "By Subbrand & Divisi", "MHS", "Insentif", "Read Me"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
    st.subheader("Klasifikasi Outlet & Omzet per Tipe Outlet")
    f_only = df_filtered[df_filtered[COL["transtype"]] == "F"]
    jumlah_outlet = f_only.drop_duplicates(subset=[COL["outlet"]]).groupby(COL["tipe_outlet"])[COL["outlet"]] \
        .nunique().reset_index(name="Jumlah Outlet")
    omzet_tipe = df_filtered.groupby(COL["tipe_outlet"]).apply(net_value).reset_index(name="Omzet")
    tbl_tipe = jumlah_outlet.merge(omzet_tipe, on=COL["tipe_outlet"], how="outer").fillna(0)
    tbl_tipe["Tipe Outlet"] = tbl_tipe[COL["tipe_outlet"]].map(TIPE_OUTLET_LABEL).fillna(tbl_tipe[COL["tipe_outlet"]])
    tbl_tipe = tbl_tipe[["Tipe Outlet", "Jumlah Outlet", "Omzet"]].sort_values("Omzet", ascending=False)
    st.dataframe(tbl_tipe, hide_index=True, use_container_width=True)
    download_button(tbl_tipe, "Download Excel (Klasifikasi Outlet)", "overview_klasifikasi_outlet.xlsx", "dl_ov1")

    st.subheader("Top Contributor")
    oc1, oc2, oc3 = st.columns(3)
    with oc1:
        st.markdown("**Salesman**")
        st.dataframe(ringkasan_sales[["Salesman", "Net Sales (Rp)"]].head(5), hide_index=True, use_container_width=True)
    with oc2:
        st.markdown("**Wilayah (Kabupaten)**")
        top_wil, _ = top_n(df_filtered, COL["kabupaten"], 5)
        st.dataframe(top_wil, hide_index=True, use_container_width=True)
    with oc3:
        st.markdown("**Subbrand**")
        top_sb, _ = top_n(df_filtered, COL["subbrand_name"], 5)
        st.dataframe(top_sb, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- By Salesman
with tab_sales:
    st.subheader("Kinerja per Salesman")
    st.caption("% OA dihitung dari standar CB per Team (Read Me). Team di luar TO-Retail/TO-Grosir tampil '-'.")
    st.dataframe(ringkasan_sales, hide_index=True, use_container_width=True)
    download_button(ringkasan_sales, "Download Excel (By Salesman)", "by_salesman.xlsx", "dl_sales")

# ---------------------------------------------------------------- By Wilayah
with tab_wilayah:
    st.subheader("Penjualan by Wilayah")
    for label, col in [("Kabupaten", COL["kabupaten"]), ("Kecamatan", COL["kecamatan"]),
                        ("Kelurahan", COL["kelurahan"])]:
        st.markdown(f"**Top 10 {label}**")
        top10, semua = top_n(df_filtered, col, 10)
        fig = px.bar(top10, x=col, y="Omzet")
        st.plotly_chart(fig, use_container_width=True)
        with st.expander(f"Lihat semua data {label}"):
            st.dataframe(semua, hide_index=True, use_container_width=True)
            download_button(semua, f"Download Excel ({label})", f"wilayah_{label.lower()}.xlsx", f"dl_wil_{label}")

    st.subheader("Penjualan by Kode Pasar")
    pasar_tbl = df_filtered.groupby(COL["kode_pasar"]).apply(net_value).reset_index(name="Omzet") \
        .sort_values("Omzet", ascending=False)
    st.dataframe(pasar_tbl, hide_index=True, use_container_width=True)
    download_button(pasar_tbl, "Download Excel (Kode Pasar)", "wilayah_kode_pasar.xlsx", "dl_pasar")

# ---------------------------------------------------------------- By Subbrand & Divisi
with tab_subbrand:
    st.subheader("Kontribusi per Subbrand")
    top_sb10, semua_sb = top_n(df_filtered, COL["subbrand_name"], 10)
    fig_sb = px.bar(top_sb10, x=COL["subbrand_name"], y="Omzet")
    st.plotly_chart(fig_sb, use_container_width=True)
    with st.expander("Lihat semua data Subbrand"):
        st.dataframe(semua_sb, hide_index=True, use_container_width=True)
        download_button(semua_sb, "Download Excel (Subbrand)", "subbrand.xlsx", "dl_sb")

    st.subheader("Kontribusi per Divisi")
    st.caption("Divisi ditampilkan sebagai kode mentah karena belum ada tabel nama Divisi.")
    top_dv10, semua_dv = top_n(df_filtered, COL["divisi"], 10)
    fig_dv = px.bar(top_dv10, x=COL["divisi"], y="Omzet")
    st.plotly_chart(fig_dv, use_container_width=True)
    with st.expander("Lihat semua data Divisi"):
        st.dataframe(semua_dv, hide_index=True, use_container_width=True)
        download_button(semua_dv, "Download Excel (Divisi)", "divisi.xlsx", "dl_dv")

# ---------------------------------------------------------------- MHS
with tab_mhs:
    st.subheader("MHS — SKU Masuk vs Target SKU")
    f_only = df_filtered[df_filtered[COL["transtype"]] == "F"]
    sku_terjual = f_only.groupby([COL["outlet"], COL["nama_outlet"], COL["salesman"], COL["channel"],
                                   COL["tipe_outlet"]])[COL["pcode"]].nunique().reset_index(name="SKU Terjual")
    sku_terjual["Target SKU"] = sku_terjual[COL["tipe_outlet"]].map(TARGET_SKU_MHS)
    sku_terjual["Kekurangan SKU"] = (sku_terjual["Target SKU"] - sku_terjual["SKU Terjual"]).clip(lower=0)
    sku_terjual = sku_terjual.rename(columns={COL["outlet"]: "No Outlet", COL["nama_outlet"]: "Nama Outlet",
                                               COL["salesman"]: "Salesman", COL["channel"]: "Channel"})
    tampil = sku_terjual.dropna(subset=["Target SKU"])
    st.dataframe(tampil[["No Outlet", "Nama Outlet", "Salesman", "Channel", "Target SKU",
                          "SKU Terjual", "Kekurangan SKU"]], hide_index=True, use_container_width=True)
    download_button(tampil, "Download Excel (MHS Resume)", "mhs_resume.xlsx", "dl_mhs")

    st.markdown("---")
    st.markdown("**Detail SKU per Outlet**")
    outlet_pilihan = st.selectbox("Pilih outlet", tampil["No Outlet"] + " - " + tampil["Nama Outlet"])
    if outlet_pilihan:
        no_outlet_sel = outlet_pilihan.split(" - ")[0]
        tipe_outlet_sel = f_only.loc[f_only[COL["outlet"]] == no_outlet_sel, COL["tipe_outlet"]].iloc[0]
        universe = universe_sku_per_tipe_outlet(f_only)
        semua_sku_tipe = universe.get(tipe_outlet_sel, pd.DataFrame(columns=[COL["pcode"], COL["nama_produk"]]))
        sku_outlet = f_only.loc[f_only[COL["outlet"]] == no_outlet_sel,
                                 [COL["pcode"], COL["nama_produk"], COL["qty"], COL["bruto"]]].drop_duplicates()

        cL, cR = st.columns(2)
        with cL:
            st.markdown("*SKU sudah masuk*")
            st.dataframe(sku_outlet, hide_index=True, use_container_width=True)
        with cR:
            st.markdown("*SKU belum masuk (dibanding SKU lain yang laku di Tipe Outlet sejenis)*")
            belum_masuk = semua_sku_tipe[~semua_sku_tipe[COL["pcode"]].isin(sku_outlet[COL["pcode"]])]
            st.dataframe(belum_masuk, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- Insentif
with tab_insentif:
    st.info("Menu Insentif akan dikembangkan lebih lanjut.")

# ---------------------------------------------------------------- Read Me
with tab_readme:
    st.subheader("Standar Team (CB / EC / IPT)")
    st.dataframe(pd.DataFrame(STANDAR_TEAM).T.rename_axis("Team").reset_index(), hide_index=True)

    st.subheader("Target SKU per Tipe Outlet (acuan MHS)")
    df_sku_std = pd.DataFrame(
        [{"Tipe Outlet": TIPE_OUTLET_LABEL.get(k, k), "Target SKU": v} for k, v in TARGET_SKU_MHS.items()]
    )
    st.dataframe(df_sku_std, hide_index=True)

    st.caption("Tabel ini acuan statis dari spesifikasi awal. Menu LTD NPL sengaja belum dibuat.")
