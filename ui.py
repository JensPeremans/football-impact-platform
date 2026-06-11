"""
ui.py — Visual design system for the Football Impact Platform.

Centralises the dark-theme CSS injection and a small library of reusable,
presentational components (KPI cards, badges, hero metrics, empty states,
balance bars, category cards, section/page headers). All components render
plain HTML/CSS through ``st.markdown(..., unsafe_allow_html=True)`` so they can
be composed freely. Native Streamlit widgets (sliders, dataframes, uploaders)
are styled globally via the CSS in :func:`inject_global_css`.

The single club accent colour (``--primary``) is injected at runtime so club
branding flows automatically into buttons, active nav, hero numbers, KPI chips,
progress bars and chart accents.
"""

import html as _html

import streamlit as st

import metrics as M

DEFAULT_PRIMARY = "#10B981"

# Category palette — order matches M.CATEGORIES, shared with charts (utils.py).
CATEGORY_COLORS = {
    "Passing": "#3B82F6",
    "Ball Progression": "#06B6D4",
    "Chance Creation": "#8B5CF6",
    "Goalscoring": "#10B981",
    "Defending": "#F59E0B",
    "Physical": "#EC4899",
    # Keeper legacy category (shown only for goalkeepers).
    "Goalkeeping": "#A855F7",
}

# Position-group palette — pitch & rankings.
POSITION_GROUP_COLORS = {
    "goalkeeper": "#F59E0B",
    "defender": "#3B82F6",
    "midfielder": "#10B981",
    "attacker": "#EF4444",
}


def category_color(name):
    return CATEGORY_COLORS.get(name, "#64748B")


def _esc(text):
    return _html.escape(str(text)) if text is not None else ""


# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
def inject_global_css(primary_hex=DEFAULT_PRIMARY):
    """Inject the global dark theme + component CSS. Call once per rerun.

    ``primary_hex`` is the club accent colour; it overrides ``--primary`` so all
    accent-driven components follow the club branding.
    """
    primary = primary_hex if primary_hex else DEFAULT_PRIMARY
    css = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    :root {
      --bg:#0F172A; --surface:#1E293B; --surface-2:#273449; --surface-3:#334155;
      --sidebar-bg:#0B1220; --border:#334155; --border-subtle:#1F2A3C;
      --text:#F1F5F9; --text-muted:#94A3B8; --text-subtle:#64748B; --text-on-accent:#0B1220;
      --primary:%PRIMARY%; --primary-soft:%PRIMARY%24;
      --accent-blue:#3B82F6; --accent-violet:#8B5CF6;
      --success:#22C55E; --warning:#F59E0B; --danger:#EF4444; --info:#38BDF8;
      --radius-card:14px; --radius-ctrl:10px;
    }

    html, body, [class*="css"] {
      font-family:'Inter','Segoe UI',system-ui,-apple-system,sans-serif;
      color-scheme:dark;
    }

    /* App surfaces */
    [data-testid="stAppViewContainer"], .main { background:var(--bg); }
    .block-container { max-width:1400px; padding-top:2.2rem; padding-bottom:3rem; }
    [data-testid="stHeader"] { background:rgba(0,0,0,0); }

    /* Sidebar */
    [data-testid="stSidebar"] { background:var(--sidebar-bg); border-right:1px solid var(--border-subtle); }
    [data-testid="stSidebar"] * { color:var(--text); }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.25rem; }

    .sidebar-brand {
      display:flex; align-items:center; gap:.55rem; padding:.35rem .15rem 1rem .15rem;
    }
    .sidebar-brand-logo { font-size:1.5rem; }
    .sidebar-brand-text { font-weight:800; font-size:1.15rem; letter-spacing:-0.01em; }

    .nav-group-label {
      text-transform:uppercase; font-size:.68rem; font-weight:700; letter-spacing:.08em;
      color:var(--text-muted); margin:.85rem .2rem .3rem .2rem;
    }

    /* Sidebar nav buttons: left aligned, compact */
    [data-testid="stSidebar"] .stButton > button {
      text-align:left; justify-content:flex-start; font-weight:600; padding:.45rem .7rem;
      background:transparent; border:1px solid transparent;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
      background:var(--surface-2); border-color:var(--border-subtle);
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
      background:var(--primary-soft); color:var(--text); border:1px solid var(--primary);
    }

    .sidebar-user {
      padding:.6rem .15rem .2rem .15rem; line-height:1.55;
    }
    .sidebar-user-name { font-weight:700; }
    .sidebar-user-meta { font-size:.82rem; color:var(--text-muted); }

    /* Typography */
    h1 { font-weight:700; font-size:1.85rem; letter-spacing:-0.01em; }
    h2 { font-weight:700; font-size:1.35rem; }
    h3 { font-weight:600; font-size:1.1rem; }
    p, .stMarkdown, label, span { color:var(--text); }

    /* Buttons */
    .stButton > button {
      border-radius:var(--radius-ctrl); font-weight:600; border:1px solid var(--border);
      background:var(--surface-2); color:var(--text); transition:all 140ms ease; padding:.4rem 1.1rem;
    }
    .stButton > button:hover { border-color:var(--primary); color:var(--text); background:var(--surface-3); }
    .stButton > button[kind="primary"], [data-testid="baseButton-primary"] {
      background:var(--primary); color:var(--text-on-accent); border:none;
    }
    .stButton > button[kind="primary"]:hover { filter:brightness(1.08); color:var(--text-on-accent); }
    .stButton > button:disabled { opacity:.5; cursor:not-allowed; }
    .stDownloadButton > button { border-radius:var(--radius-ctrl); }

    /* Inputs */
    .stTextInput input, .stNumberInput input, .stDateInput input,
    [data-baseweb="select"] > div, .stTextArea textarea {
      background:var(--surface-3) !important; border-radius:var(--radius-ctrl) !important;
      border:1px solid var(--border) !important; color:var(--text) !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus { border-color:var(--primary) !important; }

    /* Metric blocks → card look */
    [data-testid="stMetric"] {
      background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card);
      padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,.3);
    }
    [data-testid="stMetricLabel"] { color:var(--text-muted); font-weight:500; }
    [data-testid="stMetricValue"] { font-variant-numeric:tabular-nums; font-weight:800; }

    /* Bordered containers → cards */
    [data-testid="stVerticalBlockBorderWrapper"] {
      background:var(--surface); border:1px solid var(--border) !important;
      border-radius:var(--radius-card); box-shadow:0 1px 3px rgba(0,0,0,.3);
    }

    /* Dataframe */
    [data-testid="stDataFrame"] { border:1px solid var(--border); border-radius:var(--radius-card); }

    /* Tabs */
    .stTabs [data-baseweb="tab"] { color:var(--text-muted); }
    .stTabs [aria-selected="true"] { color:var(--primary); }

    /* Sliders use the primary accent */
    .stSlider [data-baseweb="slider"] [role="slider"] { background:var(--primary) !important; }

    /* Alerts a touch darker */
    [data-testid="stAlert"] { border-radius:var(--radius-ctrl); }

    /* Progress bar */
    .stProgress > div > div > div > div { background:var(--primary); }

    /* ---- Custom component classes ---- */
    .kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
      gap:16px; margin:8px 0 8px; }
    .kpi {
      background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card);
      padding:18px 18px 16px; display:flex; flex-direction:column; gap:8px;
      box-shadow:0 1px 3px rgba(0,0,0,.3); transition:transform 160ms ease, border-color 160ms ease;
    }
    .kpi:hover { transform:translateY(-2px); border-color:var(--primary); }
    .kpi__chip { width:38px; height:38px; border-radius:10px; display:flex; align-items:center;
      justify-content:center; font-size:20px; background:var(--primary-soft); }
    .kpi__value { font-size:30px; font-weight:800; line-height:1; font-variant-numeric:tabular-nums; color:var(--text); }
    .kpi__label { font-size:11px; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.06em; }
    .kpi__sub { font-size:12px; color:var(--text-subtle); }
    .kpi__bar { height:6px; border-radius:999px; background:var(--surface-3); overflow:hidden; margin-top:2px; }
    .kpi__bar > span { display:block; height:100%; background:var(--primary); }

    .card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card);
      padding:22px 24px; box-shadow:0 1px 3px rgba(0,0,0,.3); margin-bottom:8px; }
    .card--accent { border-left:4px solid var(--primary); }

    .hero { background:linear-gradient(135deg,var(--surface),var(--surface-2));
      border:1px solid var(--border); border-radius:var(--radius-card); padding:26px 28px;
      display:flex; flex-direction:column; gap:6px; }
    .hero__row { display:flex; align-items:center; gap:18px; flex-wrap:wrap; }
    .hero__avatar { width:64px; height:64px; border-radius:50%; background:var(--primary-soft);
      color:var(--primary); display:flex; align-items:center; justify-content:center;
      font-weight:800; font-size:24px; border:2px solid var(--primary); }
    .hero__name { font-size:22px; font-weight:700; }
    .hero__score { font-size:48px; font-weight:800; line-height:1; color:var(--primary);
      font-variant-numeric:tabular-nums; }
    .hero__score-label { font-size:11px; font-weight:600; color:var(--text-muted);
      text-transform:uppercase; letter-spacing:.06em; }
    .hero__secondary { display:flex; gap:26px; flex-wrap:wrap; margin-top:10px; }
    .hero__sec-val { font-size:18px; font-weight:700; font-variant-numeric:tabular-nums; }
    .hero__sec-lab { font-size:11px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em; }

    .badge { display:inline-flex; align-items:center; gap:4px; padding:2px 10px; border-radius:999px;
      font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.03em; }
    .badge--success { background:rgba(34,197,94,.15); color:#4ADE80; }
    .badge--warning { background:rgba(245,158,11,.15); color:#FBBF24; }
    .badge--danger  { background:rgba(239,68,68,.15); color:#F87171; }
    .badge--info    { background:rgba(56,189,248,.15); color:#38BDF8; }
    .badge--neutral { background:var(--surface-3); color:var(--text-muted); }
    .badge--primary { background:var(--primary-soft); color:var(--primary); }

    .empty { text-align:center; padding:42px 24px; background:var(--surface);
      border:1px dashed var(--border); border-radius:var(--radius-card); }
    .empty__icon { font-size:42px; margin-bottom:8px; }
    .empty__title { font-size:18px; font-weight:700; margin-bottom:6px; }
    .empty__body { color:var(--text-muted); font-size:14px; max-width:520px; margin:0 auto; }

    .cat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
    .cat-card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:14px 16px; }
    .cat-card__top { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
    .cat-card__chip { width:12px; height:12px; border-radius:3px; }
    .cat-card__name { font-size:12px; font-weight:600; color:var(--text-muted); }
    .cat-card__val { font-size:22px; font-weight:800; font-variant-numeric:tabular-nums; }
    .cat-card__bar { height:5px; border-radius:999px; background:var(--surface-3); overflow:hidden; margin-top:8px; }
    .cat-card__bar > span { display:block; height:100%; }

    .balance { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card);
      padding:16px 18px; }
    .balance__track { position:relative; height:12px; border-radius:999px; background:var(--surface-3);
      overflow:visible; margin:10px 0 6px; }
    .balance__fill { height:100%; border-radius:999px; }
    .balance__target { position:absolute; top:-3px; width:2px; height:18px; background:var(--text); opacity:.7; }
    .balance__legend { display:flex; justify-content:space-between; font-size:11px; color:var(--text-subtle); }

    .pagehead { margin-bottom:14px; }
    .pagehead__crumb { font-size:12px; color:var(--text-subtle); text-transform:uppercase; letter-spacing:.06em; }
    .pagehead__title { font-size:28px; font-weight:700; letter-spacing:-0.01em; margin:2px 0; }
    .pagehead__sub { color:var(--text-muted); font-size:14px; }

    .navgroup { font-size:11px; font-weight:700; color:var(--text-subtle); text-transform:uppercase;
      letter-spacing:.08em; margin:14px 0 4px 4px; }

    .quickrow { display:flex; gap:12px; flex-wrap:wrap; }

    @media (max-width: 768px) {
      .hero__score { font-size:36px; }
      .kpi__value { font-size:24px; }
    }
    </style>
    """
    css = css.replace("%PRIMARY%", primary)
    st.markdown(css, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def page_header(title, subtitle=None, crumb=None):
    html = "<div class='pagehead'>"
    if crumb:
        html += f"<div class='pagehead__crumb'>{_esc(crumb)}</div>"
    html += f"<div class='pagehead__title'>{_esc(title)}</div>"
    if subtitle:
        html += f"<div class='pagehead__sub'>{_esc(subtitle)}</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def badge(text, variant="neutral"):
    """Return a badge HTML string (compose inline into other markdown)."""
    return f"<span class='badge badge--{variant}'>{_esc(text)}</span>"


def render_badge(text, variant="neutral"):
    st.markdown(badge(text, variant), unsafe_allow_html=True)


def kpi_cards(items):
    """Render a responsive grid of KPI cards.

    ``items``: list of dicts with keys: icon, label, value, sub (optional),
    progress (optional float 0..1).
    """
    html = "<div class='kpi-grid'>"
    for it in items:
        html += "<div class='kpi'>"
        html += f"<div class='kpi__chip'>{_esc(it.get('icon',''))}</div>"
        html += f"<div class='kpi__value'>{_esc(it.get('value',''))}</div>"
        html += f"<div class='kpi__label'>{_esc(it.get('label',''))}</div>"
        if it.get("sub"):
            html += f"<div class='kpi__sub'>{_esc(it['sub'])}</div>"
        prog = it.get("progress")
        if prog is not None:
            pct = max(0, min(100, int(prog * 100)))
            html += f"<div class='kpi__bar'><span style='width:{pct}%'></span></div>"
        html += "</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def hero_metric(name, score, score_label="Impact Score", secondary=None,
                position=None, position_variant="primary", avatar_initials=None):
    """Big centred-ish hero block with the player's Impact Score prominent.

    ``secondary``: list of (label, value) tuples shown beneath the score.
    """
    html = "<div class='hero'><div class='hero__row'>"
    if avatar_initials:
        html += f"<div class='hero__avatar'>{_esc(avatar_initials)}</div>"
    html += "<div style='flex:1'>"
    html += f"<div class='hero__name'>{_esc(name)}"
    if position:
        html += " " + badge(position, position_variant)
    html += "</div>"
    if secondary:
        html += "<div class='hero__secondary'>"
        for lab, val in secondary:
            html += (f"<div><div class='hero__sec-val'>{_esc(val)}</div>"
                     f"<div class='hero__sec-lab'>{_esc(lab)}</div></div>")
        html += "</div>"
    html += "</div>"  # flex:1
    html += ("<div style='text-align:center'>"
             f"<div class='hero__score'>{_esc(score)}</div>"
             f"<div class='hero__score-label'>{_esc(score_label)}</div></div>")
    html += "</div></div>"
    st.markdown(html, unsafe_allow_html=True)


def empty_state(icon, title, body, container=None):
    """Render a centred empty-state card. Optional CTA via the returned area.

    For a CTA button, place an ``st.button`` after calling this (Streamlit
    widgets can't live inside the HTML block).
    """
    target = container if container is not None else st
    target.markdown(
        f"<div class='empty'><div class='empty__icon'>{_esc(icon)}</div>"
        f"<div class='empty__title'>{_esc(title)}</div>"
        f"<div class='empty__body'>{_esc(body)}</div></div>",
        unsafe_allow_html=True,
    )


def balance_bar(total, lo=35.0, hi=40.0, target=37.5, lo_axis=30.0, hi_axis=45.0):
    """Profile Balance indicator: progress within a [lo_axis, hi_axis] window
    with a target marker and green/red validity colouring."""
    ok = lo <= total <= hi
    color = "var(--success)" if ok else "var(--danger)"
    span = hi_axis - lo_axis
    fill_pct = max(0, min(100, (total - lo_axis) / span * 100))
    target_pct = max(0, min(100, (target - lo_axis) / span * 100))
    lo_pct = (lo - lo_axis) / span * 100
    hi_pct = (hi - lo_axis) / span * 100
    valid_zone = (f"position:absolute;top:0;height:100%;left:{lo_pct:.1f}%;"
                  f"width:{hi_pct - lo_pct:.1f}%;background:rgba(34,197,94,.12);"
                  "border-radius:999px;")
    html = (
        "<div class='balance'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center'>"
        f"<span style='font-weight:600'>Profile Balance</span>"
        f"<span style='font-size:22px;font-weight:800;color:{color};"
        f"font-variant-numeric:tabular-nums'>{total:.1f}</span></div>"
        "<div class='balance__track'>"
        f"<div style='{valid_zone}'></div>"
        f"<div class='balance__fill' style='width:{fill_pct:.1f}%;background:{color}'></div>"
        f"<div class='balance__target' style='left:{target_pct:.1f}%'></div>"
        "</div>"
        f"<div class='balance__legend'><span>{lo_axis:.0f}</span>"
        f"<span>doel {target:.1f} · geldig {lo:.0f}–{hi:.0f}</span>"
        f"<span>{hi_axis:.0f}</span></div>"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def category_cards(values, means=None):
    """Render a grid of per-category cards.

    ``values``: dict {category: value}. ``means``: optional dict for a reference
    bar (e.g. team mean). Cards follow CATEGORY_COLORS and M.CATEGORIES order.
    """
    cats = [c for c in M.CATEGORIES if c in values] or list(values.keys())
    vmax = max([abs(v) for v in values.values()] + [1.0])
    html = "<div class='cat-grid'>"
    for c in cats:
        v = values.get(c, 0.0)
        color = category_color(c)
        bar_pct = max(0, min(100, abs(v) / vmax * 100))
        sub = ""
        if means and c in means:
            sub = (f"<div style='font-size:11px;color:var(--text-subtle);margin-top:4px'>"
                   f"gem. {means[c]:.1f}</div>")
        html += (
            "<div class='cat-card'>"
            f"<div class='cat-card__top'><span class='cat-card__chip' "
            f"style='background:{color}'></span>"
            f"<span class='cat-card__name'>{_esc(c)}</span></div>"
            f"<div class='cat-card__val'>{v:.1f}</div>"
            f"<div class='cat-card__bar'><span style='width:{bar_pct:.0f}%;"
            f"background:{color}'></span></div>{sub}</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def initials(name):
    parts = [p for p in str(name).split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()
