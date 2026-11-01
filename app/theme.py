"""Eastern Bank visual identity for the Streamlit app.

Palette taken from the Eastern Bank brand: Midnight Blue #003366,
Cerulean #009CDE, Blaze Orange #FF5F00 on white. Orange is reserved for
things that need a human decision, so the eye learns that orange means
"you have work here".
"""

from __future__ import annotations

import streamlit as st

MIDNIGHT = "#003366"
CERULEAN = "#009CDE"
ORANGE = "#FF5F00"
INK = "#13263B"
SLATE = "#5A6B7D"
MIST = "#EEF4F9"
LINE = "#D5E2EC"
GREEN = "#00875A"
AMBER = "#B8860B"
RED = "#C0392B"
WHITE = "#FFFFFF"

SEQUENCE = [MIDNIGHT, CERULEAN, ORANGE, "#4C7FA8", "#7FC4E8", "#A8651F", "#8299AD"]

CSS = f"""
<style>
  .block-container {{ padding-top: 1.2rem; max-width: 1500px; }}

  /* ---- masthead ---- */
  .eb-head {{
    background: linear-gradient(97deg, {MIDNIGHT} 0%, #014a8f 58%, {CERULEAN} 100%);
    color: {WHITE}; border-radius: 10px;
    padding: 18px 24px 16px 24px; margin-bottom: 14px;
  }}
  .eb-head h1 {{
    font-size: 1.5rem; font-weight: 700; margin: 0 0 3px 0; letter-spacing: -.2px;
  }}
  .eb-head p {{ margin: 0; font-size: .86rem; opacity: .9; }}
  .eb-head .eb-rule {{
    height: 3px; width: 54px; background: {ORANGE};
    border-radius: 2px; margin: 9px 0 10px 0;
  }}

  /* ---- KPI tiles ---- */
  .eb-kpi {{
    background: {WHITE}; border: 1px solid {LINE}; border-top: 3px solid {CERULEAN};
    border-radius: 8px; padding: 13px 15px 12px 15px; height: 100%;
  }}
  .eb-kpi.accent {{ border-top-color: {ORANGE}; }}
  .eb-kpi.deep {{ border-top-color: {MIDNIGHT}; }}
  .eb-kpi .lab {{
    font-size: .68rem; text-transform: uppercase; letter-spacing: .07em;
    color: {SLATE}; font-weight: 700; margin-bottom: 5px;
  }}
  .eb-kpi .val {{
    font-size: 1.62rem; font-weight: 700; color: {MIDNIGHT}; line-height: 1.1;
  }}
  .eb-kpi .sub {{ font-size: .73rem; color: {SLATE}; margin-top: 4px; }}

  /* ---- section headings ---- */
  .eb-sec {{
    font-size: 1.03rem; font-weight: 700; color: {MIDNIGHT};
    border-left: 4px solid {CERULEAN}; padding-left: 10px;
    margin: 22px 0 4px 0;
  }}
  .eb-sub {{ font-size: .8rem; color: {SLATE}; margin: 0 0 10px 14px; }}

  /* ---- record comparison cards ---- */
  .eb-rec {{
    background: {MIST}; border: 1px solid {LINE}; border-radius: 8px;
    padding: 12px 14px; font-size: .84rem;
  }}
  .eb-rec .sys {{
    display: inline-block; background: {MIDNIGHT}; color: {WHITE};
    font-size: .64rem; font-weight: 700; letter-spacing: .06em;
    padding: 2px 8px; border-radius: 10px; margin-bottom: 8px;
  }}
  .eb-rec table {{ width: 100%; border-collapse: collapse; }}
  .eb-rec td {{ padding: 3px 0; vertical-align: top; }}
  .eb-rec td.k {{
    color: {SLATE}; width: 38%; font-size: .72rem;
    text-transform: uppercase; letter-spacing: .04em; font-weight: 600;
  }}
  .eb-rec td.v {{ color: {INK}; font-weight: 600; font-family: ui-monospace, monospace; }}
  .eb-rec td.v.diff {{ color: {ORANGE}; }}
  .eb-rec td.v.same {{ color: {GREEN}; }}
  .eb-rec td.v.none {{ color: #9AAAB8; font-weight: 400; font-style: italic; }}

  /* ---- chips ---- */
  .eb-chip {{
    display: inline-block; font-size: .7rem; font-weight: 700;
    padding: 3px 9px; border-radius: 11px; margin: 0 5px 5px 0;
    border: 1px solid transparent;
  }}
  .chip-exact {{ background: #E3F5EC; color: {GREEN}; border-color: #BFE6D3; }}
  .chip-strong {{ background: #E4F3FC; color: #0A6FA5; border-color: #BFE0F3; }}
  .chip-partial {{ background: #FFF4E6; color: #9A5B00; border-color: #FFDDB3; }}
  .chip-conflict {{ background: #FDEBE9; color: {RED}; border-color: #F6C9C4; }}
  .chip-missing {{ background: #F1F4F7; color: {SLATE}; border-color: {LINE}; }}

  /* ---- misc ---- */
  .eb-band {{
    border-radius: 7px; padding: 10px 14px; font-size: .84rem;
    border-left: 4px solid {CERULEAN}; background: {MIST}; color: {INK};
  }}
  .eb-band.warn {{ border-left-color: {ORANGE}; background: #FFF6EF; }}
  .eb-band.ok {{ border-left-color: {GREEN}; background: #EFF8F3; }}
  .eb-foot {{
    color: {SLATE}; font-size: .72rem; border-top: 1px solid {LINE};
    margin-top: 26px; padding-top: 10px;
  }}
  div[data-testid="stMetricValue"] {{ color: {MIDNIGHT}; }}
  .stTabs [data-baseweb="tab-list"] {{ gap: 3px; border-bottom: 1px solid {LINE}; }}
  .stTabs [data-baseweb="tab"] {{
    font-weight: 600; font-size: .86rem; color: {SLATE};
    padding: 9px 15px; border-radius: 7px 7px 0 0;
  }}
  .stTabs [aria-selected="true"] {{ color: {MIDNIGHT}; background: {MIST}; }}
  .stButton button {{ font-weight: 600; border-radius: 6px; }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def masthead(title: str, subtitle: str) -> None:
    st.markdown(
        f"""<div class="eb-head">
              <h1>{title}</h1>
              <div class="eb-rule"></div>
              <p>{subtitle}</p>
            </div>""",
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, sub: str = "", style: str = "") -> str:
    classes = f"eb-kpi {style}".strip()
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="{classes}"><div class="lab">{label}</div>'
        f'<div class="val">{value}</div>{sub_html}</div>'
    )


def section(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="eb-sec">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="eb-sub">{subtitle}</div>', unsafe_allow_html=True)


def band(text: str, kind: str = "") -> None:
    st.markdown(f'<div class="eb-band {kind}">{text}</div>', unsafe_allow_html=True)


def chip(text: str) -> str:
    kind = "missing"
    for suffix, name in (("_EXACT", "exact"), ("_STRONG", "strong"),
                         ("_PARTIAL", "partial"), ("_CONFLICT", "conflict")):
        if text.endswith(suffix):
            kind = name
            break
    return f'<span class="eb-chip chip-{kind}">{text.replace("_", " ").title()}</span>'


def style_plot(fig, height: int = 300, legend: bool = False):
    """One place for chart chrome, so every chart in the app matches."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=28, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12, color=INK),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        colorway=SEQUENCE,
        hoverlabel=dict(bgcolor=WHITE, bordercolor=LINE, font_size=12),
    )
    fig.update_xaxes(showgrid=False, linecolor=LINE, ticks="outside",
                     tickcolor=LINE, title_font_size=11)
    fig.update_yaxes(showgrid=True, gridcolor=MIST, zeroline=False,
                     linecolor=LINE, title_font_size=11)
    return fig
