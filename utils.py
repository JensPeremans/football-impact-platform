"""
utils.py — Helper functions shared across the app (formatting, charts).
"""

import plotly.graph_objects as go
import plotly.express as px

import metrics as M

# A clean, coach-friendly colour palette
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


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


def radar_chart(category_values_list, names, title="Category Impact"):
    """Build a radar chart.

    category_values_list: list of dict {category: value} (one per series).
    names: list of series names.
    """
    cats = M.CATEGORIES
    fig = go.Figure()
    for i, (cv, name) in enumerate(zip(category_values_list, names)):
        values = [cv.get(c, 0) for c in cats]
        values += values[:1]
        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=cats + cats[:1],
            fill="toself",
            name=name,
            line=dict(color=PALETTE[i % len(PALETTE)]),
            opacity=0.65,
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True)),
        showlegend=len(names) > 1,
        title=title,
        margin=dict(l=40, r=40, t=60, b=40),
        height=450,
    )
    return fig


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
    return fig


def rolling_line_chart(df, x, y, title, windows=(3, 5)):
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
        line=dict(color=PALETTE[0], width=2),
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
    return fig


def line_chart(df, x, y, title, color=None, markers=True):
    fig = px.line(df, x=x, y=y, title=title, color=color, markers=markers,
                  color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=380,
                      hovermode="x unified")
    return fig


def stacked_area(df, x, y, color, title):
    fig = px.area(df, x=x, y=y, color=color, title=title,
                  color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=420,
                      hovermode="x unified")
    return fig


def bar_comparison(df, x, y, color, title, barmode="group"):
    fig = px.bar(df, x=x, y=y, color=color, barmode=barmode, title=title,
                 color_discrete_sequence=PALETTE)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=420)
    return fig


def highlight_max(df, columns, color="#c6f6d5"):
    """Return a pandas Styler that highlights the max value per given column."""
    def _hl(s):
        is_max = s == s.max()
        return [f"background-color: {color}; font-weight:600" if v else "" for v in is_max]
    sty = df.style
    valid = [c for c in columns if c in df.columns]
    if valid:
        sty = sty.apply(_hl, subset=valid)
    return sty


def highlight_min(df, columns, color="#fed7d7"):
    def _hl(s):
        is_min = s == s.min()
        return [f"background-color: {color}; font-weight:600" if v else "" for v in is_min]
    sty = df.style
    valid = [c for c in columns if c in df.columns]
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
        name = s["name"]
        short_name = name if len(name) <= 16 else name.split()[-1]
        pos = s["position"]
        imp = s.get("total_impact", 0) or 0
        tip = _tooltip_rows(s.get("categories", {}))
        markers += f"""
        <div class="marker" style="left:{left}%;top:{top}%;">
          <div class="dot" style="background:{color};">{imp:.0f}</div>
          <div class="plabel">{short_name}<br><span class="ppos">{pos}</span></div>
          <div class="tooltip">
            <div class="ttname">{name}</div>
            <div class="ttpos">{pos} · Total Impact {imp:.1f}</div>
            {tip}
          </div>
        </div>"""

    def _side_item(p, sub=False):
        imp = p.get("total_impact", 0) or 0
        extra = ""
        if sub and p.get("came_on_as"):
            extra = f"<div class='subas'>Came on as: {p['came_on_as']}</div>"
        tip = _tooltip_rows(p.get("categories", {})) if p.get("categories") else ""
        tt = (f"<div class='tooltip side'><div class='ttname'>{p['name']}</div>"
              f"<div class='ttpos'>{p.get('position','')} · Total Impact {imp:.1f}</div>{tip}</div>") if tip else ""
        return (f"<div class='sideitem'><div class='sidemain'>"
                f"<span class='sidename'>{p['name']}</span>"
                f"<span class='sideimp'>{imp:.1f}</span></div>"
                f"<div class='sidepos'>{p.get('position','')}</div>{extra}{tt}</div>")

    bench_html = "".join(_side_item(b) for b in bench) or "<div class='empty'>None</div>"
    came_html = "".join(_side_item(c, sub=True) for c in came_on) or "<div class='empty'>None</div>"

    html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ box-sizing:border-box; font-family:-apple-system,Segoe UI,Roboto,sans-serif; }}
.wrap {{ display:flex; gap:14px; align-items:stretch; }}
.pitch {{
  position:relative; width:64%; padding-bottom:88%;
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
.panel {{ background:#f4f6f8; border:1px solid #e0e4e8; border-radius:10px;
  padding:10px; }}
.panel h4 {{ margin:0 0 8px; font-size:13px; color:#2e3b4e; }}
.sideitem {{ position:relative; background:#fff; border:1px solid #e2e8f0;
  border-radius:7px; padding:6px 8px; margin-bottom:6px; cursor:default; }}
.sideitem:hover .tooltip {{ display:block; left:0; transform:none; top:100%; }}
.sidemain {{ display:flex; justify-content:space-between; align-items:center; }}
.sidename {{ font-weight:600; font-size:12px; color:#1a202c; }}
.sideimp {{ font-weight:700; font-size:12px; color:#2e7d32; }}
.sidepos {{ font-size:10px; color:#718096; }}
.subas {{ font-size:10px; color:#b7791f; font-weight:600; margin-top:2px; }}
.empty {{ color:#a0aec0; font-size:12px; font-style:italic; }}
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
