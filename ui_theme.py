"""Shared look-and-feel for the Streamlit app: CSS, brand header, and small HTML components."""

from __future__ import annotations
from html import escape
from pathlib import Path

import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Montserrat:wght@400;500;600;700&display=swap');

/* Palette taken from nesterahealth.com: warm sand/cream surfaces, navy ink, steel-blue accent */
:root {
  --nh-primary: #4B6E88;       /* steel */
  --nh-primary-dark: #223241;  /* navy */
  --nh-ink: #223241;
  --nh-muted: #3A5064;
  --nh-line: #DCCAA9;
  --nh-bg: #F0E6D2;
  --nh-surface: #F3EBDD;       /* cream */
  --nh-sky: #C2D7E6;
  --nh-glow: #41D6FF;
  --nh-green: #2F4F3D;  --nh-green-bg: #DDE6D3;
  --nh-amber: #5C4A32;  --nh-amber-bg: #F0DDB0;
  --nh-red:   #8F3A30;  --nh-red-bg:   #EFCFC4;
  --nh-gray:  #3A5064;  --nh-gray-bg:  #E2D6C0;
  --nh-serif: "Merriweather", Georgia, serif;
  --nh-sans: "Montserrat", system-ui, -apple-system, "Segoe UI", sans-serif;
}

/* Hide default Streamlit chrome */
#MainMenu, footer, [data-testid="stDecoration"],
[data-testid="stToolbarActions"], [data-testid="stMainMenu"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; }

.block-container { max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem; }
html, body, [class*="css"], .stApp { font-family: var(--nh-sans); }
h1, h2, h3, .nh-hero h1 { color: var(--nh-ink); font-family: var(--nh-serif) !important; font-weight: 700; letter-spacing: -0.01em; }
.stApp { background: var(--nh-bg); }

[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, label, textarea, input,
[data-testid="stCaptionContainer"], button, [data-baseweb="tab"] { font-family: var(--nh-sans) !important; }

/* Brand bar */
.nh-brand { display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.4rem; }
.nh-logo { width: 44px; height: 40px; flex: none; }
.nh-logo svg { width: 100%; height: 100%; display: block; }
.nh-brand-name { font-size: 1.35rem; font-weight: 600; color: var(--nh-ink); line-height: 1.1; letter-spacing: -0.02em; }
.nh-brand-sub  { font-size: 0.74rem; color: var(--nh-muted); margin-top: 0.15rem; }

/* Page hero */
.nh-hero { margin: 1.1rem 0 1.4rem; padding-bottom: 1.1rem; border-bottom: 1px solid var(--nh-line); }
.nh-hero h1 { font-size: 1.85rem; line-height: 1.25; margin: 0 0 0.35rem; padding: 0; }
.nh-hero p  { color: var(--nh-muted); margin: 0; font-size: 0.92rem; }

/* Cards, KPI tiles */
.nh-card {
  background: var(--nh-surface); border: 1px solid var(--nh-line); border-radius: 12px;
  padding: 1rem 1.2rem;
}
.nh-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.9rem; margin-bottom: 1.4rem; }
.nh-kpi-label { font-size: 0.72rem; color: var(--nh-muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
.nh-kpi-value { font-size: 2rem; font-weight: 600; color: var(--nh-ink); line-height: 1.2; }
.nh-kpi.amber .nh-kpi-value { color: var(--nh-amber); }
.nh-kpi.red   .nh-kpi-value { color: var(--nh-red); }
.nh-kpi.green .nh-kpi-value { color: var(--nh-green); }

/* Status chips (pill style, like the site's "Live" / "Connected" pills) */
.nh-chip {
  display: inline-block; padding: 0.18rem 0.7rem; border-radius: 999px;
  font-size: 0.74rem; font-weight: 600; white-space: nowrap;
}
.nh-chip.green { color: var(--nh-green); background: var(--nh-green-bg); }
.nh-chip.amber { color: var(--nh-amber); background: var(--nh-amber-bg); }
.nh-chip.red   { color: var(--nh-red);   background: var(--nh-red-bg); }
.nh-chip.gray  { color: var(--nh-gray);  background: var(--nh-gray-bg); }

/* Patient roster table */
.nh-table-wrap { overflow-x: auto; border: 1px solid var(--nh-line); border-radius: 12px; }
.nh-table { width: 100%; border-collapse: collapse; background: var(--nh-surface); }
.nh-table th { text-align: left; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
               color: var(--nh-muted); background: var(--nh-bg); padding: 0.65rem 1rem; white-space: nowrap; }
.nh-table td { padding: 0.8rem 1rem; border-top: 1px solid var(--nh-line); color: var(--nh-ink); font-size: 0.9rem; }
.nh-table td .nh-sub { color: var(--nh-muted); font-size: 0.78rem; }

/* Detail header */
.nh-detail { display: grid; grid-template-columns: 1.2fr 1.6fr 1fr; gap: 1rem; }
.nh-detail .nh-kpi-value { font-size: 1.05rem; font-weight: 600; }

/* Emergency notice */
.nh-emergency {
  background: var(--nh-red-bg); color: var(--nh-red); border: 1px solid #D9A99B; border-radius: 12px;
  padding: 0.7rem 1rem; font-size: 0.85rem; margin: 0.4rem 0 1.2rem;
}

/* Chat */
[data-testid="stChatMessage"] {
  background: var(--nh-surface); border: 1px solid var(--nh-line); border-radius: 12px;
  padding: 0.9rem 1.1rem; margin-bottom: 0.7rem;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background: #E6EEF3; border-color: var(--nh-sky);
}
[data-testid="stChatMessage"] p { font-size: 0.98rem; line-height: 1.6; }

/* Buttons: steel-blue primary, rounded like the site's "Book a demo" CTA */
.stButton > button, .stDownloadButton > button {
  border-radius: 999px; font-weight: 600; border: 1px solid var(--nh-primary);
}
.stButton > button[kind="primary"] { background: var(--nh-primary); color: #fff; }
.stButton > button[kind="primary"]:hover { background: var(--nh-primary-dark); border-color: var(--nh-primary-dark); }
.stButton > button[kind="secondary"] { background: transparent; color: var(--nh-ink); }
.stButton > button[kind="secondary"]:hover { background: var(--nh-sky); color: var(--nh-ink); }

/* Make the "reopen sidebar" button easy to spot */
[data-testid="stExpandSidebarButton"] {
  background: var(--nh-primary) !important; border-radius: 10px; width: 2.4rem; height: 2.4rem;
}
[data-testid="stExpandSidebarButton"] span { color: #fff !important; }

/* Sidebar */
[data-testid="stSidebar"] { background: var(--nh-surface); border-right: 1px solid var(--nh-line); }

/* Progress bar track */
[data-testid="stProgress"] [role="progressbar"] { background: var(--nh-line); }

/* Tabs */
button[data-baseweb="tab"] { font-weight: 600; }

/* Narrow screens */
@media (max-width: 720px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 3.5rem; }
  .nh-kpis, .nh-detail { grid-template-columns: 1fr; }
  .nh-hero h1 { font-size: 1.4rem; }
  .nh-kpi-value { font-size: 1.6rem; }
}
</style>
"""

_MARK_PATH = Path(__file__).parent / "assets" / "nestera-mark.svg"


def _logo_svg() -> str:
    """Nestera mark from the sponsor site, recolored navy; falls back to nothing if the asset is missing."""
    try:
        svg = _MARK_PATH.read_text()
    except OSError:
        return ""
    return svg.replace('fill="#41d6ff"', 'fill="#223241"', 1).replace(' width="347" height="310"', "", 1)


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def brand_header(compact: bool = False) -> None:
    st.markdown(
        f'<div class="nh-brand"><div class="nh-logo">{_logo_svg()}</div>'
        '<div><div class="nh-brand-name">nestera</div>'
        '<div class="nh-brand-sub">Hospital-at-Home Daily Check-In</div></div></div>',
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str = "") -> None:
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="nh-hero"><h1>{escape(title)}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def chip(text: str, tone: str = "gray") -> str:
    return f'<span class="nh-chip {tone}">{escape(text)}</span>'


def action_tone(action: str) -> str:
    return {"Routine review": "green", "Schedule visit": "amber", "Escalate": "red"}.get(action, "gray")


def kpi_row(items: list[tuple[str, object, str]]) -> None:
    """items: (label, value, tone) where tone is '', 'green', 'amber' or 'red'."""
    cells = "".join(
        f'<div class="nh-card nh-kpi {tone}"><div class="nh-kpi-label">{escape(label)}</div>'
        f'<div class="nh-kpi-value">{escape(str(value))}</div></div>'
        for label, value, tone in items
    )
    st.markdown(f'<div class="nh-kpis">{cells}</div>', unsafe_allow_html=True)


def detail_cards(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="nh-card nh-kpi"><div class="nh-kpi-label">{escape(label)}</div>'
        f'<div class="nh-kpi-value">{escape(value)}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="nh-detail">{cells}</div>', unsafe_allow_html=True)


def roster_table(rows: list[dict]) -> None:
    """rows: name, diagnosis, status_html, action_html."""
    body = "".join(
        f'<tr><td><b>{escape(r["name"])}</b><div class="nh-sub">{escape(r["id"])}</div></td>'
        f'<td>{escape(r["diagnosis"])}</td><td>{r["status_html"]}</td><td>{r["action_html"]}</td></tr>'
        for r in rows
    )
    st.markdown(
        '<div class="nh-table-wrap"><table class="nh-table"><thead><tr><th>Patient</th><th>Primary diagnosis</th>'
        f'<th>Today\'s check-in</th><th>Recommended action</th></tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def emergency_notice(contact: str) -> None:
    st.markdown(
        '<div class="nh-emergency"><b>Emergency?</b> If you are in danger or having a medical '
        f'emergency, call <b>911</b>. For other concerns call your care team: {escape(contact)}.</div>',
        unsafe_allow_html=True,
    )
