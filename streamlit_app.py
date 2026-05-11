"""
ESOP Intelligence Agent — Professional Web Interface
Run: python3 -m streamlit run streamlit_app.py
"""
import os, sys, json, time
import streamlit as st
import anthropic
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from tools import TOOLS, execute_tool
from database import get_all_companies, get_stats, get_conn
from config import DATA_DIR
from schema import (
    SCHEME_FIELDS_ORDERED, FIELD_LABELS, HIGHLIGHT_ROWS, SECTION_ROWS
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ESOP Intelligence Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS — Claude-inspired dark design ─────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@400;500;600;700&display=swap');

/* ══════════════════════════════════════════════════════
   BASE & RESET
══════════════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; }

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background-color: #07080D;
    color: #E2E0D8;
    -webkit-font-smoothing: antialiased;
}
#MainMenu, footer, header { visibility: hidden; }

/* ══════════════════════════════════════════════════════
   BACKGROUND — deep space with radial ambient glow
══════════════════════════════════════════════════════ */
.main {
    background:
        radial-gradient(ellipse 80% 50% at 50% -10%, rgba(217,119,6,0.12) 0%, transparent 65%),
        radial-gradient(ellipse 60% 40% at 90% 80%, rgba(59,130,246,0.06) 0%, transparent 60%),
        #07080D;
}
.main .block-container {
    background: transparent;
    padding-top: 1.8rem;
    max-width: 1280px;
}

/* ══════════════════════════════════════════════════════
   SIDEBAR
══════════════════════════════════════════════════════ */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0D0E14 0%, #0A0B10 100%) !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
    box-shadow: 4px 0 24px rgba(0,0,0,0.4);
}
section[data-testid="stSidebar"] * { color: #B8B5A8 !important; }

section[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    color: #A8A5A0 !important;
    border-radius: 10px;
    font-size: 0.81rem;
    font-weight: 450;
    text-align: left;
    transition: all 0.2s cubic-bezier(0.4,0,0.2,1);
    padding: 0.5rem 0.85rem;
    width: 100%;
    letter-spacing: 0.01em;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(217,119,6,0.1);
    border-color: rgba(217,119,6,0.4);
    color: #F5C842 !important;
    transform: translateX(2px);
    box-shadow: 0 0 20px rgba(217,119,6,0.08);
}

[data-testid="stMetricValue"] { color: #F59E0B !important; font-weight: 700 !important; font-size: 1.4rem !important; }
[data-testid="stMetricLabel"] { color: #52524E !important; font-size: 0.7rem !important; }

/* ══════════════════════════════════════════════════════
   TABS — pill style with glow on active
══════════════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.03);
    border-radius: 14px;
    padding: 5px;
    gap: 3px;
    border: 1px solid rgba(255,255,255,0.06);
    backdrop-filter: blur(8px);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    padding: 8px 22px;
    font-size: 0.85rem;
    font-weight: 500;
    color: #5A5A52 !important;
    background: transparent !important;
    border: none !important;
    transition: all 0.2s ease;
    letter-spacing: 0.01em;
}
.stTabs [data-baseweb="tab"]:hover { color: #A8A5A0 !important; }
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, rgba(217,119,6,0.18), rgba(217,119,6,0.08)) !important;
    color: #F59E0B !important;
    font-weight: 600;
    border: 1px solid rgba(217,119,6,0.25) !important;
    box-shadow: 0 2px 12px rgba(217,119,6,0.12), inset 0 1px 0 rgba(255,255,255,0.05);
}

/* ══════════════════════════════════════════════════════
   CHAT — premium message bubbles
══════════════════════════════════════════════════════ */
.stChatMessage {
    background: rgba(255,255,255,0.025) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 16px !important;
    backdrop-filter: blur(12px) !important;
    transition: border-color 0.2s !important;
}
.stChatMessage:hover { border-color: rgba(255,255,255,0.1) !important; }
[data-testid="stChatMessageContent"] { color: #DDD9D0 !important; line-height: 1.65 !important; }

.stChatInputContainer > div {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(217,119,6,0.3) !important;
    border-radius: 14px !important;
    backdrop-filter: blur(12px) !important;
    box-shadow: 0 0 0 1px rgba(217,119,6,0.08), 0 8px 32px rgba(0,0,0,0.3) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stChatInputContainer > div:focus-within {
    border-color: rgba(217,119,6,0.6) !important;
    box-shadow: 0 0 0 3px rgba(217,119,6,0.1), 0 8px 32px rgba(0,0,0,0.3) !important;
}
.stChatInputContainer textarea {
    background: transparent !important;
    color: #E2E0D8 !important;
    font-size: 0.93rem !important;
}

/* ══════════════════════════════════════════════════════
   INPUTS & SELECTS
══════════════════════════════════════════════════════ */
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {
    background: rgba(255,255,255,0.04) !important;
    border-color: rgba(255,255,255,0.08) !important;
    color: #E2E0D8 !important;
    border-radius: 10px !important;
    transition: border-color 0.2s !important;
}
[data-baseweb="select"] > div:focus-within { border-color: rgba(217,119,6,0.4) !important; }
[data-baseweb="select"] span { color: #E2E0D8 !important; }
[data-baseweb="menu"] { background: #13141A !important; border: 1px solid rgba(255,255,255,0.08) !important; border-radius: 12px !important; }
[data-baseweb="option"] { background: transparent !important; color: #C8C5BE !important; }
[data-baseweb="option"]:hover { background: rgba(217,119,6,0.1) !important; color: #F5C842 !important; }
.stSelectbox label, .stTextInput label { color: #52524E !important; font-size: 0.75rem !important; letter-spacing: 0.04em !important; text-transform: uppercase !important; }

/* ══════════════════════════════════════════════════════
   DATAFRAMES
══════════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 14px !important;
    overflow: hidden !important;
}
.dvn-scroller { background: transparent !important; }

/* ══════════════════════════════════════════════════════
   BUTTONS — primary & download
══════════════════════════════════════════════════════ */
[data-testid="stDownloadButton"] > button,
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #F59E0B 0%, #D97706 50%, #B45309 100%) !important;
    color: #07080D !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    font-size: 0.84rem !important;
    letter-spacing: 0.02em !important;
    transition: all 0.25s cubic-bezier(0.4,0,0.2,1) !important;
    box-shadow: 0 4px 20px rgba(217,119,6,0.25) !important;
}
[data-testid="stDownloadButton"] > button:hover,
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #FCD34D 0%, #F59E0B 50%, #D97706 100%) !important;
    box-shadow: 0 6px 28px rgba(217,119,6,0.45) !important;
    transform: translateY(-1px) !important;
}

/* ══════════════════════════════════════════════════════
   ALERTS / INFO
══════════════════════════════════════════════════════ */
[data-testid="stAlert"] {
    background: rgba(217,119,6,0.06) !important;
    border: 1px solid rgba(217,119,6,0.2) !important;
    border-radius: 12px !important;
    color: #DDD9D0 !important;
    backdrop-filter: blur(8px) !important;
}

/* ══════════════════════════════════════════════════════
   SPINNER
══════════════════════════════════════════════════════ */
[data-testid="stSpinner"] p { color: #F59E0B !important; }

/* ══════════════════════════════════════════════════════
   CHARTS
══════════════════════════════════════════════════════ */
.js-plotly-plot {
    border-radius: 16px !important;
    overflow: hidden !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.3) !important;
}

/* ══════════════════════════════════════════════════════
   DIVIDER
══════════════════════════════════════════════════════ */
hr { border: none !important; border-top: 1px solid rgba(255,255,255,0.05) !important; margin: 1.2rem 0 !important; }

/* ══════════════════════════════════════════════════════
   CUSTOM COMPONENTS
══════════════════════════════════════════════════════ */

/* ── Hero header ── */
.hero-header {
    padding: 2rem 0 1.6rem 0;
    margin-bottom: 1.8rem;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    position: relative;
}
.hero-brand {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.4rem;
}
.hero-logo {
    width: 48px; height: 48px;
    background: linear-gradient(135deg, #F59E0B, #D97706, #92400E);
    border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.4rem;
    flex-shrink: 0;
    box-shadow: 0 0 0 1px rgba(245,158,11,0.3), 0 8px 24px rgba(217,119,6,0.35);
}
.hero-title {
    font-family: 'Space Grotesk', 'Inter', sans-serif;
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: -0.04em;
    background: linear-gradient(135deg, #FBBF24 0%, #F59E0B 40%, #FDE68A 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
    margin: 0;
}
.hero-sub {
    font-size: 0.8rem;
    color: #52524E;
    margin: 3px 0 0 0;
    letter-spacing: 0.01em;
}
.hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: rgba(16,185,129,0.1);
    border: 1px solid rgba(16,185,129,0.25);
    color: #34D399;
    border-radius: 20px;
    padding: 3px 10px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.hero-badge::before { content: "●"; font-size: 0.5rem; }

/* ── Stat cards ── */
.stat-card {
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 16px;
    padding: 1.1rem 1.3rem;
    text-align: center;
    position: relative;
    overflow: hidden;
    transition: border-color 0.25s, box-shadow 0.25s, transform 0.25s;
    backdrop-filter: blur(8px);
}
.stat-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(217,119,6,0.4), transparent);
    opacity: 0;
    transition: opacity 0.25s;
}
.stat-card:hover {
    border-color: rgba(217,119,6,0.3);
    box-shadow: 0 8px 32px rgba(217,119,6,0.1), 0 0 0 1px rgba(217,119,6,0.1);
    transform: translateY(-2px);
}
.stat-card:hover::before { opacity: 1; }
.stat-card .num {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 2.1rem;
    font-weight: 700;
    background: linear-gradient(135deg, #FBBF24, #F59E0B);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1;
    font-variant-numeric: tabular-nums;
}
.stat-card .lbl {
    font-size: 0.67rem;
    color: #52524E;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.4rem;
    font-weight: 500;
}

/* ── Glass card (generic) ── */
.glass-card {
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 16px;
    padding: 1.2rem 1.4rem;
    backdrop-filter: blur(12px);
    position: relative;
    overflow: hidden;
}
.glass-card::after {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(135deg, rgba(255,255,255,0.02) 0%, transparent 60%);
    pointer-events: none;
}

/* ── Section label ── */
.section-label {
    font-size: 0.66rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #3A3A35;
    margin: 1rem 0 0.5rem 0;
}

/* ── Tool activity card ── */
.tool-card {
    background: rgba(217,119,6,0.05);
    border: 1px solid rgba(217,119,6,0.15);
    border-left: 3px solid #F59E0B;
    border-radius: 12px;
    padding: 0.75rem 1rem;
    margin: 0.45rem 0;
    font-size: 0.83rem;
    color: #C0BDB5;
    backdrop-filter: blur(8px);
}
.tool-card .tool-name {
    font-weight: 600;
    color: #F59E0B;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.25rem;
}

/* ── Metric bar ── */
.metric-bar {
    display: flex; align-items: center;
    justify-content: space-between;
    padding: 7px 14px;
    background: rgba(255,255,255,0.03);
    border-radius: 10px;
    margin: 4px 0;
    border-left: 2px solid rgba(245,158,11,0.5);
    transition: background 0.2s;
}
.metric-bar:hover { background: rgba(255,255,255,0.05); }
.metric-bar .mname { font-size: 0.78rem; color: #7A7A72; }
.metric-bar .mval  { font-weight: 700; color: #F59E0B; font-size: 0.92rem; font-variant-numeric: tabular-nums; }

/* ── Company chip ── */
.company-chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px; padding: 4px 12px;
    font-size: 0.77rem; color: #A8A5A0;
    margin: 2px; cursor: default;
    transition: all 0.15s;
}
.company-chip:hover { border-color: rgba(217,119,6,0.3); color: #D4A843; }
.company-chip.has-data { border-color: rgba(16,185,129,0.3); color: #6EE7B7; }
.company-chip.no-data  { border-color: rgba(217,119,6,0.2); }

/* ── Sidebar brand area ── */
.sidebar-brand {
    padding: 1.2rem 0.8rem 0.8rem 0.8rem;
    background: linear-gradient(180deg, rgba(217,119,6,0.06) 0%, transparent 100%);
    border-bottom: 1px solid rgba(255,255,255,0.04);
    margin-bottom: 0.5rem;
}
.sidebar-logo-wrap {
    display: flex; align-items: center; gap: 0.65rem;
}
.sidebar-logo {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, #F59E0B, #D97706, #92400E);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem;
    box-shadow: 0 0 16px rgba(217,119,6,0.35);
    flex-shrink: 0;
}
.sidebar-name {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.95rem;
    font-weight: 700;
    color: #F0EDE5 !important;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.sidebar-tagline {
    font-size: 0.64rem;
    color: #3A3A35 !important;
    letter-spacing: 0.03em;
    margin-top: 1px;
}

/* ── ESOP status banners ── */
.esop-yes {
    background: linear-gradient(135deg, rgba(16,185,129,0.12), rgba(16,185,129,0.06));
    border: 1px solid rgba(16,185,129,0.3);
    border-radius: 14px;
    padding: 1rem 1.4rem;
    margin-bottom: 1rem;
}
.esop-no {
    background: linear-gradient(135deg, rgba(239,68,68,0.1), rgba(239,68,68,0.04));
    border: 1px solid rgba(239,68,68,0.25);
    border-radius: 14px;
    padding: 1rem 1.4rem;
    margin-bottom: 1rem;
}

/* ── Animations ── */
@keyframes fadeSlideUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
.glass-card, .stat-card { animation: fadeSlideUp 0.35s ease both; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_num(val):
    """Format a number for display — plain integers with comma separators."""
    if val is None: return "—"
    try:
        v = float(val)
        if v == int(v): return f"{int(v):,}"
        return f"{v:,.2f}"
    except: return str(val)

def fmt_pct(val):
    if val is None: return "—"
    try: return f"{float(val)*100:.2f}%"
    except: return str(val)

def get_company_excel(bse_code, company_name):
    company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
    return company_dir / "ESOP_data.xlsx"


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        # Brand
        st.markdown("""
        <div class="sidebar-brand">
            <div class="sidebar-logo-wrap">
                <div class="sidebar-logo">📊</div>
                <div>
                    <div class="sidebar-name">ESOP Agent</div>
                    <div class="sidebar-tagline">Powered by Qapita · 4,800+ BSE companies</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # Suggested queries
        st.markdown('<div class="section-label">Try asking</div>', unsafe_allow_html=True)
        suggestions = [
            ("🔍 Infosys ESOP analysis",          "Analyze ESOP data for Infosys for the last 5 years"),
            ("🤔 Does HDFC Bank have ESOPs?",     "Does HDFC Bank have an ESOP plan?"),
            ("🏭 IT sector comparison",           "Which companies in the IT sector have ESOPs? Compare them"),
            ("📊 Zomato vs Swiggy ESOPs",         "Compare ESOP programs of Zomato and Swiggy"),
            ("📈 Paytm ESOP trend",               "Show me Paytm ESOP grants and ownership trend"),
        ]
        for label, prefill in suggestions:
            if st.button(label, key=f"sug_{label[:10]}", use_container_width=True):
                st.session_state.chat_prefill = prefill
                st.rerun()

        st.divider()

        # Recent analyses (from session)
        recent = st.session_state.get("recent_companies", [])
        if recent:
            st.markdown('<div class="section-label">Recent</div>', unsafe_allow_html=True)
            for entry in recent[-5:][::-1]:
                code = entry.get("bse_code","")
                name = entry.get("company_name","")
                if st.button(f"↩  {name}", key=f"recent_{code}", use_container_width=True):
                    st.session_state.chat_prefill = f"Analyze ESOP data for {name} (BSE {code})"
                    st.rerun()
            st.divider()

        st.markdown(
            '<div style="font-size:0.67rem;color:#3A3A32;padding:0 0.2rem;line-height:1.6;">'
            'Powered by Claude Sonnet 4.6<br>+ BSE annual report filings'
            '</div>',
            unsafe_allow_html=True,
        )

    return get_stats()


# ── App Header ────────────────────────────────────────────────────────────────

def render_header(stats):
    from bse_company_db import total_companies
    st.markdown(f"""
    <div class="hero-header">
        <div class="hero-brand">
            <div class="hero-logo">📊</div>
            <div>
                <p class="hero-title">ESOP Intelligence</p>
                <p class="hero-sub">Real-time equity compensation analytics · BSE annual report filings</p>
            </div>
            <div style="margin-left:auto;">
                <span class="hero-badge">Live</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    cards = [
        (f"{total_companies():,}", "BSE Companies"),
        (stats["companies"],       "Tracked"),
        (stats["done"],            "Reports Extracted"),
        (stats["pending"],         "Pending"),
    ]
    for col, (num, lbl) in zip([col1, col2, col3, col4], cards):
        with col:
            st.markdown(
                f'<div class="stat-card"><div class="num">{num}</div>'
                f'<div class="lbl">{lbl}</div></div>',
                unsafe_allow_html=True,
            )


# ── TAB 0: Chat Agent ─────────────────────────────────────────────────────────

def render_chat_tab():
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": (
                "👋 Hello! I'm your **ESOP Intelligence Agent** — covering all 4,845+ BSE-listed companies.\n\n"
                "Just **type a company name** (full or partial) and I'll:\n"
                "1. 🔍 Find the exact company from BSE and confirm it with you\n"
                "2. 📎 Show you the annual report links (with PDF links)\n"
                "3. 📊 Answer your question — ESOP data, sector peers, competitor comparison, multi-year trends\n\n"
                "**No BSE code needed. No setup. No tracking required.**\n\n"
                "Try: *\"Analyze ESOPs for Infosys\"* · *\"Does HDFC Bank have stock options?\"* "
                "· *\"Compare IT sector ESOP programs\"* · *\"Zomato vs Swiggy ESOP\"*"
            ),
            "type": "text",
        }]

    # Render history
    for msg in st.session_state.messages:
        avatar = "🤖" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            if msg.get("content"):
                st.markdown(msg["content"])
            if msg.get("table"):
                st.dataframe(pd.DataFrame(msg["table"]), use_container_width=True, hide_index=True)
            if msg.get("chart"):
                st.plotly_chart(msg["chart"], use_container_width=True, key=f"chart_hist_{id(msg)}")
            if msg.get("excel_path") and Path(msg["excel_path"]).exists():
                with open(msg["excel_path"], "rb") as f:
                    st.download_button(
                        "⬇️ Download Excel Report",
                        f.read(),
                        file_name=Path(msg["excel_path"]).name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{msg['excel_path']}_{id(msg)}",
                    )

    # Prefill from sidebar
    prefill = st.session_state.pop("chat_prefill", None)
    user_input = st.chat_input(
        "Type a company name — e.g. 'Analyze Infosys ESOPs' or 'Does Zomato have stock options?'",
        key="chat_input",
    )
    if prefill and not user_input:
        user_input = prefill

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state["agent_running"] = True
        st.session_state["stop_requested"] = False
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            stop_col, _ = st.columns([1, 8])
            with stop_col:
                if st.button("⏹ Stop", key="stop_btn", help="Stop the agent"):
                    st.session_state["stop_requested"] = True

            with st.spinner("Thinking..."):
                responses = _run_agent(user_input)

            st.session_state["agent_running"] = False

            for resp in responses:
                if resp.get("content"):
                    st.markdown(resp["content"])
                if resp.get("table"):
                    st.dataframe(pd.DataFrame(resp["table"]), use_container_width=True, hide_index=True)
                if resp.get("chart"):
                    st.plotly_chart(resp["chart"], use_container_width=True, key=f"chart_resp_{id(resp)}")
                if resp.get("excel_path") and Path(resp["excel_path"]).exists():
                    with open(resp["excel_path"], "rb") as f:
                        st.download_button(
                            "⬇️ Download Excel Report",
                            f.read(),
                            file_name=Path(resp["excel_path"]).name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_{resp['excel_path']}_{id(resp)}",
                        )

        st.session_state.messages.extend(responses)
        st.rerun()


def _build_system_prompt() -> str:
    """Build system prompt enforcing name-first, no-tracking flow."""
    # Inject any company confirmed this session so follow-ups work
    current = st.session_state.get("current_company")
    company_ctx = ""
    if current:
        company_ctx = (
            f"\n━━ CURRENT COMPANY IN CONTEXT ━━\n"
            f"Name: {current.get('company_name', '')}  |  BSE Code: {current.get('bse_code', '')}\n"
            f"Use this BSE code directly for any follow-up questions that don't name a different company.\n"
        )

    return f"""You are an ESOP Intelligence Agent for Indian listed companies.
You search BSE annual reports in real time, extract structured ESOP data, and answer precise questions.
You cover ALL 4,845+ companies listed on BSE — no pre-existing database needed.
{company_ctx}
━━ WORKFLOW — ALWAYS FOLLOW THIS ORDER ━━

STEP 1 — IDENTIFY THE COMPANY
  • When the user mentions any company name (full or partial), ALWAYS call search_bse_company first.
  • If the result contains exactly ONE company → confirm it in one sentence and immediately proceed
    to Steps 2 and 3 WITHOUT waiting for the user to ask.
  • If the result contains MULTIPLE companies → show a numbered list and ask:
      "I found several matches. Which company did you mean?"
      1. Company A (BSE 500001) — Ticker: AAA
      2. Company B (BSE 500002) — Ticker: BBB
    Wait for the user to pick one, THEN proceed to Steps 2 and 3.
  • If the user gives a pure numeric code (e.g. "500002") → call search_bse_company with that code;
    it will resolve the name instantly. NEVER ask for the name — you have the code.

STEP 2 — SECTOR & COMPETITORS (run immediately after company confirmed)
  • Call get_sector_competitors with the confirmed BSE code.
  • This returns the sector name and a list of peers. Present them as:
      Sector: [sector name]
      Peers: Company A (BSE XXXXXX) · Company B (BSE XXXXXX) · ...

STEP 3 — ESOP SUMMARY (run immediately after Step 2, no user prompt needed)
  • Call generate_instant_report with the confirmed BSE code.
  • This fetches annual reports, extracts ESOP data, and returns a detailed summary + Excel.
  • Present the results as a clean report:

    ── ESOP STATUS ──────────────────────────
    ✅ YES — [Company] has an active ESOP plan   OR   ❌ NO ESOP plan found

    ── SCHEME SUMMARY ───────────────────────
    [For each scheme: pool, total granted, outstanding, dilution %, ownership %]

    ── KEY MANAGEMENT PERSONNEL ─────────────
    [List KMPs who received grants, if available]

    ── SECTOR PEERS ─────────────────────────
    Sector: [sector]  |  Peers: [list]

  • Always show the download button for the Excel report.
  • End with: "Would you like me to analyze any of the peer companies, or compare them?"

STEP 4 — FOLLOW-UP QUERIES (if user asks more questions after the initial summary)
  "Who else in this sector has ESOPs?" / "compare peers"
  → call generate_instant_report for each peer BSE code, then compare.

  "More detail on grants / vesting / KMP" / specific metric questions
  → use query_esop_data on the already-extracted data.

━━ TOOLS ━━
• search_bse_company      — Step 1: ALWAYS call first when user names a company
• get_sector_competitors  — Step 2: call immediately after company confirmed → sector + peers
• generate_instant_report — Step 3: call immediately after sector → full ESOP extract + summary
• get_annual_report_links — optional: show year-wise BSE PDF links on request
• compare_esop_companies  — compare multiple companies side-by-side
• query_esop_data         — deep Q&A on already-extracted data
• check_esop_status       — quick YES/NO check (only if user explicitly asks without wanting full report)
• get_dashboard_stats     — overall stats

━━ STRICT RULES ━━
1. NEVER answer ESOP numbers from training data. Always use generate_instant_report or
   query_esop_data to read the actual annual report data.

2. NEVER suggest "add to tracking", "save to database", or "add_and_fetch_company".
   The default flow is instant and stateless.

3. NEVER ask the user for a BSE code — look it up yourself with search_bse_company.

4. When presenting numbers from extracted data:
   - Plain integers with commas (e.g. 38,541,760) — never say "lakhs" or "crores"
   - Percentages: multiply by 100, add % (e.g. 0.0058 → 0.58%)
   - Always cite scheme name and fiscal year alongside every figure
   - If a field is missing, say "not available"

5. Never output raw JSON. Always convert to readable prose or a markdown table.

6. The esop_summary field returned by generate_instant_report contains pre-formatted
   per-scheme metrics — include them verbatim in your response, then add your own analysis."""


def _run_agent(user_input: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Build conversation history (text turns only — tool calls are tracked separately)
    conversation = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
        if m["role"] in ("user", "assistant") and m.get("content")
    ]
    conversation.append({"role": "user", "content": user_input})

    system   = _build_system_prompt()
    responses, messages = [], conversation[:]
    max_loops = 8  # prevent infinite tool loops

    for _ in range(max_loops):
        # Check stop button
        if st.session_state.get("stop_requested"):
            responses.append({
                "role": "assistant",
                "content": "⏹ Stopped.",
                "type": "text",
            })
            break

        # Retry on overload/rate-limit with exponential backoff
        resp = None
        for attempt in range(4):
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=8096,
                    system=system,
                    tools=TOOLS,
                    messages=messages,
                )
                break
            except anthropic.APIStatusError as e:
                if e.status_code in (529, 529) or "overloaded" in str(e).lower():
                    wait = 10 * (attempt + 1)
                    with st.spinner(f"⏳ API busy — retrying in {wait}s..."):
                        time.sleep(wait)
                elif e.status_code == 429:
                    wait = 30 * (attempt + 1)
                    with st.spinner(f"⏳ Rate limited — retrying in {wait}s..."):
                        time.sleep(wait)
                else:
                    return [{"role": "assistant", "content": f"❌ API error: {e}", "type": "text"}]
            except Exception as e:
                return [{"role": "assistant", "content": f"❌ Error: {e}", "type": "text"}]
        if resp is None:
            return [{"role": "assistant", "content": "❌ API is overloaded. Please try again in a minute.", "type": "text"}]

        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":       text_parts.append(block.text)
            elif block.type == "tool_use": tool_calls.append(block)

        if text_parts:
            responses.append({
                "role": "assistant",
                "content": "\n".join(text_parts),
                "type": "text",
            })

        if resp.stop_reason == "end_turn" or not tool_calls:
            break

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []

        for tc in tool_calls:
            with st.spinner(f"⚙️ {tc.name.replace('_', ' ').title()}..."):
                result = execute_tool(tc.name, tc.input)

            # Capture confirmed company into session state for follow-up questions
            if tc.name == "search_bse_company":
                rows = result.get("table") or []
                if len(rows) == 1:
                    st.session_state["current_company"] = {
                        "bse_code":     rows[0].get("BSE Code", ""),
                        "company_name": rows[0].get("Company", ""),
                    }
                    # Track in recents
                    recent = st.session_state.setdefault("recent_companies", [])
                    entry = {
                        "bse_code":     rows[0].get("BSE Code", ""),
                        "company_name": rows[0].get("Company", ""),
                    }
                    if entry not in recent:
                        recent.append(entry)
                        st.session_state["recent_companies"] = recent[-10:]

            # Show intermediate tool output in the chat
            tool_msg = {
                "role": "assistant",
                "content": f"🔧 **{tc.name.replace('_', ' ').title()}**\n\n{result.get('text', '')}",
                "type": "tool_result",
                "table":      result.get("table"),
                "chart":      result.get("chart"),
                "excel_path": result.get("excel_path"),
            }
            responses.append(tool_msg)

            # Pass full data text back to Claude so it can reason over it
            # For generate_instant_report, append the rich esop_summary so Claude can narrate it
            content = result.get("text", "")
            if tc.name == "generate_instant_report" and result.get("esop_summary"):
                content += f"\n\n━━ ESOP SUMMARY (use this to write your response) ━━\n{result['esop_summary']}"
                if result.get("total_grants"):
                    content += f"\n\nTotal options granted across all schemes (all years): {result['total_grants']:,}"
                if result.get("kmp_names"):
                    content += f"\nKMP recipients: {', '.join(result['kmp_names'])}"
            if tc.name == "get_sector_competitors" and result.get("sector"):
                content += f"\n\nSector: {result['sector']}"
                if result.get("peers"):
                    content += "\nPeers: " + ", ".join(f"{n} (BSE {c})" for c, n in result["peers"])

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tc.id,
                "content":     content,
            })

        messages.append({"role": "user", "content": tool_results})

    return responses


# ── TAB 1: Data Explorer ──────────────────────────────────────────────────────

def render_data_explorer():
    companies = get_all_companies()
    if not companies:
        st.info("No companies tracked yet. Go to the **Chat** tab and ask to add a company.")
        return

    # Company selector
    col_sel, col_dl = st.columns([3, 1])
    with col_sel:
        options = {c["company_name"]: c for c in companies}
        default_name = st.session_state.get("selected_company", companies[0]["company_name"])
        if default_name not in options:
            default_name = companies[0]["company_name"]
        selected_name = st.selectbox(
            "Select Company",
            list(options.keys()),
            index=list(options.keys()).index(default_name),
            label_visibility="collapsed",
        )
    company = options[selected_name]
    bse_code = company["bse_code"]
    company_name = company["company_name"]

    excel_path = get_company_excel(bse_code, company_name)

    with col_dl:
        if excel_path.exists():
            with open(excel_path, "rb") as f:
                st.download_button(
                    "⬇️ Download Excel",
                    f.read(),
                    file_name=excel_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    if not excel_path.exists():
        st.warning(f"No extracted data for **{company_name}**. Run an update first.")
        return

    # Load data
    xl = pd.ExcelFile(excel_path)
    sheets = xl.sheet_names
    scheme_sheets = [s for s in sheets if s not in ("FY wise", "KMP ESOPs")]

    if not scheme_sheets:
        st.warning("No scheme data found in the Excel file.")
        return

    # Scheme tabs inside Data Explorer
    scheme_tab_labels = ["📋 FY Summary"] + [f"📂 {s}" for s in scheme_sheets]
    if "KMP ESOPs" in sheets:
        scheme_tab_labels.append("👥 KMP ESOPs")

    scheme_tabs = st.tabs(scheme_tab_labels)

    # ── FY Summary tab ─────────────────────────────────────────────────────────
    with scheme_tabs[0]:
        _render_fy_summary(xl, company_name, scheme_sheets, excel_path, bse_code=bse_code)

    # ── Individual scheme tabs ─────────────────────────────────────────────────
    for i, scheme_name in enumerate(scheme_sheets):
        with scheme_tabs[i + 1]:
            _render_scheme_detail(xl, company_name, scheme_name)

    # ── KMP tab ───────────────────────────────────────────────────────────────
    if "KMP ESOPs" in sheets:
        with scheme_tabs[-1]:
            _render_kmp_tab(xl)


def _render_fy_summary(xl, company_name, scheme_sheets, excel_path, bse_code=""):
    st.markdown(f"### {company_name} — ESOP Summary")

    all_schemes_data = {}
    for sheet in scheme_sheets:
        df = xl.parse(sheet, header=None)
        if df.empty or len(df) < 3:
            continue
        year_headers = [str(v) for v in df.iloc[1, 1:] if pd.notna(v)]
        rows_dict = {}
        for ri in range(2, len(df)):
            label = str(df.iloc[ri, 0]) if pd.notna(df.iloc[ri, 0]) else ""
            if label:
                rows_dict[label] = list(df.iloc[ri, 1:1+len(year_headers)])
        all_schemes_data[sheet] = {"years": year_headers, "rows": rows_dict}

    if not all_schemes_data:
        st.info("No summary data available.")
        return

    # Key metrics at a glance
    _render_key_metrics_banner(all_schemes_data)

    st.markdown("---")

    # Comparative granted chart
    _render_granted_chart(all_schemes_data, company_name)

    st.markdown("---")

    # Annual report links table
    _render_report_links(bse_code, company_name)


def _render_key_metrics_banner(all_schemes_data):
    """Show latest year key metrics as large cards."""
    PCT_FIELDS = {
        "% Dilution (Pool Approved / Paid-up Capital)": ("% Dilution", "pill-red"),
        "% in Ownership (Options Outstanding / Paid-up Capital)": ("% Ownership", "pill-red"),
        "% Option Overhang (Outstanding / Paid-up Capital)": ("% Overhang", "pill-gold"),
        "Burn Rate (Options Granted in FY / Paid-up Capital)": ("Burn Rate", "pill-blue"),
    }

    # Collect from all schemes, latest year
    metrics = {}
    for scheme, data in all_schemes_data.items():
        years = data["years"]
        rows  = data["rows"]
        if not years: continue
        latest_col = len(years) - 1
        for row_label, (nice_name, pill_cls) in PCT_FIELDS.items():
            for k in rows:
                if row_label[:20].lower() in k.lower():
                    val = rows[k][latest_col] if latest_col < len(rows[k]) else None
                    if val and val != "None" and str(val).lower() != "nan":
                        if nice_name not in metrics:
                            metrics[nice_name] = (val, pill_cls, scheme)

    if not metrics:
        return

    st.markdown("**Key Ownership Metrics (Latest Year)**")
    cols = st.columns(len(metrics))
    for col, (name, (val, pill_cls, scheme)) in zip(cols, metrics.items()):
        with col:
            try:
                pct_val = f"{float(val)*100:.2f}%"
            except:
                pct_val = str(val)
            st.markdown(
                f'<div class="stat-card" style="border-top:3px solid #D97706;">'
                f'<div class="num" style="font-size:1.5rem;color:#F59E0B;">{pct_val}</div>'
                f'<div class="lbl">{name}</div>'
                f'<div style="font-size:0.68rem;color:#5A5A52;margin-top:4px;">{scheme}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_granted_chart(all_schemes_data, company_name):
    st.markdown("**Options Granted by Year & Scheme**")
    fig = go.Figure()
    colors = ["#2E75B6", "#FFC000", "#70AD47", "#ED7D31", "#9B59B6", "#E74C3C"]

    for i, (scheme, data) in enumerate(all_schemes_data.items()):
        years = data["years"]
        rows  = data["rows"]
        granted_vals = None
        for k, v in rows.items():
            if "granted" in k.lower():
                granted_vals = v
                break
        if granted_vals is None: continue
        vals = []
        for v in granted_vals:
            try:    vals.append(float(v) if v and str(v).lower() != "nan" else 0)
            except: vals.append(0)

        fig.add_trace(go.Bar(
            name=scheme, x=years, y=vals,
            marker_color=colors[i % len(colors)],
            text=[f"{int(v):,}" if v > 0 else "" for v in vals],
            textposition="outside",
        ))

    fig.update_layout(
        barmode="group",
        plot_bgcolor="#141414", paper_bgcolor="#141414",
        xaxis=dict(title="Fiscal Year", gridcolor="#2A2A2A", color="#9A9A90"),
        yaxis=dict(title="Options Granted", gridcolor="#2A2A2A", color="#9A9A90"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(color="#C0C0B8")),
        height=380, margin=dict(t=40, b=40),
        font=dict(family="Inter", size=11, color="#C0C0B8"),
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_fy_granted")


def _render_report_links(bse_code: str, company_name: str):
    """Show year-wise annual report links from the saved url_map."""
    if not bse_code:
        return

    from bse_fetcher import load_url_map
    url_map = load_url_map(bse_code)
    if not url_map:
        st.info("No annual report links saved yet. Ask the chat agent to fetch report links.")
        return

    st.markdown("**📎 Annual Report Links (BSE Filings)**")

    rows_html = ""
    for yr in sorted(url_map.keys(), reverse=True):
        info    = url_map[yr]
        fy      = f"FY {int(yr)-1}-{str(yr)[-2:]}"
        pdf_url = info.get("pdf_url", "")
        size    = info.get("size_mb") or 0
        headline = (info.get("headline") or "Annual Report")[:90]
        size_str = f"{size:.1f} MB" if size else "—"

        rows_html += f"""
        <tr style='border-bottom:1px solid #1E1E1E;'>
          <td style='padding:8px 12px;font-weight:600;color:#D97706;white-space:nowrap;'>{fy}</td>
          <td style='padding:8px 12px;color:#9A9A90;font-size:0.81rem;'>{headline}</td>
          <td style='padding:8px 12px;color:#5A5A52;white-space:nowrap;text-align:center;'>{size_str}</td>
          <td style='padding:8px 12px;text-align:center;'>
            <a href='{pdf_url}' target='_blank'
               style='background:rgba(217,119,6,0.15);color:#D97706;padding:4px 12px;
                      border-radius:6px;font-size:0.76rem;font-weight:600;
                      text-decoration:none;border:1px solid rgba(217,119,6,0.3);'>
              📄 PDF
            </a>
          </td>
        </tr>"""

    html = f"""
    <div style='overflow-x:auto;border:1px solid rgba(255,255,255,0.07);border-radius:10px;
                box-shadow:0 4px 16px rgba(0,0,0,0.3);margin-bottom:1rem;background:#141414;'>
      <table style='width:100%;border-collapse:collapse;font-family:Inter,sans-serif;font-size:0.83rem;'>
        <thead>
          <tr style='background:#1A1A1A;border-bottom:1px solid rgba(217,119,6,0.2);'>
            <th style='padding:9px 12px;text-align:left;color:#7A7A70;font-size:0.72rem;
                       letter-spacing:0.5px;text-transform:uppercase;'>Fiscal Year</th>
            <th style='padding:9px 12px;text-align:left;color:#7A7A70;font-size:0.72rem;
                       letter-spacing:0.5px;text-transform:uppercase;'>Report</th>
            <th style='padding:9px 12px;text-align:center;color:#7A7A70;font-size:0.72rem;
                       letter-spacing:0.5px;text-transform:uppercase;'>Size</th>
            <th style='padding:9px 12px;text-align:center;color:#7A7A70;font-size:0.72rem;
                       letter-spacing:0.5px;text-transform:uppercase;'>Link</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)


def _render_scheme_detail(xl, company_name, scheme_name):
    df = xl.parse(scheme_name, header=None)
    if df.empty or len(df) < 3:
        st.info("No data for this scheme.")
        return

    year_headers = [str(v) for v in df.iloc[1, 1:] if pd.notna(v)]
    n_years = len(year_headers)
    if n_years == 0:
        st.info("No year columns found.")
        return

    # Build field→values lookup from Excel rows
    raw_rows = {}
    for ri in range(2, len(df)):
        label = str(df.iloc[ri, 0]) if pd.notna(df.iloc[ri, 0]) else ""
        if label and label != "nan":
            raw_rows[label] = [df.iloc[ri, c] if c < len(df.columns) else None for c in range(1, 1+n_years)]

    # Scheme header
    st.markdown(
        f"<div style='background:linear-gradient(90deg,#1A1A1A,#2A2A2A);"
        f"border:1px solid rgba(217,119,6,0.25);border-left:4px solid #D97706;"
        f"color:#F0EFE9;padding:0.7rem 1.2rem;border-radius:10px;margin-bottom:1rem;"
        f"font-weight:600;font-size:0.95rem;'>"
        f"📂 {scheme_name}</div>",
        unsafe_allow_html=True,
    )

    # Shorten year labels: "FY 2019-20" → "FY20" to fit all columns on screen
    short_years = []
    for yr in year_headers:
        # "FY 2019-20" → "FY20", "FY 2023-24" → "FY24"
        parts = yr.replace("FY ", "").strip().split("-")
        short_years.append("FY" + (parts[1] if len(parts) > 1 else parts[0][-2:]))

    # Column headers — dark theme
    col_header_html = (
        "<th style='width:260px;min-width:220px;background:#1A1A1A;color:#9A9A90;"
        "padding:8px 12px;text-align:left;font-size:0.8rem;border-right:1px solid #2A2A2A;"
        "letter-spacing:0.3px;'>Data Field</th>"
    )
    for i, (yr, syr) in enumerate(zip(year_headers, short_years)):
        is_latest = (i == n_years - 1)
        bg = "#D97706" if is_latest else "#242424"
        fc = "#0F0F0F"  if is_latest else "#9A9A90"
        col_header_html += (
            f"<th title='{yr}' style='min-width:88px;background:{bg};color:{fc};"
            f"padding:8px 6px;text-align:center;font-weight:700;font-size:0.8rem;'>{syr}</th>"
        )

    table_rows_html = ""
    current_section = None
    PCT_FIELDS = {"dilution_pct", "ownership_pct", "overhang_pct", "burn_rate_pct"}
    n_cols = 1 + n_years

    for field_key, field_label in SCHEME_FIELDS_ORDERED:
        if field_key is None:
            table_rows_html += (
                f"<tr><td colspan='{n_cols}' "
                f"style='height:4px;background:#0F0F0F;padding:0;'></td></tr>"
            )
            continue

        if field_key in SECTION_ROWS:
            section = SECTION_ROWS[field_key]
            if section != current_section:
                current_section = section
                is_pct_section = "%" in section
                sec_bg = "#3D1F00" if is_pct_section else "#0F2A40"
                sec_fg = "#F59E0B" if is_pct_section else "#60A5FA"
                table_rows_html += (
                    f"<tr><td colspan='{n_cols}' style='background:{sec_bg};color:{sec_fg};"
                    f"font-weight:700;font-size:0.72rem;padding:5px 12px;"
                    f"letter-spacing:0.8px;text-transform:uppercase;'>{section}</td></tr>"
                )

        matched_vals = None
        for raw_label, vals in raw_rows.items():
            if field_label and field_label[:25].lower() in raw_label.lower():
                matched_vals = vals
                break

        is_highlight = field_key in HIGHLIGHT_ROWS
        is_pct       = field_key in PCT_FIELDS

        if is_highlight:
            lbl_bg = "#2A1F00"
            lbl_fg = "#F59E0B"
            lbl_fw = "700"
            row_bg = "#1E1800"
        else:
            lbl_bg = "#1A1A1A"
            lbl_fg = "#9A9A90"
            lbl_fw = "400"
            row_bg = "#141414"

        table_rows_html += (
            f"<tr>"
            f"<td style='background:{lbl_bg};color:{lbl_fg};font-weight:{lbl_fw};"
            f"font-size:0.79rem;padding:5px 10px;border-right:1px solid #2A2A2A;"
            f"white-space:normal;line-height:1.3;'>{field_label}</td>"
        )

        for i, yr in enumerate(year_headers):
            val = matched_vals[i] if matched_vals and i < len(matched_vals) else None
            is_latest = (i == n_years - 1)
            latest_border = "border-left:2px solid #D97706;" if is_latest else ""

            if is_pct and val is not None and str(val) not in ("None", "nan", ""):
                try:
                    disp = f"{float(val)*100:.2f}%"
                    fg = "#F87171"
                    fw = "700"
                except Exception:
                    disp, fg, fw = str(val), "#C0C0B8", "400"
            elif val is None or str(val) in ("None", "nan", ""):
                disp, fg, fw = "—", "#3A3A32", "400"
            else:
                fg, fw = "#E8E8E4", "400"
                try:
                    fv = float(val)
                    if fv == int(fv):  disp = f"{int(fv):,}"
                    else:              disp = f"{fv:,.2f}"
                except Exception:
                    disp = str(val)[:20]

            if is_highlight:
                cell_bg = "#1E1800"
                fg = fg if is_pct else ("#F59E0B" if fw == "700" else "#E8E8E4")
            else:
                cell_bg = row_bg

            table_rows_html += (
                f"<td style='background:{cell_bg};color:{fg};font-weight:{fw};"
                f"font-size:0.79rem;padding:5px 6px;text-align:center;{latest_border};"
                f"border-bottom:1px solid #1E1E1E;'>"
                f"{disp}</td>"
            )

        table_rows_html += "</tr>"

    html = f"""
    <div style="overflow-x:auto;border:1px solid rgba(255,255,255,0.07);border-radius:10px;
                box-shadow:0 4px 20px rgba(0,0,0,0.4);background:#141414;">
    <table style="width:100%;border-collapse:collapse;font-family:Inter,Arial,sans-serif;">
    <thead><tr>{col_header_html}</tr></thead>
    <tbody>{table_rows_html}</tbody>
    </table>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    # Mini chart below the table
    st.markdown("<br>", unsafe_allow_html=True)
    _render_scheme_mini_charts(raw_rows, year_headers, scheme_name)


def _render_scheme_mini_charts(raw_rows, year_headers, scheme_name):
    CHART_FIELDS = [
        ("granted", "Options Granted"),
        ("outstanding at the end", "Options Outstanding (End)"),
        ("exercised", "Options Exercised"),
        ("fair value", "Weighted Avg Fair Value (₹)"),
    ]

    chart_data = {}
    for keyword, label in CHART_FIELDS:
        for raw_label, vals in raw_rows.items():
            if keyword.lower() in raw_label.lower():
                ys = []
                for v in vals:
                    try:   ys.append(float(v) if v and str(v).lower() != "nan" else 0)
                    except: ys.append(0)
                if any(y > 0 for y in ys):
                    chart_data[label] = ys
                    break

    if not chart_data:
        return

    n = len(chart_data)
    cols = st.columns(min(n, 2))
    colors = ["#2E75B6", "#70AD47", "#ED7D31", "#FFC000"]

    for i, (label, vals) in enumerate(chart_data.items()):
        with cols[i % 2]:
            fig = go.Figure(go.Bar(
                x=year_headers, y=vals,
                marker_color=[colors[i % len(colors)]]*len(year_headers),
                marker_line_width=0,
            ))
            fig.update_layout(
                title=dict(text=label, font=dict(size=12, color="#C0C0B8")),
                height=220, margin=dict(t=35,b=30,l=40,r=10),
                plot_bgcolor="#141414", paper_bgcolor="#141414",
                xaxis=dict(gridcolor="#2A2A2A", tickfont=dict(size=10, color="#7A7A70")),
                yaxis=dict(gridcolor="#2A2A2A", tickfont=dict(size=10, color="#7A7A70")),
                font=dict(family="Inter", color="#C0C0B8"),
            )
            safe_scheme = scheme_name.replace(' ', '_').replace('/', '_')
            safe_label  = label.replace(' ', '_').replace('(', '').replace(')', '')
            st.plotly_chart(fig, use_container_width=True, key=f"chart_mini_{safe_scheme}_{safe_label}")


def _render_kmp_tab(xl):
    df = xl.parse("KMP ESOPs")
    if df.empty:
        st.info("No KMP data found.")
        return

    st.markdown("### Key Managerial Personnel — Individual Grants")

    # Summary cards
    total_granted = pd.to_numeric(df.get("Options Granted", pd.Series()), errors="coerce").sum()
    total_exercised = pd.to_numeric(df.get("Options Exercised", pd.Series()), errors="coerce").sum()
    unique_kmp = df["KMP Name"].nunique() if "KMP Name" in df.columns else 0

    c1, c2, c3 = st.columns(3)
    for col, (num, lbl) in zip([c1, c2, c3], [
        (fmt_num(total_granted), "Total Granted"),
        (fmt_num(total_exercised), "Total Exercised"),
        (unique_kmp, "Unique KMPs"),
    ]):
        with col:
            st.markdown(
                f'<div class="stat-card"><div class="num" style="font-size:1.4rem;color:#D97706;">{num}</div>'
                f'<div class="lbl">{lbl}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ── TAB 2: Analytics ──────────────────────────────────────────────────────────

def render_analytics_tab():
    companies = get_all_companies()
    if not companies:
        st.info("No companies tracked yet.")
        return

    options = {c["company_name"]: c for c in companies}
    default_name = st.session_state.get("selected_company", companies[0]["company_name"])
    if default_name not in options:
        default_name = companies[0]["company_name"]

    selected_name = st.selectbox(
        "Company", list(options.keys()),
        index=list(options.keys()).index(default_name),
        key="analytics_company",
        label_visibility="collapsed",
    )
    company = options[selected_name]
    bse_code, company_name = company["bse_code"], company["company_name"]
    excel_path = get_company_excel(bse_code, company_name)

    if not excel_path.exists():
        st.warning(f"No extracted data for **{company_name}**.")
        return

    xl = pd.ExcelFile(excel_path)
    scheme_sheets = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]

    st.markdown(f"### {company_name} — ESOP Analytics")

    # Collect all scheme data
    all_data = {}
    for sheet in scheme_sheets:
        df = xl.parse(sheet, header=None)
        if df.empty or len(df) < 3: continue
        years = [str(v) for v in df.iloc[1, 1:] if pd.notna(v)]
        rows_dict = {}
        for ri in range(2, len(df)):
            lbl = str(df.iloc[ri, 0]) if pd.notna(df.iloc[ri, 0]) else ""
            if lbl and lbl != "nan":
                rows_dict[lbl] = [df.iloc[ri, c] for c in range(1, 1+len(years))]
        all_data[sheet] = {"years": years, "rows": rows_dict}

    if not all_data:
        st.info("No data to visualize.")
        return

    # ── Chart 1: Options movement waterfall (per scheme) ─────────────────────
    st.markdown("#### Options Movement Over Years")

    MOVEMENT_KEYWORDS = {
        "Granted":     "Options Granted",
        "Exercised":   "Options Exercised",
        "Lapsed":      "Options Lapsed",
        "Forfeited":   "Options Forfeited",
        "Outstanding": "Options Outstanding (End)",
    }

    scheme_choice = st.selectbox("Scheme", scheme_sheets, key="analytics_scheme")
    data = all_data.get(scheme_choice, {})
    years = data.get("years", [])
    rows  = data.get("rows", {})

    if years and rows:
        movement_data = {}
        for nice, keyword in MOVEMENT_KEYWORDS.items():
            for k, v in rows.items():
                if keyword[:12].lower() in k.lower():
                    vals = []
                    for x in v:
                        try:   vals.append(float(x) if x and str(x).lower() != "nan" else 0)
                        except: vals.append(0)
                    movement_data[nice] = vals
                    break

        if movement_data:
            colors_map = {
                "Granted":     "#2E75B6",
                "Exercised":   "#70AD47",
                "Lapsed":      "#ED7D31",
                "Forfeited":   "#E74C3C",
                "Outstanding": "#FFC000",
            }
            fig = go.Figure()
            for label, vals in movement_data.items():
                fig.add_trace(go.Scatter(
                    x=years, y=vals, name=label,
                    mode="lines+markers",
                    line=dict(color=colors_map.get(label, "#999"), width=2.5),
                    marker=dict(size=7),
                ))
            fig.update_layout(
                plot_bgcolor="#141414", paper_bgcolor="#141414",
                height=380, margin=dict(t=20,b=40,l=60,r=20),
                xaxis=dict(title="Fiscal Year", gridcolor="#2A2A2A", color="#9A9A90"),
                yaxis=dict(title="No. of Options", gridcolor="#2A2A2A", color="#9A9A90"),
                legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                            font=dict(color="#C0C0B8")),
                font=dict(family="Inter", size=11, color="#C0C0B8"),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"chart_movement_{scheme_choice}")

    st.divider()

    # ── Chart 2: % Ownership gauge (latest year) ─────────────────────────────
    st.markdown("#### % Ownership & Dilution (Latest Year)")

    PCT_LABELS = {
        "% in Ownership": "% in Ownership (Options Outstanding / Paid-up Capital)",
        "% Dilution":     "% Dilution (Pool Approved / Paid-up Capital)",
        "% Overhang":     "% Option Overhang (Outstanding / Paid-up Capital)",
        "Burn Rate":      "Burn Rate (Options Granted in FY / Paid-up Capital)",
    }

    gauge_cols = st.columns(len(all_data))
    for col_i, (scheme, s_data) in enumerate(all_data.items()):
        with gauge_cols[col_i % len(gauge_cols)]:
            st.markdown(f"**{scheme}**")
            for nice_name, search_label in PCT_LABELS.items():
                val = None
                for k, v in s_data["rows"].items():
                    if search_label[:22].lower() in k.lower() and v:
                        last_val = v[-1]
                        try:
                            val = float(last_val) * 100
                        except: pass
                        break
                if val is not None:
                    color = "#EF4444" if val > 5 else "#22C55E" if val < 2 else "#F59E0B"
                    st.markdown(
                        f"<div class='metric-bar'>"
                        f"<span class='mname'>{nice_name}</span>"
                        f"<span class='mval' style='color:{color};'>{val:.2f}%</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    st.divider()

    # ── Chart 3: Fair value vs stock price ────────────────────────────────────
    st.markdown("#### Fair Value vs Stock Price")

    fig2 = go.Figure()
    for scheme, s_data in all_data.items():
        yrs = s_data["years"]
        fv_vals, sp_vals = [], []

        for k, v in s_data["rows"].items():
            if "fair value" in k.lower():
                fv_vals = [_safe_float(x) for x in v]
            if "stock price" in k.lower():
                sp_vals = [_safe_float(x) for x in v]

        if fv_vals:
            fig2.add_trace(go.Scatter(
                x=yrs, y=fv_vals, name=f"{scheme} — Fair Value",
                mode="lines+markers", line=dict(width=2, dash="dot"),
            ))
        if sp_vals:
            fig2.add_trace(go.Scatter(
                x=yrs, y=sp_vals, name=f"{scheme} — Stock Price",
                mode="lines+markers", line=dict(width=2),
            ))

    fig2.update_layout(
        plot_bgcolor="#141414", paper_bgcolor="#141414",
        height=320, margin=dict(t=10,b=40,l=60,r=20),
        xaxis=dict(title="Fiscal Year", gridcolor="#2A2A2A", color="#9A9A90"),
        yaxis=dict(title="Price (₹)", gridcolor="#2A2A2A", color="#9A9A90"),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    font=dict(color="#C0C0B8")),
        font=dict(family="Inter", size=11, color="#C0C0B8"),
    )
    st.plotly_chart(fig2, use_container_width=True, key="chart_fairvalue_stockprice")


def _safe_float(v):
    try:   return float(v) if v and str(v).lower() != "nan" else None
    except: return None


# ── Main ──────────────────────────────────────────────────────────────────────

def render_instant_report_tab():
    from tools import generate_instant_report, search_bse_company
    from bse_company_db import total_companies

    # Apply pending code selection before the widget renders
    if "_pending_instant_code" in st.session_state:
        st.session_state["instant_code_input"] = st.session_state.pop("_pending_instant_code")

    st.markdown("""
    <div style='background:#1A1A1A;border:1px solid rgba(217,119,6,0.25);border-left:4px solid #D97706;
                border-radius:12px;padding:1rem 1.4rem;margin-bottom:1.4rem;'>
        <div style='font-size:1rem;font-weight:700;color:#F0EFE9;margin-bottom:0.3rem;'>
            ⚡ Instant ESOP Report
        </div>
        <div style='font-size:0.82rem;color:#7A7A70;'>
            Enter any BSE code → the agent fetches annual reports, extracts ESOP data,
            and hands you a ready-to-download Excel. No database required.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Input row ──────────────────────────────────────────────────────────────
    col_code, col_btn = st.columns([3, 1])
    with col_code:
        bse_input = st.text_input(
            "BSE Security Code",
            placeholder=f"e.g. 532540 · 500209 · 543320  ({total_companies():,} companies supported)",
            label_visibility="collapsed",
            key="instant_code_input",
        )
    with col_btn:
        run = st.button("⚡ Generate Report", use_container_width=True, type="primary")

    # ── Live company preview while typing ─────────────────────────────────────
    if bse_input and bse_input.strip().isdigit():
        r = search_bse_company({"company_name": bse_input.strip()})
        table = r.get("table") or []
        if table:
            c = table[0]
            st.markdown(
                f"<div style='background:#1A1A1A;border:1px solid rgba(255,255,255,0.07);"
                f"border-radius:8px;padding:0.5rem 1rem;margin-bottom:0.6rem;display:flex;"
                f"align-items:center;gap:1rem;'>"
                f"<span style='font-weight:700;color:#D97706;font-size:1rem;'>{c.get('BSE Code','')}</span>"
                f"<span style='color:#E8E8E4;font-size:0.95rem;'>{c.get('Company','')}</span>"
                f"<span style='color:#5A5A52;font-size:0.78rem;'>{c.get('Ticker','')} · {c.get('ISIN','')}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    elif bse_input and not bse_input.strip().isdigit():
        # Name search
        r = search_bse_company({"company_name": bse_input.strip()})
        rows = r.get("table") or []
        if rows:
            st.markdown(f"**{len(rows)} match(es) — click BSE code to use:**")
            for row in rows[:6]:
                code = row.get("BSE Code", "")
                name = row.get("Company", "")
                tick = row.get("Ticker", "")
                if st.button(f"{code}  ·  {name}  ({tick})", key=f"pick_{code}"):
                    st.session_state["_pending_instant_code"] = code
                    st.rerun()

    # ── Run the pipeline ──────────────────────────────────────────────────────
    if run and bse_input and bse_input.strip().isdigit():
        bse_code = bse_input.strip()
        result_key = f"instant_result_{bse_code}"

        progress_box = st.empty()
        steps_so_far = []

        def show(msg: str):
            steps_so_far.append(msg)
            progress_box.markdown("\n\n".join(steps_so_far))

        show(f"**⚡ Starting instant report for BSE {bse_code}...**")

        with st.spinner("Fetching annual reports from BSE…"):
            result = generate_instant_report({"bse_code": bse_code})

        progress_box.empty()

        if result["status"] == "ok":
            excel_path = result.get("excel_path", "")
            company   = result.get("company", "")
            has_esop  = result.get("has_esop", False)
            schemes   = result.get("schemes", [])

            # Status banner
            if has_esop:
                st.markdown(
                    f"<div class='esop-yes'>"
                    f"<span style='font-size:1.05rem;font-weight:700;color:#34D399;'>✅ ESOP PLAN FOUND</span>"
                    f"<span style='color:#6B7280;font-size:0.84rem;margin-left:1rem;'>"
                    f"{company} · {len(schemes)} scheme(s): {', '.join(schemes)}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div class='esop-no'>"
                    f"<span style='font-size:1.05rem;font-weight:700;color:#F87171;'>❌ NO ESOP PLAN FOUND</span>"
                    f"<span style='color:#6B7280;font-size:0.84rem;margin-left:1rem;'>"
                    f"{company} — no stock option data in annual reports</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Progress log
            with st.expander("📋 Processing log", expanded=False):
                st.markdown(result.get("text", ""))

            # Download button
            if excel_path and Path(excel_path).exists():
                with open(excel_path, "rb") as f:
                    data = f.read()
                st.download_button(
                    "⬇️  Download ESOP Excel Report",
                    data=data,
                    file_name=Path(excel_path).name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_instant_{bse_code}",
                    use_container_width=True,
                )

            # Quick preview table if data exists
            if excel_path and Path(excel_path).exists() and has_esop:
                st.markdown("---")
                st.markdown("**Quick Preview — Options Granted by Year**")
                try:
                    xl = pd.ExcelFile(excel_path)
                    scheme_sheets = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]
                    rows = []
                    for sheet in scheme_sheets:
                        df = xl.parse(sheet, header=None)
                        if df.empty or len(df) < 3:
                            continue
                        years = [str(v) for v in df.iloc[1, 1:] if pd.notna(v)]
                        for ri in range(2, len(df)):
                            lbl = str(df.iloc[ri, 0]) if pd.notna(df.iloc[ri, 0]) else ""
                            if "granted" in lbl.lower():
                                for yi, yr in enumerate(years):
                                    val = df.iloc[ri, yi + 1] if yi + 1 < len(df.columns) else None
                                    try:
                                        v = int(float(val)) if pd.notna(val) else None
                                    except Exception:
                                        v = None
                                    rows.append({
                                        "Scheme": sheet,
                                        "Year":   yr,
                                        "Options Granted": f"{v:,}" if v else "—",
                                    })
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                except Exception:
                    pass

        else:
            st.error(result.get("text", "Report generation failed."))

    elif run and bse_input:
        st.warning("Please enter a numeric BSE code (e.g. 532540). To search by name, type the company name above.")

    # ── Recent instant reports (session) ───────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">How it works</div>', unsafe_allow_html=True)
    st.markdown("""
<div style='font-size:0.82rem;color:#7A7A70;line-height:1.8;'>
1. Enter a BSE Security Code (6-digit number from bseindia.com)<br>
2. The agent fetches the last 5 annual reports directly from BSE<br>
3. PDFs are downloaded and ESOP data is extracted using AI<br>
4. A structured Excel report is generated instantly<br>
5. Download and use — no account or database needed
</div>
    """, unsafe_allow_html=True)


def main():
    stats = render_sidebar()
    render_header(stats)

    tab_labels = ["⚡ Instant Report", "💬 Chat Agent", "📊 Data Explorer", "📈 Analytics"]

    tab_instant, tab0, tab1, tab2 = st.tabs(tab_labels)

    with tab_instant:
        render_instant_report_tab()

    with tab0:
        render_chat_tab()

    with tab1:
        render_data_explorer()

    with tab2:
        render_analytics_tab()

    if "active_tab" in st.session_state:
        del st.session_state["active_tab"]


if __name__ == "__main__":
    main()
