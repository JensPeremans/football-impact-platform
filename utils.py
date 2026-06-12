"""
utils.py — Helper functions shared across the app (formatting, charts).
"""

import html as _html

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import metrics as M

# Category palette — order aligned with M.CATEGORIES so radar axes & bars share
# one colour-per-category mapping across the whole app (see ui.CATEGORY_COLORS).
PALETTE = ["#3B82F6", "#06B6D4", "#8B5CF6", "#10B981", "#F59E0B", "#EC4899"]

# Position-group palette (pitch & rankings).
POSITION_GROUP_COLORS = {
    "goalkeeper": "#F59E0B",
    "defender": "#3B82F6",
    "midfielder": "#10B981",
    "attacker": "#EF4444",
}

# Chart text/grid tokens (dark theme).
_GRID = "rgba(51,65,85,0.4)"
_GRID_POLAR = "rgba(51,65,85,0.55)"
_AXIS = "#475569"
_TEXT = "#CBD5E1"
_TEXT_MUTED = "#94A3B8"
_TITLE = "#F1F5F9"


def _apply_dark_layout(fig, primary=None):
    """Apply the shared dark Plotly theme to any figure.

    ``primary`` (optional) sets the club accent as the first colourway entry so
    single-series charts adopt the club colour.
    """
    colorway = list(PALETTE)
    if primary:
        colorway = [primary] + [c for c in PALETTE if c.lower() != primary.lower()]
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color=_TEXT, size=12),
        title=dict(font=dict(color=_TITLE, size=16)),
        legend=dict(bgcolor="rgba(30,41,59,0.6)", bordercolor="#334155",
                    borderwidth=1, font=dict(color=_TEXT)),
        colorway=colorway,
    )
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_AXIS, linecolor=_AXIS,
                     tickfont=dict(color=_TEXT_MUTED))
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_AXIS, linecolor=_AXIS,
                     tickfont=dict(color=_TEXT_MUTED))
    # Polar (radar) styling — only affects figures that have a polar subplot.
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(gridcolor=_GRID_POLAR, tickfont=dict(color="#64748B"),
                            linecolor=_AXIS),
            angularaxis=dict(gridcolor=_GRID_POLAR, tickfont=dict(color=_TEXT)),
        )
    )
    return fig


def fmt_score(match):
    """Return 'H : A' score string for a match row."""
    h = match["home_score"] if match["home_score"] is not None else "-"
    a = match["away_score"] if match["away_score"] is not None else "-"
    return f"{h} : {a}"


def match_label(match):
    """Human readable match label for dropdowns."""
    return (f"{match['match_date']} — {match['team_name']} vs {match['opponent']} "
            f"({fmt_score(match)})")


def result_for_home(match):
    """W / D / L from the home team's perspective."""
    h, a = match["home_score"], match["away_score"]
    if h is None or a is None:
        return "—"
    if h > a:
        return "W"
    if h < a:
        return "L"
    return "D"


def radar_chart(category_values_list, names, title="Category Impact", primary=None):
    """Build a radar chart.

    category_values_list: list of dict {category: value} (one per series).
    names: list of series names.
    primary: optional club accent for single-series fill.
    """
    cats = M.CATEGORIES
    fig = go.Figure()
    single = len(names) == 1
    for i, (cv, name) in enumerate(zip(category_values_list, names)):
        values = [cv.get(c, 0) for c in cats]
        values += values[:1]
        line_color = (primary if (single and primary) else PALETTE[i % len(PALETTE)])
        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=cats + cats[:1],
            fill="toself",
            name=name,
            line=dict(color=line_color),
            opacity=0.6,
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True)),
        showlegend=len(names) > 1,
        title=title,
        margin=dict(l=40, r=40, t=60, b=40),
        height=450,
    )
    return _apply_dark_layout(fig, primary)


def metric_radar_chart(values_list, names, axis_labels, title="Metric detail",
                       range_max=100, hover_raw=None):
    """Build a radar chart over arbitrary metric axes (MVP-B drill-down).

    Unlike ``radar_chart`` (which is hard-wired to the 6 impact CATEGORIES),
    this helper plots any list of axes — used to show the individual metrics
    inside one category on a normalised 0–100 scale.

    Args:
        values_list: list of value-lists (one per series), each aligned to
                     ``axis_labels`` (normalised 0–100 values).
        names:       list of series names (one per value-list).
        axis_labels: the metric labels used as the radar axes.
        title:       chart title.
        range_max:   fixed radial range so charts stay comparable (default 100).
        hover_raw:   optional list (per series) of raw/unnormalised values to
                     show in the hover tooltip alongside the normalised value.
    """
    axis_labels = list(axis_labels)
    fig = go.Figure()
    for i, (vals, name) in enumerate(zip(values_list, names)):
        vals = list(vals)
        r = vals + vals[:1]
        theta = axis_labels + axis_labels[:1]
        customdata = None
        hovertemplate = ("<b>%{theta}</b><br>Score: %{r:.0f}/100<extra>"
                         + str(name) + "</extra>")
        if hover_raw is not None and i < len(hover_raw) and hover_raw[i] is not None:
            raw = list(hover_raw[i])
            customdata = raw + raw[:1]
            hovertemplate = ("<b>%{theta}</b><br>Score: %{r:.0f}/100"
                             "<br>Gemiddelde: %{customdata:.2f}<extra>"
                             + str(name) + "</extra>")
        fig.add_trace(go.Scatterpolar(
            r=r, theta=theta, fill="toself", name=name,
            line=dict(color=PALETTE[i % len(PALETTE)]), opacity=0.6,
            customdata=customdata, hovertemplate=hovertemplate,
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, range_max])),
        showlegend=len(names) > 1,
        title=title,
        margin=dict(l=40, r=40, t=60, b=40),
        height=450,
    )
    return _apply_dark_layout(fig)


def rolling_line_chart(df, x, y, title, windows=(3, 5), primary=None):
    """Line chart of a raw time series plus N-match rolling averages.

    Keeps the raw match-by-match values as the primary (solid) line and overlays
    one smoothed line per window in ``windows`` (dashed/dotted) to cut noise on
    the Evolution Dashboard. The rolling means use ``min_periods=1`` so the early
    points still render when a player has fewer matches than the window.

    Args:
        df:      DataFrame with the data (will be sorted on ``x``).
        x, y:    column names for the x-axis and the value to smooth.
        title:   chart title.
        windows: iterable of rolling-window sizes (default 3 and 5 matches).
    """
    d = df.sort_values(x)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d[x], y=d[y], mode="lines+markers", name="Raw data",
        line=dict(color=primary or PALETTE[0], width=2),
    ))
    dash_styles = ["dash", "dot", "dashdot"]
    for i, w in enumerate(windows):
        roll = d[y].rolling(window=w, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=d[x], y=roll, mode="lines", name=f"{w}-match average",
            line=dict(color=PALETTE[(i + 1) % len(PALETTE)], width=2,
                      dash=dash_styles[i % len(dash_styles)]),
        ))
    fig.update_layout(title=title, margin=dict(l=20, r=20, t=50, b=20),
                      height=380, hovermode="x unified")
    return _apply_dark_layout(fig, primary)


def line_chart(df, x, y, title, color=None, markers=True, primary=None):
    fig = px.line(df, x=x, y=y, title=title, color=color, markers=markers,
                  color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=380,
                      hovermode="x unified")
    return _apply_dark_layout(fig, primary)


def stacked_area(df, x, y, color, title):
    fig = px.area(df, x=x, y=y, color=color, title=title,
                  color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=420,
                      hovermode="x unified")
    return _apply_dark_layout(fig)


def bar_comparison(df, x, y, color, title, barmode="group"):
    fig = px.bar(df, x=x, y=y, color=color, barmode=barmode, title=title,
                 color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=420)
    return _apply_dark_layout(fig)


def _numeric_columns(df, columns):
    """Return only the columns that exist in ``df`` AND can be treated as numeric.

    A column qualifies when it is already a numeric dtype, or when its values can
    be coerced to numbers (e.g. an object column that still holds numbers).
    Columns that do not exist or that are genuinely non-numeric (text, mixed
    placeholders like "—") are skipped so the styler never calls ``max()``/``min()``
    on incomparable values.
    """
    valid = []
    for c in columns:
        if c not in df.columns:
            continue  # non-existent column -> skip
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            valid.append(c)
            continue
        # Object/mixed column: keep it only if it contains at least one real number.
        coerced = pd.to_numeric(s, errors="coerce")
        if coerced.notna().any():
            valid.append(c)
    return valid


def highlight_max(df, columns, color="rgba(16,185,129,0.22)"):
    """Return a pandas Styler that highlights the max value per given column.

    Only numeric columns are highlighted. Non-existent and non-numeric (text)
    columns are silently skipped so no error is raised on text data.
    """
    def _hl(s):
        numeric = pd.to_numeric(s, errors="coerce")
        mx = numeric.max(skipna=True)
        if pd.isna(mx):
            return ["" for _ in s]
        is_max = numeric == mx
        return [f"background-color: {color}; font-weight:600; color:#F1F5F9" if bool(v) else "" for v in is_max]
    sty = df.style
    valid = _numeric_columns(df, columns)
    if valid:
        sty = sty.apply(_hl, subset=valid)
    return sty


def highlight_min(df, columns, color="rgba(239,68,68,0.20)"):
    """Return a pandas Styler that highlights the min value per given column.

    Only numeric columns are highlighted. Non-existent and non-numeric (text)
    columns are silently skipped so no error is raised on text data.
    """
    def _hl(s):
        numeric = pd.to_numeric(s, errors="coerce")
        mn = numeric.min(skipna=True)
        if pd.isna(mn):
            return ["" for _ in s]
        is_min = numeric == mn
        return [f"background-color: {color}; font-weight:600; color:#F1F5F9" if bool(v) else "" for v in is_min]
    sty = df.style
    valid = _numeric_columns(df, columns)
    if valid:
        sty = sty.apply(_hl, subset=valid)
    return sty


# ---------------------------------------------------------------------------
# Football pitch visualisation (Sprint 2, Phase 4)
# ---------------------------------------------------------------------------
def _impact_color(value, vmax):
    """Green-scale colour for an impact value (higher = more saturated green)."""
    if vmax <= 0:
        frac = 0.0
    else:
        frac = max(0.0, min(1.0, value / vmax))
    # interpolate light -> strong green
    r = int(220 - frac * 180)
    g = int(235 - frac * 70)
    b = int(220 - frac * 180)
    return f"rgb({r},{g},{b})"


def _tooltip_rows(categories):
    cats = ["Passing", "Progression", "Chance Creation",
            "Finishing", "Defending", "Goalkeeping"]
    short = {"Passing": "Passing", "Progression": "Progression",
             "Chance Creation": "Chance Creation", "Finishing": "Finishing",
             "Defending": "Defending", "Goalkeeping": "Goalkeeping"}
    rows = ""
    for c in cats:
        v = categories.get(c, 0.0)
        rows += (f"<div class='ttrow'><span>{short[c]} Impact</span>"
                 f"<b>{v:.1f}</b></div>")
    return rows


def pitch_html(starters, bench, came_on, height=760):
    """Build an interactive football-pitch HTML block.

    starters: list of dicts {name, position, coord:(x,y), total_impact, categories}
    bench:    list of dicts {name, position, total_impact}
    came_on:  list of dicts {name, position, came_on_as, total_impact, categories}

    Starters are placed at fixed pitch coordinates (no overlap); bench and
    substitutes are listed on the right sideline. Hovering a player shows a
    tooltip with the 6 category impacts.
    """
    all_imp = [s.get("total_impact", 0) or 0 for s in starters] or [0]
    vmax = max(all_imp + [1])

    markers = ""
    for s in starters:
        x, y = s["coord"]
        left = x
        top = 100 - y  # invert so attackers sit near the top
        color = _impact_color(s.get("total_impact", 0) or 0, vmax)
        raw_name = s["name"] or ""
        name = _html.escape(raw_name)
        short_name = name if len(raw_name) <= 16 else _html.escape(raw_name.split()[-1])
        pos = _html.escape(str(s["position"] or ""))
        imp = s.get("total_impact", 0) or 0
        tip = _tooltip_rows(s.get("categories", {}))
        markers += f"""
        <div class="marker" style="left:{left}%;top:{top}%;">
          <div class="dot" style="background:{color};">{imp:.0f}</div>
          <div class="plabel">{short_name}<br><span class="ppos">{pos}</span></div>
          <div class="tooltip">
            <div class="ttname">{name}</div>
            <div class="ttpos">{pos} · Impact Score {imp:.1f}</div>
            {tip}
          </div>
        </div>"""

    def _side_item(p, sub=False):
        imp = p.get("total_impact", 0) or 0
        extra = ""
        p_name = _html.escape(str(p['name'] or ""))
        p_pos = _html.escape(str(p.get('position', '') or ""))
        if sub and p.get("came_on_as"):
            extra = f"<div class='subas'>Came on as: {_html.escape(str(p['came_on_as']))}</div>"
        tip = _tooltip_rows(p.get("categories", {})) if p.get("categories") else ""
        tt = (f"<div class='tooltip side'><div class='ttname'>{p_name}</div>"
              f"<div class='ttpos'>{p_pos} · Impact Score {imp:.1f}</div>{tip}</div>") if tip else ""
        return (f"<div class='sideitem'><div class='sidemain'>"
                f"<span class='sidename'>{p_name}</span>"
                f"<span class='sideimp'>{imp:.1f}</span></div>"
                f"<div class='sidepos'>{p_pos}</div>{extra}{tt}</div>")

    bench_html = "".join(_side_item(b) for b in bench) or "<div class='empty'>None</div>"
    came_html = "".join(_side_item(c, sub=True) for c in came_on) or "<div class='empty'>None</div>"

    html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ box-sizing:border-box; font-family:-apple-system,Segoe UI,Roboto,sans-serif; }}
.wrap {{ display:flex; gap:14px; align-items:stretch; }}
.pitch {{
  position:relative; width:64%; height:700px;
  background:linear-gradient(#2e7d32,#388e3c); border-radius:10px;
  box-shadow:inset 0 0 0 3px rgba(255,255,255,.7); overflow:visible;
}}
.stripes {{ position:absolute; inset:0; border-radius:10px; overflow:hidden; }}
.stripes div {{ position:absolute; left:0; right:0; height:10%; }}
.stripes div:nth-child(odd) {{ background:rgba(255,255,255,.05); }}
.lines {{ position:absolute; inset:0; }}
.line {{ position:absolute; border:2px solid rgba(255,255,255,.75); }}
.center-circle {{ left:35%; top:40%; width:30%; height:20%; border-radius:50%; }}
.center-line {{ left:0; right:0; top:50%; height:0; border-top:2px solid rgba(255,255,255,.75); }}
.box-top {{ left:25%; top:0; width:50%; height:16%; border-top:none; }}
.box-bottom {{ left:25%; bottom:0; width:50%; height:16%; border-bottom:none; }}
.marker {{ position:absolute; transform:translate(-50%,-50%); text-align:center; z-index:2; }}
.marker:hover {{ z-index:99; }}
.dot {{ width:34px; height:34px; line-height:34px; border-radius:50%;
  margin:0 auto; font-weight:700; color:#0b3d0b; font-size:12px;
  border:2px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,.4); cursor:pointer; }}
.plabel {{ color:#fff; font-size:10px; font-weight:600; margin-top:2px;
  text-shadow:0 1px 2px rgba(0,0,0,.7); white-space:nowrap; }}
.ppos {{ font-size:8.5px; opacity:.85; font-weight:500; }}
.tooltip {{ display:none; position:absolute; left:50%; top:115%;
  transform:translateX(-50%); background:#111; color:#fff; padding:8px 10px;
  border-radius:8px; width:185px; text-align:left; font-size:11px; z-index:100;
  box-shadow:0 4px 14px rgba(0,0,0,.5); }}
.marker:hover .tooltip {{ display:block; }}
.ttname {{ font-weight:700; font-size:12px; }}
.ttpos {{ opacity:.8; margin-bottom:5px; font-size:10px; }}
.ttrow {{ display:flex; justify-content:space-between; padding:1px 0;
  border-top:1px solid rgba(255,255,255,.12); }}
.side {{ width:55%; }}
.sidebar {{ width:36%; display:flex; flex-direction:column; gap:10px; }}
.panel {{ background:#1E293B; border:1px solid #334155; border-radius:10px;
  padding:10px; }}
.panel h4 {{ margin:0 0 8px; font-size:13px; color:#F1F5F9; }}
.sideitem {{ position:relative; background:#273449; border:1px solid #334155;
  border-radius:7px; padding:6px 8px; margin-bottom:6px; cursor:default; }}
.sideitem:hover .tooltip {{ display:block; left:0; transform:none; top:100%; }}
.sidemain {{ display:flex; justify-content:space-between; align-items:center; }}
.sidename {{ font-weight:600; font-size:12px; color:#F1F5F9; }}
.sideimp {{ font-weight:700; font-size:12px; color:#34D399; }}
.sidepos {{ font-size:10px; color:#94A3B8; }}
.subas {{ font-size:10px; color:#FBBF24; font-weight:600; margin-top:2px; }}
.empty {{ color:#64748B; font-size:12px; font-style:italic; }}
</style></head><body>
<div class="wrap">
  <div class="pitch">
    <div class="stripes">{''.join('<div style="top:%d%%"></div>' % (i*10) for i in range(10))}</div>
    <div class="lines">
      <div class="line center-line"></div>
      <div class="line center-circle"></div>
      <div class="line box-top"></div>
      <div class="line box-bottom"></div>
    </div>
    {markers}
  </div>
  <div class="sidebar">
    <div class="panel"><h4>🪑 Bench</h4>{bench_html}</div>
    <div class="panel"><h4>🔁 Came On</h4>{came_html}</div>
  </div>
</div>
</body></html>"""
    return html, height
