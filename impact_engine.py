"""
impact_engine.py — Impact score calculation logic.

Given a player's raw stat values ({metric_key: value}) and a profile's weights
({metric_key: weight}), computes:

  * Total Impact         = Σ (value × weight × sign) over weighted metrics
  * Impact per 90        = (Total Impact / minutes_played) × 90
  * Impact per Action    = Total Impact / total_actions
  * Offensive Efficiency = offensive impact / offensive actions
  * Defensive Efficiency = defensive impact / defensive actions
  * Category impacts      = per-category breakdown (6 categories)

Context metrics (minutes, total actions, splits) never contribute to impact
because their default weight is 0 (and they are excluded explicitly too).
"""

import metrics as M


def compute_impact(stats, weights):
    """Compute the full impact breakdown for one player-match.

    Args:
        stats:   {metric_key: value}
        weights: {metric_key: weight}
    Returns dict with totals, per-90, per-action, efficiencies, category map.
    """
    stats = stats or {}
    weights = weights or {}

    total_impact = 0.0
    offensive_impact = 0.0
    defensive_impact = 0.0
    category_impact = {c: 0.0 for c in M.CATEGORIES}
    contributions = {}  # metric_key -> contribution (for transparency)

    for key, meta in M.METRIC_BY_KEY.items():
        if key in M.CONTEXT_KEYS:
            continue
        value = stats.get(key)
        weight = weights.get(key, 0.0)
        if value is None or weight == 0:
            continue
        contrib = value * weight * meta["sign"]
        contributions[key] = contrib
        total_impact += contrib
        category_impact[meta["category"]] += contrib
        if meta["action_group"] == M.OFFENSIVE:
            offensive_impact += contrib
        elif meta["action_group"] == M.DEFENSIVE:
            defensive_impact += contrib

    minutes = stats.get("minutes_played") or 0.0
    total_actions = stats.get("total_actions") or 0.0
    off_actions = stats.get("offensive_actions") or 0.0
    def_actions = stats.get("defensive_actions") or 0.0

    impact_per_90 = (total_impact / minutes * 90.0) if minutes > 0 else 0.0
    impact_per_action = (total_impact / total_actions) if total_actions > 0 else 0.0
    off_eff = (offensive_impact / off_actions) if off_actions > 0 else 0.0
    def_eff = (defensive_impact / def_actions) if def_actions > 0 else 0.0

    return {
        "total_impact": round(total_impact, 1),
        "impact_per_90": round(impact_per_90, 1),
        "impact_per_action": round(impact_per_action, 1),
        "offensive_impact": round(offensive_impact, 1),
        "defensive_impact": round(defensive_impact, 1),
        "offensive_efficiency": round(off_eff, 1),
        "defensive_efficiency": round(def_eff, 1),
        "category_impact": {c: round(v, 1) for c, v in category_impact.items()},
        "contributions": contributions,
        "minutes_played": minutes,
        "total_actions": total_actions,
    }


def compute_player_match_rows(player_stats_list, weights):
    """Apply compute_impact to a list of player-stat dicts (from DB helpers).

    Each element must have 'stats' key. Returns list with an added 'impact' key.
    """
    out = []
    for row in player_stats_list:
        impact = compute_impact(row.get("stats", {}), weights)
        new = dict(row)
        new["impact"] = impact
        out.append(new)
    return out


# ---------------------------------------------------------------------------
# Position-aware scoring (Sprint 2)
# ---------------------------------------------------------------------------
def effective_position(row):
    """Return the position a player actually played in this match.

    A substitute ("Came On") may have entered in a different role than their
    nominal position; in that case the 'came_on_as' position is used for scoring.
    """
    status = (row.get("status") or "Starter")
    if status == M.STATUS_CAME_ON and row.get("came_on_as"):
        return row["came_on_as"]
    return row.get("position")


def weights_for_position(importances_map, position):
    """Build {metric_key: weight} for a position from a profile importances map.

    importances_map: {position: {category: importance(0-10)}}.
    Falls back to framework defaults for unknown positions.
    """
    importances_map = importances_map or {}
    cat_imps = importances_map.get(position)
    if cat_imps is None:
        defaults = M.default_position_category_importances()
        cat_imps = defaults.get(position, {c: 5.0 for c in M.CATEGORIES})
    return M.build_position_metric_weights(cat_imps)


def compute_player_match_rows_positional(player_stats_list, importances_map):
    """Score each player-match with weights derived from its played position.

    Each row gets an 'impact' key and an 'effective_position' key. Bench players
    (no minutes / no stats) still score 0 naturally.
    """
    out = []
    for row in player_stats_list:
        pos = effective_position(row)
        weights = weights_for_position(importances_map, pos)
        impact = compute_impact(row.get("stats", {}), weights)
        new = dict(row)
        new["impact"] = impact
        new["effective_position"] = pos
        out.append(new)
    return out


def aggregate_team_impact(player_rows):
    """Sum impacts across players for team-level totals."""
    agg = {
        "total_impact": 0.0, "offensive_impact": 0.0, "defensive_impact": 0.0,
        "category_impact": {c: 0.0 for c in M.CATEGORIES},
    }
    for r in player_rows:
        imp = r["impact"]
        agg["total_impact"] += imp["total_impact"]
        agg["offensive_impact"] += imp["offensive_impact"]
        agg["defensive_impact"] += imp["defensive_impact"]
        for c in M.CATEGORIES:
            agg["category_impact"][c] += imp["category_impact"][c]
    agg["total_impact"] = round(agg["total_impact"], 1)
    agg["offensive_impact"] = round(agg["offensive_impact"], 1)
    agg["defensive_impact"] = round(agg["defensive_impact"], 1)
    agg["category_impact"] = {c: round(v, 1) for c, v in agg["category_impact"].items()}
    return agg


def _summarize_rows(rows, position_key="position"):
    """Build career-level aggregates from already-scored rows.

    `position_key` chooses which field is treated as "the position played"
    when picking the usual position ('position' or 'effective_position').
    """
    n = len(rows)
    if n == 0:
        return {"matches": 0}

    total_minutes = sum((r.get("minutes_played") or 0) for r in rows)
    total_impact = sum(r["impact"]["total_impact"] for r in rows)
    total_goals = sum((r["stats"].get("goals") or 0) for r in rows)
    total_assists = sum((r["stats"].get("assists") or 0) for r in rows)

    cat_avg = {c: 0.0 for c in M.CATEGORIES}
    for r in rows:
        for c in M.CATEGORIES:
            cat_avg[c] += r["impact"]["category_impact"][c]
    cat_avg = {c: round(v / n, 1) for c, v in cat_avg.items()}

    # Avg Impact/90 = (total impact across all matches) / (total minutes) * 90.
    avg_per_90 = round((total_impact / total_minutes) * 90.0, 1) if total_minutes > 0 else 0.0

    positions = [r.get(position_key) for r in rows if r.get(position_key)]
    avg_position = max(set(positions), key=positions.count) if positions else "—"

    return {
        "matches": n,
        "total_minutes": round(total_minutes, 1),
        "total_impact": round(total_impact, 1),
        "avg_impact": round(total_impact / n, 1),
        "avg_impact_per_90": avg_per_90,
        "total_goals": int(total_goals),
        "total_assists": int(total_assists),
        "category_avg": cat_avg,
        "avg_position": avg_position,
        "rows": rows,
    }


def career_summary(history_rows, weights):
    """Compute career-level aggregates for a player given match history.

    history_rows: list from db.get_player_match_history (each has 'stats').
    Returns dict with matches, total_minutes, totals, averages, category avgs.
    """
    rows = compute_player_match_rows(history_rows, weights)
    return _summarize_rows(rows, position_key="position")


def career_summary_positional(history_rows, importances_map):
    """Position-aware career summary plus a per-position breakdown.

    Each match is scored with the weights of the position actually played.
    Returns the same shape as career_summary() plus a 'by_position' key:
        {position: summary_dict}  (each summary built the same way).
    """
    rows = compute_player_match_rows_positional(history_rows, importances_map)
    summary = _summarize_rows(rows, position_key="effective_position")
    if not rows:
        return summary

    # Per-position breakdown (Phase 8)
    by_position = {}
    grouped = {}
    for r in rows:
        grouped.setdefault(r.get("effective_position") or "Unknown", []).append(r)
    for pos, prows in grouped.items():
        by_position[pos] = _summarize_rows(prows, position_key="effective_position")
    summary["by_position"] = by_position
    return summary


# ===========================================================================
# MVP-B — Per-metric drill-down (read-only, uses existing stat_values data)
# ===========================================================================
#
# These helpers expose the *individual* metrics that sit underneath each of the
# 6 impact categories, so the Player Profile screen can drill down from the
# category overview radar into a category-specific metric radar. They only read
# the raw stats already returned by db.get_player_match_history / stat_values —
# no new tables, no schema changes, no impact-score changes.
# ---------------------------------------------------------------------------

def _percentile(sorted_vals, pct):
    """Linear-interpolated percentile of an already-sorted, non-empty list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def aggregate_player_metrics(history_rows):
    """Average raw value per metric across a player's matches.

    Only matches where the metric is actually present (value not None) count
    toward that metric's average. Context metrics (minutes, total actions, …)
    are skipped. Returns {metric_key: average_value}.
    """
    sums, counts = {}, {}
    for r in (history_rows or []):
        stats = r.get("stats") or {}
        for k, v in stats.items():
            if v is None or k in M.CONTEXT_KEYS:
                continue
            sums[k] = sums.get(k, 0.0) + float(v)
            counts[k] = counts.get(k, 0) + 1
    return {k: sums[k] / counts[k] for k in sums if counts[k] > 0}


def metric_reference(stats_list, pct=90):
    """Build a per-metric normalisation reference from many stat dicts.

    For each non-context metric the reference is the ``pct``-th percentile of
    all observed (non-null) values across the supplied stat dicts (squad-wide).
    Percentage metrics use a fixed reference of 100 (they are already 0–100).
    Returns {metric_key: reference_value} (always > 0).
    """
    buckets = {}
    for stats in (stats_list or []):
        for k, v in (stats or {}).items():
            if v is None or k in M.CONTEXT_KEYS:
                continue
            buckets.setdefault(k, []).append(float(v))
    ref = {}
    for k, arr in buckets.items():
        meta = M.METRIC_BY_KEY.get(k, {})
        if meta.get("is_pct"):
            ref[k] = 100.0
            continue
        arr.sort()
        p = _percentile(arr, pct)
        ref[k] = p if p and p > 0 else (arr[-1] if arr and arr[-1] > 0 else 1.0)
    return ref


def category_metric_breakdown(history_rows, category, reference=None):
    """Per-metric breakdown for one category, normalised to 0–100.

    Args:
        history_rows: a player's match history (each row has a 'stats' dict).
        category:     one of M.CATEGORIES.
        reference:    optional {metric_key: reference_value} from
                      ``metric_reference`` for squad-relative scaling. When
                      omitted, percentages map directly and counts use the
                      player's own average as the reference (less comparable).

    Returns a list of dicts (one per metric in the category, in catalog order):
        {key, label, avg, normalized, is_pct}
    where ``normalized`` is a 0–100 score for the radar axis and ``avg`` is the
    player's raw per-match average for the hover tooltip.
    """
    avgs = aggregate_player_metrics(history_rows)
    reference = reference or {}
    out = []
    for m in M.metrics_by_category().get(category, []):
        k = m["key"]
        if k in M.CONTEXT_KEYS:
            continue
        avg = avgs.get(k)
        is_pct = bool(m.get("is_pct"))
        if avg is None:
            normalized = 0.0
            raw = 0.0
        elif is_pct:
            normalized = max(0.0, min(100.0, avg))
            raw = avg
        else:
            ref = reference.get(k) or (avg if avg > 0 else 1.0)
            normalized = max(0.0, min(100.0, (avg / ref) * 100.0)) if ref > 0 else 0.0
            raw = avg
        out.append({
            "key": k, "label": m["label"],
            "avg": round(raw, 2), "normalized": round(normalized, 1),
            "is_pct": is_pct,
        })
    return out


def player_has_goalkeeping(history_rows):
    """True if the player ever recorded a goalkeeping action.

    Used so the Goalkeeping drill-down is only offered for keepers (field
    players never produce these stats).
    """
    gk_keys = ("keeper_saves", "expected_saves", "conceded_goals",
               "keeper_claims", "goalkicks")
    for r in (history_rows or []):
        stats = r.get("stats") or {}
        for k in gk_keys:
            v = stats.get(k)
            if v is not None and v != 0:
                return True
    return False


# ===========================================================================
# Verbetering #1 — Form Indicator (read-only, no impact-score changes)
# ===========================================================================
#
# Compares a player's *recent* form (the last N matches) against their season /
# career baseline so the coach can answer "is this player in form?" at a glance.
# Works on already-scored rows (each row has impact.total_impact). Does not touch
# the scoring logic — it only aggregates the totals that compute_player_match_*
# already produced.
# ---------------------------------------------------------------------------

# Classification thresholds on the percentage difference (recent vs baseline).
# (arrow, dutch_label, english_label)
_FORM_LEVELS = [
    (15.0, "↑", "Sterk stijgend", "Strongly rising"),
    (5.0, "↗", "Stijgend", "Rising"),
    (-5.0, "→", "Stabiel", "Stable"),
    (-15.0, "↘", "Dalend", "Declining"),
]
_FORM_FALLBACK = ("↓", "Sterk dalend", "Strongly declining")


def classify_form(pct):
    """Map a percentage difference onto (arrow, dutch_label, english_label).

    Thresholds:
        >= +15%  -> ↑ Sterk stijgend
        +5..+15% -> ↗ Stijgend
        -5..+5%  -> → Stabiel
        -15..-5% -> ↘ Dalend
        <= -15%  -> ↓ Sterk dalend
    """
    for threshold, arrow, nl, en in _FORM_LEVELS:
        if pct >= threshold:
            return arrow, nl, en
    return _FORM_FALLBACK


def form_indicator(scored_rows, window=5):
    """Recent-vs-baseline form for a player.

    Args:
        scored_rows: chronologically ordered (ascending date) list of rows that
                     already contain ``impact.total_impact`` — exactly what
                     ``compute_player_match_rows`` / ``..._positional`` return.
        window:      how many most-recent matches count as "recent form".

    Returns a dict:
        {
          "sufficient": bool,           # False when < window matches available
          "matches": int,               # total matches considered
          "window": int,                # effective recent window used
          "recent_avg": float,          # avg total impact over last `window`
          "season_avg": float,          # avg total impact over all matches
          "pct": float,                 # ((recent - season) / season) * 100
          "arrow": str, "label": str,   # classification (Dutch label)
          "label_en": str,
        }
    When there are fewer than ``window`` matches the indicator is flagged as
    ``sufficient=False`` so the UI can show an "insufficient data" fallback.
    """
    rows = list(scored_rows or [])
    n = len(rows)
    base = {
        "sufficient": False, "matches": n, "window": window,
        "recent_avg": 0.0, "season_avg": 0.0, "pct": 0.0,
        "arrow": "—", "label": "Onvoldoende data", "label_en": "Insufficient data",
    }
    if n < window:
        return base

    impacts = [r["impact"]["total_impact"] for r in rows]
    season_avg = sum(impacts) / n
    recent = impacts[-window:]
    recent_avg = sum(recent) / len(recent)

    if season_avg == 0:
        pct = 0.0
    else:
        pct = ((recent_avg - season_avg) / abs(season_avg)) * 100.0

    arrow, nl, en = classify_form(pct)
    return {
        "sufficient": True, "matches": n, "window": window,
        "recent_avg": round(recent_avg, 1), "season_avg": round(season_avg, 1),
        "pct": round(pct, 1), "arrow": arrow, "label": nl, "label_en": en,
    }


# ===========================================================================
# Verbetering #2 — Automatic Strengths / Weaknesses summary (read-only)
# ===========================================================================
#
# Surfaces a player's top strengths and main work-ons at a glance so the coach
# does not have to interpret radars. It reuses the MVP-B per-metric breakdown
# (``category_metric_breakdown``) across every category, flattens the metrics
# into one list, filters out metrics the player has no data for, and picks the
# highest / lowest normalised (0–100) scores. No scoring changes, no DB changes.
# ---------------------------------------------------------------------------

def get_strengths_weaknesses(history_rows, reference=None, is_keeper=False,
                             top_n=3):
    """Identify a player's top strengths and main work-ons.

    Args:
        history_rows: the player's match history (rows with a 'stats' dict).
        reference:    optional {metric_key: reference_value} for squad-relative
                      0–100 scaling (same object used by the drill-down radars).
        is_keeper:    when False the Goalkeeping category is excluded (field
                      players never produce those stats meaningfully).
        top_n:        how many strengths / weaknesses to return (default 3).

    Returns ``(strengths, weaknesses)`` — two lists of dicts, each:
        {metric_name, score, category, key}
    where ``score`` is the 0–100 normalised value. ``strengths`` is sorted
    highest-first; ``weaknesses`` lowest-first (most urgent work-on first).

    Filtering:
      * Goalkeeping metrics dropped for field players.
      * Only metrics the player actually has data for are considered — a metric
        is "observed" when it appears in ``aggregate_player_metrics`` (i.e. its
        sample size > 0). This deliberately keeps genuine *low* scores as
        weaknesses while discarding "no data" metrics (which would otherwise
        normalise to 0 and pollute the work-ons).
    When fewer than ``top_n`` qualifying metrics exist, whatever is available is
    returned (possibly empty lists), so the UI can show a fallback.
    """
    observed = set(aggregate_player_metrics(history_rows).keys())

    flat = []
    for category in M.CATEGORIES:
        if category == "Goalkeeping" and not is_keeper:
            continue
        for d in category_metric_breakdown(history_rows, category, reference):
            # Keep only metrics with real data (sample size > 0). A genuine low
            # score is a valid work-on; a "never recorded" metric is not.
            if d["key"] not in observed:
                continue
            flat.append({
                "metric_name": d["label"],
                "score": d["normalized"],
                "category": category,
                "key": d["key"],
            })

    # Highest scores = strengths.
    by_desc = sorted(flat, key=lambda x: x["score"], reverse=True)
    strengths = by_desc[:top_n]
    strength_keys = {s["key"] for s in strengths}

    # Lowest scores = weaknesses; skip any metric already shown as a strength
    # (only relevant for players with a very small metric pool — prevents the
    # same metric appearing in both lists).
    by_asc = sorted(flat, key=lambda x: x["score"])
    weaknesses = [w for w in by_asc if w["key"] not in strength_keys][:top_n]

    return strengths, weaknesses
