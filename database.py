"""
database.py — SQLite schema, initialisation and query helpers.

The schema is intentionally multi-club ready even though the MVP runs as a
single club. All writes go through small helper functions so the rest of the
app never builds SQL by hand.
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta

import bcrypt

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
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL,
    -- Phase 2 — self-service onboarding, subscription limits.
    subscription_status TEXT NOT NULL DEFAULT 'trial',
    max_users           INTEGER NOT NULL DEFAULT 3,
    max_teams           INTEGER NOT NULL DEFAULT 3,
    is_active           INTEGER NOT NULL DEFAULT 1,
    -- Phase 4 — subscription plans (no payment provider yet).
    subscription_plan   TEXT NOT NULL DEFAULT 'trial',
    max_extra_users     INTEGER NOT NULL DEFAULT 0,
    trial_start_date    TEXT,
    trial_end_date      TEXT,
    -- Visual upgrade — club branding (single accent colour, hex).
    primary_color       TEXT NOT NULL DEFAULT '#10B981'
);

-- Phase 1 — authentication & multi-tenancy. Each user belongs to exactly one
-- club; all data access is scoped to the user's club_id (see query helpers).
-- Phase 2 — roles: platform_admin | club_admin | analyst | coach; unique
-- email; per-user active flag.
-- Phase 3 — team assignments moved to the user_team_assignments junction table
-- (many-to-many), so users no longer carry a single team_id column.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    club_id       INTEGER NOT NULL,
    role          TEXT NOT NULL DEFAULT 'coach',
    created_at    TEXT NOT NULL,
    email         TEXT UNIQUE,
    is_active     INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE
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
    club_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    age_group   TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
    UNIQUE (club_id, name, age_group)
);

CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id     INTEGER NOT NULL,
    team_id     INTEGER,                       -- Phase 3 — team ownership
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL,
    UNIQUE (club_id, name)
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id     INTEGER NOT NULL,
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
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    UNIQUE (team_id, opponent, match_date)
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id         INTEGER NOT NULL,
    match_id        INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    position        TEXT,
    status          TEXT NOT NULL DEFAULT 'Starter',
    came_on_as      TEXT,
    minutes_played  REAL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
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

-- Granular metric-level weighting (v2.1). Each field position stores a
-- per-metric weight (REAL, step 0.5 in the UI) in the 0–10 range. Goalkeepers
-- keep the legacy category-level position_weights route, so only field
-- positions are stored here.
CREATE TABLE IF NOT EXISTS position_metric_weights (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    position_profile_id INTEGER NOT NULL,
    position            TEXT NOT NULL,
    metric_key          TEXT NOT NULL,
    weight              REAL NOT NULL CHECK (weight >= 0 AND weight <= 10),
    FOREIGN KEY (position_profile_id) REFERENCES position_profiles(id) ON DELETE CASCADE,
    UNIQUE (position_profile_id, position, metric_key)
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
    club_id                         INTEGER NOT NULL,
    team_id                         INTEGER,            -- Phase 3 — team ownership
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
    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL,
    FOREIGN KEY (player_id) REFERENCES players(id),
    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL,
    UNIQUE (club_id, player_name, session_name, period, data_source)
);

-- Phase 3 — many-to-many user↔team assignments. analyst/coach users only see
-- data for the teams they are assigned to here.
CREATE TABLE IF NOT EXISTS user_team_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    team_id       INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    UNIQUE (user_id, team_id)
);

CREATE INDEX IF NOT EXISTS idx_uta_user ON user_team_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_uta_team ON user_team_assignments(team_id);
CREATE INDEX IF NOT EXISTS idx_players_team   ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_physical_team  ON physical_data(team_id);
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

# Phase 1 — club isolation indexes. Kept separate from SCHEMA because they
# reference the club_id columns, which legacy databases only gain *after*
# _migrate_club_isolation runs. Applied once columns are guaranteed present.
CLUB_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_teams_club    ON teams(club_id);
CREATE INDEX IF NOT EXISTS idx_players_club  ON players(club_id);
CREATE INDEX IF NOT EXISTS idx_matches_club  ON matches(club_id);
CREATE INDEX IF NOT EXISTS idx_pms_club      ON player_match_stats(club_id);
CREATE INDEX IF NOT EXISTS idx_physical_club ON physical_data(club_id);
CREATE INDEX IF NOT EXISTS idx_users_club    ON users(club_id);
"""


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db(db_path=DB_PATH):
    """Create schema and seed default club + admin user + profiles (idempotent)."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        # Re-run the schema so any indexes dropped during a table rebuild in
        # _migrate are restored (CREATE ... IF NOT EXISTS makes this safe).
        conn.executescript(SCHEMA)
        # club_id columns are guaranteed present now → safe to add their indexes.
        conn.executescript(CLUB_INDEXES)
        conn.commit()
        club_id = ensure_club(conn, "Default Club")
        seed_default_profiles(conn, club_id)
        seed_default_position_profiles(conn, club_id)
        seed_default_admin(conn, club_id)
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

    # -----------------------------------------------------------------------
    # Phase 1 — authentication & club isolation.
    # Adds a ``club_id`` to every data table and rebuilds the tables whose
    # UNIQUE constraints must become club-scoped (teams, players, physical_data)
    # so two clubs can hold same-named entities without colliding. Existing rows
    # are assigned to the default club. Fully idempotent.
    # -----------------------------------------------------------------------
    _migrate_club_isolation(conn)

    # -----------------------------------------------------------------------
    # Phase 2 — self-service onboarding, club limits & expanded roles.
    # Adds subscription/limit columns to clubs and email/is_active/team_id to
    # users. Promotes the legacy 'admin' user to 'platform_admin'. Idempotent.
    # -----------------------------------------------------------------------
    _migrate_phase2(conn)

    # -----------------------------------------------------------------------
    # Phase 3 — team-level data isolation within clubs.
    # Adds team_id to players & physical_data, creates the
    # user_team_assignments junction table, back-fills team_id for existing
    # rows, migrates any legacy users.team_id into the junction table and then
    # drops the users.team_id column. Idempotent.
    # -----------------------------------------------------------------------
    _migrate_phase3(conn)

    # -----------------------------------------------------------------------
    # v2.1 — granular metric-level weighting.
    # Creates the position_metric_weights table (also in SCHEMA for fresh DBs)
    # and back-fills it for every existing position profile from the framework
    # defaults so all field positions land on a valid Profile Balance (37.5).
    # Goalkeepers are intentionally NOT seeded here (legacy category route).
    # Idempotent: only inserts rows that don't already exist.
    # -----------------------------------------------------------------------
    _migrate_granular_weights(conn)

    # -----------------------------------------------------------------------
    # Visual upgrade — club branding. Adds a single ``primary_color`` column
    # to clubs (hex accent colour) defaulting to the framework emerald. Fully
    # idempotent (skips if the column already exists).
    # -----------------------------------------------------------------------
    _migrate_club_branding(conn)


DEFAULT_PRIMARY_COLOR = "#10B981"
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _migrate_club_branding(conn):
    """Add the clubs.primary_color column and backfill the default colour."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "primary_color" not in cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN primary_color TEXT NOT NULL "
            f"DEFAULT '{DEFAULT_PRIMARY_COLOR}'"
        )
        conn.execute(
            "UPDATE clubs SET primary_color = ? WHERE primary_color IS NULL "
            "OR primary_color = ''",
            (DEFAULT_PRIMARY_COLOR,),
        )
        conn.commit()
        print("✓ Migrated: added primary_color to clubs")


def get_club_branding(conn, club_id):
    """Return the club's accent colour (hex), falling back to the default."""
    club = get_club(conn, club_id)
    if club is None:
        return DEFAULT_PRIMARY_COLOR
    keys = club.keys()
    val = club["primary_color"] if "primary_color" in keys else None
    if val and _HEX_COLOR_RE.match(val):
        return val
    return DEFAULT_PRIMARY_COLOR


def update_club_branding(conn, club_id, primary_color):
    """Validate and persist a club's accent colour. Raises ValueError on bad hex."""
    if not primary_color or not _HEX_COLOR_RE.match(primary_color.strip()):
        raise ValueError("Ongeldige kleurcode. Gebruik een hex-waarde zoals #10B981.")
    conn.execute(
        "UPDATE clubs SET primary_color = ? WHERE id = ?",
        (primary_color.strip(), club_id),
    )
    conn.commit()


def _migrate_granular_weights(conn):
    """Back-fill position_metric_weights for existing profiles. Idempotent."""
    # Ensure the table exists even on older DBs that predate SCHEMA changes.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS position_metric_weights (
               id                  INTEGER PRIMARY KEY AUTOINCREMENT,
               position_profile_id INTEGER NOT NULL,
               position            TEXT NOT NULL,
               metric_key          TEXT NOT NULL,
               weight              REAL NOT NULL CHECK (weight >= 0 AND weight <= 10),
               FOREIGN KEY (position_profile_id) REFERENCES position_profiles(id) ON DELETE CASCADE,
               UNIQUE (position_profile_id, position, metric_key)
           )"""
    )
    profiles = conn.execute("SELECT id FROM position_profiles").fetchall()
    if not profiles:
        conn.commit()
        return
    defaults = M.default_position_metric_weights()
    seeded = 0
    for prof in profiles:
        pid = prof["id"]
        existing = {
            (r["position"], r["metric_key"])
            for r in conn.execute(
                """SELECT position, metric_key FROM position_metric_weights
                   WHERE position_profile_id=?""",
                (pid,),
            ).fetchall()
        }
        rows = [
            (pid, pos, mkey, float(w))
            for pos, mweights in defaults.items()
            for mkey, w in mweights.items()
            if (pos, mkey) not in existing
        ]
        if rows:
            conn.executemany(
                """INSERT INTO position_metric_weights
                   (position_profile_id, position, metric_key, weight)
                   VALUES (?, ?, ?, ?)""",
                rows,
            )
            seeded += len(rows)
    conn.commit()
    if seeded:
        print(f"✓ Migrated: seeded {seeded} granular metric weights "
              f"across {len(profiles)} position profile(s)")


def _migrate_phase3(conn):
    """Add team_id to data tables + user_team_assignments junction. Idempotent."""
    conn.execute("PRAGMA foreign_keys = OFF")

    # 1. Junction table (also created via SCHEMA for fresh DBs).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_team_assignments (
               assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id       INTEGER NOT NULL,
               team_id       INTEGER NOT NULL,
               created_at    TEXT NOT NULL,
               FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
               FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
               UNIQUE (user_id, team_id)
           )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uta_user ON user_team_assignments(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uta_team ON user_team_assignments(team_id)"
    )

    # 2. team_id columns on players & physical_data.
    if not _has_column(conn, "players", "team_id"):
        conn.execute(
            "ALTER TABLE players ADD COLUMN team_id INTEGER REFERENCES teams(id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id)"
        )
        print("✓ Migrated: added team_id to players")
    if not _has_column(conn, "physical_data", "team_id"):
        conn.execute(
            "ALTER TABLE physical_data ADD COLUMN team_id INTEGER REFERENCES teams(id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_physical_team ON physical_data(team_id)"
        )
        print("✓ Migrated: added team_id to physical_data")

    # 3. Migrate any legacy users.team_id → junction, then drop the column.
    if _has_column(conn, "users", "team_id"):
        for r in conn.execute(
            "SELECT id, team_id FROM users WHERE team_id IS NOT NULL"
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO user_team_assignments "
                "(user_id, team_id, created_at) VALUES (?, ?, ?)",
                (r["id"], r["team_id"], _now()),
            )
        try:
            conn.execute("ALTER TABLE users DROP COLUMN team_id")
            print("✓ Migrated: moved users.team_id → user_team_assignments")
        except Exception as exc:  # pragma: no cover - older sqlite
            print(f"⚠ Could not drop users.team_id ({exc}); leaving column unused")

    conn.commit()

    # 4. Back-fill team_id for existing rows (per club).
    _backfill_team_ids(conn)

    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def _ensure_unassigned_team(conn, club_id):
    """Return the id of this club's 'Unassigned' team, creating it if needed."""
    row = conn.execute(
        "SELECT id FROM teams WHERE club_id = ? AND name = ? "
        "AND IFNULL(age_group,'') = ''",
        (club_id, "Unassigned"),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO teams (club_id, name, age_group, created_at) "
        "VALUES (?, 'Unassigned', NULL, ?)",
        (club_id, _now()),
    )
    return cur.lastrowid


def _backfill_team_ids(conn):
    """Assign a team_id to every players/physical_data row lacking one."""
    # ---- players ----
    players = conn.execute(
        "SELECT id, club_id FROM players WHERE team_id IS NULL"
    ).fetchall()
    for p in players:
        # Prefer the team of the matches this player actually appeared in.
        row = conn.execute(
            """SELECT m.team_id AS tid, COUNT(*) AS n
                 FROM player_match_stats pms
                 JOIN matches m ON m.id = pms.match_id
                WHERE pms.player_id = ?
                GROUP BY m.team_id
                ORDER BY n DESC LIMIT 1""",
            (p["id"],),
        ).fetchone()
        team_id = row["tid"] if row and row["tid"] else None
        if team_id is None:
            # No matches → first existing team of the club, else 'Unassigned'.
            t = conn.execute(
                "SELECT id FROM teams WHERE club_id = ? ORDER BY id LIMIT 1",
                (p["club_id"],),
            ).fetchone()
            team_id = t["id"] if t else _ensure_unassigned_team(conn, p["club_id"])
        conn.execute(
            "UPDATE players SET team_id = ? WHERE id = ?", (team_id, p["id"])
        )

    # ---- physical_data ----
    pds = conn.execute(
        "SELECT id, club_id, match_id, player_id, player_name "
        "FROM physical_data WHERE team_id IS NULL"
    ).fetchall()
    for pd_row in pds:
        team_id = None
        # 1) linked match's team
        if pd_row["match_id"] is not None:
            m = conn.execute(
                "SELECT team_id FROM matches WHERE id = ?", (pd_row["match_id"],)
            ).fetchone()
            if m:
                team_id = m["team_id"]
        # 2) linked player's team
        if team_id is None and pd_row["player_id"] is not None:
            pl = conn.execute(
                "SELECT team_id FROM players WHERE id = ?", (pd_row["player_id"],)
            ).fetchone()
            if pl and pl["team_id"]:
                team_id = pl["team_id"]
        # 3) player matched by name within the club
        if team_id is None and pd_row["player_name"]:
            pl = conn.execute(
                "SELECT team_id FROM players WHERE club_id = ? AND name = ?",
                (pd_row["club_id"], pd_row["player_name"]),
            ).fetchone()
            if pl and pl["team_id"]:
                team_id = pl["team_id"]
        # 4) fall back to first team / Unassigned
        if team_id is None:
            t = conn.execute(
                "SELECT id FROM teams WHERE club_id = ? ORDER BY id LIMIT 1",
                (pd_row["club_id"],),
            ).fetchone()
            team_id = t["id"] if t else _ensure_unassigned_team(conn, pd_row["club_id"])
        conn.execute(
            "UPDATE physical_data SET team_id = ? WHERE id = ?",
            (team_id, pd_row["id"]),
        )
    conn.commit()


def _migrate_phase2(conn):
    """Add Phase 2 onboarding/limit columns and upgrade roles. Idempotent."""
    club_cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "subscription_status" not in club_cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN subscription_status TEXT NOT NULL "
            "DEFAULT 'trial'"
        )
        print("✓ Migrated: added subscription_status to clubs")
    if "max_users" not in club_cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN max_users INTEGER NOT NULL DEFAULT 3"
        )
        print("✓ Migrated: added max_users to clubs")
    if "max_teams" not in club_cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN max_teams INTEGER NOT NULL DEFAULT 3"
        )
        print("✓ Migrated: added max_teams to clubs")
    if "is_active" not in club_cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
        )
        print("✓ Migrated: added is_active to clubs")
    # Phase 4 — subscription plan columns.
    if "subscription_plan" not in club_cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN subscription_plan TEXT NOT NULL "
            "DEFAULT 'trial'"
        )
        print("✓ Migrated: added subscription_plan to clubs")
    if "max_extra_users" not in club_cols:
        conn.execute(
            "ALTER TABLE clubs ADD COLUMN max_extra_users INTEGER NOT NULL "
            "DEFAULT 0"
        )
        print("✓ Migrated: added max_extra_users to clubs")
    if "trial_start_date" not in club_cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN trial_start_date TEXT")
        print("✓ Migrated: added trial_start_date to clubs")
    if "trial_end_date" not in club_cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN trial_end_date TEXT")
        print("✓ Migrated: added trial_end_date to clubs")

    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in user_cols:
        # SQLite cannot ADD a UNIQUE column directly; add plain then index.
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email "
            "ON users(email) WHERE email IS NOT NULL"
        )
        print("✓ Migrated: added email to users")
    if "is_active" not in user_cols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
        )
        print("✓ Migrated: added is_active to users")
    # Note: users.team_id (single-team link) is intentionally NOT added here.
    # Phase 3 manages team membership via the user_team_assignments junction
    # table and drops any legacy users.team_id column.

    # Promote the legacy default admin to platform_admin.
    conn.execute(
        "UPDATE users SET role = 'platform_admin' "
        "WHERE username = 'admin' AND role = 'admin'"
    )
    conn.commit()


def _has_column(conn, table, column):
    return column in {
        r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _migrate_club_isolation(conn):
    """Add club_id to data tables + rebuild club-scoped UNIQUE constraints."""
    # Nothing to do if already migrated.
    if _has_column(conn, "players", "club_id") and _has_column(conn, "teams", "club_id"):
        return

    # Ensure a default club exists and grab its id for back-filling.
    default_club_id = ensure_club(conn, "Default Club")
    conn.commit()

    # Foreign keys must be off while we drop/rename parent tables.
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")

    # teams: add club_id + UNIQUE(club_id, name, age_group)
    if not _has_column(conn, "teams", "club_id"):
        conn.executescript(
            """
            CREATE TABLE teams__new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                club_id     INTEGER NOT NULL,
                name        TEXT NOT NULL,
                age_group   TEXT,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
                UNIQUE (club_id, name, age_group)
            );
            """
        )
        conn.execute(
            "INSERT INTO teams__new (id, club_id, name, age_group, created_at) "
            "SELECT id, ?, name, age_group, created_at FROM teams",
            (default_club_id,),
        )
        conn.execute("DROP TABLE teams")
        conn.execute("ALTER TABLE teams__new RENAME TO teams")
        print("✓ Migrated: added club_id to teams")

    # players: add club_id + UNIQUE(club_id, name)
    if not _has_column(conn, "players", "club_id"):
        conn.executescript(
            """
            CREATE TABLE players__new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                club_id     INTEGER NOT NULL,
                name        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
                UNIQUE (club_id, name)
            );
            """
        )
        conn.execute(
            "INSERT INTO players__new (id, club_id, name, created_at) "
            "SELECT id, ?, name, created_at FROM players",
            (default_club_id,),
        )
        conn.execute("DROP TABLE players")
        conn.execute("ALTER TABLE players__new RENAME TO players")
        print("✓ Migrated: added club_id to players")

    # matches: simple ADD COLUMN (UNIQUE(team_id, ...) is already club-scoped
    # because each team belongs to one club).
    if not _has_column(conn, "matches", "club_id"):
        conn.execute("ALTER TABLE matches ADD COLUMN club_id INTEGER REFERENCES clubs(id)")
        conn.execute(
            "UPDATE matches SET club_id = ? WHERE club_id IS NULL", (default_club_id,)
        )
        print("✓ Migrated: added club_id to matches")

    # player_match_stats: simple ADD COLUMN.
    if not _has_column(conn, "player_match_stats", "club_id"):
        conn.execute(
            "ALTER TABLE player_match_stats ADD COLUMN club_id INTEGER REFERENCES clubs(id)"
        )
        conn.execute(
            "UPDATE player_match_stats SET club_id = ? WHERE club_id IS NULL",
            (default_club_id,),
        )
        print("✓ Migrated: added club_id to player_match_stats")

    # physical_data: rebuild for UNIQUE(club_id, player_name, session_name,
    # period, data_source). Copy all existing columns dynamically.
    if not _has_column(conn, "physical_data", "club_id"):
        old_cols = [
            r["name"] for r in conn.execute(
                "PRAGMA table_info(physical_data)"
            ).fetchall()
        ]
        col_list = ", ".join(old_cols)
        conn.executescript(
            """
            CREATE TABLE physical_data__new (
                id                              INTEGER PRIMARY KEY AUTOINCREMENT,
                club_id                         INTEGER NOT NULL,
                player_id                       INTEGER,
                match_id                        INTEGER,
                player_name                     TEXT,
                period                          TEXT NOT NULL DEFAULT 'Full Match',
                session_name                    TEXT,
                match_date                      TEXT,
                start_time                      TEXT,
                end_time                        TEXT,
                total_time_minutes              REAL,
                total_distance                  REAL,
                distance_per_minute             REAL,
                sprint_distance                 REAL,
                high_intensity_distance         REAL,
                hml_distance                    REAL,
                top_speed                       REAL,
                top_speed_ms                    REAL,
                percentage_max_speed            REAL,
                sprint_count                    REAL,
                high_intensity_events           REAL,
                high_intensity_bursts_distance  REAL,
                high_intensity_bursts_count     REAL,
                accelerations                   REAL,
                decelerations                   REAL,
                acc_dec_total                   REAL,
                max_acceleration                REAL,
                session_load                    REAL,
                edi_percentage                  REAL,
                distance_zone5                  REAL,
                distance_zone6                  REAL,
                entries_zone6                   REAL,
                data_source                     TEXT,
                source_filename                 TEXT,
                uploaded_at                     TEXT,
                raw_data                        TEXT,
                session_type                    TEXT NOT NULL DEFAULT 'unlinked',
                FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE,
                FOREIGN KEY (player_id) REFERENCES players(id),
                FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL,
                UNIQUE (club_id, player_name, session_name, period, data_source)
            );
            """
        )
        conn.execute(
            f"INSERT INTO physical_data__new (club_id, {col_list}) "
            f"SELECT ?, {col_list} FROM physical_data",
            (default_club_id,),
        )
        conn.execute("DROP TABLE physical_data")
        conn.execute("ALTER TABLE physical_data__new RENAME TO physical_data")
        print("✓ Migrated: added club_id to physical_data")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
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


def get_club(conn, club_id):
    """Return the club row for ``club_id`` (or None)."""
    return conn.execute(
        "SELECT * FROM clubs WHERE id = ?", (club_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Authentication (Phase 1)
# ---------------------------------------------------------------------------
def hash_password(password):
    """Return a bcrypt hash (str) for the given plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    """Return True if ``password`` matches the stored bcrypt ``password_hash``."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def get_user_by_username(conn, username):
    """Return the user row for ``username`` (or None)."""
    return conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()


def get_user_by_email(conn, email):
    """Return the user row for ``email`` (or None)."""
    if not email:
        return None
    return conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()


def create_user(conn, username, password, club_id, role="coach",
                email=None, team_id=None, is_active=True):
    """Create a new user with a bcrypt-hashed password. Returns the new id.

    Phase 3: ``team_id`` (single team) is accepted for backwards compatibility;
    when provided it is recorded as a row in ``user_team_assignments`` rather
    than on the users table.
    """
    cur = conn.execute(
        """INSERT INTO users
               (username, password_hash, club_id, role, created_at,
                email, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (username, hash_password(password), club_id, role, _now(),
         (email or None), 1 if is_active else 0),
    )
    user_id = cur.lastrowid
    conn.commit()
    if team_id is not None:
        assign_user_to_team(conn, user_id, team_id)
    return user_id


def authenticate(conn, username, password):
    """Validate credentials. Return the user row on success, else None.

    Note: ``is_active`` checks for the user and their club are handled by the
    caller (see ``authenticate_full``) so a distinct error message can be
    shown. This function only verifies the password.
    """
    user = get_user_by_username(conn, username)
    if user and verify_password(password, user["password_hash"]):
        return user
    return None


def authenticate_full(conn, username, password):
    """Authenticate and enforce active-status for the user and their club.

    Returns ``(user_row, error)``. On success ``error`` is None. On failure
    ``user_row`` is None and ``error`` is one of:
      'invalid'        — bad username/password
      'user_inactive'  — account deactivated
      'club_inactive'  — club deactivated/suspended
    """
    user = authenticate(conn, username, password)
    if not user:
        return None, "invalid"
    # is_active may be absent on very old rows → treat missing as active.
    if "is_active" in user.keys() and not user["is_active"]:
        return None, "user_inactive"
    club = get_club(conn, user["club_id"])
    if club is not None and "is_active" in club.keys() and not club["is_active"]:
        return None, "club_inactive"
    # Phase 4 — subscription/trial access gate. platform_admin bypasses.
    if club is not None and user["role"] != "platform_admin":
        keys = club.keys()
        status = club["subscription_status"] if "subscription_status" in keys else "active"
        if status not in ACTIVE_STATUSES:
            # inactive / cancelled / expired → no access.
            return None, "subscription_inactive"
        if status == "trial":
            trial_end = club["trial_end_date"] if "trial_end_date" in keys else None
            if _trial_expired(trial_end):
                # Auto-mark expired so the state is persistent.
                conn.execute(
                    "UPDATE clubs SET subscription_status = 'expired' WHERE id = ?",
                    (club["id"],),
                )
                conn.commit()
                return None, "trial_expired"
    return user, None


# ---------------------------------------------------------------------------
# Phase 2 — onboarding, club limits, club/user/team management
# ---------------------------------------------------------------------------
VALID_ROLES = ("platform_admin", "club_admin", "analyst", "coach")
# Roles a club_admin is allowed to assign to members of their own club.
CLUB_ASSIGNABLE_ROLES = ("analyst", "coach")

# ---------------------------------------------------------------------------
# Phase 4 — subscription plans. Limits count EXTRA users only; the single
# club_admin is NOT counted as an extra user. No payment provider yet.
# ---------------------------------------------------------------------------
TRIAL_DAYS = 7
PLAN_LIMITS = {
    "trial":    {"max_teams": 1,  "max_extra_users": 1},
    "basic":    {"max_teams": 1,  "max_extra_users": 1},
    "advanced": {"max_teams": 3,  "max_extra_users": 3},
    "pro":      {"max_teams": 5,  "max_extra_users": 10},
    "elite":    {"max_teams": 10, "max_extra_users": 30},
}
VALID_PLANS = tuple(PLAN_LIMITS.keys())
VALID_STATUSES = ("active", "trial", "inactive", "cancelled", "expired")
# Statuses that grant access. 'trial' access is additionally time-gated.
ACTIVE_STATUSES = ("active", "trial")


def get_club_user_count(conn, club_id):
    """Number of users belonging to a club (active + inactive)."""
    return conn.execute(
        "SELECT COUNT(*) c FROM users WHERE club_id = ?", (club_id,)
    ).fetchone()["c"]


def get_extra_user_count(conn, club_id):
    """Number of EXTRA users in a club: everyone except club_admin/platform_admin.

    The single club_admin (and any platform_admin) is never counted against
    the subscription's max_extra_users limit.
    """
    return conn.execute(
        "SELECT COUNT(*) c FROM users WHERE club_id = ? "
        "AND role NOT IN ('club_admin', 'platform_admin')",
        (club_id,),
    ).fetchone()["c"]


def get_club_team_count(conn, club_id):
    """Number of teams belonging to a club."""
    return conn.execute(
        "SELECT COUNT(*) c FROM teams WHERE club_id = ?", (club_id,)
    ).fetchone()["c"]


def _club_limits(conn, club_id):
    """Return (max_extra_users, max_teams) for a club, with safe fallbacks."""
    club = get_club(conn, club_id)
    if club is None:
        return 0, 0
    keys = club.keys()
    max_teams = club["max_teams"] if "max_teams" in keys else 1
    if "max_extra_users" in keys and club["max_extra_users"] is not None:
        max_extra = club["max_extra_users"]
    else:
        # Legacy DB without the column: derive from old max_users (minus the
        # one club_admin seat) so behaviour stays sensible.
        legacy = club["max_users"] if "max_users" in keys else 1
        max_extra = max(0, (legacy or 1) - 1)
    return max_extra, max_teams


def can_add_user(conn, club_id):
    """True if the club can still add another EXTRA user.

    The club_admin does not count; only extra users are limited.
    """
    max_extra, _ = _club_limits(conn, club_id)
    return get_extra_user_count(conn, club_id) < max_extra


def can_add_team(conn, club_id):
    """True if the club has not yet reached its max_teams limit."""
    _, max_teams = _club_limits(conn, club_id)
    return get_club_team_count(conn, club_id) < max_teams


def get_club_plan_info(conn, club_id):
    """Return a dict summarising a club's plan, status and usage vs limits.

    Keys: plan, status, max_teams, max_extra_users, team_count,
    extra_user_count, teams_left, extra_users_left, trial_end_date,
    trial_active, access. Used by both the platform-admin and club-admin UI.
    """
    club = get_club(conn, club_id)
    if club is None:
        return None
    keys = club.keys()
    plan = club["subscription_plan"] if "subscription_plan" in keys else "trial"
    status = club["subscription_status"] if "subscription_status" in keys else "trial"
    max_extra, max_teams = _club_limits(conn, club_id)
    team_count = get_club_team_count(conn, club_id)
    extra_count = get_extra_user_count(conn, club_id)
    trial_end = club["trial_end_date"] if "trial_end_date" in keys else None
    trial_active = True
    if status == "trial" and trial_end:
        trial_active = not _trial_expired(trial_end)
    access = (status in ACTIVE_STATUSES) and (status != "trial" or trial_active)
    return {
        "plan": plan,
        "status": status,
        "max_teams": max_teams,
        "max_extra_users": max_extra,
        "team_count": team_count,
        "extra_user_count": extra_count,
        "teams_left": max(0, max_teams - team_count),
        "extra_users_left": max(0, max_extra - extra_count),
        "trial_end_date": trial_end,
        "trial_active": trial_active,
        "access": access,
    }


def _trial_expired(trial_end_date):
    """True if a trial_end_date (ISO string) is strictly in the past."""
    if not trial_end_date:
        return False
    try:
        end = datetime.fromisoformat(trial_end_date)
    except (ValueError, TypeError):
        return False
    return datetime.now() > end


def apply_plan_limits(conn, club_id, plan):
    """Set max_teams/max_extra_users from PLAN_LIMITS for the given plan.

    Does not change status or trial dates. Returns the applied limits dict.
    """
    plan = (plan or "").strip().lower()
    limits = PLAN_LIMITS.get(plan)
    if limits is None:
        raise ValueError("invalid_plan")
    conn.execute(
        "UPDATE clubs SET subscription_plan = ?, max_teams = ?, "
        "max_extra_users = ? WHERE id = ?",
        (plan, limits["max_teams"], limits["max_extra_users"], club_id),
    )
    conn.commit()
    return limits


def club_name_exists(conn, name):
    """Case-insensitive check whether a club name is already taken."""
    return conn.execute(
        "SELECT 1 FROM clubs WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone() is not None


def list_clubs(conn):
    """All clubs with their user/team counts (for the platform admin panel)."""
    rows = conn.execute("SELECT * FROM clubs ORDER BY id").fetchall()
    out = []
    for c in rows:
        d = dict(c)
        d["user_count"] = get_club_user_count(conn, c["id"])
        d["extra_user_count"] = get_extra_user_count(conn, c["id"])
        d["team_count"] = get_club_team_count(conn, c["id"])
        out.append(d)
    return out


def list_users_for_club(conn, club_id):
    """All users of a club with a comma-joined list of their assigned teams.

    ``team_name`` aggregates every team the user is assigned to (Phase 3 is
    many-to-many). Users with no assignment get NULL.
    """
    return conn.execute(
        """SELECT u.*,
                  (SELECT GROUP_CONCAT(t.name, ', ')
                     FROM user_team_assignments uta
                     JOIN teams t ON t.id = uta.team_id
                    WHERE uta.user_id = u.id) AS team_name
           FROM users u
           WHERE u.club_id = ? ORDER BY u.id""",
        (club_id,),
    ).fetchall()


def list_teams(conn, club_id):
    """All teams of a club (for management + dropdowns)."""
    return conn.execute(
        "SELECT * FROM teams WHERE club_id = ? ORDER BY name, age_group",
        (club_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Phase 3 — team-level access control (user ↔ team assignments)
# ---------------------------------------------------------------------------
def _team_filter_sql(team_ids, column="team_id"):
    """Build a SQL fragment + params for filtering ``column`` by team_ids.

    Returns ``(" AND <clause>", params)``.
      * ``team_ids is None`` → no filtering (admin scopes): empty fragment.
      * empty list           → ``" AND 1=0"`` (matches nothing).
      * non-empty list       → ``" AND column IN (?,?,...)"``.
    """
    if team_ids is None:
        return "", []
    ids = list(team_ids)
    if not ids:
        return " AND 1=0", []
    placeholders = ",".join("?" * len(ids))
    return f" AND {column} IN ({placeholders})", ids


def list_user_team_ids(conn, user_id):
    """Raw list of team_ids assigned to a user via the junction table."""
    return [
        r["team_id"] for r in conn.execute(
            "SELECT team_id FROM user_team_assignments WHERE user_id = ? "
            "ORDER BY team_id",
            (user_id,),
        ).fetchall()
    ]


def get_user_team_ids(conn, user_id):
    """Return the list of team_ids a user may access, based on their role.

    * platform_admin → every team in the database.
    * club_admin     → every team in the user's club.
    * analyst/coach  → only the teams assigned in user_team_assignments.
    """
    user = conn.execute(
        "SELECT id, club_id, role FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        return []
    role = user["role"]
    if role == "platform_admin":
        return [r["id"] for r in conn.execute("SELECT id FROM teams").fetchall()]
    if role == "club_admin":
        return [
            r["id"] for r in conn.execute(
                "SELECT id FROM teams WHERE club_id = ?", (user["club_id"],)
            ).fetchall()
        ]
    return list_user_team_ids(conn, user_id)


def get_teams_for_user(conn, user_id):
    """Return the team rows (as dicts) a user may access."""
    ids = get_user_team_ids(conn, user_id)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM teams WHERE id IN ({placeholders}) ORDER BY name, age_group",
        ids,
    ).fetchall()
    return [dict(r) for r in rows]


def assign_user_to_team(conn, user_id, team_id):
    """Create a user↔team assignment. Returns True on success.

    Validates that the user and the team belong to the same club; returns
    False (no-op) when they do not, or when either does not exist.
    """
    user = conn.execute(
        "SELECT club_id FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    team = conn.execute(
        "SELECT club_id FROM teams WHERE id = ?", (team_id,)
    ).fetchone()
    if not user or not team or user["club_id"] != team["club_id"]:
        return False
    conn.execute(
        "INSERT OR IGNORE INTO user_team_assignments (user_id, team_id, created_at) "
        "VALUES (?, ?, ?)",
        (user_id, team_id, _now()),
    )
    conn.commit()
    return True


def remove_user_team_assignment(conn, user_id, team_id):
    """Delete a user↔team assignment. Returns True if a row was removed."""
    cur = conn.execute(
        "DELETE FROM user_team_assignments WHERE user_id = ? AND team_id = ?",
        (user_id, team_id),
    )
    conn.commit()
    return cur.rowcount > 0


def set_user_team_assignments(conn, user_id, team_ids):
    """Replace a user's team assignments with exactly ``team_ids``.

    Only teams in the same club as the user are accepted. Returns the list of
    team_ids that were actually assigned.
    """
    user = conn.execute(
        "SELECT club_id FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        return []
    valid = {
        r["id"] for r in conn.execute(
            "SELECT id FROM teams WHERE club_id = ?", (user["club_id"],)
        ).fetchall()
    }
    wanted = [t for t in (team_ids or []) if t in valid]
    conn.execute(
        "DELETE FROM user_team_assignments WHERE user_id = ?", (user_id,)
    )
    for t in wanted:
        conn.execute(
            "INSERT OR IGNORE INTO user_team_assignments "
            "(user_id, team_id, created_at) VALUES (?, ?, ?)",
            (user_id, t, _now()),
        )
    conn.commit()
    return wanted


def create_team(conn, club_id, name, age_group=None):
    """Create a team for a club, enforcing the max_teams limit.

    Raises ValueError('limit_reached') if at the limit, or
    ValueError('duplicate') if a same-name/age_group team already exists.
    Returns the new team id.
    """
    name = (name or "").strip()
    age_group = (age_group or "").strip() or None
    if not name:
        raise ValueError("empty_name")
    if not can_add_team(conn, club_id):
        raise ValueError("limit_reached")
    existing = conn.execute(
        "SELECT id FROM teams WHERE club_id = ? AND name = ? "
        "AND IFNULL(age_group,'') = IFNULL(?, '')",
        (club_id, name, age_group),
    ).fetchone()
    if existing:
        raise ValueError("duplicate")
    cur = conn.execute(
        "INSERT INTO teams (club_id, name, age_group, created_at) "
        "VALUES (?, ?, ?, ?)",
        (club_id, name, age_group, _now()),
    )
    conn.commit()
    return cur.lastrowid


def create_club_user(conn, club_id, username, password, role="coach",
                     email=None, team_id=None):
    """Create a user for a club, enforcing limits + uniqueness.

    Raises ValueError with one of: 'limit_reached', 'empty', 'bad_role',
    'username_taken', 'email_taken'. Returns the new user id.

    Security: a club_admin may only create 'coach' or 'analyst' users. The
    elevated roles (club_admin / platform_admin) cannot be assigned through
    this path, so club admins can never grant platform rights.
    """
    username = (username or "").strip()
    email = (email or "").strip() or None
    if not username or not password:
        raise ValueError("empty")
    if role not in CLUB_ASSIGNABLE_ROLES:
        raise ValueError("bad_role")
    if not can_add_user(conn, club_id):
        raise ValueError("limit_reached")
    if get_user_by_username(conn, username):
        raise ValueError("username_taken")
    if email and get_user_by_email(conn, email):
        raise ValueError("email_taken")
    return create_user(conn, username, password, club_id, role=role,
                       email=email, team_id=team_id, is_active=True)


def set_user_active(conn, user_id, is_active, club_id=None):
    """Activate/deactivate a user. Scoped to club_id when provided."""
    if club_id is not None:
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ? AND club_id = ?",
            (1 if is_active else 0, user_id, club_id),
        )
    else:
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
    conn.commit()


def update_club_limits(conn, club_id, max_teams, max_extra_users):
    """Platform-admin: directly set a club's team / extra-user limits.

    This is the manual override used after a plan is chosen; it does not
    change the plan label itself.
    """
    conn.execute(
        "UPDATE clubs SET max_teams = ?, max_extra_users = ? WHERE id = ?",
        (int(max_teams), int(max_extra_users), club_id),
    )
    conn.commit()


def update_club_plan(conn, club_id, plan):
    """Platform-admin: change plan AND auto-apply that plan's limits."""
    return apply_plan_limits(conn, club_id, plan)


def update_club_trial_end(conn, club_id, trial_end_date):
    """Platform-admin: set/extend a club's trial_end_date (ISO string)."""
    conn.execute(
        "UPDATE clubs SET trial_end_date = ? WHERE id = ?",
        (trial_end_date, club_id),
    )
    conn.commit()


def set_club_active(conn, club_id, is_active):
    """Platform-admin: activate/deactivate (suspend) a club."""
    conn.execute(
        "UPDATE clubs SET is_active = ? WHERE id = ?",
        (1 if is_active else 0, club_id),
    )
    conn.commit()


def update_club_subscription(conn, club_id, status):
    """Platform-admin: set a club's subscription_status label.

    Valid values: active | trial | inactive | cancelled | expired.
    """
    status = (status or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError("invalid_status")
    conn.execute(
        "UPDATE clubs SET subscription_status = ? WHERE id = ?",
        (status, club_id),
    )
    conn.commit()


def register_club(conn, club_name, username, email, password):
    """Self-service onboarding: create a club + its first club_admin user.

    The new club starts on the 'trial' plan; its limits come from
    PLAN_LIMITS['trial'] (1 team / 1 extra user). The first user becomes
    'club_admin'. Default style/position
    profiles are seeded so every screen works immediately.

    Raises ValueError: 'club_taken', 'username_taken', 'email_taken',
    'empty'. Returns (user_id, club_id).
    """
    club_name = (club_name or "").strip()
    username = (username or "").strip()
    email = (email or "").strip() or None
    if not club_name or not username or not password:
        raise ValueError("empty")
    if club_name_exists(conn, club_name):
        raise ValueError("club_taken")
    if get_user_by_username(conn, username):
        raise ValueError("username_taken")
    if email and get_user_by_email(conn, email):
        raise ValueError("email_taken")

    now = datetime.now()
    trial_start = now.isoformat(timespec="seconds")
    trial_end = (now + timedelta(days=TRIAL_DAYS)).isoformat(timespec="seconds")
    # Trial limits come from PLAN_LIMITS so there is a single source of truth.
    t_teams = PLAN_LIMITS["trial"]["max_teams"]
    t_extra = PLAN_LIMITS["trial"]["max_extra_users"]
    cur = conn.execute(
        """INSERT INTO clubs
               (name, created_at, subscription_status, max_users, max_teams,
                is_active, subscription_plan, max_extra_users,
                trial_start_date, trial_end_date)
           VALUES (?, ?, 'trial', ?, ?, 1, 'trial', ?, ?, ?)""",
        (club_name, _now(), t_extra + 1, t_teams, t_extra,
         trial_start, trial_end),
    )
    club_id = cur.lastrowid
    # Seed starter profiles for the new club.
    seed_default_profiles(conn, club_id)
    seed_default_position_profiles(conn, club_id)
    user_id = create_user(conn, username, password, club_id,
                          role="club_admin", email=email, is_active=True)
    conn.commit()
    return user_id, club_id


def seed_default_admin(conn, club_id):
    """Create the default admin/admin123 platform-admin account if missing."""
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", ("admin",)
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO users
               (username, password_hash, club_id, role, created_at, is_active)
           VALUES (?, ?, ?, ?, ?, 1)""",
        ("admin", hash_password("admin123"), club_id, "platform_admin", _now()),
    )
    print("✓ Seeded default admin user (admin / admin123, platform_admin)")
    return cur.lastrowid


def ensure_club_seeded(conn, club_id):
    """Ensure a club has its default style + position profiles seeded.

    Called on login so that newly-created clubs get the same starter profiles
    that the default club received during init.
    """
    seed_default_profiles(conn, club_id)
    seed_default_position_profiles(conn, club_id)
    conn.commit()


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
    # v2.1 — granular per-metric weights (field positions only; keepers use the
    # legacy category route above).
    _seed_metric_weights_for_profile(conn, pid)


def _seed_metric_weights_for_profile(conn, position_profile_id):
    """(Re)seed the granular metric weights for a profile from framework defaults.

    Only field positions are seeded — goalkeepers keep the legacy
    category-level position_weights route. Existing rows for the profile are
    left untouched unless they collide (idempotent upsert).
    """
    metric_defaults = M.default_position_metric_weights()
    rows = [
        (position_profile_id, pos, mkey, float(w))
        for pos, mweights in metric_defaults.items()
        for mkey, w in mweights.items()
    ]
    conn.executemany(
        """INSERT INTO position_metric_weights
           (position_profile_id, position, metric_key, weight)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(position_profile_id, position, metric_key)
           DO UPDATE SET weight=excluded.weight""",
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
                            is_default=False, metric_weights=None):
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
    # v2.1 — seed granular metric weights for field positions.
    metric_weights = metric_weights or M.default_position_metric_weights()
    mrows = [
        (pid, pos, mkey, float(w))
        for pos, mweights in metric_weights.items()
        for mkey, w in mweights.items()
    ]
    conn.executemany(
        """INSERT INTO position_metric_weights
           (position_profile_id, position, metric_key, weight)
           VALUES (?, ?, ?, ?)""",
        mrows,
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
    # v2.1 — reset granular metric weights too.
    conn.execute(
        "DELETE FROM position_metric_weights WHERE position_profile_id=?",
        (position_profile_id,),
    )
    _seed_metric_weights_for_profile(conn, position_profile_id)
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Granular metric-level weights (v2.1)
# ---------------------------------------------------------------------------
def get_position_metric_weights(conn, position_profile_id):
    """Return {position: {metric_key: weight}} for field positions in a profile.

    Falls back to framework defaults for any missing position/metric so a
    freshly-migrated or partially-populated profile always scores sensibly.
    """
    rows = conn.execute(
        """SELECT position, metric_key, weight FROM position_metric_weights
           WHERE position_profile_id=?""",
        (position_profile_id,),
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["position"], {})[r["metric_key"]] = r["weight"]
    defaults = M.default_position_metric_weights()
    for pos, mweights in defaults.items():
        out.setdefault(pos, {})
        for mkey, w in mweights.items():
            out[pos].setdefault(mkey, w)
    return out


def update_position_metric_weights(conn, position_profile_id, metric_weights,
                                   validate=True):
    """Upsert granular metric weights for one or more field positions.

    Args:
        metric_weights: {position: {metric_key: weight(0-10)}}.
        validate:       when True (default) every supplied position's Profile
                        Balance must fall in the 35–40 window, otherwise a
                        ValueError is raised and nothing is written.

    Returns True on success. Raises ValueError on a balance / range violation.
    """
    # Server-side validation — never trust the client.
    if validate:
        for pos, mweights in metric_weights.items():
            for mkey, w in mweights.items():
                try:
                    wf = float(w)
                except (TypeError, ValueError):
                    raise ValueError(f"Ongeldig gewicht voor {pos}/{mkey}: {w!r}")
                if wf < 0 or wf > 10:
                    raise ValueError(
                        f"Gewicht voor {pos}/{mkey} moet tussen 0 en 10 liggen "
                        f"(was {wf}).")
            ok, total, status = M.validate_position_balance(mweights)
            if not ok:
                raise ValueError(
                    f"Profile Balance voor {pos} is {total} ({status}); "
                    f"moet tussen {M.BALANCE_MIN} en {M.BALANCE_MAX} liggen.")

    for pos, mweights in metric_weights.items():
        for mkey, w in mweights.items():
            conn.execute(
                """INSERT INTO position_metric_weights
                   (position_profile_id, position, metric_key, weight)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(position_profile_id, position, metric_key)
                   DO UPDATE SET weight=excluded.weight""",
                (position_profile_id, pos, mkey, float(w)),
            )
    conn.commit()
    return True


def reset_position_metric_weights_to_default(conn, position_profile_id,
                                             position=None):
    """Reset granular metric weights to framework defaults.

    When ``position`` is given only that position is reset; otherwise all field
    positions in the profile are reset.
    """
    defaults = M.default_position_metric_weights()
    if position is not None:
        conn.execute(
            """DELETE FROM position_metric_weights
               WHERE position_profile_id=? AND position=?""",
            (position_profile_id, position),
        )
        mweights = defaults.get(position, {})
        conn.executemany(
            """INSERT INTO position_metric_weights
               (position_profile_id, position, metric_key, weight)
               VALUES (?, ?, ?, ?)""",
            [(position_profile_id, position, mkey, float(w))
             for mkey, w in mweights.items()],
        )
    else:
        conn.execute(
            "DELETE FROM position_metric_weights WHERE position_profile_id=?",
            (position_profile_id,),
        )
        _seed_metric_weights_for_profile(conn, position_profile_id)
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Lookups / upserts used by the parser
# ---------------------------------------------------------------------------
def get_or_create_team(conn, club_id, name, age_group=None):
    row = conn.execute(
        "SELECT id FROM teams WHERE club_id = ? AND name = ? "
        "AND IFNULL(age_group,'') = IFNULL(?, '')",
        (club_id, name, age_group),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO teams (club_id, name, age_group, created_at) VALUES (?, ?, ?, ?)",
        (club_id, name, age_group, _now()),
    )
    return cur.lastrowid


def get_or_create_player(conn, club_id, name, team_id=None):
    """Return the player id, creating the player if needed.

    Phase 3: the player is tagged with ``team_id`` (team ownership). When the
    player already exists but has no team yet, the team is back-filled.
    """
    row = conn.execute(
        "SELECT id, team_id FROM players WHERE club_id = ? AND name = ?",
        (club_id, name),
    ).fetchone()
    if row:
        if team_id is not None and row["team_id"] is None:
            conn.execute(
                "UPDATE players SET team_id = ? WHERE id = ?", (team_id, row["id"])
            )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO players (club_id, team_id, name, created_at) VALUES (?, ?, ?, ?)",
        (club_id, team_id, name, _now()),
    )
    return cur.lastrowid


def find_match(conn, club_id, team_id, opponent, match_date):
    return conn.execute(
        "SELECT id FROM matches WHERE club_id=? AND team_id=? AND opponent=? "
        "AND match_date=?",
        (club_id, team_id, opponent, match_date),
    ).fetchone()


def create_match(conn, club_id, team_id, opponent, match_date, home_score,
                 away_score, is_home, season, source_file, upload_hash=None,
                 session_type="match"):
    cur = conn.execute(
        """INSERT INTO matches
           (club_id, team_id, opponent, match_date, home_score, away_score, is_home,
            season, source_file, upload_hash, session_type, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (club_id, team_id, opponent, match_date, home_score, away_score,
         1 if is_home else 0, season, source_file, upload_hash,
         session_type or "match", _now()),
    )
    return cur.lastrowid


def find_match_by_hash(conn, club_id, upload_hash):
    """Return the first match row sharing this upload hash within a club, or None."""
    if not upload_hash:
        return None
    return conn.execute(
        "SELECT * FROM matches WHERE club_id = ? AND upload_hash = ? ORDER BY id LIMIT 1",
        (club_id, upload_hash),
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


def delete_match(conn, match_id, cleanup_players=True, club_id=None):
    """Cascade-delete a single match within a transaction.

    Removes the match, its player_match_stats and stat_values (via FK cascade),
    then optionally cleans up players left with zero matches.

    When ``club_id`` is provided the match is only deleted if it belongs to
    that club (returns zero counts otherwise), preventing cross-club deletes.

    Returns a dict of deletion counts. Rolls back on any error.
    """
    try:
        if club_id is not None:
            owns = conn.execute(
                "SELECT 1 FROM matches WHERE id = ? AND club_id = ?",
                (match_id, club_id),
            ).fetchone()
            if not owns:
                return {"matches": 0, "player_stats": 0,
                        "stat_values": 0, "players": 0}
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


def delete_matches_by_source(conn, source_file, club_id=None):
    """Delete every match that came from a given source PDF (cascade).

    Scoped to ``club_id`` when provided so only the owning club's matches are
    removed. Returns aggregated deletion counts. Transaction-safe.
    """
    try:
        if club_id is not None:
            rows = conn.execute(
                "SELECT id FROM matches WHERE club_id = ? "
                "AND IFNULL(source_file,'') = IFNULL(?, '')",
                (club_id, source_file),
            ).fetchall()
        else:
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


def upsert_player_match_stats(conn, club_id, match_id, player_id, position,
                              minutes_played, status="Starter", came_on_as=None):
    cur = conn.execute(
        """INSERT INTO player_match_stats
             (club_id, match_id, player_id, position, status, came_on_as,
              minutes_played, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(match_id, player_id) DO UPDATE SET
             position=excluded.position, status=excluded.status,
             came_on_as=excluded.came_on_as, minutes_played=excluded.minutes_played""",
        (club_id, match_id, player_id, position, status or "Starter", came_on_as,
         minutes_played, _now()),
    )
    if cur.lastrowid:
        row = conn.execute(
            "SELECT id FROM player_match_stats WHERE match_id=? AND player_id=?",
            (match_id, player_id),
        ).fetchone()
        return row["id"]
    return cur.lastrowid


def update_player_match_position(conn, player_match_stat_id, new_position,
                                 club_id=None):
    """Update the ``position`` of a single player_match_stats row.

    Used by the Match Dashboard position-editing flow. Impact scores are
    computed live from this field, so changing it here is sufficient for the
    new position to flow through to all impact calculations and the pitch
    visualisation on the next page rerun.

    Returns True if a row was updated, False otherwise.
    """
    if club_id is not None:
        cur = conn.execute(
            "UPDATE player_match_stats SET position = ? WHERE id = ? AND club_id = ?",
            (new_position, player_match_stat_id, club_id),
        )
    else:
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


def list_matches(conn, club_id, team_ids=None):
    frag, fp = _team_filter_sql(team_ids, "m.team_id")
    return conn.execute(
        f"""SELECT m.*, t.name AS team_name, t.age_group
           FROM matches m JOIN teams t ON t.id = m.team_id
           WHERE m.club_id = ?{frag}
           ORDER BY m.match_date DESC""",
        (club_id, *fp),
    ).fetchall()


def list_matches_detailed(conn, club_id, team_ids=None):
    """Matches enriched with player count and source PDF for management views."""
    frag, fp = _team_filter_sql(team_ids, "m.team_id")
    return conn.execute(
        f"""SELECT m.*, t.name AS team_name, t.age_group,
                  (SELECT COUNT(*) FROM player_match_stats pms
                   WHERE pms.match_id = m.id) AS player_count
           FROM matches m JOIN teams t ON t.id = m.team_id
           WHERE m.club_id = ?{frag}
           ORDER BY m.match_date DESC""",
        (club_id, *fp),
    ).fetchall()


def list_upload_history(conn, club_id, team_ids=None):
    """Group matches by their source PDF for the upload-history table.

    Returns a list of dicts: source_file, n_matches, first_uploaded,
    last_uploaded, match_ids.
    """
    frag, fp = _team_filter_sql(team_ids, "m.team_id")
    rows = conn.execute(
        f"""SELECT m.id, m.source_file, m.created_at, m.match_date, m.opponent
           FROM matches m
           WHERE m.club_id = ?{frag}
           ORDER BY m.created_at DESC, m.id DESC""",
        (club_id, *fp),
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


def get_match(conn, match_id, club_id=None, team_ids=None):
    frag, fp = _team_filter_sql(team_ids, "m.team_id")
    if club_id is not None:
        return conn.execute(
            f"""SELECT m.*, t.name AS team_name, t.age_group
               FROM matches m JOIN teams t ON t.id = m.team_id
               WHERE m.id=? AND m.club_id=?{frag}""",
            (match_id, club_id, *fp),
        ).fetchone()
    return conn.execute(
        f"""SELECT m.*, t.name AS team_name, t.age_group
           FROM matches m JOIN teams t ON t.id = m.team_id WHERE m.id=?{frag}""",
        (match_id, *fp),
    ).fetchone()


def get_match_player_stats(conn, match_id, club_id=None):
    """Return list of dicts: player stats rows for a match with stat values folded in."""
    if club_id is not None:
        pms_rows = conn.execute(
            """SELECT pms.id AS pms_id, pms.position, pms.status, pms.came_on_as,
                      pms.minutes_played, p.id AS player_id, p.name AS player_name
               FROM player_match_stats pms JOIN players p ON p.id = pms.player_id
               WHERE pms.match_id=? AND pms.club_id=?""",
            (match_id, club_id),
        ).fetchall()
    else:
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


def list_players(conn, club_id, team_ids=None):
    frag, fp = _team_filter_sql(team_ids, "p.team_id")
    return conn.execute(
        f"""SELECT p.id, p.name, p.team_id, COUNT(pms.id) AS appearances
           FROM players p LEFT JOIN player_match_stats pms ON pms.player_id = p.id
           WHERE p.club_id = ?{frag}
           GROUP BY p.id ORDER BY p.name""",
        (club_id, *fp),
    ).fetchall()


def get_player_match_history(conn, player_id, club_id=None, team_ids=None):
    """Return chronological list of {match info + stats} for a player."""
    frag, fp = _team_filter_sql(team_ids, "m.team_id")
    if club_id is not None:
        rows = conn.execute(
            f"""SELECT pms.id AS pms_id, pms.position, pms.status, pms.came_on_as,
                      pms.minutes_played,
                      m.id AS match_id, m.opponent, m.match_date, m.home_score,
                      m.away_score, m.is_home, m.season, m.session_type,
                      t.name AS team_name
               FROM player_match_stats pms
               JOIN matches m ON m.id = pms.match_id
               JOIN teams t ON t.id = m.team_id
               WHERE pms.player_id=? AND pms.club_id=?{frag}
               ORDER BY m.match_date ASC""",
            (player_id, club_id, *fp),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT pms.id AS pms_id, pms.position, pms.status, pms.came_on_as,
                      pms.minutes_played,
                      m.id AS match_id, m.opponent, m.match_date, m.home_score,
                      m.away_score, m.is_home, m.season, m.session_type,
                      t.name AS team_name
               FROM player_match_stats pms
               JOIN matches m ON m.id = pms.match_id
               JOIN teams t ON t.id = m.team_id
               WHERE pms.player_id=?{frag}
               ORDER BY m.match_date ASC""",
            (player_id, *fp),
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


def get_player(conn, player_id, club_id=None, team_ids=None):
    frag, fp = _team_filter_sql(team_ids, "team_id")
    if club_id is not None:
        return conn.execute(
            f"SELECT * FROM players WHERE id=? AND club_id=?{frag}",
            (player_id, club_id, *fp),
        ).fetchone()
    return conn.execute(
        f"SELECT * FROM players WHERE id=?{frag}", (player_id, *fp)
    ).fetchone()


def summary_counts(conn, club_id, team_ids=None):
    mfrag, mfp = _team_filter_sql(team_ids, "team_id")
    matches = conn.execute(
        f"SELECT COUNT(*) c FROM matches WHERE club_id=?{mfrag}",
        (club_id, *mfp),
    ).fetchone()["c"]
    players = conn.execute(
        f"SELECT COUNT(*) c FROM players WHERE club_id=?{mfrag}",
        (club_id, *mfp),
    ).fetchone()["c"]
    dr = conn.execute(
        f"SELECT MIN(match_date) mn, MAX(match_date) mx FROM matches "
        f"WHERE club_id=?{mfrag}",
        (club_id, *mfp),
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


def save_physical_data(conn, club_id, df, match_id=None, source_filename=None,
                       session_type="unlinked", session_name=None, team_id=None):
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

    # Resolve the team this session belongs to (Phase 3 ownership).
    # Priority: explicit team_id arg → linked match's team.
    match_team_id = None
    if match_id is not None:
        m = conn.execute(
            "SELECT team_id FROM matches WHERE id = ? AND club_id = ?",
            (match_id, club_id),
        ).fetchone()
        if m:
            match_team_id = m["team_id"]

    inserted = linked = unlinked = 0
    all_cols = (_PHYSICAL_CONTEXT_COLS + _PHYSICAL_METRIC_COLS
                + ["data_source"])
    for _, row in df.iterrows():
        name = row.get("player_name")
        if not name:
            continue
        # Link to existing player if present (do not auto-create here).
        pr = conn.execute(
            "SELECT id, team_id FROM players WHERE club_id = ? AND name = ?",
            (club_id, name),
        ).fetchone()
        player_id = pr["id"] if pr else None
        if player_id:
            linked += 1
        else:
            unlinked += 1

        # Effective team_id: linked match's team → caller's team_id →
        # linked player's team. Keeps every row attributable to a team.
        row_team_id = match_team_id or team_id
        if row_team_id is None and pr is not None and pr["team_id"]:
            row_team_id = pr["team_id"]

        values = {col: row.get(col) for col in all_cols}
        # numeric coercion for metric columns
        for col in _PHYSICAL_METRIC_COLS:
            values[col] = _clean_num(values.get(col))
        # optional session-name override (applied uniformly to all rows)
        if session_name is not None:
            values["session_name"] = session_name

        conn.execute(
            f"""INSERT INTO physical_data
                (club_id, team_id, player_id, match_id, source_filename,
                 uploaded_at, raw_data, session_type, {", ".join(all_cols)})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, {", ".join(["?"] * len(all_cols))})
                ON CONFLICT(club_id, player_name, session_name, period, data_source)
                DO UPDATE SET
                  team_id=COALESCE(excluded.team_id, physical_data.team_id),
                  player_id=excluded.player_id,
                  match_id=excluded.match_id,
                  source_filename=excluded.source_filename,
                  uploaded_at=excluded.uploaded_at,
                  raw_data=excluded.raw_data,
                  session_type=excluded.session_type,
                  {", ".join(f"{c}=excluded.{c}" for c in
                             (_PHYSICAL_CONTEXT_COLS[1:] + _PHYSICAL_METRIC_COLS))}
            """,
            (club_id, row_team_id, player_id, match_id, source_filename, _now(),
             row.get("raw_data"), session_type, *[values[col] for col in all_cols]),
        )
        inserted += 1
    conn.commit()
    return {"inserted": inserted, "linked": linked, "unlinked": unlinked}


def get_physical_data(conn, club_id, player_name=None, session_name=None,
                      period=None, data_source=None, session_type=None,
                      match_id=None, team_ids=None):
    """Return physical_data rows as a list of sqlite Row, filtered as given.

    Always scoped to ``club_id``. Extra filters ``session_type``
    ('match'/'training'/'unlinked') and ``match_id`` allow the dashboard to
    scope data per session category. ``team_ids`` restricts rows to the given
    teams (Phase 3 team isolation; None = no team restriction).
    """
    clauses, params = ["club_id = ?"], [club_id]
    tfrag, tfp = _team_filter_sql(team_ids, "team_id")
    if tfrag:
        clauses.append(tfrag.replace(" AND ", "", 1))
        params.extend(tfp)
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


def get_player_physical_for_match(conn, player_id, match_id, club_id=None):
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
    if club_id is not None:
        rows = conn.execute(
            "SELECT * FROM physical_data WHERE player_id = ? AND match_id = ? "
            "AND club_id = ?",
            (player_id, match_id, club_id),
        ).fetchall()
    else:
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


def get_player_physical_aggregate(conn, player_id, club_id=None):
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
    if club_id is not None:
        rows = conn.execute(
            "SELECT * FROM physical_data WHERE player_id = ? AND club_id = ?",
            (player_id, club_id),
        ).fetchall()
    else:
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


def list_physical_sessions(conn, club_id, session_type=None, team_ids=None):
    """Distinct physical sessions for filters.

    Returns one row per (session_name, data_source) with: session_name,
    match_date, data_source, session_type, match_id, n_rows, n_players and the
    distinct periods present. Scoped to ``club_id``; optionally filtered by
    ``session_type`` and ``team_ids`` (Phase 3 team isolation).
    """
    params = [club_id]
    where = "WHERE club_id = ?"
    if session_type:
        where += " AND session_type = ?"
        params.append(session_type)
    tfrag, tfp = _team_filter_sql(team_ids, "team_id")
    if tfrag:
        where += tfrag
        params.extend(tfp)
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


def get_all_physical_sessions(conn, club_id, team_ids=None):
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
            WHERE pd.club_id = ?{tfrag}
            GROUP BY pd.session_name, pd.data_source
            ORDER BY COALESCE(MAX(m.match_date), MIN(pd.match_date)) DESC,
                     pd.session_name""".format(
            tfrag=_team_filter_sql(team_ids, "pd.team_id")[0]),
        (club_id, *_team_filter_sql(team_ids, "pd.team_id")[1]),
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


def list_physical_players(conn, club_id, team_ids=None):
    """Distinct player names present in physical_data for a club."""
    tfrag, tfp = _team_filter_sql(team_ids, "team_id")
    return [r["player_name"] for r in conn.execute(
        f"SELECT DISTINCT player_name FROM physical_data WHERE club_id = ?{tfrag} "
        f"ORDER BY player_name",
        (club_id, *tfp),
    ).fetchall()]


def get_player_physical_summary(conn, player_name, club_id=None):
    """Aggregated physical stats for one player across all sessions.

    Sums distances/counts and takes the max of speed-type metrics.
    """
    if club_id is not None:
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
               FROM physical_data WHERE player_name = ? AND club_id = ?""",
            (player_name, club_id),
        ).fetchone()
    else:
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


def physical_summary_counts(conn, club_id, team_ids=None):
    """Top-level counts for the physical dashboard header.

    Includes per session_type session counts ('match'/'training'/'unlinked'),
    where a session is one distinct (session_name, data_source) pair. Scoped to
    ``club_id`` and optionally ``team_ids`` (Phase 3 team isolation).
    """
    tfrag, tfp = _team_filter_sql(team_ids, "team_id")
    n_rows = conn.execute(
        f"SELECT COUNT(*) c FROM physical_data WHERE club_id = ?{tfrag}",
        (club_id, *tfp),
    ).fetchone()["c"]
    n_sessions = conn.execute(
        f"SELECT COUNT(*) c FROM (SELECT 1 FROM physical_data WHERE club_id = ?{tfrag} "
        f"GROUP BY session_name, data_source)",
        (club_id, *tfp),
    ).fetchone()["c"]
    n_players = conn.execute(
        f"SELECT COUNT(DISTINCT player_name) c FROM physical_data "
        f"WHERE club_id = ?{tfrag}",
        (club_id, *tfp),
    ).fetchone()["c"]

    # Sessions per type (count distinct session_name+data_source per type).
    per_type = {"match": 0, "training": 0, "unlinked": 0}
    rows = conn.execute(
        f"SELECT session_type, COUNT(*) c FROM ("
        f"  SELECT session_type, session_name, data_source FROM physical_data"
        f"  WHERE club_id = ?{tfrag}"
        f"  GROUP BY session_name, data_source"
        f") GROUP BY session_type",
        (club_id, *tfp),
    ).fetchall()
    for r in rows:
        per_type[r["session_type"]] = r["c"]

    return {
        "rows": n_rows, "sessions": n_sessions, "players": n_players,
        "match": per_type["match"], "training": per_type["training"],
        "unlinked": per_type["unlinked"],
    }


def delete_physical_session(conn, session_name, data_source=None, club_id=None):
    """Delete all physical rows of a session. Returns number of rows removed.

    Scoped to ``club_id`` when provided so a club can only delete its own data.
    """
    clauses = ["session_name=?"]
    params = [session_name]
    if data_source:
        clauses.append("data_source=?"); params.append(data_source)
    if club_id is not None:
        clauses.append("club_id=?"); params.append(club_id)
    cur = conn.execute(
        f"DELETE FROM physical_data WHERE {' AND '.join(clauses)}", params
    )
    conn.commit()
    return cur.rowcount



def get_matches_for_date(conn, target_date, window_days=0, club_id=None,
                         team_ids=None):
    """Return matches on (or near) a date for match-link suggestions.

    Args:
        target_date: ISO date string 'YYYY-MM-DD'.
        window_days: when > 0, also include matches within +/- this many days,
                     ordered by closeness to ``target_date``.
        club_id:     when provided, only matches of that club are returned.
        team_ids:    when provided, only matches of those teams are returned
                     (Phase 3 team isolation).

    Returns a list of sqlite Row with: id, match_date, opponent, is_home,
    team_name (joined from teams).
    """
    club_clause = " AND m.club_id = ?" if club_id is not None else ""
    tfrag, tfp = _team_filter_sql(team_ids, "m.team_id")
    if window_days and window_days > 0:
        params = [target_date, window_days, target_date, window_days]
        if club_id is not None:
            params.append(club_id)
        params.extend(tfp)
        params.append(target_date)
        return conn.execute(
            f"""SELECT m.id, m.match_date, m.opponent, m.is_home,
                      t.name AS team_name
                 FROM matches m JOIN teams t ON t.id = m.team_id
                WHERE m.match_date BETWEEN date(?, '-' || ? || ' days')
                                       AND date(?, '+' || ? || ' days')
                                       {club_clause}{tfrag}
                ORDER BY ABS(julianday(m.match_date) - julianday(?))""",
            params,
        ).fetchall()
    params = [target_date]
    if club_id is not None:
        params.append(club_id)
    params.extend(tfp)
    return conn.execute(
        f"""SELECT m.id, m.match_date, m.opponent, m.is_home,
                  t.name AS team_name
             FROM matches m JOIN teams t ON t.id = m.team_id
            WHERE m.match_date = ?{club_clause}{tfrag}
            ORDER BY m.match_date DESC""",
        params,
    ).fetchall()


def link_physical_session_to_match(conn, session_name, data_source, match_id,
                                   new_session_name=None, club_id=None):
    """Link a physical session to a match.

    Sets ``session_type='match'`` and fills ``match_id`` for every row of the
    given (session_name, data_source). Optionally renames the session via
    ``new_session_name`` (e.g. "vs KV Mechelen (14-03-2026)").

    Scoped to ``club_id`` when provided so only the owning club's rows update,
    and the target match must belong to the same club.

    Returns the number of rows updated.

    Raises ValueError if the match does not exist (within the club).
    """
    if club_id is not None:
        m = conn.execute(
            "SELECT id FROM matches WHERE id = ? AND club_id = ?",
            (match_id, club_id),
        ).fetchone()
    else:
        m = conn.execute(
            "SELECT id FROM matches WHERE id = ?", (match_id,)
        ).fetchone()
    if not m:
        raise ValueError(f"Match {match_id} not found")

    sets = "session_type = 'match', match_id = ?"
    params = [match_id]
    if new_session_name:
        sets += ", session_name = ?"
        params.append(new_session_name)
    where = "session_name = ? AND data_source = ?"
    params.extend([session_name, data_source])
    if club_id is not None:
        where += " AND club_id = ?"
        params.append(club_id)
    cur = conn.execute(
        f"UPDATE physical_data SET {sets} WHERE {where}", params
    )
    conn.commit()
    return cur.rowcount


def unlink_physical_session(conn, session_name, data_source=None,
                            new_session_name=None, club_id=None):
    """Unlink a physical session from a match.

    Sets ``session_type='unlinked'`` and ``match_id=NULL`` for every row of the
    given session. When ``data_source`` is None the operation applies to all
    rows matching ``session_name`` (used by the Data Management overview, which
    identifies sessions by ``session_name`` only). Optionally renames the
    session. Scoped to ``club_id`` when provided.

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
    if club_id is not None:
        where += " AND club_id = ?"
        params.append(club_id)

    cur = conn.execute(
        f"UPDATE physical_data SET {sets} WHERE {where}", params
    )
    conn.commit()
    return cur.rowcount
