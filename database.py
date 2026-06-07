"""
database.py — SQLite schema, initialisation and query helpers.

The schema is intentionally multi-club ready even though the MVP runs as a
single club. All writes go through small helper functions so the rest of the
app never builds SQL by hand.
"""

import os
import sqlite3
from datetime import datetime

import metrics as M

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "football_impact.db")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS clubs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS style_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
    UNIQUE (club_id, name)
);

CREATE TABLE IF NOT EXISTS metric_weights (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL,
    metric_key  TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 0,
    category    TEXT,
    FOREIGN KEY (profile_id) REFERENCES style_profiles(id) ON DELETE CASCADE,
    UNIQUE (profile_id, metric_key)
);

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    age_group   TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (name, age_group)
);

CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL,
    opponent    TEXT NOT NULL,
    match_date  TEXT NOT NULL,
    home_score  INTEGER,
    away_score  INTEGER,
    is_home     INTEGER NOT NULL DEFAULT 1,
    season      TEXT,
    source_file TEXT,
    upload_hash TEXT,
    session_type TEXT NOT NULL DEFAULT 'match',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    UNIQUE (team_id, opponent, match_date)
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    position        TEXT,
    status          TEXT NOT NULL DEFAULT 'Starter',
    came_on_as      TEXT,
    minutes_played  REAL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
    UNIQUE (match_id, player_id)
);

-- Position-based coaching profiles (Sprint 2). Each profile stores an
-- importance score (0-10) per (position, category). Kept separate from the
-- legacy metric_weights table so existing playing-style profiles still work.
CREATE TABLE IF NOT EXISTS position_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
    UNIQUE (club_id, name)
);

CREATE TABLE IF NOT EXISTS position_weights (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    position_profile_id INTEGER NOT NULL,
    position            TEXT NOT NULL,
    category            TEXT NOT NULL,
    importance          REAL NOT NULL DEFAULT 5,
    FOREIGN KEY (position_profile_id) REFERENCES position_profiles(id) ON DELETE CASCADE,
    UNIQUE (position_profile_id, position, category)
);

CREATE TABLE IF NOT EXISTS stat_values (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    player_match_stats_id   INTEGER NOT NULL,
    metric_key              TEXT NOT NULL,
    value                   REAL,
    FOREIGN KEY (player_match_stats_id) REFERENCES player_match_stats(id) ON DELETE CASCADE,
    UNIQUE (player_match_stats_id, metric_key)
);

CREATE TABLE IF NOT EXISTS physical_data (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id                       INTEGER,
    match_id                        INTEGER,            -- optional link to a match (session)
    player_name                     TEXT,               -- as parsed (kept for standalone data)
    period                          TEXT NOT NULL DEFAULT 'Full Match',
    session_name                    TEXT,
    match_date                      TEXT,
    start_time                      TEXT,
    end_time                        TEXT,
    total_time_minutes              REAL,
    -- distance metrics (m)
    total_distance                  REAL,
    distance_per_minute             REAL,
    sprint_distance                 REAL,
    high_intensity_distance         REAL,
    hml_distance                    REAL,
    -- speed metrics
    top_speed                       REAL,               -- km/h
    top_speed_ms                    REAL,               -- m/s
    percentage_max_speed            REAL,               -- %
    -- sprint / intensity counts
    sprint_count                    REAL,
    high_intensity_events           REAL,
    high_intensity_bursts_distance  REAL,
    high_intensity_bursts_count     REAL,
    -- acceleration metrics
    accelerations                   REAL,
    decelerations                   REAL,
    acc_dec_total                   REAL,
    max_acceleration                REAL,               -- m/s²
    -- load metrics
    session_load                    REAL,
    edi_percentage                  REAL,               -- %
    -- zone metrics
    distance_zone5                  REAL,
    distance_zone6                  REAL,
    entries_zone6                   REAL,
    -- metadata / traceability
    data_source                     TEXT,
    source_filename                 TEXT,
    uploaded_at                     TEXT,
    raw_data                        TEXT,               -- JSON of the original row
    -- session classification: 'match' | 'training' | 'unlinked'
    session_type                    TEXT NOT NULL DEFAULT 'unlinked',
    FOREIGN KEY (player_id) REFERENCES players(id),
    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL,
    UNIQUE (player_name, session_name, period, data_source)
);

CREATE INDEX IF NOT EXISTS idx_physical_player  ON physical_data(player_id);
CREATE INDEX IF NOT EXISTS idx_physical_match   ON physical_data(match_id);
CREATE INDEX IF NOT EXISTS idx_physical_date    ON physical_data(match_date);
CREATE INDEX IF NOT EXISTS idx_physical_period  ON physical_data(period);
CREATE INDEX IF NOT EXISTS idx_physical_session_type ON physical_data(session_type);

CREATE INDEX IF NOT EXISTS idx_matches_team   ON matches(team_id);
CREATE INDEX IF NOT EXISTS idx_matches_date   ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_pms_match      ON player_match_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_pms_player     ON player_match_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_sv_pms         ON stat_values(player_match_stats_id);
CREATE INDEX IF NOT EXISTS idx_sv_metric      ON stat_values(metric_key);
CREATE INDEX IF NOT EXISTS idx_weights_profile ON metric_weights(profile_id);
"""


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db(db_path=DB_PATH):
    """Create schema and seed default club + 4 style profiles (idempotent)."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        club_id = ensure_club(conn, "Default Club")
        seed_default_profiles(conn, club_id)
        seed_default_position_profiles(conn, club_id)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    """Idempotent lightweight migrations for existing databases."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(matches)").fetchall()}
    if "upload_hash" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN upload_hash TEXT")
    if "source_file" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN source_file TEXT")
    # Phase 10 — session architecture prep (matches double as 'sessions').
    if "session_type" not in cols:
        conn.execute(
            "ALTER TABLE matches ADD COLUMN session_type TEXT NOT NULL DEFAULT 'match'"
        )

    # Phase 2 — player availability status.
    pms_cols = {
        r["name"] for r in conn.execute(
            "PRAGMA table_info(player_match_stats)"
        ).fetchall()
    }
    if "status" not in pms_cols:
        conn.execute(
            "ALTER TABLE player_match_stats ADD COLUMN status TEXT NOT NULL DEFAULT 'Starter'"
        )
    if "came_on_as" not in pms_cols:
        conn.execute("ALTER TABLE player_match_stats ADD COLUMN came_on_as TEXT")

    # Physical data — session classification (match / training / unlinked).
    pd_cols = {
        r["name"] for r in conn.execute(
            "PRAGMA table_info(physical_data)"
        ).fetchall()
    }
    if "session_type" not in pd_cols:
        conn.execute(
            "ALTER TABLE physical_data "
            "ADD COLUMN session_type TEXT NOT NULL DEFAULT 'unlinked'"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_physical_session_type "
            "ON physical_data(session_type)"
        )
        print("✓ Migrated: added session_type to physical_data")
    conn.commit()


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def ensure_club(conn, name):
    row = conn.execute("SELECT id FROM clubs WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO clubs (name, created_at) VALUES (?, ?)", (name, _now())
    )
    return cur.lastrowid


def seed_default_profiles(conn, club_id):
    """Insert the 4 default profiles + their metric weights if not present."""
    existing = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM style_profiles WHERE club_id = ?", (club_id,)
        ).fetchall()
    }
    for name, spec in M.DEFAULT_PROFILES.items():
        if name in existing:
            continue
        cur = conn.execute(
            """INSERT INTO style_profiles (club_id, name, description, is_default, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (club_id, name, spec["description"], 1 if spec["is_default"] else 0, _now()),
        )
        profile_id = cur.lastrowid
        rows = M.build_profile_weights(name)
        conn.executemany(
            """INSERT INTO metric_weights (profile_id, metric_key, weight, category)
               VALUES (?, ?, ?, ?)""",
            [(profile_id, k, w, c) for (k, w, c) in rows],
        )


# ---------------------------------------------------------------------------
# Position-based profiles (Sprint 2)
# ---------------------------------------------------------------------------
def seed_default_position_profiles(conn, club_id):
    """Seed a single default position profile with framework category defaults."""
    existing = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM position_profiles WHERE club_id = ?", (club_id,)
        ).fetchall()
    }
    name = "Position-Based (Default)"
    if name in existing:
        return
    cur = conn.execute(
        """INSERT INTO position_profiles (club_id, name, description, is_default, created_at)
           VALUES (?, ?, ?, 1, ?)""",
        (club_id, name,
         "Default per-position category importances (0-10) used to score impact "
         "according to what matters for each position.", _now()),
    )
    pid = cur.lastrowid
    defaults = M.default_position_category_importances()
    rows = [
        (pid, pos, cat, float(imp))
        for pos, cats in defaults.items()
        for cat, imp in cats.items()
    ]
    conn.executemany(
        """INSERT INTO position_weights (position_profile_id, position, category, importance)
           VALUES (?, ?, ?, ?)""",
        rows,
    )


def list_position_profiles(conn, club_id=None):
    if club_id is None:
        return conn.execute(
            "SELECT * FROM position_profiles ORDER BY id"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM position_profiles WHERE club_id=? ORDER BY id", (club_id,)
    ).fetchall()


def get_position_profile_importances(conn, position_profile_id):
    """Return {position: {category: importance}} for a position profile."""
    rows = conn.execute(
        "SELECT position, category, importance FROM position_weights WHERE position_profile_id=?",
        (position_profile_id,),
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["position"], {})[r["category"]] = r["importance"]
    # ensure every position/category exists (fall back to framework defaults)
    defaults = M.default_position_category_importances()
    for pos, cats in defaults.items():
        out.setdefault(pos, {})
        for cat, imp in cats.items():
            out[pos].setdefault(cat, imp)
    return out


def update_position_profile_importances(conn, position_profile_id, importances):
    """importances: {position: {category: importance(0-10)}}."""
    for pos, cats in importances.items():
        for cat, imp in cats.items():
            conn.execute(
                """INSERT INTO position_weights
                   (position_profile_id, position, category, importance)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(position_profile_id, position, category)
                   DO UPDATE SET importance=excluded.importance""",
                (position_profile_id, pos, cat, float(imp)),
            )
    conn.commit()


def create_position_profile(conn, club_id, name, description, importances,
                            is_default=False):
    cur = conn.execute(
        """INSERT INTO position_profiles (club_id, name, description, is_default, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (club_id, name, description, 1 if is_default else 0, _now()),
    )
    pid = cur.lastrowid
    rows = [
        (pid, pos, cat, float(imp))
        for pos, cats in importances.items()
        for cat, imp in cats.items()
    ]
    conn.executemany(
        """INSERT INTO position_weights (position_profile_id, position, category, importance)
           VALUES (?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return pid


def reset_position_profile_to_default(conn, position_profile_id):
    """Reset all importances of a position profile to the framework defaults."""
    defaults = M.default_position_category_importances()
    conn.execute(
        "DELETE FROM position_weights WHERE position_profile_id=?",
        (position_profile_id,),
    )
    rows = [
        (position_profile_id, pos, cat, float(imp))
        for pos, cats in defaults.items()
        for cat, imp in cats.items()
    ]
    conn.executemany(
        """INSERT INTO position_weights (position_profile_id, position, category, importance)
           VALUES (?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Lookups / upserts used by the parser
# ---------------------------------------------------------------------------
def get_or_create_team(conn, name, age_group=None):
    row = conn.execute(
        "SELECT id FROM teams WHERE name = ? AND IFNULL(age_group,'') = IFNULL(?, '')",
        (name, age_group),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO teams (name, age_group, created_at) VALUES (?, ?, ?)",
        (name, age_group, _now()),
    )
    return cur.lastrowid


def get_or_create_player(conn, name):
    row = conn.execute("SELECT id FROM players WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO players (name, created_at) VALUES (?, ?)", (name, _now())
    )
    return cur.lastrowid


def find_match(conn, team_id, opponent, match_date):
    return conn.execute(
        "SELECT id FROM matches WHERE team_id=? AND opponent=? AND match_date=?",
        (team_id, opponent, match_date),
    ).fetchone()


def create_match(conn, team_id, opponent, match_date, home_score, away_score,
                 is_home, season, source_file, upload_hash=None,
                 session_type="match"):
    cur = conn.execute(
        """INSERT INTO matches
           (team_id, opponent, match_date, home_score, away_score, is_home,
            season, source_file, upload_hash, session_type, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (team_id, opponent, match_date, home_score, away_score,
         1 if is_home else 0, season, source_file, upload_hash,
         session_type or "match", _now()),
    )
    return cur.lastrowid


def find_match_by_hash(conn, upload_hash):
    """Return the first match row sharing this upload hash, or None."""
    if not upload_hash:
        return None
    return conn.execute(
        "SELECT * FROM matches WHERE upload_hash = ? ORDER BY id LIMIT 1",
        (upload_hash,),
    ).fetchone()


def cleanup_orphaned_players(conn):
    """Delete players that have no remaining player_match_stats rows.

    Returns the number of player records removed. Caller controls commit.
    """
    # A player is only "orphaned" when nothing else references them. Besides
    # player_match_stats we must also exclude players still referenced by
    # physical_data (player_id), otherwise deleting them raises a FOREIGN KEY
    # constraint failure (physical_data.player_id is a RESTRICT FK). Such a
    # player keeps GPS data, so it is intentionally preserved.
    orphan_rows = conn.execute(
        """SELECT p.id FROM players p
           WHERE NOT EXISTS (
               SELECT 1 FROM player_match_stats pms WHERE pms.player_id = p.id
           )
           AND NOT EXISTS (
               SELECT 1 FROM physical_data pd WHERE pd.player_id = p.id
           )"""
    ).fetchall()
    orphan_ids = [r["id"] for r in orphan_rows]
    for pid in orphan_ids:
        conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    return len(orphan_ids)


def _match_delete_counts(conn, match_id):
    """Count rows that will be removed when deleting one match."""
    pms_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM player_match_stats WHERE match_id = ?", (match_id,)
        ).fetchall()
    ]
    n_pms = len(pms_ids)
    n_sv = 0
    if pms_ids:
        placeholders = ",".join("?" * len(pms_ids))
        n_sv = conn.execute(
            f"SELECT COUNT(*) c FROM stat_values WHERE player_match_stats_id IN ({placeholders})",
            pms_ids,
        ).fetchone()["c"]
    return n_pms, n_sv


def delete_match(conn, match_id, cleanup_players=True):
    """Cascade-delete a single match within a transaction.

    Removes the match, its player_match_stats and stat_values (via FK cascade),
    then optionally cleans up players left with zero matches.

    Returns a dict of deletion counts. Rolls back on any error.
    """
    try:
        n_pms, n_sv = _match_delete_counts(conn, match_id)
        # ON DELETE CASCADE handles player_match_stats + stat_values, but we
        # delete explicitly so behaviour is identical regardless of PRAGMA state.
        pms_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM player_match_stats WHERE match_id = ?", (match_id,)
            ).fetchall()
        ]
        if pms_ids:
            placeholders = ",".join("?" * len(pms_ids))
            conn.execute(
                f"DELETE FROM stat_values WHERE player_match_stats_id IN ({placeholders})",
                pms_ids,
            )
        conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (match_id,))
        # Physical sessions linked to this match are NOT deleted (GPS data is
        # uploaded separately and valuable); instead they are unlinked so we
        # never leave a session with session_type='match' pointing at a match
        # that no longer exists. The match_id FK is ON DELETE SET NULL, but we
        # also reset session_type explicitly to keep the state consistent.
        conn.execute(
            "UPDATE physical_data SET match_id = NULL, session_type = 'unlinked' "
            "WHERE match_id = ?",
            (match_id,),
        )
        conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
        n_players = cleanup_orphaned_players(conn) if cleanup_players else 0
        conn.commit()
        return {"matches": 1, "player_stats": n_pms,
                "stat_values": n_sv, "players": n_players}
    except Exception:
        conn.rollback()
        raise


def delete_matches_by_source(conn, source_file):
    """Delete every match that came from a given source PDF (cascade).

    Returns aggregated deletion counts. Transaction-safe.
    """
    try:
        rows = conn.execute(
            "SELECT id FROM matches WHERE IFNULL(source_file,'') = IFNULL(?, '')",
            (source_file,),
        ).fetchall()
        match_ids = [r["id"] for r in rows]
        totals = {"matches": 0, "player_stats": 0, "stat_values": 0, "players": 0}
        for mid in match_ids:
            n_pms, n_sv = _match_delete_counts(conn, mid)
            pms_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM player_match_stats WHERE match_id = ?", (mid,)
                ).fetchall()
            ]
            if pms_ids:
                placeholders = ",".join("?" * len(pms_ids))
                conn.execute(
                    f"DELETE FROM stat_values WHERE player_match_stats_id IN ({placeholders})",
                    pms_ids,
                )
            conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (mid,))
            # Unlink (don't delete) any linked physical sessions — see delete_match.
            conn.execute(
                "UPDATE physical_data SET match_id = NULL, session_type = 'unlinked' "
                "WHERE match_id = ?",
                (mid,),
            )
            conn.execute("DELETE FROM matches WHERE id = ?", (mid,))
            totals["matches"] += 1
            totals["player_stats"] += n_pms
            totals["stat_values"] += n_sv
        # clean orphans once at the end
        totals["players"] = cleanup_orphaned_players(conn)
        conn.commit()
        return totals
    except Exception:
        conn.rollback()
        raise


def upsert_player_match_stats(conn, match_id, player_id, position, minutes_played,
                              status="Starter", came_on_as=None):
    cur = conn.execute(
        """INSERT INTO player_match_stats
             (match_id, player_id, position, status, came_on_as, minutes_played, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(match_id, player_id) DO UPDATE SET
             position=excluded.position, status=excluded.status,
             came_on_as=excluded.came_on_as, minutes_played=excluded.minutes_played""",
        (match_id, player_id, position, status or "Starter", came_on_as,
         minutes_played, _now()),
    )
    if cur.lastrowid:
        row = conn.execute(
            "SELECT id FROM player_match_stats WHERE match_id=? AND player_id=?",
            (match_id, player_id),
        ).fetchone()
        return row["id"]
    return cur.lastrowid


def update_player_match_position(conn, player_match_stat_id, new_position):
    """Update the ``position`` of a single player_match_stats row.

    Used by the Match Dashboard position-editing flow. Impact scores are
    computed live from this field, so changing it here is sufficient for the
    new position to flow through to all impact calculations and the pitch
    visualisation on the next page rerun.

    Returns True if a row was updated, False otherwise.
    """
    cur = conn.execute(
        "UPDATE player_match_stats SET position = ? WHERE id = ?",
        (new_position, player_match_stat_id),
    )
    conn.commit()
    return cur.rowcount > 0


def save_stat_values(conn, pms_id, stat_dict):
    """stat_dict: {metric_key: value}. Overwrites existing for this pms."""
    conn.execute("DELETE FROM stat_values WHERE player_match_stats_id = ?", (pms_id,))
    conn.executemany(
        """INSERT INTO stat_values (player_match_stats_id, metric_key, value)
           VALUES (?, ?, ?)""",
        [(pms_id, k, (None if v is None else float(v))) for k, v in stat_dict.items()],
    )


# ---------------------------------------------------------------------------
# Read helpers used by the UI
# ---------------------------------------------------------------------------
def list_profiles(conn, club_id=None):
    if club_id is None:
        return conn.execute("SELECT * FROM style_profiles ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM style_profiles WHERE club_id=? ORDER BY id", (club_id,)
    ).fetchall()


def get_default_club_id(conn):
    row = conn.execute("SELECT id FROM clubs ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def get_profile_weights(conn, profile_id):
    """Return {metric_key: weight} for a profile."""
    rows = conn.execute(
        "SELECT metric_key, weight FROM metric_weights WHERE profile_id=?",
        (profile_id,),
    ).fetchall()
    return {r["metric_key"]: r["weight"] for r in rows}


def update_profile_weights(conn, profile_id, weights):
    """weights: {metric_key: weight}."""
    for k, w in weights.items():
        cat = M.METRIC_BY_KEY.get(k, {}).get("category")
        conn.execute(
            """INSERT INTO metric_weights (profile_id, metric_key, weight, category)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(profile_id, metric_key) DO UPDATE SET weight=excluded.weight""",
            (profile_id, k, float(w), cat),
        )
    conn.commit()


def create_profile(conn, club_id, name, description, weights, is_default=False):
    cur = conn.execute(
        """INSERT INTO style_profiles (club_id, name, description, is_default, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (club_id, name, description, 1 if is_default else 0, _now()),
    )
    pid = cur.lastrowid
    conn.executemany(
        """INSERT INTO metric_weights (profile_id, metric_key, weight, category)
           VALUES (?, ?, ?, ?)""",
        [(pid, k, float(w), M.METRIC_BY_KEY.get(k, {}).get("category"))
         for k, w in weights.items()],
    )
    conn.commit()
    return pid


def reset_profile_to_default(conn, profile_id, profile_name):
    """Reset weights to the framework defaults (only works for the 4 named defaults)."""
    if profile_name not in M.DEFAULT_PROFILES:
        return False
    rows = M.build_profile_weights(profile_name)
    conn.execute("DELETE FROM metric_weights WHERE profile_id=?", (profile_id,))
    conn.executemany(
        """INSERT INTO metric_weights (profile_id, metric_key, weight, category)
           VALUES (?, ?, ?, ?)""",
        [(profile_id, k, w, c) for (k, w, c) in rows],
    )
    conn.commit()
    return True


def list_matches(conn):
    return conn.execute(
        """SELECT m.*, t.name AS team_name, t.age_group
           FROM matches m JOIN teams t ON t.id = m.team_id
           ORDER BY m.match_date DESC"""
    ).fetchall()


def list_matches_detailed(conn):
    """Matches enriched with player count and source PDF for management views."""
    return conn.execute(
        """SELECT m.*, t.name AS team_name, t.age_group,
                  (SELECT COUNT(*) FROM player_match_stats pms
                   WHERE pms.match_id = m.id) AS player_count
           FROM matches m JOIN teams t ON t.id = m.team_id
           ORDER BY m.match_date DESC"""
    ).fetchall()


def list_upload_history(conn):
    """Group matches by their source PDF for the upload-history table.

    Returns a list of dicts: source_file, n_matches, first_uploaded,
    last_uploaded, match_ids.
    """
    rows = conn.execute(
        """SELECT m.id, m.source_file, m.created_at, m.match_date, m.opponent
           FROM matches m
           ORDER BY m.created_at DESC, m.id DESC"""
    ).fetchall()
    groups = {}
    order = []
    for r in rows:
        key = r["source_file"] or "Unknown"
        if key not in groups:
            groups[key] = {
                "source_file": key,
                "n_matches": 0,
                "first_uploaded": r["created_at"],
                "last_uploaded": r["created_at"],
                "match_ids": [],
                "matches": [],
            }
            order.append(key)
        g = groups[key]
        g["n_matches"] += 1
        g["match_ids"].append(r["id"])
        g["matches"].append({
            "id": r["id"], "match_date": r["match_date"], "opponent": r["opponent"],
        })
        if r["created_at"] and r["created_at"] < g["first_uploaded"]:
            g["first_uploaded"] = r["created_at"]
        if r["created_at"] and r["created_at"] > g["last_uploaded"]:
            g["last_uploaded"] = r["created_at"]
    return [groups[k] for k in order]


def get_match(conn, match_id):
    return conn.execute(
        """SELECT m.*, t.name AS team_name, t.age_group
           FROM matches m JOIN teams t ON t.id = m.team_id WHERE m.id=?""",
        (match_id,),
    ).fetchone()


def get_match_player_stats(conn, match_id):
    """Return list of dicts: player stats rows for a match with stat values folded in."""
    pms_rows = conn.execute(
        """SELECT pms.id AS pms_id, pms.position, pms.status, pms.came_on_as,
                  pms.minutes_played, p.id AS player_id, p.name AS player_name
           FROM player_match_stats pms JOIN players p ON p.id = pms.player_id
           WHERE pms.match_id=?""",
        (match_id,),
    ).fetchall()
    result = []
    for r in pms_rows:
        stats = {
            sv["metric_key"]: sv["value"]
            for sv in conn.execute(
                "SELECT metric_key, value FROM stat_values WHERE player_match_stats_id=?",
                (r["pms_id"],),
            ).fetchall()
        }
        result.append({
            "pms_id": r["pms_id"], "player_id": r["player_id"],
            "player_name": r["player_name"], "position": r["position"],
            "status": (r["status"] or "Starter"), "came_on_as": r["came_on_as"],
            "minutes_played": r["minutes_played"], "stats": stats,
        })
    return result


def list_players(conn):
    return conn.execute(
        """SELECT p.id, p.name, COUNT(pms.id) AS appearances
           FROM players p LEFT JOIN player_match_stats pms ON pms.player_id = p.id
           GROUP BY p.id ORDER BY p.name"""
    ).fetchall()


def get_player_match_history(conn, player_id):
    """Return chronological list of {match info + stats} for a player."""
    rows = conn.execute(
        """SELECT pms.id AS pms_id, pms.position, pms.status, pms.came_on_as,
                  pms.minutes_played,
                  m.id AS match_id, m.opponent, m.match_date, m.home_score,
                  m.away_score, m.is_home, m.season, m.session_type,
                  t.name AS team_name
           FROM player_match_stats pms
           JOIN matches m ON m.id = pms.match_id
           JOIN teams t ON t.id = m.team_id
           WHERE pms.player_id=?
           ORDER BY m.match_date ASC""",
        (player_id,),
    ).fetchall()
    out = []
    for r in rows:
        stats = {
            sv["metric_key"]: sv["value"]
            for sv in conn.execute(
                "SELECT metric_key, value FROM stat_values WHERE player_match_stats_id=?",
                (r["pms_id"],),
            ).fetchall()
        }
        out.append({
            "match_id": r["match_id"], "opponent": r["opponent"],
            "match_date": r["match_date"], "home_score": r["home_score"],
            "away_score": r["away_score"], "is_home": r["is_home"],
            "season": r["season"], "session_type": r["session_type"],
            "team_name": r["team_name"],
            "position": r["position"], "status": (r["status"] or "Starter"),
            "came_on_as": r["came_on_as"],
            "minutes_played": r["minutes_played"],
            "stats": stats,
        })
    return out


def get_player(conn, player_id):
    return conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()


def summary_counts(conn):
    matches = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    players = conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]
    dr = conn.execute(
        "SELECT MIN(match_date) mn, MAX(match_date) mx FROM matches"
    ).fetchone()
    return {"matches": matches, "players": players,
            "date_min": dr["mn"], "date_max": dr["mx"]}



# ---------------------------------------------------------------------------
# Physical data (GPS / tracking) — separate from technical/impact pipeline
# ---------------------------------------------------------------------------
# Canonical metric columns of the physical_data table (excludes id / metadata).
_PHYSICAL_METRIC_COLS = [
    "total_time_minutes", "total_distance", "distance_per_minute",
    "sprint_distance", "high_intensity_distance", "hml_distance",
    "top_speed", "top_speed_ms", "percentage_max_speed",
    "sprint_count", "high_intensity_events",
    "high_intensity_bursts_distance", "high_intensity_bursts_count",
    "accelerations", "decelerations", "acc_dec_total", "max_acceleration",
    "session_load", "edi_percentage",
    "distance_zone5", "distance_zone6", "entries_zone6",
]
PHYSICAL_METRIC_COLS = list(_PHYSICAL_METRIC_COLS)

_PHYSICAL_CONTEXT_COLS = [
    "player_name", "period", "session_name", "match_date",
    "start_time", "end_time",
]


def _clean_num(v):
    """Convert a value to float for SQLite, mapping NaN/None to None."""
    if v is None:
        return None
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def save_physical_data(conn, df, match_id=None, source_filename=None,
                       session_type="unlinked", session_name=None):
    """Insert parsed physical rows (a DataFrame from physical_parser) into the DB.

    Player names are linked to existing players when an exact match exists,
    otherwise ``player_id`` is left NULL (physical data can be standalone).
    The UNIQUE(player_name, session_name, period, data_source) constraint makes
    re-imports idempotent (existing rows are replaced).

    Args:
        match_id:      Match to link to (only when ``session_type == 'match'``).
        source_filename: Original upload filename (traceability).
        session_type:  ``'match'`` | ``'training'`` | ``'unlinked'``.
                       When ``'match'`` a ``match_id`` should be supplied; for
                       other types ``match_id`` is forced to ``NULL``.
        session_name:  Optional override for the session name written to every
                       row (e.g. "vs KV Mechelen (14-03-2026)"). When omitted
                       the parser-provided ``session_name`` from the DataFrame
                       is used (backwards compatible).

    Returns a dict with counts: {'inserted', 'linked', 'unlinked'}.
    """
    # Guard: only 'match' sessions keep a match_id link.
    if session_type != "match":
        match_id = None

    inserted = linked = unlinked = 0
    all_cols = (_PHYSICAL_CONTEXT_COLS + _PHYSICAL_METRIC_COLS
                + ["data_source"])
    for _, row in df.iterrows():
        name = row.get("player_name")
        if not name:
            continue
        # Link to existing player if present (do not auto-create here).
        pr = conn.execute("SELECT id FROM players WHERE name = ?", (name,)).fetchone()
        player_id = pr["id"] if pr else None
        if player_id:
            linked += 1
        else:
            unlinked += 1

        values = {col: row.get(col) for col in all_cols}
        # numeric coercion for metric columns
        for col in _PHYSICAL_METRIC_COLS:
            values[col] = _clean_num(values.get(col))
        # optional session-name override (applied uniformly to all rows)
        if session_name is not None:
            values["session_name"] = session_name

        conn.execute(
            f"""INSERT INTO physical_data
                (player_id, match_id, source_filename, uploaded_at, raw_data,
                 session_type, {", ".join(all_cols)})
                VALUES (?, ?, ?, ?, ?, ?, {", ".join(["?"] * len(all_cols))})
                ON CONFLICT(player_name, session_name, period, data_source)
                DO UPDATE SET
                  player_id=excluded.player_id,
                  match_id=excluded.match_id,
                  source_filename=excluded.source_filename,
                  uploaded_at=excluded.uploaded_at,
                  raw_data=excluded.raw_data,
                  session_type=excluded.session_type,
                  {", ".join(f"{c}=excluded.{c}" for c in
                             (_PHYSICAL_CONTEXT_COLS[1:] + _PHYSICAL_METRIC_COLS))}
            """,
            (player_id, match_id, source_filename, _now(), row.get("raw_data"),
             session_type, *[values[col] for col in all_cols]),
        )
        inserted += 1
    conn.commit()
    return {"inserted": inserted, "linked": linked, "unlinked": unlinked}


def get_physical_data(conn, player_name=None, session_name=None, period=None,
                      data_source=None, session_type=None, match_id=None):
    """Return physical_data rows as a list of sqlite Row, filtered as given.

    Extra filters ``session_type`` ('match'/'training'/'unlinked') and
    ``match_id`` allow the dashboard to scope data per session category.
    """
    clauses, params = [], []
    if player_name:
        clauses.append("player_name = ?"); params.append(player_name)
    if session_name:
        clauses.append("session_name = ?"); params.append(session_name)
    if period:
        clauses.append("period = ?"); params.append(period)
    if data_source:
        clauses.append("data_source = ?"); params.append(data_source)
    if session_type:
        clauses.append("session_type = ?"); params.append(session_type)
    if match_id is not None:
        clauses.append("match_id = ?"); params.append(match_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(
        f"SELECT * FROM physical_data{where} ORDER BY match_date DESC, "
        f"player_name, period",
        params,
    ).fetchall()


# The six headline physical metrics surfaced per player in the Match Dashboard.
# (Problem 1 — individual physical data per player.)
PHYSICAL_PLAYER_METRICS = [
    "total_distance", "sprint_distance", "high_intensity_distance",
    "top_speed", "accelerations", "decelerations",
]
# Metrics that must be combined with MAX (not SUM) when several period rows
# (e.g. First Half / Second Half) are merged for a single player+match.
_PHYSICAL_MAX_METRICS = {"top_speed", "max_acceleration", "percentage_max_speed"}


def get_player_physical_for_match(conn, player_id, match_id):
    """Return the individual physical/GPS metrics for ONE player in ONE match.

    Uses only the physical_data rows linked to ``match_id`` for the given
    ``player_id`` — no team aggregation. Returns a dict containing the six
    headline metrics (``total_distance``, ``sprint_distance``,
    ``high_intensity_distance``, ``top_speed``, ``accelerations``,
    ``decelerations``) together with ``total_time_minutes`` and the source
    ``period``.

    When several period rows exist for the same player+match (e.g. First Half /
    Second Half / Full Match) a single ``Full Match`` row is preferred; when no
    Full Match row is present the half rows are merged (distances/counts summed,
    speed-type metrics taken as the maximum).

    Returns ``None`` when no physical data is linked for that player+match, so
    callers can render a "No GPS data" placeholder.
    """
    if player_id is None or match_id is None:
        return None
    rows = conn.execute(
        "SELECT * FROM physical_data WHERE player_id = ? AND match_id = ?",
        (player_id, match_id),
    ).fetchall()
    if not rows:
        return None

    # Prefer an explicit Full Match row when available.
    full = [r for r in rows
            if (r["period"] or "").strip().lower() == "full match"]
    use = full if full else rows

    metric_cols = list(PHYSICAL_PLAYER_METRICS) + ["total_time_minutes"]
    result = {}
    for col in metric_cols:
        vals = []
        for r in use:
            v = r[col] if col in r.keys() else None
            if v is not None:
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                vals.append(fv)
        if not vals:
            result[col] = None
        elif col in _PHYSICAL_MAX_METRICS:
            result[col] = max(vals)
        else:
            result[col] = sum(vals)

    periods = sorted({(r["period"] or "").strip() for r in use if r["period"]})
    result["period"] = "Full Match" if full else (", ".join(periods) or None)
    return result


# The seven physical metrics surfaced on the Player Profile (Problem 2).
# The first six map directly to physical_data columns; ``distance_per_minute``
# is a calculated metric (total_distance / total_time_minutes).
PHYSICAL_PROFILE_METRICS = [
    "total_distance", "sprint_distance", "high_intensity_distance",
    "top_speed", "accelerations", "decelerations", "distance_per_minute",
]


def _merge_physical_session_rows(rows):
    """Collapse the period rows of ONE session into a single per-match dict.

    Prefers an explicit ``Full Match`` row; otherwise merges the half rows
    (distances/counts summed, speed-type metrics taken as the maximum). Only
    the metrics needed for the Player Profile are returned, plus
    ``total_time_minutes``.
    """
    full = [r for r in rows
            if (r["period"] or "").strip().lower() == "full match"]
    use = full if full else rows

    cols = ["total_distance", "sprint_distance", "high_intensity_distance",
            "top_speed", "accelerations", "decelerations",
            "total_time_minutes"]
    merged = {}
    for col in cols:
        vals = []
        for r in use:
            v = r[col] if col in r.keys() else None
            if v is None:
                continue
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if not vals:
            merged[col] = None
        elif col in _PHYSICAL_MAX_METRICS:
            merged[col] = max(vals)
        else:
            merged[col] = sum(vals)
    return merged


def get_player_physical_aggregate(conn, player_id):
    """Aggregate a single player's physical/GPS data across ALL their matches.

    Uses ONLY the ``physical_data`` rows belonging to ``player_id`` — no team
    data, no benchmarks, no match/training mix beyond what is linked to the
    player. The per-session period rows are merged into one value per session
    (see ``_merge_physical_session_rows``) and then averaged across sessions.

    Returns a dict with:
      - the seven Player-Profile metrics (``total_distance``,
        ``sprint_distance``, ``high_intensity_distance``, ``top_speed``,
        ``accelerations``, ``decelerations``, ``distance_per_minute``) as
        per-match averages, where ``top_speed`` is the player's overall best;
      - ``sessions``: number of distinct sessions/matches contributing data;
      - ``total_minutes``: summed playing time across sessions.

    Returns ``None`` when the player has no physical data at all, so callers
    can render a "No physical data available" placeholder.
    """
    if player_id is None:
        return None
    rows = conn.execute(
        "SELECT * FROM physical_data WHERE player_id = ?", (player_id,)
    ).fetchall()
    if not rows:
        return None

    # Group rows per session (one session == one match).
    by_session = {}
    for r in rows:
        key = (r["session_name"], r["data_source"])
        by_session.setdefault(key, []).append(r)

    per_session = [_merge_physical_session_rows(g) for g in by_session.values()]

    def _avg(col):
        vals = [s[col] for s in per_session if s.get(col) is not None]
        return (sum(vals) / len(vals)) if vals else None

    def _max(col):
        vals = [s[col] for s in per_session if s.get(col) is not None]
        return max(vals) if vals else None

    def _sum(col):
        vals = [s[col] for s in per_session if s.get(col) is not None]
        return sum(vals) if vals else None

    result = {
        "total_distance": _avg("total_distance"),
        "sprint_distance": _avg("sprint_distance"),
        "high_intensity_distance": _avg("high_intensity_distance"),
        "top_speed": _max("top_speed"),
        "accelerations": _avg("accelerations"),
        "decelerations": _avg("decelerations"),
        "sessions": len(per_session),
        "total_minutes": _sum("total_time_minutes"),
    }

    # Distance per Minute is a calculated metric: aggregate distance over
    # aggregate playing time (avoids divide-by-zero / per-session noise).
    tot_dist = _sum("total_distance")
    tot_min = _sum("total_time_minutes")
    if tot_dist is not None and tot_min:
        result["distance_per_minute"] = tot_dist / tot_min
    else:
        result["distance_per_minute"] = None

    return result


def list_physical_sessions(conn, session_type=None):
    """Distinct physical sessions for filters.

    Returns one row per (session_name, data_source) with: session_name,
    match_date, data_source, session_type, match_id, n_rows, n_players and the
    distinct periods present. Optionally filtered by ``session_type``.
    """
    params = []
    where = ""
    if session_type:
        where = "WHERE session_type = ?"
        params.append(session_type)
    return conn.execute(
        f"""SELECT session_name, MIN(match_date) AS match_date,
                   data_source,
                   MAX(session_type) AS session_type,
                   MAX(match_id) AS match_id,
                   COUNT(*) AS n_rows,
                   COUNT(DISTINCT player_name) AS n_players,
                   GROUP_CONCAT(DISTINCT period) AS periods
            FROM physical_data
            {where}
            GROUP BY session_name, data_source
            ORDER BY match_date DESC""",
        params,
    ).fetchall()


def get_all_physical_sessions(conn):
    """List every unique physical session with aggregated info for management.

    Returns one dict per (session_name, data_source) with:
        session_name, session_type, data_source,
        match_date     -> match_date of the linked match if available,
                          else the physical_data match_date,
        n_players      -> distinct players in the session,
        n_rows         -> total physical_data records in the session,
        match_id       -> linked match id (or None),
        linked_match   -> human readable match name if match_id is set, else None.

    This powers the Physical Sessions overview in the Data Management screen.
    """
    rows = conn.execute(
        """SELECT pd.session_name                       AS session_name,
                  MAX(pd.session_type)                  AS session_type,
                  pd.data_source                        AS data_source,
                  MAX(pd.match_id)                      AS match_id,
                  COUNT(*)                              AS n_rows,
                  COUNT(DISTINCT pd.player_name)        AS n_players,
                  MIN(pd.match_date)                    AS phys_date,
                  MAX(m.match_date)                     AS linked_date,
                  MAX(t.name)                           AS team_name,
                  MAX(t.age_group)                      AS age_group,
                  MAX(m.opponent)                       AS opponent,
                  MAX(m.is_home)                        AS is_home
             FROM physical_data pd
             LEFT JOIN matches m ON m.id = pd.match_id
             LEFT JOIN teams   t ON t.id = m.team_id
            GROUP BY pd.session_name, pd.data_source
            ORDER BY COALESCE(MAX(m.match_date), MIN(pd.match_date)) DESC,
                     pd.session_name""",
    ).fetchall()

    sessions = []
    for r in rows:
        linked_match = None
        if r["match_id"] is not None and r["team_name"]:
            home = r["team_name"] + (f" {r['age_group']}" if r["age_group"] else "")
            if r["is_home"]:
                linked_match = f"{home} vs {r['opponent']}"
            else:
                linked_match = f"{r['opponent']} vs {home}"
        sessions.append({
            "session_name": r["session_name"],
            "session_type": r["session_type"] or "unlinked",
            "data_source": r["data_source"],
            "match_date": r["linked_date"] or r["phys_date"],
            "n_players": r["n_players"],
            "n_rows": r["n_rows"],
            "match_id": r["match_id"],
            "linked_match": linked_match,
        })
    return sessions


def list_physical_players(conn):
    """Distinct player names present in physical_data."""
    return [r["player_name"] for r in conn.execute(
        "SELECT DISTINCT player_name FROM physical_data ORDER BY player_name"
    ).fetchall()]


def get_player_physical_summary(conn, player_name):
    """Aggregated physical stats for one player across all sessions.

    Sums distances/counts and takes the max of speed-type metrics.
    """
    row = conn.execute(
        """SELECT
              COUNT(DISTINCT session_name) AS sessions,
              SUM(total_distance)          AS total_distance,
              SUM(sprint_distance)         AS sprint_distance,
              SUM(high_intensity_distance) AS high_intensity_distance,
              SUM(accelerations)           AS accelerations,
              SUM(decelerations)           AS decelerations,
              MAX(top_speed)               AS top_speed,
              MAX(max_acceleration)        AS max_acceleration,
              AVG(distance_per_minute)     AS avg_distance_per_minute,
              SUM(session_load)            AS session_load
           FROM physical_data WHERE player_name = ?""",
        (player_name,),
    ).fetchone()
    return dict(row) if row else {}


def physical_summary_counts(conn):
    """Top-level counts for the physical dashboard header.

    Includes per session_type session counts ('match'/'training'/'unlinked'),
    where a session is one distinct (session_name, data_source) pair.
    """
    n_rows = conn.execute("SELECT COUNT(*) c FROM physical_data").fetchone()["c"]
    n_sessions = conn.execute(
        "SELECT COUNT(*) c FROM (SELECT 1 FROM physical_data "
        "GROUP BY session_name, data_source)"
    ).fetchone()["c"]
    n_players = conn.execute(
        "SELECT COUNT(DISTINCT player_name) c FROM physical_data"
    ).fetchone()["c"]

    # Sessions per type (count distinct session_name+data_source per type).
    per_type = {"match": 0, "training": 0, "unlinked": 0}
    rows = conn.execute(
        "SELECT session_type, COUNT(*) c FROM ("
        "  SELECT session_type, session_name, data_source FROM physical_data"
        "  GROUP BY session_name, data_source"
        ") GROUP BY session_type"
    ).fetchall()
    for r in rows:
        per_type[r["session_type"]] = r["c"]

    return {
        "rows": n_rows, "sessions": n_sessions, "players": n_players,
        "match": per_type["match"], "training": per_type["training"],
        "unlinked": per_type["unlinked"],
    }


def delete_physical_session(conn, session_name, data_source=None):
    """Delete all physical rows of a session. Returns number of rows removed."""
    if data_source:
        cur = conn.execute(
            "DELETE FROM physical_data WHERE session_name=? AND data_source=?",
            (session_name, data_source),
        )
    else:
        cur = conn.execute(
            "DELETE FROM physical_data WHERE session_name=?", (session_name,)
        )
    conn.commit()
    return cur.rowcount



def get_matches_for_date(conn, target_date, window_days=0):
    """Return matches on (or near) a date for match-link suggestions.

    Args:
        target_date: ISO date string 'YYYY-MM-DD'.
        window_days: when > 0, also include matches within +/- this many days,
                     ordered by closeness to ``target_date``.

    Returns a list of sqlite Row with: id, match_date, opponent, is_home,
    team_name (joined from teams).
    """
    if window_days and window_days > 0:
        return conn.execute(
            """SELECT m.id, m.match_date, m.opponent, m.is_home,
                      t.name AS team_name
                 FROM matches m JOIN teams t ON t.id = m.team_id
                WHERE m.match_date BETWEEN date(?, '-' || ? || ' days')
                                       AND date(?, '+' || ? || ' days')
                ORDER BY ABS(julianday(m.match_date) - julianday(?))""",
            (target_date, window_days, target_date, window_days, target_date),
        ).fetchall()
    return conn.execute(
        """SELECT m.id, m.match_date, m.opponent, m.is_home,
                  t.name AS team_name
             FROM matches m JOIN teams t ON t.id = m.team_id
            WHERE m.match_date = ?
            ORDER BY m.match_date DESC""",
        (target_date,),
    ).fetchall()


def link_physical_session_to_match(conn, session_name, data_source, match_id,
                                   new_session_name=None):
    """Link a physical session to a match.

    Sets ``session_type='match'`` and fills ``match_id`` for every row of the
    given (session_name, data_source). Optionally renames the session via
    ``new_session_name`` (e.g. "vs KV Mechelen (14-03-2026)").

    Returns the number of rows updated.

    Raises ValueError if the match does not exist.
    """
    m = conn.execute("SELECT id FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not m:
        raise ValueError(f"Match {match_id} not found")

    if new_session_name:
        cur = conn.execute(
            """UPDATE physical_data
                  SET session_type = 'match',
                      match_id = ?,
                      session_name = ?
                WHERE session_name = ? AND data_source = ?""",
            (match_id, new_session_name, session_name, data_source),
        )
    else:
        cur = conn.execute(
            """UPDATE physical_data
                  SET session_type = 'match',
                      match_id = ?
                WHERE session_name = ? AND data_source = ?""",
            (match_id, session_name, data_source),
        )
    conn.commit()
    return cur.rowcount


def unlink_physical_session(conn, session_name, data_source=None,
                            new_session_name=None):
    """Unlink a physical session from a match.

    Sets ``session_type='unlinked'`` and ``match_id=NULL`` for every row of the
    given session. When ``data_source`` is None the operation applies to all
    rows matching ``session_name`` (used by the Data Management overview, which
    identifies sessions by ``session_name`` only). Optionally renames the
    session.

    Returns the number of rows updated.
    """
    sets = "session_type = 'unlinked', match_id = NULL"
    params = []
    if new_session_name:
        sets += ", session_name = ?"
        params.append(new_session_name)

    where = "session_name = ?"
    params.append(session_name)
    if data_source:
        where += " AND data_source = ?"
        params.append(data_source)

    cur = conn.execute(
        f"UPDATE physical_data SET {sets} WHERE {where}", params
    )
    conn.commit()
    return cur.rowcount
