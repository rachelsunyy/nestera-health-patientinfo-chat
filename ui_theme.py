"""Shared look-and-feel for the Streamlit app: CSS, brand header, and small HTML components."""

from __future__ import annotations
from html import escape

import streamlit as st

_CSS = """
<style>
:root {
  --nh-primary: #0E7490;
  --nh-primary-dark: #0B4F63;
  --nh-ink: #14303B;
  --nh-muted: #5B7380;
  --nh-line: #DCE7EC;
  --nh-surface: #F3F8FA;
  --nh-green: #167A4A;  --nh-green-bg: #E3F5EB;
  --nh-amber: #A15C07;  --nh-amber-bg: #FDF0D5;
  --nh-red:   #B42318;  --nh-red-bg:   #FDE7E4;
  --nh-gray:  #52646E;  --nh-gray-bg:  #E8EEF1;
}

/* Hide default Streamlit chrome */
#MainMenu, footer, [data-testid="stDecoration"],
[data-testid="stToolbarActions"], [data-testid="stMainMenu"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; }

.block-container { max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem; }
html, body, [class*="css"] { font-family: -apple-system, "Segoe UI", Inter, Roboto, sans-serif; }
h1, h2, h3 { color: var(--nh-ink); letter-spacing: -0.01em; }

/* Brand bar */
.nh-brand { display: flex; align-items: center; gap: 0.85rem; margin-bottom: 0.4rem; }
.nh-logo {
  width: 42px; height: 42px; border-radius: 12px; flex: none;
  background: linear-gradient(135deg, var(--nh-primary), var(--nh-primary-dark));
  display: flex; align-items: center; justify-content: center;
}
.nh-brand-name { font-size: 1.05rem; font-weight: 700; color: var(--nh-ink); line-height: 1.1; }
.nh-brand-sub  { font-size: 0.78rem; color: var(--nh-muted); }

/* Page hero */
.nh-hero { margin: 1.1rem 0 1.4rem; padding-bottom: 1.1rem; border-bottom: 1px solid var(--nh-line); }
.nh-hero h1 { font-size: 2rem; margin: 0 0 0.25rem; padding: 0; }
.nh-hero p  { color: var(--nh-muted); margin: 0; font-size: 0.95rem; }

/* Cards, KPI tiles */
.nh-card {
  background: #fff; border: 1px solid var(--nh-line); border-radius: 14px;
  padding: 1rem 1.2rem; box-shadow: 0 1px 2px rgba(20, 48, 59, 0.04);
}
.nh-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.9rem; margin-bottom: 1.4rem; }
.nh-kpi-label { font-size: 0.78rem; color: var(--nh-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.nh-kpi-value { font-size: 2rem; font-weight: 700; color: var(--nh-ink); line-height: 1.2; }
.nh-kpi.amber .nh-kpi-value { color: var(--nh-amber); }
.nh-kpi.red   .nh-kpi-value { color: var(--nh-red); }
.nh-kpi.green .nh-kpi-value { color: var(--nh-green); }

/* Status chips */
.nh-chip {
  display: inline-block; padding: 0.18rem 0.65rem; border-radius: 999px;
  font-size: 0.78rem; font-weight: 600; white-space: nowrap;
}
.nh-chip.green { color: var(--nh-green); background: var(--nh-green-bg); }
.nh-chip.amber { color: var(--nh-amber); background: var(--nh-amber-bg); }
.nh-chip.red   { color: var(--nh-red);   background: var(--nh-red-bg); }
.nh-chip.gray  { color: var(--nh-gray);  background: var(--nh-gray-bg); }

/* Patient roster table */
.nh-table { width: 100%; border-collapse: collapse; background: #fff;
            border: 1px solid var(--nh-line); border-radius: 14px; overflow: hidden; }
.nh-table th { text-align: left; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
               color: var(--nh-muted); background: var(--nh-surface); padding: 0.65rem 1rem; }
.nh-table td { padding: 0.8rem 1rem; border-top: 1px solid var(--nh-line); color: var(--nh-ink); font-size: 0.93rem; }
.nh-table td .nh-sub { color: var(--nh-muted); font-size: 0.8rem; }

/* Detail header */
.nh-detail { display: grid; grid-template-columns: 1.2fr 1.6fr 1fr; gap: 1rem; }
.nh-detail .nh-kpi-value { font-size: 1.15rem; font-weight: 650; }

/* Emergency notice */
.nh-emergency {
  background: var(--nh-red-bg); color: var(--nh-red); border-radius: 12px;
  padding: 0.7rem 1rem; font-size: 0.88rem; margin: 0.4rem 0 1.2rem;
}

/* Chat */
[data-testid="stChatMessage"] {
  background: #fff; border: 1px solid var(--nh-line); border-radius: 14px;
  padding: 0.9rem 1.1rem; margin-bottom: 0.7rem;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background: var(--nh-surface); border-color: #CFE3EA;
}
[data-testid="stChatMessage"] p { font-size: 1.02rem; line-height: 1.55; }

/* Make the "reopen sidebar" button easy to spot */
[data-testid="stExpandSidebarButton"] {
  background: var(--nh-primary) !important; border-radius: 10px; width: 2.4rem; height: 2.4rem;
  box-shadow: 0 1px 4px rgba(20, 48, 59, 0.25);
}
[data-testid="stExpandSidebarButton"] span { color: #fff !important; }

/* Sidebar */
[data-testid="stSidebar"] { background: var(--nh-surface); border-right: 1px solid var(--nh-line); }

/* Tabs */
button[data-baseweb="tab"] { font-weight: 600; }
</style>
"""

_LOGO_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" '
    'stroke-width="2.6" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>'
)


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def brand_header(compact: bool = False) -> None:
    st.markdown(
        f'<div class="nh-brand"><div class="nh-logo">{_LOGO_SVG}</div>'
        '<div><div class="nh-brand-name">Nestera Health</div>'
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
        '<table class="nh-table"><thead><tr><th>Patient</th><th>Primary diagnosis</th>'
        f'<th>Today\'s check-in</th><th>Recommended action</th></tr></thead><tbody>{body}</tbody></table>',
        unsafe_allow_html=True,
    )


def emergency_notice(contact: str) -> None:
    st.markdown(
        '<div class="nh-emergency"><b>Emergency?</b> If you are in danger or having a medical '
        f'emergency, call <b>911</b>. For other concerns call your care team: {escape(contact)}.</div>',
        unsafe_allow_html=True,
    )
