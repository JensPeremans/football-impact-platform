"""physical_parser.py — Universal physical / GPS-tracking data parser.

Turns two very different physical-performance export formats into ONE
standardised tidy DataFrame so the rest of the platform never has to care
where the numbers came from:

  * ``game_xlsx``    — "Game …" Excel report (zone-based, full-match totals,
                       speeds in km/h, EDI as a 0–1 ratio).
  * ``catapult_csv`` — Catapult / PlayerTek "Single-Session Match Periods
                       Report" CSV (per-half rows, speeds in m/s).

Design goals
------------
* **Format-agnostic** — column lookup is alias driven and case-insensitive,
  so new export variants only need an alias added (no code changes).
* **Unit-normalised** — every speed becomes km/h, EDI becomes a 0–100
  percentage, player names become Title Case, times become minutes.
* **Lossless** — the original row is preserved (JSON) for traceability and a
  validation report lists every metric that could not be found.

This module is deliberately INDEPENDENT from the technical/impact pipeline
(``pdf_parser`` / ``impact_engine``): physical data lives in its own table.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re

import pandas as pd


class PhysicalParseError(Exception):
    """Raised when a physical-data file cannot be parsed."""


# ---------------------------------------------------------------------------
# Canonical field list (internal model)
# ---------------------------------------------------------------------------
# The parser always returns exactly these columns (missing ones become NaN),
# plus any "extra" recognised metric that happens to be present.
STANDARD_FIELDS = [
    # Identification / context
    "player_name",
    "period",
    "session_name",
    "match_date",
    "start_time",
    "end_time",
    "total_time_minutes",
    # Distance metrics (metres)
    "total_distance",
    "distance_per_minute",
    "sprint_distance",
    "high_intensity_distance",
    "hml_distance",
    # Speed metrics
    "top_speed",            # km/h  (canonical display unit)
    "top_speed_ms",         # m/s   (raw, when available)
    "percentage_max_speed",  # %
    # Sprint / intensity counts
    "sprint_count",
    "high_intensity_events",
    "high_intensity_bursts_distance",  # metres
    "high_intensity_bursts_count",
    # Acceleration metrics
    "accelerations",
    "decelerations",
    "acc_dec_total",
    "max_acceleration",     # m/s²
    # Load metrics
    "session_load",         # arbitrary units (PlayerLoad)
    "edi_percentage",       # % (0–100)
    # Zone metrics (metres / counts)
    "distance_zone5",
    "distance_zone6",
    "entries_zone6",
]

# Numeric fields that must end up as floats/ints (everything except text/meta).
_TEXT_FIELDS = {"player_name", "period", "session_name", "match_date",
                "start_time", "end_time"}
NUMERIC_FIELDS = [f for f in STANDARD_FIELDS if f not in _TEXT_FIELDS]


# ---------------------------------------------------------------------------
# A. Alias mappings  (canonical_field -> list of accepted source headers)
# ---------------------------------------------------------------------------
ALIASES = {
    # --- Identification / context ---
    "player_name": [
        "Player Name", "Athlete", "Player", "Name", "Player Full Name",
        "Athlete Name", "Speler",
    ],
    "period": [
        "Title", "Period", "Match Period", "Half", "Periode",
    ],
    "start_time": ["Start Time", "Start", "Session Start"],
    "end_time": ["End Time", "End", "Session End"],
    "total_time_minutes": [
        "Total Time", "Duration", "Time", "Total Duration", "Minutes Played",
    ],
    # --- Distance ---
    "total_distance": [
        "Total Distance", "Distance", "Distance Covered", "Total Distance (m)",
        "Total Dist", "Distance (m)", "Total Distance (Absolute)",
    ],
    "distance_per_minute": [
        "Metres per Minute", "Meters per Minute", "Distance/Min", "m/min",
        "Distance Per Minute", "Meterage per Minute",
    ],
    "sprint_distance": [
        "Sprint Distance", "Sprinting Distance", "Sprint Distance (m)",
        "Distance Zone 6 (Absolute)", "Distance Zone 6 (Relative)",
        "Distance Zone 6",
    ],
    "high_intensity_distance": [
        "High Intensity Running", "HI Running", "High Speed Running",
        "High Intensity Distance", "HIR", "Distance Zone 5 (Absolute)",
        "Distance Zone 5 (Relative)", "Distance Zone 5",
    ],
    "hml_distance": [
        "HML Distance", "High Metabolic Load Distance", "HML Dist",
    ],
    # --- Speed ---
    "top_speed": [
        "Top Speed", "Max Speed", "Maximum Speed", "Top Speed (km/h)",
        "Top Speed (m/s)", "Max Speed (km/h)", "Peak Speed", "Vmax",
    ],
    "percentage_max_speed": [
        "Percentage of Max Speed", "% Max Speed", "Percent Max Speed",
        "Max Speed %",
    ],
    # --- Sprints / intensity counts ---
    "sprint_count": [
        "No. of Sprints", "Number of Sprints", "Sprint Count", "Sprints",
        "Entries Zone 6 (Relative)", "Entries Zone 6 (Absolute)",
    ],
    "high_intensity_events": [
        "No. of High Intensity Events", "Number of High Intensity Events",
        "High Intensity Events", "HI Events",
    ],
    "high_intensity_bursts_distance": [
        "High Intensity Bursts Total Distance",
        "HI Bursts Distance", "High Intensity Burst Distance",
    ],
    "high_intensity_bursts_count": [
        "Number Of High Intensity Bursts", "Number of High Intensity Bursts",
        "HI Bursts", "High Intensity Bursts",
    ],
    # --- Acceleration ---
    "accelerations": [
        "Accelerations", "Accelerations (Absolute)", "Acc", "No. of Accelerations",
    ],
    "decelerations": [
        "Decelerations", "Decelerations (Absolute)", "Dec", "No. of Decelerations",
    ],
    "acc_dec_total": [
        "ACC/DEC", "Acc/Dec", "Acceleration/Deceleration", "Total Acc Dec",
    ],
    "max_acceleration": [
        "Max Acceleration", "Maximum Acceleration", "Peak Acceleration",
    ],
    # --- Load ---
    "session_load": [
        "Session Load", "Player Load", "PlayerLoad", "Load", "Total Load",
    ],
    "edi_percentage": [
        "EDI %", "EDI", "EDI Percentage", "Equivalent Distance Index",
    ],
    # --- Zone metrics ---
    "distance_zone5": [
        "Distance Zone 5 (Absolute)", "Distance Zone 5 (Relative)",
        "Zone 5 Distance", "Distance Zone 5",
    ],
    "distance_zone6": [
        "Distance Zone 6 (Absolute)", "Distance Zone 6 (Relative)",
        "Zone 6 Distance", "Distance Zone 6",
    ],
    "entries_zone6": [
        "Entries Zone 6 (Relative)", "Entries Zone 6 (Absolute)",
        "Zone 6 Entries",
    ],
}

# Which source headers indicate a value is already in m/s (so we ×3.6 -> km/h).
_SPEED_MS_HEADERS = {"top speed", "top speed (m/s)"}
_SPEED_KMH_HEADERS = {"max speed", "top speed (km/h)", "max speed (km/h)",
                      "maximum speed", "peak speed"}

# Dutch + English month names for date extraction from filenames.
_MONTHS = {
    "jan": 1, "januari": 1, "january": 1,
    "feb": 2, "februari": 2, "february": 2,
    "mrt": 3, "maart": 3, "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "augustus": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


# ---------------------------------------------------------------------------
# B. Delimiter & file-type detection
# ---------------------------------------------------------------------------
def detect_csv_delimiter(file_path: str) -> str:
    """Auto-detect the delimiter of a CSV file.

    Game-report CSV exports frequently use a semicolon (``;``) — common in
    European locales — while Catapult exports use a comma. Reading a
    semicolon file with the default comma delimiter collapses every column
    into one, which breaks format detection. This helper inspects a sample of
    the file and returns the most likely delimiter, trying ``,  ;  \\t  |``.

    Falls back to a frequency count and finally to ``','`` so the caller never
    crashes on an exotic file.
    """
    import csv

    try:
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(8192)
    except (OSError, UnicodeDecodeError):
        # Binary/locked/odd-encoding file: let pandas deal with it later.
        return ","

    if not sample:
        return ","

    candidates = [",", ";", "\t", "|"]

    # 1) Try csv.Sniffer first (restricted to our candidate set).
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(candidates))
        if dialect.delimiter in candidates:
            return dialect.delimiter
    except (csv.Error, Exception):  # noqa: BLE001 - any sniff failure -> fallback
        pass

    # 2) Fallback: count occurrences on the header line (first non-empty row).
    header = next((ln for ln in sample.splitlines() if ln.strip()), "")
    counts = {d: header.count(d) for d in candidates}
    best, best_n = max(counts.items(), key=lambda kv: kv[1])
    return best if best_n > 0 else ","


# Signature columns that mark a "Game report" (zone-based full-match totals),
# whether exported as XLSX or CSV.
_GAME_REPORT_REQUIRED = ["Player Name", "Total Distance"]
_GAME_REPORT_SPEED = ["Max Speed", "Top Speed", "Maximum Speed", "Peak Speed"]
_GAME_REPORT_OPTIONAL = ["Distance Zone 5", "Distance Zone 6", "Total Time",
                         "Distance Zone 5 (Absolute)", "Distance Zone 6 (Absolute)",
                         "HML Distance", "EDI %"]


def is_game_report_csv(df: pd.DataFrame) -> bool:
    """Return True when ``df`` looks like a Game-report export.

    A Game report needs ``Player Name`` + ``Total Distance`` plus a speed
    column (``Max Speed`` / ``Top Speed``) OR at least one characteristic
    optional column (zone distances, total time, HML, EDI). Matching is
    case-insensitive and whitespace-tolerant.
    """
    norm_cols = {_norm_header(c) for c in df.columns}

    def has(name):
        return _norm_header(name) in norm_cols

    has_required = all(has(c) for c in _GAME_REPORT_REQUIRED)
    has_speed = any(has(c) for c in _GAME_REPORT_SPEED)
    has_optional = any(has(c) for c in _GAME_REPORT_OPTIONAL)
    return has_required and (has_speed or has_optional)


def detect_file_type(df: pd.DataFrame, filename: str) -> str:
    """Return ``'catapult_csv'``, ``'game_xlsx'``, ``'game_csv'`` or ``'unknown'``.

    Detection is based on the extension plus the signature columns described in
    the analysis report. Game reports are recognised in both XLSX and CSV form;
    the CSV variant is reported as ``'game_csv'`` but normalised identically.
    """
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    columns = {str(c).strip() for c in df.columns}

    # Catapult / PlayerTek CSV — per-period rows keyed by Athlete + Title.
    if ext == "csv" and "Athlete" in columns and "Title" in columns:
        return "catapult_csv"

    # Game-report CSV — same report type as the XLSX, exported as CSV.
    if ext == "csv" and is_game_report_csv(df):
        return "game_csv"

    # Game XLSX — zone metrics, full-match totals keyed by Player Name.
    if ext in ("xlsx", "xls") and "Player Name" in columns:
        return "game_xlsx"

    # Fallbacks on column patterns (extension-agnostic).
    if "Athlete" in columns and "Title" in columns:
        return "catapult_csv"
    if is_game_report_csv(df):
        # Match-report signature without a clear extension: classify by ext.
        return "game_csv" if ext == "csv" else "game_xlsx"
    if "Player Name" in columns and (
        "HML Distance" in columns or "EDI %" in columns
        or "Total Distance" in columns
    ):
        return "game_csv" if ext == "csv" else "game_xlsx"

    return "unknown"


# ---------------------------------------------------------------------------
# C. Column mapping engine
# ---------------------------------------------------------------------------
def map_columns(df: pd.DataFrame, aliases: dict = ALIASES) -> dict:
    """Map canonical field names to the actual column found in ``df``.

    Matching is case-insensitive and whitespace-tolerant. When several aliases
    of one field are present (e.g. Zone 6 Absolute *and* Relative) the first
    alias in the list wins, preserving the documented priority order.

    Returns ``{canonical_field: source_column_name}`` for fields that exist.
    """
    # Build a lookup of normalised header -> original header.
    norm_to_orig = {}
    for col in df.columns:
        norm_to_orig[_norm_header(col)] = col

    mapping = {}
    for field, names in aliases.items():
        for alias in names:
            key = _norm_header(alias)
            if key in norm_to_orig:
                mapping[field] = norm_to_orig[key]
                break
    return mapping


def _norm_header(h) -> str:
    """Normalise a header for matching: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", str(h).strip().lower())


# ---------------------------------------------------------------------------
# D. Normalisation helpers
# ---------------------------------------------------------------------------
def normalize_speed_to_kmh(value, source_unit: str):
    """Convert a speed to km/h. ``source_unit`` is ``'m/s'`` or ``'km/h'``."""
    v = _to_float(value)
    if v is None:
        return None
    if source_unit == "m/s":
        return round(v * 3.6, 2)
    return round(v, 2)


def normalize_edi_to_percentage(value):
    """Normalise EDI to a 0–100 percentage.

    Values that look like a 0–1 ratio (<= 1.5) are multiplied by 100; values
    that already look like a percentage are returned unchanged.
    """
    v = _to_float(value)
    if v is None:
        return None
    if v <= 1.5:
        return round(v * 100.0, 1)
    return round(v, 1)


def normalize_player_name(name) -> str:
    """Title-case a player name, keeping apostrophes (D'HAENE -> D'Haene).

    Returns "" for missing/blank values (None, NaN, or strings that are just
    a NaN placeholder) so that nameless rows are dropped instead of being
    stored as a phantom "Nan" player.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    raw = str(name).strip()
    if not raw or raw.lower() in {"nan", "none", "null", "n/a", "na", "-"}:
        return ""
    parts = raw.split()
    out = []
    for part in parts:
        if "'" in part:
            out.append("'".join(p.capitalize() for p in part.split("'")))
        elif "-" in part:
            out.append("-".join(p.capitalize() for p in part.split("-")))
        else:
            out.append(part.capitalize())
    return " ".join(out)


def normalize_period(value) -> str:
    """Map a raw period label to a canonical one."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Full Match"
    s = str(value).strip().lower()
    mapping = {
        "first half": "First Half", "1st half": "First Half",
        "1e helft": "First Half", "eerste helft": "First Half",
        "second half": "Second Half", "2nd half": "Second Half",
        "2e helft": "Second Half", "tweede helft": "Second Half",
        "full match": "Full Match", "whole session": "Full Match",
        "full session": "Full Match", "total": "Full Match",
    }
    return mapping.get(s, str(value).strip() or "Full Match")


def _to_float(value):
    """Best-effort float conversion (handles text-stored numbers, commas)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and pd.isna(value)) else float(value)
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-", "n/a", "na"}:
        return None
    s = s.replace(",", ".") if s.count(",") == 1 and s.count(".") == 0 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _time_to_minutes(value):
    """Convert a HH:MM:SS / datetime.time / timedelta to float minutes."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, _dt.time):
        return round(value.hour * 60 + value.minute + value.second / 60.0, 2)
    if isinstance(value, _dt.timedelta):
        return round(value.total_seconds() / 60.0, 2)
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d+):(\d{1,2})(?::(\d{1,2}))?", s)
    if m:
        h = int(m.group(1)); mi = int(m.group(2)); se = int(m.group(3) or 0)
        return round(h * 60 + mi + se / 60.0, 2)
    return _to_float(value)


def _parse_iso(value):
    """Parse an ISO-8601 timestamp; return (iso_string, date_string) or (None, None)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(s)
        return dt.isoformat(), dt.date().isoformat()
    except ValueError:
        # Fall back to a plain date match.
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value))
        if m:
            return str(value), m.group(0)
        return str(value), None


def _date_from_filename(filename: str):
    """Extract an ISO date from a filename (Dutch/English month names or numeric)."""
    if not filename:
        return None
    name = os.path.basename(filename)
    # Pattern: "25 Oktober 2025" / "1 Mar 26" / "01 March 2026"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{2,4})", name)
    if m:
        day = int(m.group(1)); mon = _MONTHS.get(m.group(2).lower()); yr = int(m.group(3))
        if mon:
            if yr < 100:
                yr += 2000
            try:
                return _dt.date(yr, mon, day).isoformat()
            except ValueError:
                return None
    # Pattern: "2026-03-01"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        return m.group(0)
    return None


def _session_name_from_filename(filename: str) -> str:
    if not filename:
        return "Physical session"
    base = os.path.basename(filename)
    base = re.sub(r"\.(csv|xlsx|xls)$", "", base, flags=re.IGNORECASE)
    return base.strip() or "Physical session"


# ---------------------------------------------------------------------------
# E. Main parse function
# ---------------------------------------------------------------------------
def _load_dataframe(file_path: str) -> pd.DataFrame:
    ext = file_path.lower().rsplit(".", 1)[-1]
    try:
        if ext in ("xlsx", "xls"):
            return pd.read_excel(file_path)
        # CSV: auto-detect the delimiter (comma, semicolon, tab or pipe) so
        # European semicolon-separated Game-report exports are read correctly
        # instead of collapsing into one column.
        delimiter = detect_csv_delimiter(file_path)
        return pd.read_csv(file_path, delimiter=delimiter, encoding="utf-8-sig")
    except Exception as e:  # noqa
        raise PhysicalParseError(f"Could not read file: {e}") from e


def _unknown_format_message(raw: pd.DataFrame) -> str:
    """Build a clear, actionable error when the GPS format is not recognised.

    Lists the expected signature columns per supported system alongside the
    columns actually found in the uploaded file, so the coach can immediately
    see the mismatch instead of a vague "unrecognised format" message.
    """
    found = [str(c).strip() for c in raw.columns]
    found_str = ", ".join(found) if found else "(geen kolommen gevonden)"
    return (
        "Onverwachte kolommen in bestand — het GPS-formaat is niet herkend.\n\n"
        "**Ondersteunde formaten (één van deze sets):**\n"
        "- **Catapult / PlayerTek (CSV):** o.a. `Athlete`, `Title` "
        "(per-periode rijen)\n"
        "- **Wedstrijd-rapport (XLSX):** o.a. `Player Name`, plus bijv. "
        "`Total Distance`, `Max Speed`, `HML Distance` of `EDI %`\n"
        "- **Wedstrijd-rapport (CSV):** zelfde kolommen als de XLSX "
        "(`Player Name`, `Total Distance`, `Max Speed`, `Distance Zone 5/6`); "
        "scheidingsteken `,` of `;` wordt automatisch herkend\n\n"
        "**Gevonden kolommen in jouw bestand:**\n"
        f"- {found_str}\n\n"
        "💡 *Tip: controleer of je het juiste GPS-systeem exporteert en of de "
        "kolomnamen (eventueel in de eerste rij) niet zijn aangepast.*"
    )


def parse_physical_file(file_path: str, original_name: str | None = None):
    """Parse a physical-data file into a standardised DataFrame + report.

    Returns ``(df, report)`` where ``df`` always has the :data:`STANDARD_FIELDS`
    columns (missing metrics filled with ``NaN``) plus a ``data_source`` and
    ``raw_data`` column, and ``report`` is the validation dict from
    :func:`validate_and_warn`.
    """
    filename = original_name or os.path.basename(file_path)
    raw = _load_dataframe(file_path)
    if raw.empty:
        raise PhysicalParseError("File contains no data rows.")

    file_type = detect_file_type(raw, filename)
    if file_type == "unknown":
        raise PhysicalParseError(_unknown_format_message(raw))

    mapping = map_columns(raw, ALIASES)

    # Decide the unit of the speed source column once (per file).
    speed_col = mapping.get("top_speed")
    speed_unit = "km/h"
    if speed_col is not None:
        h = _norm_header(speed_col)
        if h in _SPEED_MS_HEADERS or file_type == "catapult_csv":
            speed_unit = "m/s"
        if h in _SPEED_KMH_HEADERS or file_type in ("game_xlsx", "game_csv"):
            speed_unit = "km/h"

    session_name = _session_name_from_filename(filename)
    file_date = _date_from_filename(filename)

    records = []
    for _, src in raw.iterrows():
        rec = {f: None for f in STANDARD_FIELDS}

        # --- text / context fields ---
        if "player_name" in mapping:
            rec["player_name"] = normalize_player_name(src[mapping["player_name"]])
        rec["period"] = normalize_period(
            src[mapping["period"]] if "period" in mapping else None)
        rec["session_name"] = session_name

        start_iso = end_iso = None
        date_from_row = None
        if "start_time" in mapping:
            start_iso, date_from_row = _parse_iso(src[mapping["start_time"]])
        if "end_time" in mapping:
            end_iso, _ = _parse_iso(src[mapping["end_time"]])
        rec["start_time"] = start_iso
        rec["end_time"] = end_iso
        rec["match_date"] = date_from_row or file_date

        # total time: explicit column, else derive from start/end.
        if "total_time_minutes" in mapping:
            rec["total_time_minutes"] = _time_to_minutes(src[mapping["total_time_minutes"]])
        elif start_iso and end_iso:
            try:
                d = _dt.datetime.fromisoformat(end_iso) - _dt.datetime.fromisoformat(start_iso)
                rec["total_time_minutes"] = round(d.total_seconds() / 60.0, 2)
            except Exception:  # noqa
                pass

        # --- numeric metrics (generic) ---
        for field in NUMERIC_FIELDS:
            if field in ("top_speed", "top_speed_ms", "edi_percentage",
                         "total_time_minutes"):
                continue  # handled specially
            if field in mapping:
                rec[field] = _to_float(src[mapping[field]])

        # --- speed (normalise to km/h, keep m/s when source is m/s) ---
        if speed_col is not None:
            raw_speed = _to_float(src[speed_col])
            rec["top_speed"] = normalize_speed_to_kmh(raw_speed, speed_unit)
            rec["top_speed_ms"] = (round(raw_speed, 2) if speed_unit == "m/s"
                                   and raw_speed is not None
                                   else (round(raw_speed / 3.6, 2)
                                         if raw_speed is not None else None))

        # --- EDI (ratio -> percentage) ---
        if "edi_percentage" in mapping:
            rec["edi_percentage"] = normalize_edi_to_percentage(src[mapping["edi_percentage"]])

        # --- acc/dec total: derive when absent ---
        if rec["acc_dec_total"] is None and rec["accelerations"] is not None \
                and rec["decelerations"] is not None:
            rec["acc_dec_total"] = rec["accelerations"] + rec["decelerations"]

        rec["data_source"] = file_type
        rec["raw_data"] = json.dumps(
            {str(k): (None if (isinstance(v, float) and pd.isna(v)) else
                      (v.isoformat() if isinstance(v, (_dt.time, _dt.datetime)) else v))
             for k, v in src.to_dict().items()},
            default=str,
        )
        records.append(rec)

    out = pd.DataFrame(records)
    # Drop rows without a player name (e.g. trailing totals).
    out = out[out["player_name"].astype(bool)].reset_index(drop=True)

    report = validate_and_warn(out, set(mapping.keys()), filename, file_type)
    return out, report


# ---------------------------------------------------------------------------
# F. Validation & warnings
# ---------------------------------------------------------------------------
def validate_and_warn(df, found_fields, filename, file_type):
    """Build a validation report listing found / missing metrics.

    ``found_fields`` is the set of canonical fields that were mapped from the
    source file. Warnings are printed to stdout and returned in the report.
    """
    all_metric_fields = [f for f in STANDARD_FIELDS if f not in _TEXT_FIELDS
                         and f not in ("top_speed_ms", "acc_dec_total")]
    missing = [f for f in all_metric_fields if f not in found_fields]
    present = sorted(found_fields)

    warnings = []
    for f in missing:
        warnings.append(f"metric '{f}' not present in this file")

    report = {
        "filename": filename,
        "file_type": file_type,
        "rows": int(len(df)),
        "players": int(df["player_name"].nunique()) if not df.empty else 0,
        "periods": sorted(df["period"].dropna().unique().tolist()) if not df.empty else [],
        "found_metrics": present,
        "missing_metrics": missing,
        "warnings": warnings,
    }

    print(f"[physical_parser] {filename} → {file_type}: "
          f"{report['rows']} rows, {report['players']} players, "
          f"periods={report['periods']}")
    if warnings:
        for w in warnings:
            print(f"  ⚠️  {w}")
    return report
