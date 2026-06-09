"""
pdf_parser.py — Robust SciSports match-analysis PDF parser.

Handles BOTH document versions:
  * Version A (older, e.g. Sep 2025 Charleroi): "Forward Passes", "Box
    Penetrations", "Total xGoals", "Events inside the Box", dashes for nulls,
    decimal minutes.
  * Version B (newer, Oct/Nov 2025): "Direct Passes", "Box Receptions",
    "Final 3rd Receptions", "Forward Dribbles", "xG" (conditional), integer
    minutes, "0 (0.0%)" zeros.

All stats are normalised into the canonical metric_keys defined in metrics.py
and returned ready to be persisted by database.py.
"""

import hashlib
import os
import re

import pdfplumber

import database as db
import metrics as M


class PDFParseError(Exception):
    """Raised when a PDF is not a valid SciSports player report."""


# ---------------------------------------------------------------------------
# Value parsing helpers
# ---------------------------------------------------------------------------
def _parse_count_pct(raw):
    """Parse 'N (P%)' -> (count, pct). Handles '-' and plain ints.

    Returns (count_or_None, pct_or_None).
    """
    if raw is None:
        return None, None
    raw = raw.strip()
    if raw in ("-", "", "—"):
        return None, None
    m = re.match(r"^(\d+)\s*\(\s*(\d+\.?\d*)\s*%\s*\)$", raw)
    if m:
        return int(m.group(1)), float(m.group(2))
    m = re.match(r"^(\d+\.?\d*)$", raw)
    if m:
        return float(m.group(1)), None
    return None, None


def _parse_number(raw):
    """Parse an integer / float / '-' single value -> float or None."""
    if raw is None:
        return None
    raw = raw.strip()
    if raw in ("-", "", "—"):
        return None
    m = re.match(r"^(\d+\.?\d*)$", raw)
    if m:
        return float(m.group(1))
    # count(pct) where we only want the count
    m = re.match(r"^(\d+)\s*\(", raw)
    if m:
        return float(m.group(1))
    return None


# Value token regex used after a label. Matches, in priority order:
#   count with percent: 24 (66.7%)
#   split: 29 / 10
#   dash: -
#   number: 90.4 / 3 / 0.20000000298023224
VALUE_RE = r"(\d+\s*\(\s*\d+\.?\d*\s*%\s*\)|\d+\.?\d*\s*/\s*\d+|-|\d+\.?\d*)"


def _extract_label(text, label_regex):
    """Find `label_regex` followed by a value token; return the raw value string."""
    pat = re.compile(label_regex + r"\s+" + VALUE_RE)
    m = pat.search(text)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_cover(text):
    """Extract match metadata from page 1 text."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    info = {"match_date": None, "home_team": None, "away_team": None,
            "home_score": None, "away_score": None}

    # date = first ISO date
    for l in lines:
        m = DATE_RE.search(l)
        if m:
            info["match_date"] = m.group(1)
            break

    # title -> home team
    for l in lines:
        m = re.match(r"Match Report\s*-\s*(.+)", l)
        if m:
            info["home_team"] = m.group(1).strip()
            break

    # score lines: "<Team> : <score>"
    score_lines = []
    for l in lines:
        m = re.match(r"^(.+?)\s*:\s*(\d+)$", l)
        if m and not l.lower().startswith("match report"):
            score_lines.append((m.group(1).strip(), int(m.group(2))))
    if len(score_lines) >= 2:
        info["home_team"] = info["home_team"] or score_lines[0][0]
        info["home_score"] = score_lines[0][1]
        info["away_team"] = score_lines[1][0]
        info["away_score"] = score_lines[1][1]
    return info


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------
def detect_version(full_text):
    if ("Forward Passes" in full_text or "Box Penetrations" in full_text
            or "Total xGoals" in full_text):
        return "A"
    return "B"


# ---------------------------------------------------------------------------
# Player header
# ---------------------------------------------------------------------------
# Locate player blocks by the "Player Performance" marker and accept ANY
# position label between the parentheses (e.g. "Centre back", "Left back",
# "Defensive midfield", "Attacking midfield", "Left wing", "Centre forward").
# The position is whatever sits inside the last pair of parentheses before the
# match date on the header line.
HEADER_RE = re.compile(
    r"Player Performance\s*\((.+?)\):\s*(.+?)\s*\(([^()]+?)\)\s+(\d{4}-\d{2}-\d{2})"
)

# Map the raw SciSports position labels onto the 20 canonical positions used
# throughout the app (see metrics.POSITIONS). Lookup is case-insensitive.
#
# SciSports PDFs do not distinguish Left/Centre/Right variants for central
# defenders / midfielders / strikers, so those map to the CENTRE (C) variant as
# a best guess. The coach can refine the exact L/C/R variant in the post-import
# position-confirmation step (Phase 3). Unknown labels fall back to a title-cased
# version of the raw text so every player is still imported.
POSITION_MAP = {
    "goalkeeper": "Goalkeeper",
    "keeper": "Goalkeeper",
    "gk": "Goalkeeper",
    # Central defenders -> centre variant (refine to L/C/R on confirm)
    "centre back": "Centrale Verdediger (C)",
    "center back": "Centrale Verdediger (C)",
    "central defender": "Centrale Verdediger (C)",
    "central defence": "Centrale Verdediger (C)",
    "centre back (left)": "Centrale Verdediger (L)",
    "centre back (right)": "Centrale Verdediger (R)",
    "defender": "Centrale Verdediger (C)",
    # Full backs (side known)
    "left back": "Left Back",
    "right back": "Right Back",
    "full back": "Left Back",
    "fullback": "Left Back",
    # Wing backs (side known)
    "left wing back": "Left Wingback",
    "left wingback": "Left Wingback",
    "right wing back": "Right Wingback",
    "right wingback": "Right Wingback",
    # Defensive midfield
    "defensive midfield": "Defensive Midfielder",
    "defensive midfielder": "Defensive Midfielder",
    "holding midfield": "Defensive Midfielder",
    # Central midfield -> centre variant
    "centre midfield": "Central Midfielder (C)",
    "center midfield": "Central Midfielder (C)",
    "central midfield": "Central Midfielder (C)",
    "central midfielder": "Central Midfielder (C)",
    "centre midfielder": "Central Midfielder (C)",
    "midfielder": "Central Midfielder (C)",
    "midfield": "Central Midfielder (C)",
    # Attacking midfield -> centre variant
    "attacking midfield": "Attacking Midfielder (C)",
    "attacking midfielder": "Attacking Midfielder (C)",
    # Wingers (side known)
    "left wing": "Left Winger",
    "left winger": "Left Winger",
    "right wing": "Right Winger",
    "right winger": "Right Winger",
    # Strikers / forwards -> centre variant
    "centre forward": "Striker (C)",
    "center forward": "Striker (C)",
    "striker": "Striker (C)",
    "forward": "Striker (C)",
    "second striker": "Striker (C)",
}


def normalize_position(raw_position):
    """Map a raw PDF position label onto one of the 20 canonical app positions.

    Unknown labels are accepted as-is (title-cased) so the parser never drops a
    player just because the position wording is new; the coach can correct them
    in the post-import confirmation step.
    """
    if not raw_position:
        return None
    key = re.sub(r"\s+", " ", raw_position.strip().lower())
    if key in POSITION_MAP:
        return POSITION_MAP[key]
    return raw_position.strip().title()


def parse_player_page(text):
    """Parse a single player page's text into a normalised stat dict.

    Returns dict with keys: team, name, position, stats{metric_key: value}.
    Returns None if the page is not a player page (e.g. glossary).
    """
    hm = HEADER_RE.search(text)
    if not hm:
        return None
    team, name, raw_position, _date = hm.groups()
    raw_position = raw_position.strip()
    position = normalize_position(raw_position)
    is_gk = "keeper" in raw_position.lower() or position == "Goalkeeper"

    stats = {}

    def set_v(key, value):
        if value is not None:
            stats[key] = value

    # ---- General Information ----
    set_v("minutes_played", _parse_number(_extract_label(text, r"Minutes Played")))
    set_v("total_actions", _parse_number(_extract_label(text, r"Total Actions")))

    m = re.search(r"Offensive\s*/\s*Defensive\s+(\d+)\s*/\s*(\d+)", text)
    if m:
        set_v("offensive_actions", float(m.group(1)))
        set_v("defensive_actions", float(m.group(2)))
    m = re.search(r"Goals\s*/\s*Assists\s+(\d+)\s*/\s*(\d+)", text)
    if m:
        set_v("goals", float(m.group(1)))
        set_v("assists", float(m.group(2)))

    # ---- Goalkeeper performance ----
    if is_gk:
        set_v("keeper_saves", _parse_number(_extract_label(text, r"Keeper Saves")))
        es = _parse_number(_extract_label(text, r"Expected Saves"))
        set_v("expected_saves", round(es, 1) if es is not None else None)
        set_v("conceded_goals", _parse_number(_extract_label(text, r"Conceded Goals")))
        set_v("keeper_claims", _parse_number(_extract_label(text, r"Keeper Claims")))
        set_v("goalkicks", _parse_number(_extract_label(text, r"Goalkicks")))

    # ---- Chance creation (field players get full set; GK gets subset) ----
    if not is_gk:
        set_v("shots", _parse_number(_extract_label(text, r"Shots(?!\s+on)")))
        set_v("shots_on_target", _parse_number(_extract_label(text, r"Shots on Target")))
        c, p = _parse_count_pct(_extract_label(text, r"Crosses"))
        set_v("crosses", c); set_v("crosses_pct", p)

    # Key/Pre-Key/Dribbles present for everyone (GK subset too)
    c, p = _parse_count_pct(_extract_label(text, r"(?<!-)(?<!Pre-)Key Passes"))
    set_v("key_passes", c)
    set_v("pre_key_passes", _parse_number(_extract_label(text, r"Pre-Key Passes")))
    set_v("dribbles", _parse_number(_extract_label(text, r"(?<!Forward )Dribbles")))

    if not is_gk:
        # Version B specifics
        set_v("forward_dribbles", _parse_number(_extract_label(text, r"Forward Dribbles")))
        set_v("final_third_receptions",
              _parse_number(_extract_label(text, r"Final 3rd Receptions")))
        # box entries: B = Box Receptions, A = Box Penetrations
        be = _parse_number(_extract_label(text, r"Box Receptions"))
        if be is None:
            be = _parse_number(_extract_label(text, r"Box Penetrations"))
        set_v("box_entries", be)
        set_v("events_inside_box",
              _parse_number(_extract_label(text, r"Events inside the Box")))
        # xG: B = "xG", A = "Total xGoals"
        xg = _extract_label(text, r"Total xGoals")
        if xg is None:
            xg = _extract_label(text, r"(?<!Total )(?<!\w)xG(?!oals)")
        xgv = _parse_number(xg)
        set_v("xg", round(xgv, 2) if xgv is not None else None)

    # ---- Passing performance ----
    c, p = _parse_count_pct(_extract_label(text, r"Total Passes"))
    set_v("total_passes", c); set_v("total_passes_pct", p)
    # Forward (A) / Direct (B) passes -> forward_passes
    fp = _extract_label(text, r"Direct Passes")
    if fp is None:
        fp = _extract_label(text, r"Forward Passes")
    c, p = _parse_count_pct(fp)
    set_v("forward_passes", c); set_v("forward_passes_pct", p)

    c, p = _parse_count_pct(_extract_label(text, r"Switch Passes"))
    set_v("switch_passes", c); set_v("switch_passes_pct", p)
    c, p = _parse_count_pct(_extract_label(text, r"Short Passes \(<10 m\)\u00b9?"))
    set_v("short_passes", c); set_v("short_passes_pct", p)
    c, p = _parse_count_pct(_extract_label(text, r"Med\. Passes \(10-34 m\)\u00b9?"))
    set_v("med_passes", c); set_v("med_passes_pct", p)
    c, p = _parse_count_pct(_extract_label(text, r"Long Passes \(>34 m\)\u00b9?"))
    set_v("long_passes", c); set_v("long_passes_pct", p)
    c, p = _parse_count_pct(_extract_label(text, r"Passes to Hot Zone"))
    set_v("passes_hot_zone", c)
    c, p = _parse_count_pct(_extract_label(text, r"Passes to Assist Zone"))
    set_v("passes_assist_zone", c)
    c, p = _parse_count_pct(_extract_label(text, r"Passes to Final 3rd"))
    set_v("passes_final_third", c); set_v("passes_final_third_pct", p)
    c, p = _parse_count_pct(_extract_label(text, r"Deep Completions"))
    set_v("deep_completions", c)

    # ---- Defending performance ----
    set_v("recoveries", _parse_number(_extract_label(text, r"Recoveries")))
    set_v("clearances", _parse_number(_extract_label(text, r"Clearances")))
    set_v("interceptions", _parse_number(_extract_label(text, r"Interceptions")))
    set_v("blocks", _parse_number(_extract_label(text, r"Blocks")))
    c, p = _parse_count_pct(_extract_label(text, r"Tackles"))
    set_v("tackles", c); set_v("tackles_pct", p)
    c, p = _parse_count_pct(_extract_label(text, r"Aerials"))
    set_v("aerials", c); set_v("aerials_pct", p)

    return {"team": team.strip(), "name": name.strip(),
            "position": position, "stats": stats}


# ---------------------------------------------------------------------------
# Season derivation
# ---------------------------------------------------------------------------
def derive_season(match_date):
    """ISO date -> 'YYYY/YYYY+1'. Season starts in July (month >= 7)."""
    try:
        year, month, _ = match_date.split("-")
        year = int(year); month = int(month)
    except Exception:
        return None
    if month >= 7:
        return f"{year}/{year + 1}"
    return f"{year - 1}/{year}"


# ---------------------------------------------------------------------------
# Team name / age-group split
# ---------------------------------------------------------------------------
def split_team_age(team_name):
    """'Zulte Waregem U18' -> ('Zulte Waregem', 'U18')."""
    m = re.match(r"^(.*?)\s+(U\d{1,2})$", team_name.strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return team_name.strip(), None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def compute_file_hash(file_path):
    """Return the MD5 hex digest of a file's raw bytes."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_pdf(file_path, original_name=None):
    """Parse a PDF file into structured match + player data (no DB writes).

    original_name lets callers (e.g. the Streamlit uploader, which writes the
    bytes to a temp file) preserve the user-facing filename for source tracking.
    """
    if not os.path.exists(file_path):
        raise PDFParseError(f"File not found: {file_path}")

    try:
        pdf = pdfplumber.open(file_path)
    except Exception as e:
        raise PDFParseError(f"Could not open PDF: {e}")

    with pdf:
        pages_text = []
        for pg in pdf.pages:
            pages_text.append(pg.extract_text() or "")

    if not pages_text:
        raise PDFParseError("PDF contains no extractable text.")

    full_text = "\n".join(pages_text)

    # Validate it's a SciSports player report
    if "Player Performance" not in full_text or "Match Report" not in full_text:
        raise PDFParseError(
            "This does not look like a SciSports Match Analysis (Player Version) report."
        )

    version = detect_version(full_text)
    cover = parse_cover(pages_text[0])
    if not cover.get("match_date") or not cover.get("home_team"):
        raise PDFParseError("Could not read match metadata from the cover page.")

    players = []
    for txt in pages_text[1:]:
        if "GLOSSARY" in txt[:80].upper():
            continue
        parsed = parse_player_page(txt)
        if parsed:
            players.append(parsed)

    if not players:
        raise PDFParseError("No player pages could be parsed from this PDF.")

    return {
        "version": version,
        "cover": cover,
        "players": players,
        "season": derive_season(cover["match_date"]),
        "source_file": original_name or os.path.basename(file_path),
        "upload_hash": compute_file_hash(file_path),
    }


def store_parsed(conn, parsed, club_id, overrides=None, session_type="match"):
    """Persist a parsed PDF into the database. Returns (match_id, created_bool, n_players).

    All created rows are tagged with ``club_id`` so the data is isolated to the
    uploading user's club.

    `overrides` (optional) is a dict keyed by player name with coach-confirmed values:
        {player_name: {"position": str, "status": str, "came_on_as": str|None}}
    Any field that is missing falls back to the parsed/default value.
    """
    overrides = overrides or {}
    cover = parsed["cover"]
    home_team_full = cover["home_team"]
    team_name, age_group = split_team_age(home_team_full)
    # opponent = away team (this is the [home] variant => our team is home)
    opponent = cover.get("away_team") or "Unknown"

    team_id = db.get_or_create_team(conn, club_id, team_name, age_group)

    existing = db.find_match(conn, club_id, team_id, opponent, cover["match_date"])
    if existing:
        # Replace existing data for idempotent re-uploads
        db.delete_match(conn, existing["id"], club_id=club_id)

    match_id = db.create_match(
        conn, club_id, team_id, opponent, cover["match_date"],
        cover.get("home_score"), cover.get("away_score"),
        is_home=True, season=parsed["season"], source_file=parsed["source_file"],
        upload_hash=parsed.get("upload_hash"), session_type=session_type,
    )

    n = 0
    for p in parsed["players"]:
        player_id = db.get_or_create_player(conn, club_id, p["name"], team_id=team_id)
        minutes = p["stats"].get("minutes_played")
        ov = overrides.get(p["name"], {})
        position = ov.get("position") or p["position"]
        status = ov.get("status") or "Starter"
        came_on_as = ov.get("came_on_as") or None
        pms_id = db.upsert_player_match_stats(
            conn, club_id, match_id, player_id, position, minutes,
            status=status, came_on_as=came_on_as,
        )
        db.save_stat_values(conn, pms_id, p["stats"])
        n += 1

    conn.commit()
    return match_id, (existing is None), n
