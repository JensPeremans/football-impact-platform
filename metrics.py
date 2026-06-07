"""
metrics.py — Central catalog of all metrics for the Football Impact Platform.

Defines:
  - METRICS: the canonical list of every metric_key we track, including the
    human label, category, whether it is a "good" (positive) or "bad"
    (negative) contribution to impact, and which group of actions it counts
    toward (offensive / defensive / neutral) for efficiency calculations.
  - CATEGORIES: the 6 Impact Framework v1.0 categories.
  - DEFAULT_PROFILES: the 4 pre-configured playing-style profiles with weights.

The PDF parser normalises both SciSports PDF versions into these metric_keys.
"""

# The 6 Impact Framework v1.0 categories
CATEGORIES = [
    "Passing",
    "Progression",
    "Chance Creation",
    "Finishing",
    "Defending",
    "Goalkeeping",
]

# action_group used for offensive / defensive efficiency calculations
OFFENSIVE = "offensive"
DEFENSIVE = "defensive"
NEUTRAL = "neutral"

# Each metric:
#   key        -> stable metric_key stored in stat_values
#   label      -> human friendly label (used in UI)
#   category   -> one of CATEGORIES
#   sign       -> +1 for positive contribution, -1 for negative (e.g. conceded goals)
#   action_group -> offensive / defensive / neutral
#   is_pct     -> True if this is a completion-percentage companion metric
#   base_weight-> sensible neutral default weight (profiles scale these)
METRICS = [
    # ---------------- General (neutral context, weight 0 by default) -------
    {"key": "minutes_played", "label": "Minutes Played", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": False, "base_weight": 0.0, "context": True},
    {"key": "total_actions", "label": "Total Actions", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": False, "base_weight": 0.0, "context": True},
    {"key": "offensive_actions", "label": "Offensive Actions", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.0, "context": True},
    {"key": "defensive_actions", "label": "Defensive Actions", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 0.0, "context": True},

    # ---------------- Finishing -------------------------------------------
    # Base weights for goals/assists/xG were reduced in v2 so that pure output
    # no longer dominates every profile's ranking (see weight_tuning_summary.md).
    {"key": "goals", "label": "Goals", "category": "Finishing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 4.5},
    {"key": "assists", "label": "Assists", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 3.5},
    {"key": "shots", "label": "Shots", "category": "Finishing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.0},
    {"key": "shots_on_target", "label": "Shots on Target", "category": "Finishing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 2.0},
    {"key": "xg", "label": "Expected Goals (xG)", "category": "Finishing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 2.5},

    # ---------------- Chance Creation -------------------------------------
    {"key": "key_passes", "label": "Key Passes", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 3.0},
    {"key": "pre_key_passes", "label": "Pre-Key Passes", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.5},
    {"key": "crosses", "label": "Crosses", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.0},
    {"key": "crosses_pct", "label": "Cross Completion %", "category": "Chance Creation",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "passes_hot_zone", "label": "Passes to Hot Zone", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.5},
    {"key": "passes_assist_zone", "label": "Passes to Assist Zone", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.2},
    {"key": "events_inside_box", "label": "Events inside the Box", "category": "Chance Creation",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.0},

    # ---------------- Progression -----------------------------------------
    {"key": "forward_passes", "label": "Forward / Direct Passes", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.0},
    {"key": "forward_passes_pct", "label": "Forward Pass %", "category": "Progression",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "passes_final_third", "label": "Passes to Final 3rd", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.2},
    {"key": "passes_final_third_pct", "label": "Final 3rd Pass %", "category": "Progression",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "dribbles", "label": "Dribbles", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.8},
    {"key": "forward_dribbles", "label": "Forward Dribbles", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.0},
    {"key": "box_entries", "label": "Box Entries (Penetrations/Receptions)", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.5},
    {"key": "final_third_receptions", "label": "Final 3rd Receptions", "category": "Progression",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.8},

    # ---------------- Passing ---------------------------------------------
    {"key": "total_passes", "label": "Total Passes", "category": "Passing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.3},
    {"key": "total_passes_pct", "label": "Pass Completion %", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.05},
    {"key": "switch_passes", "label": "Switch Passes", "category": "Passing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.6},
    {"key": "switch_passes_pct", "label": "Switch Pass %", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.01},
    {"key": "short_passes", "label": "Short Passes (<10m)", "category": "Passing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.2},
    {"key": "short_passes_pct", "label": "Short Pass %", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "med_passes", "label": "Med. Passes (10-34m)", "category": "Passing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.2},
    {"key": "med_passes_pct", "label": "Med. Pass %", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "long_passes", "label": "Long Passes (>34m)", "category": "Passing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 0.3},
    {"key": "long_passes_pct", "label": "Long Pass %", "category": "Passing",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "deep_completions", "label": "Deep Completions", "category": "Passing",
     "sign": 1, "action_group": OFFENSIVE, "is_pct": False, "base_weight": 1.0},

    # ---------------- Defending -------------------------------------------
    {"key": "recoveries", "label": "Recoveries", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 1.0},
    {"key": "clearances", "label": "Clearances", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 0.8},
    {"key": "interceptions", "label": "Interceptions", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 1.5},
    {"key": "blocks", "label": "Blocks", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 1.2},
    {"key": "tackles", "label": "Tackles", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 1.2},
    {"key": "tackles_pct", "label": "Tackle Success %", "category": "Defending",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},
    {"key": "aerials", "label": "Aerials", "category": "Defending",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 1.0},
    {"key": "aerials_pct", "label": "Aerial Success %", "category": "Defending",
     "sign": 1, "action_group": NEUTRAL, "is_pct": True, "base_weight": 0.02},

    # ---------------- Goalkeeping -----------------------------------------
    {"key": "keeper_saves", "label": "Keeper Saves", "category": "Goalkeeping",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 4.0},
    {"key": "expected_saves", "label": "Expected Saves", "category": "Goalkeeping",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 2.0},
    {"key": "conceded_goals", "label": "Conceded Goals", "category": "Goalkeeping",
     "sign": -1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 4.0},
    {"key": "keeper_claims", "label": "Keeper Claims", "category": "Goalkeeping",
     "sign": 1, "action_group": DEFENSIVE, "is_pct": False, "base_weight": 2.0},
    {"key": "goalkicks", "label": "Goalkicks", "category": "Goalkeeping",
     "sign": 1, "action_group": NEUTRAL, "is_pct": False, "base_weight": 0.2},
]

# quick lookups
METRIC_BY_KEY = {m["key"]: m for m in METRICS}
METRIC_KEYS = [m["key"] for m in METRICS]

# Metrics that are "context only" (minutes, total actions, splits) and should
# not normally carry weight. Profiles still store a 0 weight so they appear in
# the editor, but they are excluded from default scoring.
CONTEXT_KEYS = {m["key"] for m in METRICS if m.get("context")}


def metrics_by_category():
    """Return {category: [metric, ...]} preserving METRICS order."""
    out = {c: [] for c in CATEGORIES}
    for m in METRICS:
        out[m["category"]].append(m)
    return out


# ---------------------------------------------------------------------------
# Default playing-style profiles.
#
# Each profile defines per-metric *multipliers* applied to base_weight. A
# multiplier of 1.0 = neutral, >1 emphasises the metric, <1 de-emphasises it.
# Metrics not listed for a profile fall back to multiplier 1.0. Context metrics
# always resolve to weight 0.
# ---------------------------------------------------------------------------

#
# v2 tuning notes
# ---------------
# To break the ~0.96 cross-profile correlation seen in v1, each profile now:
#   * boosts its SIGNATURE metrics with much stronger multipliers (4x-6x), and
#   * actively SUPPRESSES metrics that conflict with its philosophy
#     (multipliers < 1.0, e.g. 0.2-0.5). Suppression is applied multiplicatively
#     in impact_engine.compute_impact (value * weight * sign), so a 0.2 weight
#     keeps the action visible but contributes only 20% of its base impact.
#
# Dataset-mapping note: the brief references some metrics that the SciSports
# Player-Version reports do not expose at player level. They are mapped to the
# closest available proxy:
#   * "xA / Expected Assists"   -> xg (only expected metric available)
#   * "Progressive Passes"      -> passes_final_third
#   * "Backwards Passes"        -> switch_passes (lateral / non-progressive proxy)
#   * "Duels Won"               -> aerials (+ tackles)
#   * "PPDA (opponent passes)"  -> NOT available (team-level only) -> omitted
#
DEFAULT_PROFILES = {
    "Possession Football": {
        "description": ("Rewards ball retention, high pass completion and patient "
                        "build-up. Suppresses long/direct/vertical play and duels."),
        "is_default": True,
        "multipliers": {
            # signature: retention QUALITY (completion %, short/switch) rather
            # than raw pass volume (which just tracks high-touch players and
            # makes Possession indistinguishable from Direct).
            "total_passes_pct": 12.0, "total_passes": 1.0,
            "short_passes": 2.0, "short_passes_pct": 8.0,
            "switch_passes": 2.0, "switch_passes_pct": 6.0,
            "med_passes": 1.5, "med_passes_pct": 6.0,
            # suppressions: verticality / direct progression (vs Direct profile)
            "forward_passes": 0.25, "long_passes": 0.2, "long_passes_pct": 0.4,
            "passes_final_third": 0.4, "deep_completions": 0.6,
            "box_entries": 0.3, "forward_dribbles": 0.3,
            "final_third_receptions": 0.4,
            # suppressions: chance creation / shooting (vs Chance Creation profile)
            "crosses": 0.25, "shots": 0.3, "shots_on_target": 0.3, "goals": 0.6,
            "key_passes": 0.4, "pre_key_passes": 0.4, "dribbles": 0.4,
            "passes_hot_zone": 0.4, "passes_assist_zone": 0.5,
            "events_inside_box": 0.3,
            # suppress raw defending (possession = avoid needing to defend)
            "recoveries": 0.4, "clearances": 0.3, "interceptions": 0.5,
            "blocks": 0.3, "tackles": 0.4, "aerials": 0.3,
            # keep keepers from dominating outfield play
            "keeper_saves": 0.8, "expected_saves": 0.8, "goalkicks": 1.0,
        },
    },
    "Direct Football": {
        "description": ("Rewards vertical progression: forward/long passes, box "
                        "entries, deep completions. Suppresses sideways/short play."),
        "is_default": False,
        "multipliers": {
            # signature: progression & verticality
            "forward_passes": 7.0, "forward_passes_pct": 3.0,
            "passes_final_third": 6.0, "passes_final_third_pct": 2.5,  # progressive proxy
            "deep_completions": 6.0,
            "box_entries": 5.0,
            "long_passes": 3.0, "long_passes_pct": 2.5,
            "forward_dribbles": 3.5, "final_third_receptions": 2.5,
            "shots_on_target": 1.8, "shots": 1.8, "aerials": 2.0,
            # suppressions: retention / lateral / backwards / build-up volume
            "switch_passes": 0.2, "switch_passes_pct": 0.3,  # backwards proxy
            "short_passes": 0.3, "short_passes_pct": 0.4,
            "med_passes": 0.4, "med_passes_pct": 0.5,
            "total_passes": 0.3, "total_passes_pct": 0.4,
            "recoveries": 0.5, "clearances": 0.5, "interceptions": 0.6,
            # suppress pure-creation metrics (vs Chance Creation profile)
            "crosses": 0.4, "key_passes": 0.5, "pre_key_passes": 0.5,
            "dribbles": 0.5, "passes_hot_zone": 0.5, "passes_assist_zone": 0.5,
            "keeper_saves": 0.8, "goalkicks": 1.5,
        },
    },
    "High Pressing": {
        "description": ("Rewards aggressive ball-winning: recoveries, tackles, "
                        "interceptions, duels. Prevention over finishing/build-up."),
        "is_default": False,
        "multipliers": {
            # signature: ball winning
            "recoveries": 7.0,
            "tackles": 6.0, "tackles_pct": 3.0,
            "interceptions": 6.0,
            "aerials": 4.5, "aerials_pct": 2.0,  # duels-won proxy
            "blocks": 3.0, "clearances": 2.0,
            "forward_passes": 1.0,
            # suppressions: finishing, build-up & long balls (prevention, not output)
            "xg": 0.4, "goals": 0.5, "shots": 0.4, "shots_on_target": 0.5,
            "key_passes": 0.4, "pre_key_passes": 0.4, "crosses": 0.4,
            "dribbles": 0.5, "forward_dribbles": 0.5, "box_entries": 0.4,
            "long_passes": 0.2, "long_passes_pct": 0.4,
            "total_passes": 0.3, "total_passes_pct": 0.4,
            "short_passes": 0.3, "med_passes": 0.3, "switch_passes": 0.3,
            "passes_final_third": 0.5, "deep_completions": 0.5,
            "keeper_saves": 1.5, "keeper_claims": 2.0, "expected_saves": 1.5,
        },
    },
    "Chance Creation Focus": {
        "description": ("Rewards creativity: key passes, assists, xA(=xG), crosses, "
                        "dribbles and box threat. Suppresses defensive/retention work."),
        "is_default": False,
        "multipliers": {
            # signature: creation
            "key_passes": 7.0, "pre_key_passes": 3.5,
            "assists": 2.0,  # base 3.5 x 2.0 = effective 7.0
            "xg": 5.0,       # xA proxy
            "crosses": 5.0, "crosses_pct": 2.0,
            "dribbles": 4.5, "forward_dribbles": 3.0,
            "passes_hot_zone": 3.5, "passes_assist_zone": 3.5,
            "events_inside_box": 3.0, "box_entries": 2.5,
            "shots_on_target": 2.2, "shots": 2.0,
            # suppressions: defensive work & sterile passing volume
            "tackles": 0.2, "interceptions": 0.2, "recoveries": 0.2,
            "clearances": 0.2, "blocks": 0.2, "aerials": 0.3,
            "total_passes": 0.4, "total_passes_pct": 0.4,
            "short_passes": 0.4, "med_passes": 0.4, "long_passes": 0.4,
            "switch_passes": 0.4, "keeper_saves": 0.6,
            # suppress direct build-up progression (vs Direct profile): reward
            # the final creative act, not the route there
            "forward_passes": 0.4, "passes_final_third": 0.6,
            "deep_completions": 0.5, "final_third_receptions": 0.5,
        },
    },
}


def build_profile_weights(profile_name):
    """Return list of (metric_key, weight, category) tuples for a default profile."""
    spec = DEFAULT_PROFILES[profile_name]
    mults = spec["multipliers"]
    rows = []
    for m in METRICS:
        if m["key"] in CONTEXT_KEYS:
            weight = 0.0
        else:
            weight = round(m["base_weight"] * mults.get(m["key"], 1.0), 4)
        rows.append((m["key"], weight, m["category"]))
    return rows


# ===========================================================================
# SPRINT 2 — Position-based coaching system
# ===========================================================================
#
# The platform is position-aware: every player-match has one of the 20 specific
# positions below. Position-based *profiles* assign an importance score (0-10)
# to each of the 6 impact CATEGORIES, separately for each position. The impact
# engine translates those importances into per-metric weights at scoring time
# (see importance_to_multiplier / build_position_metric_weights).
# ---------------------------------------------------------------------------

# The 20 canonical positions (order = top→bottom of a vertical pitch layout).
POSITIONS = [
    "Goalkeeper",
    "Left Back", "Right Back",
    "Centrale Verdediger (L)", "Centrale Verdediger (C)", "Centrale Verdediger (R)",
    "Left Wingback", "Right Wingback",
    "Defensive Midfielder (L)", "Defensive Midfielder (C)", "Defensive Midfielder (R)",
    "Central Midfielder (L)", "Central Midfielder (C)", "Central Midfielder (R)",
    "Attacking Midfielder (L)", "Attacking Midfielder (C)", "Attacking Midfielder (R)",
    "Left Winger", "Right Winger",
    "Striker (L)", "Striker (C)", "Striker (R)",
]
POSITION_SET = set(POSITIONS)

# Broad tactical groups, used to assign sensible default category importances.
POSITION_GROUP = {
    "Goalkeeper": "goalkeeper",
    "Left Back": "fullback", "Right Back": "fullback",
    "Centrale Verdediger (L)": "centreback",
    "Centrale Verdediger (C)": "centreback",
    "Centrale Verdediger (R)": "centreback",
    "Left Wingback": "wingback", "Right Wingback": "wingback",
    "Defensive Midfielder (L)": "defmid",
    "Defensive Midfielder (C)": "defmid",
    "Defensive Midfielder (R)": "defmid",
    "Central Midfielder (L)": "centremid",
    "Central Midfielder (C)": "centremid",
    "Central Midfielder (R)": "centremid",
    "Attacking Midfielder (L)": "attmid",
    "Attacking Midfielder (C)": "attmid",
    "Attacking Midfielder (R)": "attmid",
    "Left Winger": "winger", "Right Winger": "winger",
    "Striker (L)": "striker", "Striker (C)": "striker", "Striker (R)": "striker",
}

# Default category importances (0-10) per tactical group. Order of keys follows
# CATEGORIES. These are the coach-facing defaults that Phase 6 seeds.
_GROUP_CATEGORY_DEFAULTS = {
    #              Passing Progress ChanceCr Finish Defend GK
    "goalkeeper": {"Passing": 5, "Progression": 2, "Chance Creation": 1,
                   "Finishing": 0, "Defending": 4, "Goalkeeping": 10},
    "fullback":   {"Passing": 6, "Progression": 6, "Chance Creation": 6,
                   "Finishing": 1, "Defending": 8, "Goalkeeping": 0},
    "centreback": {"Passing": 7, "Progression": 4, "Chance Creation": 1,
                   "Finishing": 1, "Defending": 9, "Goalkeeping": 0},
    "wingback":   {"Passing": 6, "Progression": 7, "Chance Creation": 7,
                   "Finishing": 2, "Defending": 7, "Goalkeeping": 0},
    "defmid":     {"Passing": 8, "Progression": 6, "Chance Creation": 3,
                   "Finishing": 1, "Defending": 8, "Goalkeeping": 0},
    "centremid":  {"Passing": 8, "Progression": 7, "Chance Creation": 6,
                   "Finishing": 3, "Defending": 6, "Goalkeeping": 0},
    "attmid":     {"Passing": 7, "Progression": 8, "Chance Creation": 9,
                   "Finishing": 6, "Defending": 3, "Goalkeeping": 0},
    "winger":     {"Passing": 5, "Progression": 7, "Chance Creation": 9,
                   "Finishing": 6, "Defending": 3, "Goalkeeping": 0},
    "striker":    {"Passing": 4, "Progression": 5, "Chance Creation": 8,
                   "Finishing": 9, "Defending": 2, "Goalkeeping": 0},
}


def default_position_category_importances():
    """Return {position: {category: importance(0-10)}} for all 20 positions."""
    out = {}
    for pos in POSITIONS:
        grp = POSITION_GROUP.get(pos, "centremid")
        out[pos] = dict(_GROUP_CATEGORY_DEFAULTS[grp])
    return out


# Fixed (x, y) pitch coordinates per position on a 0-100 grid.
# x = left(0)→right(100), y = own goal(0)→opponent goal(100). A vertical pitch
# rendered bottom-up. Coordinates are spaced so markers never overlap.
POSITION_COORDS = {
    "Goalkeeper": (50, 6),
    "Centrale Verdediger (L)": (35, 18),
    "Centrale Verdediger (C)": (50, 15),
    "Centrale Verdediger (R)": (65, 18),
    "Left Back": (16, 26),
    "Right Back": (84, 26),
    "Left Wingback": (11, 42),
    "Right Wingback": (89, 42),
    "Defensive Midfielder (L)": (32, 38),
    "Defensive Midfielder (C)": (50, 38),
    "Defensive Midfielder (R)": (68, 38),
    "Central Midfielder (L)": (32, 53),
    "Central Midfielder (C)": (50, 53),
    "Central Midfielder (R)": (68, 53),
    "Attacking Midfielder (L)": (32, 69),
    "Attacking Midfielder (C)": (50, 67),
    "Attacking Midfielder (R)": (68, 69),
    "Left Winger": (15, 80),
    "Right Winger": (85, 80),
    "Striker (L)": (38, 90),
    "Striker (C)": (50, 92),
    "Striker (R)": (62, 90),
}

# Player-match availability status (Phase 2).
STATUS_STARTER = "Starter"
STATUS_BENCH = "Bench"
STATUS_CAME_ON = "Came On"
STATUSES = [STATUS_STARTER, STATUS_BENCH, STATUS_CAME_ON]

# Session types (Phase 10 — architecture prep only).
SESSION_MATCH = "match"
SESSION_TRAINING = "training"
SESSION_COMBINED = "combined"
SESSION_TYPES = [SESSION_MATCH, SESSION_TRAINING, SESSION_COMBINED]


def importance_to_multiplier(importance):
    """Translate a 0-10 coach importance score into a category multiplier.

    Scale anchor points:
        0      -> 0.0   (category ignored)
        5      -> 1.0   (neutral / average importance)
        10     -> 2.0   (very important, double impact)
    Linear in between, so multiplier = importance / 5.0.
    """
    try:
        imp = float(importance)
    except (TypeError, ValueError):
        return 1.0
    if imp < 0:
        imp = 0.0
    if imp > 10:
        imp = 10.0
    return imp / 5.0


def build_position_metric_weights(category_importances):
    """Build {metric_key: weight} from per-category 0-10 importances.

    Each metric's effective weight = base_weight * importance_multiplier(category).
    Context metrics always resolve to 0. `category_importances` is a dict
    {category: importance(0-10)}; missing categories default to neutral (5).
    """
    category_importances = category_importances or {}
    weights = {}
    for m in METRICS:
        if m["key"] in CONTEXT_KEYS:
            weights[m["key"]] = 0.0
            continue
        imp = category_importances.get(m["category"], 5.0)
        weights[m["key"]] = round(m["base_weight"] * importance_to_multiplier(imp), 4)
    return weights
