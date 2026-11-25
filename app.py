"""Consumer Complaint Monitoring & Response Dashboard (Bank of America, CFPB data 2017-2023).

Run:  streamlit run app.py
DB:   set DATABASE_URL env var, or .streamlit/secrets.toml with  [postgres] url = "postgresql+psycopg2://user:pass@host:5432/dbname"
"""
import os
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine

# ---------- CONFIG: edit these to match your database ----------
TABLE = "complaints"
COLS = {  # left = name used in this app, right = column name in your table
    "complaint_id": "complaint_id",
    "submitted_via": "submitted_via",
    "date_submitted": "date_submitted",
    "date_received": "date_received",
    "state": "state",
    "product": "product",
    "sub_product": "sub_product",
    "issue": "issue",
    "sub_issue": "sub_issue",
    "public_response": "company_public_response",
    "response": "company_response_to_consumer",
    "timely": "timely_response",
}
# ---------------------------------------------------------------

st.set_page_config(page_title="Consumer Complaint Dashboard", layout="wide")


@st.cache_data(show_spinner="Loading data from PostgreSQL...")
def load_data() -> pd.DataFrame:
    url = os.getenv("DATABASE_URL") or st.secrets["postgres"]["url"]
    engine = create_engine(url)
    select = ", ".join(f'"{db}" AS {app}' for app, db in COLS.items())
    df = pd.read_sql(f'SELECT {select} FROM "{TABLE}"', engine)

    df["date_submitted"] = pd.to_datetime(df["date_submitted"])
    df["date_received"] = pd.to_datetime(df["date_received"])
    df["yr"] = df["date_submitted"].dt.year
    df["qtr"] = df["date_submitted"].dt.quarter
    df["month_start"] = df["date_submitted"].dt.to_period("M").dt.to_timestamp()
    df["forwarding_days"] = (df["date_received"].dt.normalize() - df["date_submitted"].dt.normalize()).dt.days
    # Blank sub-issue / public response are meaningful, not errors: label them rather than drop them
    df["sub_issue"] = df["sub_issue"].fillna("Not recorded")
    df["sub_product"] = df["sub_product"].fillna("Not recorded")
    df["public_response"] = df["public_response"].fillna("Not recorded")
    return df


df_all = load_data()

# ---------- Sidebar: navigation + filters ----------
st.sidebar.title("Complaint Dashboard")
page = st.sidebar.radio(
    "Page",
    ["1. Executive Overview", "2. Product & Issue", "3. Company Response", "4. Complaint Timeline"],
)
st.sidebar.header("Filters")
years = sorted(df_all["yr"].unique())
sel_years = st.sidebar.multiselect("Year", years, default=years)
products = sorted(df_all["product"].dropna().unique())
sel_products = st.sidebar.multiselect("Product", products, default=products)
states = sorted(df_all["state"].dropna().unique())
sel_states = st.sidebar.multiselect("State (blank = all)", states)

df = df_all[df_all["yr"].isin(sel_years) & df_all["product"].isin(sel_products)]
if sel_states:
    df = df[df["state"].isin(sel_states)]

if df.empty:
    st.warning("No records match the current filters.")
    st.stop()

st.sidebar.caption(
    "Data: CFPB consumer complaints, Bank of America, 1 May 2017 - 28 Aug 2023. "
    "2017 and 2023 are partial years."
)

# ---------- KPI calculations ----------
total = len(df)
yn = df[df["timely"].isin(["Yes", "No"])]
timely_pct = 100 * (yn["timely"] == "Yes").mean() if len(yn) else float("nan")
excluded = total - len(yn)
in_progress = int((df["response"] == "In progress").sum())
avg_fwd = df["forwarding_days"].mean()
med_fwd = df["forwarding_days"].median()


def kpi_help():
    with st.expander("KPI definitions"):
        st.markdown(
            """
- **Total complaints**: count of unique Complaint IDs after filters.
- **Timely response %**: complaints marked *Yes* / (*Yes* + *No*). Blank values (linked to *In progress*) are excluded from the denominator and reported separately.
- **In progress**: complaints whose company response is recorded as *In progress*.
- **Forwarding interval**: days between *Date submitted* (CFPB received) and *Date received* (CFPB sent to company). This is **not** the company's response or resolution time.
- **YoY change**: (this year - previous year) / previous year. 2017 and 2023 are partial years, so treat their YoY with caution.
- A complaint is a consumer-reported issue; it does not prove misconduct. A recorded response is not proof of resolution.
            """
        )


def bar(data, x, y, title, orient="v", **kw):
    fig = px.bar(data, x=x, y=y, title=title, orientation=orient, **kw)
    fig.update_layout(margin=dict(t=50, l=10, r=10, b=10))
    return fig


# ---------- Page 1 ----------
if page.startswith("1"):
    st.title("Executive Complaint Overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total complaints", f"{total:,}")
    c2.metric("Timely response %", f"{timely_pct:.1f}%", help=f"{excluded:,} records excluded (not Yes/No)")
    c3.metric("Avg forwarding interval", f"{avg_fwd:.2f} days", help=f"Median: {med_fwd:.1f} days")
    c4.metric("In progress", f"{in_progress:,}")

    monthly = df.groupby("month_start").size().reset_index(name="complaints")
    st.plotly_chart(px.line(monthly, x="month_start", y="complaints", title="Monthly complaint volume"),
                    use_container_width=True)

    left, right = st.columns(2)
    prod = df["product"].value_counts().reset_index()
    prod.columns = ["product", "complaints"]
    prod["pct"] = (100 * prod["complaints"] / prod["complaints"].sum()).round(1)
    left.plotly_chart(px.pie(prod, names="product", values="complaints", title="Product share of complaints", hole=0.4),
                      use_container_width=True)

    annual = df.groupby("yr").size().reset_index(name="complaints")
    annual["yoy_pct"] = (annual["complaints"].pct_change() * 100).round(1)
    annual["label"] = annual["yr"].astype(str)
    annual.loc[annual["yr"] == 2017, "label"] = "2017 (May-Dec)"
    annual.loc[annual["yr"] == 2023, "label"] = "2023 (to 28 Aug)"
    right.plotly_chart(bar(annual, "label", "complaints", "Annual complaint volume", text="complaints"),
                       use_container_width=True)
    st.caption("Annual table with year-over-year change (partial years not like-for-like):")
    st.dataframe(annual[["label", "complaints", "yoy_pct"]].rename(columns={"label": "Year", "yoy_pct": "YoY %"}),
                 hide_index=True)
    kpi_help()

# ---------- Page 2 ----------
elif page.startswith("2"):
    st.title("Product & Issue Analysis")
    left, right = st.columns(2)
    prod = df["product"].value_counts().reset_index()
    prod.columns = ["product", "complaints"]
    prod["pct"] = (100 * prod["complaints"] / total).round(1)
    left.plotly_chart(bar(prod.sort_values("complaints"), "complaints", "product", "Complaints by product",
                          orient="h", text="pct"), use_container_width=True)

    sub = df.groupby(["product", "sub_product"]).size().reset_index(name="complaints")
    sub = sub.sort_values("complaints", ascending=False).head(15)
    right.plotly_chart(bar(sub.sort_values("complaints"), "complaints", "sub_product", "Top 15 sub-products",
                           orient="h", color="product"), use_container_width=True)

    n_issues = st.slider("Number of issues to show", 5, 25, 15)
    iss = df["issue"].value_counts().head(n_issues).reset_index()
    iss.columns = ["issue", "complaints"]
    st.plotly_chart(bar(iss.sort_values("complaints"), "complaints", "issue", f"Top {n_issues} reported issues",
                        orient="h"), use_container_width=True)

    top_issues = df["issue"].value_counts().head(10).index
    heat = (df[df["issue"].isin(top_issues)].groupby(["product", "issue"]).size()
            .reset_index(name="complaints").pivot(index="issue", columns="product", values="complaints").fillna(0))
    st.plotly_chart(px.imshow(heat, text_auto=True, aspect="auto", color_continuous_scale="Blues",
                              title="Product vs issue (top 10 issues)"), use_container_width=True)

    prod_pick = st.selectbox("Top issues within a product", sorted(df["product"].unique()))
    pi = df[df["product"] == prod_pick]["issue"].value_counts().head(10).reset_index()
    pi.columns = ["issue", "complaints"]
    st.plotly_chart(bar(pi.sort_values("complaints"), "complaints", "issue", f"Top issues: {prod_pick}",
                        orient="h"), use_container_width=True)

    with st.expander("Sub-issues"):
        si = df.groupby(["issue", "sub_issue"]).size().reset_index(name="complaints")
        st.dataframe(si.sort_values("complaints", ascending=False), hide_index=True)
    kpi_help()

# ---------- Page 3 ----------
elif page.startswith("3"):
    st.title("Company Response Analysis")
    c1, c2, c3 = st.columns(3)
    c1.metric("Timely response %", f"{timely_pct:.1f}%")
    c2.metric("Records excluded from %", f"{excluded:,}", help="Blank / not Yes-No")
    c3.metric("In progress", f"{in_progress:,}")

    left, right = st.columns(2)
    resp = df["response"].value_counts().reset_index()
    resp.columns = ["response", "complaints"]
    resp["pct"] = (100 * resp["complaints"] / total).round(1)
    left.plotly_chart(bar(resp.sort_values("complaints"), "complaints", "response",
                          "Company response to consumer", orient="h", text="pct"), use_container_width=True)

    tim = df["timely"].fillna("Blank (excluded)").value_counts().reset_index()
    tim.columns = ["timely", "complaints"]
    right.plotly_chart(px.pie(tim, names="timely", values="complaints", title="Timely response (incl. excluded)",
                              hole=0.4), use_container_width=True)

    pub = df["public_response"].value_counts().reset_index()
    pub.columns = ["public_response", "complaints"]
    st.plotly_chart(bar(pub.sort_values("complaints"), "complaints", "public_response",
                        "Company public response", orient="h"), use_container_width=True)

    trend = df.groupby(["yr", "response"]).size().reset_index(name="complaints")
    st.plotly_chart(px.bar(trend, x="yr", y="complaints", color="response", barmode="relative",
                           title="Response categories over time"), use_container_width=True)
    st.caption("A recorded response is not proof the complaint was resolved to the consumer's satisfaction.")
    kpi_help()

# ---------- Page 4 ----------
else:
    st.title("Complaint Timeline Analysis")
    left, right = st.columns(2)
    monthly = df.groupby("month_start").size().reset_index(name="complaints")
    left.plotly_chart(px.line(monthly, x="month_start", y="complaints", title="Monthly complaints"),
                      use_container_width=True)
    annual = df.groupby("yr").size().reset_index(name="complaints")
    right.plotly_chart(bar(annual, "yr", "complaints", "Annual complaints", text="complaints"),
                       use_container_width=True)

    neg = int((df["forwarding_days"] < 0).sum())
    if neg:
        st.warning(f"{neg:,} records have a negative forwarding interval (date received before date submitted). Review in your cleaning log.")
    fd = df[df["forwarding_days"] >= 0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Average interval", f"{fd['forwarding_days'].mean():.2f} days")
    c2.metric("Median interval", f"{fd['forwarding_days'].median():.1f} days")
    c3.metric("Max interval", f"{int(fd['forwarding_days'].max())} days")

    cap = fd["forwarding_days"].quantile(0.99)
    st.plotly_chart(px.histogram(fd[fd["forwarding_days"] <= cap], x="forwarding_days",
                                 title=f"Forwarding interval distribution (days, up to 99th percentile = {cap:.0f})"),
                    use_container_width=True)

    byprod = fd.groupby("product")["forwarding_days"].agg(["mean", "median"]).round(2).reset_index()
    st.plotly_chart(bar(byprod.sort_values("mean"), "mean", "product", "Average forwarding interval by product (days)",
                        orient="h"), use_container_width=True)

    method = st.radio("Unusually long interval rule", ["IQR (Q3 + 1.5 x IQR)", "99th percentile"], horizontal=True)
    q1, q3 = fd["forwarding_days"].quantile([0.25, 0.75])
    thr = q3 + 1.5 * (q3 - q1) if method.startswith("IQR") else fd["forwarding_days"].quantile(0.99)
    long_df = fd[fd["forwarding_days"] > thr]
    st.write(f"**Threshold: > {thr:.1f} days.** {len(long_df):,} complaints ({100 * len(long_df) / len(fd):.1f}%) flagged.")
    st.dataframe(long_df[["complaint_id", "product", "issue", "date_submitted", "date_received", "forwarding_days"]]
                 .sort_values("forwarding_days", ascending=False).head(200), hide_index=True)
    kpi_help()
