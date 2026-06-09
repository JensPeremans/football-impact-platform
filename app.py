"""
app.py — Football Impact Data Platform (Streamlit).

Seven screens:
  1. Upload & Overview
  2. Match Dashboard
  3. Player Profile
  4. Player Comparison
  5. Evolution Dashboard
  6. Profile Editor
  7. Data Management

Run:  streamlit run app.py
"""

import os
import tempfile

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

import database as db
import pdf_parser as P
import physical_parser as PP
import impact_engine as IE
import metrics as M
import utils as U

st.set_page_config(page_title="Football Impact Platform", page_icon="⚽",
                   layout="wide", initial_sidebar_state="expanded")


# ---------------------------------------------------------------------------
# Init / cached resources
# ---------------------------------------------------------------------------
@st.cache_resource
def _bootstrap():
    db.init_db()
    return True


_bootstrap()


def conn():
    # one connection per call (sqlite + streamlit reruns); cheap for this scale
    return db.get_connection()


# ---------------------------------------------------------------------------
# Authentication & club isolation (Phase 1)
# ---------------------------------------------------------------------------
def _club():
    """Return the club_id of the currently logged-in user (or None)."""
    return st.session_state.get("club_id")


def _team_ids():
    """Return the list of team_ids the current user is restricted to, or None.

    Phase 3 team-level isolation:
    - platform_admin / club_admin -> None (no team restriction; club_id scoping
      already limits them to their own club's data).
    - analyst / coach -> list of team_ids they are assigned to (possibly empty,
      meaning they can see nothing until assigned to a team).
    """
    role = st.session_state.get("role")
    if role in ("platform_admin", "club_admin"):
        return None
    return db.get_user_team_ids(conn(), st.session_state.get("user_id"))


def _selectable_teams():
    """Return list of team rows the current user may upload/select data for."""
    role = st.session_state.get("role")
    if role in ("platform_admin", "club_admin"):
        return db.list_teams(conn(), _club())
    return db.get_teams_for_user(conn(), st.session_state.get("user_id"))


def _init_auth_state():
    """Ensure all auth-related session_state keys exist."""
    for key, default in (
        ("logged_in", False),
        ("user_id", None),
        ("username", None),
        ("club_id", None),
        ("role", None),
        ("auth_view", "login"),   # 'login' | 'register'
    ):
        if key not in st.session_state:
            st.session_state[key] = default


def do_logout():
    """Clear the auth session and any cached, club-scoped data."""
    for key in ("logged_in", "user_id", "username", "club_id", "role"):
        st.session_state[key] = False if key == "logged_in" else None
    st.session_state["auth_view"] = "login"
    st.cache_data.clear()


def _login_user(user):
    """Populate session_state from a user row and seed the club's profiles."""
    st.session_state["logged_in"] = True
    st.session_state["user_id"] = user["id"]
    st.session_state["username"] = user["username"]
    st.session_state["club_id"] = user["club_id"]
    st.session_state["role"] = user["role"]
    db.ensure_club_seeded(conn(), user["club_id"])
    st.cache_data.clear()


def _password_problems(password):
    """Return a list of strength problems (empty list == strong enough)."""
    problems = []
    if len(password or "") < 8:
        problems.append("at least 8 characters")
    if not any(ch.isalpha() for ch in (password or "")):
        problems.append("a letter")
    if not any(ch.isdigit() for ch in (password or "")):
        problems.append("a number")
    return problems


def screen_login():
    """Render the login screen shown before any authenticated screen."""
    st.markdown("## ⚽ Football Impact Platform")
    st.caption("Please sign in to continue.")
    with st.form("login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        c = conn()
        user, err = db.authenticate_full(c, (username or "").strip(), password or "")
        if user:
            _login_user(user)
            st.rerun()
        elif err == "user_inactive":
            st.error("Your account has been deactivated. Contact your club admin.")
        elif err == "club_inactive":
            st.error("This club is currently inactive. Contact the platform admin.")
        else:
            st.error("Invalid username or password.")

    st.divider()
    st.caption("New club? Create a free trial account.")
    if st.button("📝 Register a new club", key="goto_register",
                 use_container_width=True):
        st.session_state["auth_view"] = "register"
        st.rerun()


def screen_register():
    """Self-service onboarding: create a new club + first club_admin user."""
    st.markdown("## 📝 Register your club")
    st.caption("Create a free trial account. You'll become the club admin and "
               "can add up to 3 teams and 3 users.")
    with st.form("register_form"):
        club_name = st.text_input("Club name *", key="reg_club")
        username = st.text_input("Your username *", key="reg_user")
        email = st.text_input("Email *", key="reg_email")
        password = st.text_input("Password *", type="password", key="reg_pw")
        confirm = st.text_input("Confirm password *", type="password",
                                key="reg_pw2")
        submitted = st.form_submit_button("Create club & sign in",
                                          type="primary")
    if submitted:
        c = conn()
        club_name = (club_name or "").strip()
        username = (username or "").strip()
        email = (email or "").strip()
        # ---- validation ----
        errs = []
        if not club_name or not username or not email:
            errs.append("Club name, username and email are required.")
        if "@" not in email or "." not in email:
            errs.append("Please enter a valid email address.")
        if password != confirm:
            errs.append("Passwords do not match.")
        pw_problems = _password_problems(password)
        if pw_problems:
            errs.append("Password must contain " + ", ".join(pw_problems) + ".")
        if not errs and db.club_name_exists(c, club_name):
            errs.append("That club name is already taken.")
        if not errs and db.get_user_by_username(c, username):
            errs.append("That username is already taken.")
        if not errs and db.get_user_by_email(c, email):
            errs.append("That email is already registered.")
        if errs:
            for e in errs:
                st.error(e)
        else:
            try:
                uid, cid = db.register_club(c, club_name, username, email,
                                            password)
                user = db.get_user_by_username(c, username)
                _login_user(user)
                st.success(f"Welcome, {username}! Your club '{club_name}' is ready.")
                st.rerun()
            except ValueError as ve:
                st.error(f"Could not create club: {ve}")

    st.divider()
    if st.button("← Back to sign in", key="goto_login",
                 use_container_width=True):
        st.session_state["auth_view"] = "login"
        st.rerun()


@st.cache_data(show_spinner=False)
def squad_metric_reference(club_id, team_ids_key=None):
    """Squad-wide per-metric normalisation reference for the drill-down radars.

    Reads every player's stat history once and asks impact_engine for the
    90th-percentile reference per metric. Cached per club + team scope (cleared
    on new uploads via ``st.cache_data.clear()``); read-only, no schema changes.

    ``team_ids_key`` is a hashable tuple of team_ids (or None) so the cache key
    reflects team-level isolation for analysts/coaches.
    """
    c = conn()
    team_ids = list(team_ids_key) if team_ids_key is not None else None
    all_stats = []
    for p in db.list_players(c, club_id, team_ids=team_ids):
        if not p["appearances"]:
            continue
        for r in db.get_player_match_history(c, p["id"], club_id, team_ids=team_ids):
            all_stats.append(r["stats"])
    return IE.metric_reference(all_stats, pct=90)


def get_profiles(c):
    return db.list_profiles(c, _club())


def profile_selector(c, key, label="Playing Style Profile"):
    profiles = get_profiles(c)
    if not profiles:
        st.warning("No profiles available.")
        return None, {}
    names = [p["name"] for p in profiles]
    idx = 0
    chosen = st.selectbox(label, names, index=idx, key=key)
    prof = next(p for p in profiles if p["name"] == chosen)
    weights = db.get_profile_weights(c, prof["id"])
    return prof, weights


# ---------------------------------------------------------------------------
# Unified scoring selector (Sprint 2) — position-based profiles are preferred,
# legacy playing-style profiles remain available for backward compatibility.
# ---------------------------------------------------------------------------
def scoring_selector(c, key, label="Scoring profile"):
    """Let the user pick a position-based profile (default) or a legacy style.

    Returns a 'scorer' dict:
      {'kind': 'position', 'profile': row, 'importances': {...}}  or
      {'kind': 'legacy',   'profile': row, 'weights': {...}}
    """
    pos_profiles = db.list_position_profiles(c, _club())
    style_profiles = db.list_profiles(c, _club())
    options, mapping = [], {}
    for p in pos_profiles:
        lbl = f"⚽ {p['name']}"
        options.append(lbl)
        mapping[lbl] = ("position", p)
    for p in style_profiles:
        lbl = f"🎚️ {p['name']} (legacy style)"
        options.append(lbl)
        mapping[lbl] = ("legacy", p)
    if not options:
        st.warning("No profiles available.")
        return None
    chosen = st.selectbox(label, options, index=0, key=key)
    kind, prof = mapping[chosen]
    if kind == "position":
        return {"kind": "position", "profile": prof,
                "importances": db.get_position_profile_importances(c, prof["id"])}
    return {"kind": "legacy", "profile": prof,
            "weights": db.get_profile_weights(c, prof["id"])}


def score_match_rows(rows, scorer):
    if scorer and scorer["kind"] == "position":
        return IE.compute_player_match_rows_positional(rows, scorer["importances"])
    return IE.compute_player_match_rows(rows, (scorer or {}).get("weights", {}))


def career_sum(history, scorer):
    if scorer and scorer["kind"] == "position":
        return IE.career_summary_positional(history, scorer["importances"])
    return IE.career_summary(history, (scorer or {}).get("weights", {}))


# Legacy / generic SciSports position labels (pre-Sprint-2 data) mapped to a
# representative canonical position so they can still be placed on the pitch.
_LEGACY_POS_COORD = {
    "goalkeeper": "Goalkeeper",
    "defender": "Centrale Verdediger (C)",
    "centre back": "Centrale Verdediger (C)",
    "center back": "Centrale Verdediger (C)",
    "full back": "Right Back",
    "midfielder": "Central Midfielder (C)",
    "central midfield": "Central Midfielder (C)",
    "defensive midfield": "Defensive Midfielder (C)",
    "defensive midfielder": "Defensive Midfielder (C)",
    "attacking midfield": "Attacking Midfielder (C)",
    "winger": "Right Winger",
    "forward": "Striker (C)",
    "striker": "Striker (C)",
    "attacker": "Striker (C)",
}

# Parser-emitted / legacy labels that are no longer canonical positions but map
# 1:1 onto a specific canonical position. The SciSports PDF parser still emits
# the single label "Defensive Midfielder" (now split into L/C/R); resolve it to
# the centre variant so imports keep working without touching the parser.
_POSITION_ALIASES = {
    "Defensive Midfielder": "Defensive Midfielder (C)",
}


def _canonical_position(pos):
    """Map a (possibly legacy) position label onto a canonical M.POSITIONS entry.

    Returns the input unchanged when it is already canonical or has no alias.
    """
    if not pos or pos in M.POSITION_SET:
        return pos
    return _POSITION_ALIASES.get(pos, pos)


def _resolve_coord(eff_pos, raw_pos):
    """Find a pitch coordinate for a position, tolerating legacy generic labels."""
    for p in (eff_pos, raw_pos):
        if p and p in M.POSITION_COORDS:
            return M.POSITION_COORDS[p]
    for p in (eff_pos, raw_pos):
        if not p:
            continue
        canon = _LEGACY_POS_COORD.get(p.strip().lower())
        if canon and canon in M.POSITION_COORDS:
            return M.POSITION_COORDS[canon]
    return (50, 50)


def _spread_overlaps(starters):
    """Nudge starters that share the same coordinate apart horizontally so the
    markers don't stack (common with legacy generic positions)."""
    groups = {}
    for s in starters:
        groups.setdefault(s["coord"], []).append(s)
    for (x, y), members in groups.items():
        n = len(members)
        if n == 1:
            continue
        span = min(12 * (n - 1), 80)
        start = x - span / 2.0
        step = span / (n - 1) if n > 1 else 0
        for i, s in enumerate(members):
            nx = max(6, min(94, start + i * step))
            s["coord"] = (nx, y)
    return starters


def _build_pitch_lists(rows):
    """Split scored match rows into starters / bench / came-on lists for the
    pitch visualization (Phase 4)."""
    starters, bench, came_on = [], [], []
    for r in rows:
        status = r.get("status") or M.STATUS_STARTER
        imp = r.get("impact", {}) or {}
        total = imp.get("total_impact", 0) or 0
        cats = imp.get("category_impact", {}) or {}
        eff_pos = r.get("effective_position") or r.get("position")
        if status == M.STATUS_BENCH:
            bench.append({"name": r["player_name"],
                          "position": r.get("position"),
                          "total_impact": total})
        elif status == M.STATUS_CAME_ON:
            came_on.append({"name": r["player_name"],
                            "position": r.get("position"),
                            "came_on_as": r.get("came_on_as") or eff_pos,
                            "total_impact": total, "categories": cats})
        else:  # Starter
            coord = _resolve_coord(eff_pos, r.get("position"))
            starters.append({"name": r["player_name"], "position": eff_pos,
                             "coord": coord, "total_impact": total,
                             "categories": cats})
    _spread_overlaps(starters)
    return starters, bench, came_on


# ---------------------------------------------------------------------------
# Phase 3 — Position & status confirmation after PDF import
# ---------------------------------------------------------------------------
def _render_import_confirmation(c):
    """Show an editable confirmation table for each parsed PDF before saving.

    The coach can refine each player's position (the PDF cannot distinguish
    left/centre/right for some lines), set the line-up status
    (Starter / Bench / Came On) and, for substitutes, the position they came
    on as. Nothing is written to the database until 'Confirm & Save' is clicked.
    """
    pending = st.session_state.get("pending_imports")
    if not pending:
        return

    st.divider()
    st.subheader("📝 Confirm positions & line-up status")
    st.caption("The PDF cannot always tell left/centre/right apart. Review each "
               "player, correct the position if needed, and mark who started, "
               "who was on the bench, and who came on as a substitute. "
               "Nothing is saved until you confirm.")

    none_label = "— none —"
    came_on_options = [none_label] + list(M.POSITIONS)

    for idx, item in enumerate(pending):
        parsed = item["parsed"]
        cover = parsed["cover"]
        title = (f"{cover['home_team']} vs {cover['away_team']} "
                 f"— {cover['match_date']}")
        with st.container(border=True):
            st.markdown(f"**{item['file_name']}** — {title}")
            if item["is_dupe"]:
                st.warning("⚠️ A match with identical PDF contents already exists; "
                           "saving will overwrite it.")

            session_type = st.selectbox(
                "Session type", M.SESSION_TYPES, index=0,
                key=f"sess_{idx}",
                help="Match = competitive game, Training = practice session, "
                     "Combined = aggregated data.",
            )

            init_rows = []
            for p in parsed["players"]:
                init_rows.append({
                    "Player": p["name"],
                    "Min": p["stats"].get("minutes_played"),
                    "Position": _canonical_position(p["position"])
                    if _canonical_position(p["position"]) in M.POSITION_SET
                    else M.POSITIONS[0],
                    "Status": M.STATUS_STARTER,
                    "Came on as": none_label,
                })
            df = pd.DataFrame(init_rows)
            edited = st.data_editor(
                df, hide_index=True, use_container_width=True,
                key=f"editor_import_{idx}",
                column_config={
                    "Player": st.column_config.TextColumn("Player", disabled=True),
                    "Min": st.column_config.NumberColumn("Min", disabled=True),
                    "Position": st.column_config.SelectboxColumn(
                        "Position", options=list(M.POSITIONS), required=True),
                    "Status": st.column_config.SelectboxColumn(
                        "Status", options=list(M.STATUSES), required=True),
                    "Came on as": st.column_config.SelectboxColumn(
                        "Came on as", options=came_on_options,
                        help="Only relevant when status is 'Came On'."),
                },
            )
            st.session_state[f"_edited_import_{idx}"] = edited
            st.session_state[f"_sess_import_{idx}"] = session_type

    csave, ccancel = st.columns([1, 1])
    if csave.button("💾 Confirm & Save all", type="primary",
                    key="confirm_save_imports"):
        log = st.container()
        for idx, item in enumerate(pending):
            edited = st.session_state.get(f"_edited_import_{idx}")
            session_type = st.session_state.get(f"_sess_import_{idx}", "match")
            overrides = {}
            if edited is not None:
                for _, r in edited.iterrows():
                    came = r["Came on as"]
                    overrides[r["Player"]] = {
                        "position": r["Position"],
                        "status": r["Status"],
                        "came_on_as": None if came == none_label else came,
                    }
            try:
                match_id, created, n = P.store_parsed(
                    c, item["parsed"], _club(), overrides=overrides,
                    session_type=session_type)
                verb = "Imported" if created else "Re-imported (updated)"
                log.success(f"✅ **{item['file_name']}** — {verb}: {n} players "
                            f"({session_type}).")
            except Exception as e:  # noqa
                log.error(f"❌ **{item['file_name']}** — Save failed: {e}")
        st.session_state.pop("pending_imports", None)
        st.cache_data.clear()
        st.rerun()
    if ccancel.button("✖️ Cancel", key="cancel_imports"):
        st.session_state.pop("pending_imports", None)
        st.rerun()


# ---------------------------------------------------------------------------
# Screen 1 — Upload & Overview
# ---------------------------------------------------------------------------
def screen_upload():
    st.header("📤 Upload & Overview")
    st.caption("Upload SciSports Match Analysis (Player Version) PDFs. "
               "Both report formats are supported and parsed automatically.")

    c = conn()
    uploaded = st.file_uploader(
        "Drop one or more SciSports PDF reports here",
        type=["pdf"], accept_multiple_files=True,
    )

    override_dupes = st.checkbox(
        "Upload anyway if a duplicate is detected",
        value=False,
        help="When unchecked, a PDF whose contents were already uploaded is skipped "
             "with a warning. Tick this to import it again regardless.",
    )

    if uploaded:
        if st.button("⚙️ Process uploaded PDFs", type="primary"):
            progress = st.progress(0.0)
            log = st.container()
            pending = []
            for i, uf in enumerate(uploaded):
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uf.getbuffer())
                        tmp_path = tmp.name
                    parsed = P.parse_pdf(tmp_path, original_name=uf.name)

                    # --- Duplicate detection (hash of raw PDF bytes) ---
                    dupe = db.find_match_by_hash(c, _club(), parsed.get("upload_hash"))
                    if dupe and not override_dupes:
                        log.warning(
                            f"⚠️ **{uf.name}** — This PDF appears to have already been "
                            f"uploaded on **{(dupe['created_at'] or '')[:10] or 'an earlier date'}** "
                            f"(source: *{dupe['source_file']}*). Skipped. "
                            f"Tick *“Upload anyway”* above and re-process to import it regardless."
                        )
                        progress.progress((i + 1) / len(uploaded))
                        continue

                    pending.append({"file_name": uf.name, "parsed": parsed,
                                    "is_dupe": bool(dupe)})
                    log.info(
                        f"📄 **{uf.name}** — parsed: "
                        f"{parsed['cover']['home_team']} vs {parsed['cover']['away_team']} "
                        f"({parsed['cover']['match_date']}, format {parsed['version']}) — "
                        f"{len(parsed['players'])} players. Confirm positions below ⬇️"
                    )
                except P.PDFParseError as e:
                    log.error(f"❌ **{uf.name}** — {e}")
                except Exception as e:  # noqa
                    log.error(f"❌ **{uf.name}** — Unexpected error: {e}")
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                progress.progress((i + 1) / len(uploaded))
            if pending:
                st.session_state["pending_imports"] = pending

    # --- Phase 3: position & status confirmation step ---
    _render_import_confirmation(c)

    st.divider()

    # Summary
    s = db.summary_counts(c, _club(), team_ids=_team_ids())
    col1, col2, col3 = st.columns(3)
    col1.metric("Matches", s["matches"])
    col2.metric("Players", s["players"])
    dr = "—"
    if s["date_min"]:
        dr = f"{s['date_min']} → {s['date_max']}"
    col3.metric("Date range", dr)

    st.subheader("Processed matches")
    matches = db.list_matches(c, _club(), team_ids=_team_ids())
    if not matches:
        st.info("No matches yet. Upload some PDFs above to get started.")
        return

    rows = []
    for m in matches:
        rows.append({
            "ID": m["id"],
            "Date": m["match_date"],
            "Team": m["team_name"] + (f" {m['age_group']}" if m["age_group"] else ""),
            "Opponent": m["opponent"],
            "Score": U.fmt_score(m),
            "Result": U.result_for_home(m),
            "Season": m["season"],
            "Source": m["source_file"],
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("🗑️ Delete a match"):
        ids = {U.match_label(m): m["id"] for m in matches}
        sel = st.selectbox("Select match to delete", list(ids.keys()))
        if st.button("Delete match", type="secondary"):
            db.delete_match(c, ids[sel], club_id=_club())
            st.success("Deleted.")
            st.rerun()


# ---------------------------------------------------------------------------
# Screen 2 — Match Dashboard
# ---------------------------------------------------------------------------
def _render_position_editor(c, rows):
    """Render an inline, editable position table for the current match.

    Problem 3: lets a coach change ``player_match_stats.position`` for any
    player straight from the Match Dashboard. The list of selectable positions
    is the canonical set from ``metrics.POSITIONS``. When a position is
    changed we persist it immediately via ``db.update_player_match_position``
    and rerun so every downstream view (pitch, team totals, rankings) reflects
    the recomputed impact scores.
    """
    with st.expander("✏️ Edit player positions", expanded=False):
        st.caption(
            "Change a player's position and the impact scores recalculate "
            "automatically (they are computed live from the position). "
            "Edits are saved immediately."
        )

        positions = list(M.POSITIONS)
        # Map each player_match_stats id -> its current (canonical) position so
        # we can detect exactly which rows changed after the edit.
        original = {}
        edit_rows = []
        for r in rows:
            pms_id = r["pms_id"]
            pos = r.get("position")
            if pos not in M.POSITION_SET:
                pos = _canonical_position(pos)
                if pos not in M.POSITION_SET:
                    pos = positions[0]
            original[pms_id] = pos
            edit_rows.append({
                "pms_id": pms_id,
                "Player": r["player_name"],
                "Position": pos,
                "Total Impact": r["impact"]["total_impact"],
            })

        edit_df = pd.DataFrame(edit_rows)
        edited = st.data_editor(
            edit_df,
            hide_index=True,
            use_container_width=True,
            key="match_position_editor",
            column_config={
                "pms_id": None,  # hidden internal id
                "Player": st.column_config.TextColumn("Player", disabled=True),
                "Position": st.column_config.SelectboxColumn(
                    "Position", options=positions, required=True,
                    help="Pick from the canonical positions defined in metrics.py."),
                "Total Impact": st.column_config.NumberColumn(
                    "Total Impact", disabled=True,
                    help="Live score for the current position."),
            },
        )

        # Detect and persist any position changes.
        changes = []
        for _, er in edited.iterrows():
            pms_id = int(er["pms_id"])
            new_pos = er["Position"]
            if new_pos and new_pos != original.get(pms_id):
                changes.append((pms_id, er["Player"], original.get(pms_id), new_pos))

        if changes:
            for pms_id, player, old_pos, new_pos in changes:
                db.update_player_match_position(c, pms_id, new_pos, club_id=_club())
                # st.toast survives the rerun, so the confirmation stays
                # visible after impact scores recalculate.
                st.toast(f"✅ {player}: '{old_pos}' → '{new_pos}'. "
                         f"Impact recalculated.", icon="✅")
            st.cache_data.clear()
            st.rerun()


def screen_match():
    st.header("📊 Match Dashboard")
    c = conn()
    matches = db.list_matches(c, _club(), team_ids=_team_ids())
    if not matches:
        st.info("No matches available. Upload PDFs in the Upload & Overview screen.")
        return

    labels = {U.match_label(m): m for m in matches}

    # --- Compact header: selectors on one row, match meta on the next ---
    hc1, hc2 = st.columns([3, 2])
    with hc1:
        sel = st.selectbox("Select match", list(labels.keys()))
    match = labels[sel]
    with hc2:
        scorer = scoring_selector(c, key="match_profile")

    # GPS / physical data indicator (read-only; impact pipeline unchanged),
    # condensed into a single inline badge instead of a full-width banner.
    gps_rows = db.get_physical_data(c, _club(), session_type="match", match_id=match["id"], team_ids=_team_ids())
    if gps_rows:
        n_players = len({r["player_name"] for r in gps_rows})
        gps_badge = f"✅ GPS: {len(gps_rows)} records · {n_players} spelers"
    else:
        gps_badge = "ℹ️ Geen GPS-data gekoppeld"

    # Single compact metadata row: date · match · score · result · GPS status.
    score = U.fmt_score(match)
    result = U.result_for_home(match)
    st.markdown(
        f"📅 **{match['match_date']}**  ·  "
        f"⚽ **{match['team_name']} vs {match['opponent']}**  ·  "
        f"🔢 **{score}**  ·  🏆 **{result}**  ·  {gps_badge}"
    )

    player_stats = db.get_match_player_stats(c, match["id"], _club())
    rows = score_match_rows(player_stats, scorer)
    if not rows:
        st.warning("No player stats for this match.")
        return

    # --- Problem 3: editable player positions -------------------------------
    # Coaches can re-assign any player's position after import. Impact scores
    # are computed live from player_match_stats.position, so a change here
    # flows straight through to the pitch, team totals and rankings below on
    # the next rerun (no re-import needed).
    _render_position_editor(c, rows)

    # --- Phase 4: football pitch visualization ---
    st.subheader("🟢 Line-up & Impact on the pitch")
    st.caption("Starters are placed by position; colour & number show Total "
               "Impact. Hover a player for the 6-category breakdown. Bench and "
               "substitutes are listed on the right.")
    starters, bench, came_on = _build_pitch_lists(rows)
    pitch, pheight = U.pitch_html(starters, bench, came_on)
    components.html(pitch, height=pheight, scrolling=False)

    # Team aggregate (starters + came-on count toward team play)
    agg = IE.aggregate_team_impact(rows)
    st.subheader("Team totals")
    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("Total Impact", agg["total_impact"])
    tc2.metric("Offensive Impact", agg["offensive_impact"])
    tc3.metric("Defensive Impact", agg["defensive_impact"])
    st.plotly_chart(
        U.radar_chart([agg["category_impact"]], ["Team"],
                      title="Team Category Impact"),
        use_container_width=True,
    )

    # Player ranking
    st.subheader("Player ranking — by Total Impact")
    rank_rows = []
    for r in sorted(rows, key=lambda x: x["impact"]["total_impact"], reverse=True):
        imp = r["impact"]
        rank_rows.append({
            "Player": r["player_name"],
            "Pos": r.get("effective_position") or r["position"],
            "Status": r.get("status") or M.STATUS_STARTER,
            "Min": r["minutes_played"],
            "Total Impact": imp["total_impact"],
            "Impact/90": imp["impact_per_90"],
            "Impact/Action": imp["impact_per_action"],
            "Off. Eff.": imp["offensive_efficiency"],
            "Def. Eff.": imp["defensive_efficiency"],
        })
    rank_df = pd.DataFrame(rank_rows)
    st.dataframe(
        U.highlight_max(rank_df, ["Total Impact", "Impact/90", "Impact/Action",
                                  "Off. Eff.", "Def. Eff."]),
        use_container_width=True, hide_index=True,
    )

    # Detailed key metrics
    st.subheader("Player key statistics")
    key_metrics = ["goals", "assists", "shots", "key_passes", "total_passes",
                   "total_passes_pct", "forward_passes", "passes_final_third",
                   "dribbles", "recoveries", "interceptions", "tackles", "aerials"]
    detail_rows = []
    for r in sorted(rows, key=lambda x: x["impact"]["total_impact"], reverse=True):
        d = {"Player": r["player_name"], "Pos": r["position"]}
        for mk in key_metrics:
            d[M.METRIC_BY_KEY[mk]["label"]] = r["stats"].get(mk)
        detail_rows.append(d)
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    # --- Physical / GPS data (read-only; impact pipeline unchanged) ---
    # BUG 5 fix: previously the dashboard only showed a one-line GPS badge.
    # When a physical session is linked to this match we now also render the
    # underlying tracking data (KPIs + per-player table) so it is actually
    # visible, mirroring the layout used on the Physical / GPS screen.
    _render_match_physical(gps_rows)

    # --- Problem 1: individual physical data per player ---------------------
    # Per-player GPS metrics (own data only, no team totals). Players without
    # linked GPS data show "No GPS data".
    _render_match_player_physical(c, rows, match["id"])


# Display labels + formatting for the six headline per-player physical metrics.
_PLAYER_PHYSICAL_FORMAT = [
    ("total_distance",          "Total Distance",  "km"),
    ("sprint_distance",         "Sprint Distance", "km"),
    ("high_intensity_distance", "High Intensity Distance", "km"),
    ("top_speed",               "Top Speed",       "kmh"),
    ("accelerations",           "Accelerations",   "count"),
    ("decelerations",           "Decelerations",   "count"),
]

_NO_GPS = "No GPS data"


def _fmt_player_physical(value, kind):
    """Format a single physical metric value for display.

    ``kind``: 'km' (metres → km), 'kmh' (km/h), 'count' (whole number).
    Returns the ``_NO_GPS`` placeholder when ``value`` is None.
    """
    if value is None:
        return _NO_GPS
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _NO_GPS
    if kind == "km":
        return f"{v / 1000:.2f} km"
    if kind == "kmh":
        return f"{v:.1f} km/h"
    if kind == "count":
        return f"{int(round(v))}"
    if kind == "permin":
        return f"{v:.1f} m/min"
    return f"{v:.1f}"


# --- Problem 2: Player Profile physical section ---------------------------
# The seven metrics shown on the Player Profile, with display labels + format.
_PLAYER_PROFILE_PHYSICAL_FORMAT = [
    ("total_distance",          "Total Distance",          "km"),
    ("sprint_distance",         "Sprint Distance",         "km"),
    ("high_intensity_distance", "High Intensity Distance", "km"),
    ("top_speed",               "Top Speed",               "kmh"),
    ("accelerations",           "Accelerations",           "count"),
    ("decelerations",           "Decelerations",           "count"),
    ("distance_per_minute",     "Distance per Minute",     "permin"),
]

# Fixed physiological reference scales used to normalise the 5 spiderchart
# categories onto a 0–100 axis. These are NOT team/squad benchmarks — they are
# constant reference ranges so a single player's aggregate can be plotted as a
# shape. Each category maps a (min, max) range; values are clamped to [0, 100].
_PHYSICAL_SPIDER_SCALES = {
    # category: (low, high, builder(agg) -> raw value or None)
    "Volume":         (0.0, 12000.0),   # total distance (m)
    "Speed":          (18.0, 36.0),     # top speed (km/h)
    "High Intensity": (0.0, 1500.0),    # high-intensity + sprint distance (m)
    "Acc/Dec":        (0.0, 200.0),     # accelerations + decelerations (count)
    "Load":           (0.0, 120.0),     # distance per minute (m/min)
}

# Order of the spiderchart axes.
_PHYSICAL_SPIDER_ORDER = ["Volume", "Speed", "High Intensity", "Acc/Dec", "Load"]


def _physical_spider_raw(agg):
    """Build the raw (un-normalised) value for each of the 5 spider categories.

    Uses ONLY the selected player's aggregate ``agg``. Missing inputs yield
    ``None`` for that category.
    """
    def _add(*keys):
        vals = [agg.get(k) for k in keys]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    return {
        "Volume":         agg.get("total_distance"),
        "Speed":          agg.get("top_speed"),
        "High Intensity": _add("high_intensity_distance", "sprint_distance"),
        "Acc/Dec":        _add("accelerations", "decelerations"),
        "Load":           agg.get("distance_per_minute"),
    }


def _normalize_physical_spider(agg):
    """Return (values, labels, raw) for the 5-category physical spiderchart.

    ``values``: list of 0–100 normalised scores aligned to ``labels``.
    ``raw``:    the underlying raw values (for the hover tooltip).
    Normalisation is linear within each category's fixed reference range and
    clamped to [0, 100]. A ``None`` raw value normalises to 0.
    """
    raw_map = _physical_spider_raw(agg)
    values, labels, raw = [], [], []
    for cat in _PHYSICAL_SPIDER_ORDER:
        low, high = _PHYSICAL_SPIDER_SCALES[cat]
        rv = raw_map.get(cat)
        if rv is None:
            norm = 0.0
        else:
            norm = (float(rv) - low) / (high - low) * 100.0
            norm = max(0.0, min(100.0, norm))
        labels.append(cat)
        values.append(round(norm, 1))
        raw.append(round(float(rv), 1) if rv is not None else 0.0)
    return values, labels, raw


def _render_player_physical_profile(c, pid, name):
    """Render the Physical Profile section for one player on the Player Profile.

    Shows the seven headline metrics (averaged across the player's matches) and
    a 5-axis physical spiderchart. Uses ONLY the selected player's own data;
    shows a "No physical data available" message when the player has no GPS
    data linked.
    """
    st.subheader("🏃 Physical Profile")
    agg = db.get_player_physical_aggregate(c, pid, _club())
    if agg is None:
        st.info("No physical data available")
        return

    st.caption(
        f"Aggregated across {agg.get('sessions', 0)} match(es) with linked GPS "
        "data for this player only. Distances in km, speed in km/h, "
        "accelerations/decelerations as counts, distance per minute in m/min."
    )

    # Seven headline metrics in two rows of columns.
    fmt = _PLAYER_PROFILE_PHYSICAL_FORMAT
    cols = st.columns(4)
    for i, (key, label, kind) in enumerate(fmt[:4]):
        cols[i].metric(label, _fmt_player_physical(agg.get(key), kind))
    cols = st.columns(4)
    for i, (key, label, kind) in enumerate(fmt[4:]):
        cols[i].metric(label, _fmt_player_physical(agg.get(key), kind))

    # Physical spiderchart (5 normalised categories).
    values, labels, raw = _normalize_physical_spider(agg)
    st.plotly_chart(
        U.metric_radar_chart([values], [name], labels, hover_raw=[raw],
                             title=f"{name} — Physical Profile"),
        use_container_width=True,
    )
    st.caption(
        "Spiderchart categories are normalised to a 0–100 scale using fixed "
        "physiological reference ranges (not team benchmarks): "
        "Volume = total distance, Speed = top speed, "
        "High Intensity = high-intensity + sprint distance, "
        "Acc/Dec = accelerations + decelerations, Load = distance per minute. "
        "Hover to see the player's raw aggregated values."
    )


def _render_match_player_physical(c, rows, match_id):
    """Render a per-player physical/GPS table for the match.

    For every player in the line-up the function fetches ONLY that player's
    own physical data for this match (via ``db.get_player_physical_for_match``)
    and shows the six headline metrics. Players without linked GPS data show
    "No GPS data".
    """
    st.subheader("🏃 Individuele fysieke data per speler")
    st.caption("Per-player GPS metrics for this match (each player's own data "
               "only). Total/Sprint/High-Intensity distance in km, Top Speed "
               "in km/h, Accelerations & Decelerations as counts. "
               "Players without linked GPS data show \"No GPS data\".")

    table_rows = []
    n_with_data = 0
    for r in sorted(rows, key=lambda x: x["impact"]["total_impact"],
                    reverse=True):
        phys = db.get_player_physical_for_match(c, r.get("player_id"), match_id, _club())
        entry = {
            "Player": r["player_name"],
            "Pos": r.get("effective_position") or r["position"],
        }
        if phys is None:
            for _key, label, _kind in _PLAYER_PHYSICAL_FORMAT:
                entry[label] = _NO_GPS
        else:
            n_with_data += 1
            for key, label, kind in _PLAYER_PHYSICAL_FORMAT:
                entry[label] = _fmt_player_physical(phys.get(key), kind)
        table_rows.append(entry)

    st.caption(f"{n_with_data} van {len(table_rows)} speler(s) met "
               f"gekoppelde GPS-data.")
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True,
                 hide_index=True)


def _render_match_physical(gps_rows):
    """Render linked physical/GPS data for a match (KPIs + per-player table).

    ``gps_rows`` is the list of sqlite Rows returned by
    ``db.get_physical_data(session_type='match', match_id=...)``. When empty,
    a short hint is shown so the user knows where to link a session.
    """
    st.subheader("🏃 Physical / GPS data")
    if not gps_rows:
        st.info("Geen GPS-/fysieke data gekoppeld aan deze wedstrijd. "
                "Koppel een sessie via het scherm **Physical / GPS Data** "
                "(sectie *Sessiebeheer → Koppelen*) om de tracking-data hier "
                "te tonen.")
        return

    pdf_ = _physical_rows_to_df(gps_rows)
    if pdf_.empty:
        st.info("Geen GPS-/fysieke records gevonden voor deze wedstrijd.")
        return

    def _sum(col):
        return float(pdf_[col].dropna().sum()) if col in pdf_ else 0.0

    def _max(col):
        s = pdf_[col].dropna() if col in pdf_ else pd.Series(dtype=float)
        return float(s.max()) if not s.empty else 0.0

    n_players = pdf_["player_name"].nunique() if "player_name" in pdf_ else 0
    st.caption(f"{len(gps_rows)} record(s) · {n_players} speler(s) gekoppeld.")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Totale afstand (m)", f"{_sum('total_distance'):,.0f}")
    k2.metric("Sprintafstand (m)", f"{_sum('sprint_distance'):,.0f}")
    k3.metric("Topsnelheid (km/u)", f"{_max('top_speed'):.1f}")
    k4.metric("Versnellingen", f"{_sum('accelerations'):,.0f}")

    # Per-player aggregated table (sum, except speed/accel peaks → max)
    agg_spec = {col: ("max" if col in ("top_speed", "max_acceleration",
                                        "percentage_max_speed") else "sum")
                for col in db.PHYSICAL_METRIC_COLS if col in pdf_}
    grouped = (pdf_.groupby("player_name", as_index=False).agg(agg_spec)
               if agg_spec else pdf_)
    nice = {
        "player_name": "Speler", "total_distance": "Afstand (m)",
        "sprint_distance": "Sprint (m)", "high_intensity_distance": "HI-afstand (m)",
        "top_speed": "Topsnelheid (km/u)", "accelerations": "Versn.",
        "decelerations": "Vertr.", "session_load": "Load",
        "distance_per_minute": "m/min", "edi_percentage": "EDI %",
    }
    show_cols = ["player_name"] + [col for col in
                 ["total_distance", "sprint_distance", "high_intensity_distance",
                  "top_speed", "distance_per_minute", "accelerations",
                  "decelerations", "session_load", "edi_percentage"]
                 if col in grouped.columns]
    tbl = grouped[show_cols].rename(columns=nice).sort_values(
        nice.get("total_distance", "Speler"),
        ascending=False) if "total_distance" in grouped.columns else \
        grouped[show_cols].rename(columns=nice)
    st.dataframe(tbl, use_container_width=True, hide_index=True,
                 column_config={col: st.column_config.NumberColumn(format="%.1f")
                                for col in tbl.columns if col != "Speler"})


# ---------------------------------------------------------------------------
# Screen 3 — Player Profile
# ---------------------------------------------------------------------------
def screen_player():
    st.header("👤 Player Profile")
    c = conn()
    players = [p for p in db.list_players(c, _club(), team_ids=_team_ids()) if p["appearances"] > 0]
    if not players:
        st.info("No players available. Upload PDFs first.")
        return

    pmap = {p["name"]: p["id"] for p in players}
    sel = st.selectbox("Select player", list(pmap.keys()))
    pid = pmap[sel]

    scorer = scoring_selector(c, key="player_profile")

    full_history = db.get_player_match_history(c, pid, _club(), team_ids=_team_ids())

    # --- BUG 4 fix: allow viewing the whole career OR a single match ---------
    # Career Overview is the default (unchanged behaviour). Single Match filters
    # the history to one game so every section below (KPIs, radar, drill-down,
    # strengths/weaknesses) reflects just that match.
    view_mode = st.radio(
        "Weergave", ["Career Overview", "Single Match"],
        horizontal=True, key="player_view_mode",
        help=("Career Overview toont het carrière-/seizoensgemiddelde; "
              "Single Match toont de cijfers van één geselecteerde wedstrijd."),
    )

    history = full_history
    if view_mode == "Single Match":
        if not full_history:
            st.info("Geen wedstrijden beschikbaar voor deze speler.")
            return
        match_labels = {}
        for r in full_history:
            loc = "thuis" if r.get("is_home") else "uit"
            label = (f"{r['match_date']} — {r['opponent']} "
                     f"({r['home_score']}:{r['away_score']}, {loc})")
            match_labels[label] = r["match_id"]
        chosen_match = st.selectbox("Selecteer wedstrijd", list(match_labels.keys()),
                                    key="player_single_match")
        chosen_mid = match_labels[chosen_match]
        history = [r for r in full_history if r["match_id"] == chosen_mid]

    summary = career_sum(history, scorer)

    st.subheader(sel)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Usual position", summary["avg_position"])
    c2.metric("Matches", summary["matches"])
    c3.metric("Total minutes", summary["total_minutes"])
    c4.metric("Goals / Assists", f"{summary['total_goals']} / {summary['total_assists']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg Total Impact", summary["avg_impact"])
    c2.metric("Avg Impact / 90", summary["avg_impact_per_90"])
    c3.metric("Career Total Impact", summary["total_impact"])

    # --- Verbetering #1: Form indicator (last 5 matches vs season average) ---
    form = IE.form_indicator(summary.get("rows", []), window=5)
    if form["sufficient"]:
        c4.metric(
            "Vorm (laatste 5)",
            f"{form['arrow']} {form['pct']:+.0f}%",
            delta=form["label"],
            delta_color="off",
            help=(f"Laatste {form['window']} wedstrijden ({form['recent_avg']}) "
                  f"vs. seizoensgemiddelde ({form['season_avg']}).  "
                  "Last 5 matches vs season average."),
        )
    else:
        c4.metric(
            "Vorm (laatste 5)", "—",
            help=("Minimaal 5 wedstrijden nodig om vorm te bepalen "
                  f"(nu {form['matches']}). Insufficient data."),
        )

    # Radar
    st.subheader("Category impact profile (per-match average)")
    st.plotly_chart(
        U.radar_chart([summary["category_avg"]], [sel],
                      title=f"{sel} — Avg Category Impact"),
        use_container_width=True,
    )

    is_keeper = (summary.get("avg_position") == "Goalkeeper"
                 or IE.player_has_goalkeeping(history))
    _tids = _team_ids()
    reference = squad_metric_reference(_club(), tuple(_tids) if _tids is not None else None)

    # --- Verbetering #2: automatic strengths & weaknesses summary --------
    st.subheader("💪 Sterktes & Werkpunten")
    st.caption("Automatisch afgeleid uit de genormaliseerde metric-scores "
               "(0–100, t.o.v. de selectie). De top sterktes en belangrijkste "
               "werkpunten in één oogopslag — geen radar-interpretatie nodig.")
    strengths, weaknesses = IE.get_strengths_weaknesses(
        history, reference, is_keeper=is_keeper, top_n=3)

    if not strengths and not weaknesses:
        st.info("Onvoldoende data beschikbaar voor een sterkte/werkpunt-analyse.")
    else:
        sw1, sw2 = st.columns(2)
        with sw1:
            st.markdown("**💪 Sterktes**")
            if strengths:
                for s in strengths:
                    st.markdown(
                        f"✅ **{s['metric_name']}** — {s['score']:.0f}/100  \n"
                        f"<span style='color:#6b7280;font-size:0.85em'>"
                        f"{s['category']}</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Onvoldoende data.")
        with sw2:
            st.markdown("**⚠️ Werkpunten**")
            if weaknesses:
                for w in weaknesses:
                    st.markdown(
                        f"⚠️ **{w['metric_name']}** — {w['score']:.0f}/100  \n"
                        f"<span style='color:#6b7280;font-size:0.85em'>"
                        f"{w['category']}</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Onvoldoende data.")

    # --- MVP-B: category drill-down -------------------------------------
    st.subheader("🔬 Drill-down: metrics within a category")
    st.caption("Pick a category from the overview above to inspect the "
               "individual metrics behind it. Scores are normalised to a "
               "0–100 scale relative to the squad (90th percentile) so the "
               "axes stay comparable; the player's raw per-match average is "
               "shown on hover.")

    drill_cats = [cat for cat in M.CATEGORIES
                  if cat != "Goalkeeping" or is_keeper]

    chosen_cat = st.selectbox("Category to drill into", drill_cats,
                              key="drill_category")
    breakdown = IE.category_metric_breakdown(history, chosen_cat, reference)

    if not breakdown:
        st.info("No metrics recorded for this category yet.")
    else:
        labels = [d["label"] for d in breakdown]
        vals = [d["normalized"] for d in breakdown]
        raws = [d["avg"] for d in breakdown]
        if len(labels) >= 3:
            st.plotly_chart(
                U.metric_radar_chart([vals], [sel], labels, hover_raw=[raws],
                                     title=f"{sel} — {chosen_cat} metrics"),
                use_container_width=True,
            )
        else:
            # A radar needs ≥3 axes to form a shape; fall back to a bar chart.
            st.bar_chart(pd.DataFrame({"Score (0–100)": vals}, index=labels))
        st.dataframe(
            pd.DataFrame([{
                "Metric": d["label"],
                "Avg / match": d["avg"],
                "Score (0–100)": d["normalized"],
                "Type": "percentage" if d["is_pct"] else "count",
            } for d in breakdown]),
            use_container_width=True, hide_index=True,
        )

    # --- Phase 8: per-position breakdown ---
    by_pos = summary.get("by_position")
    if by_pos:
        st.subheader("📍 Performance per position")
        st.caption("This player's impact is scored with the weights of the "
                   "position actually played in each match, then split per "
                   "position so you can see where they perform best.")
        bp_rows = []
        for pos, s in sorted(by_pos.items(),
                             key=lambda kv: kv[1]["total_impact"], reverse=True):
            bp_rows.append({
                "Position": pos,
                "Matches": s["matches"],
                "Minutes": s["total_minutes"],
                "Avg Impact": s["avg_impact"],
                "Avg Impact/90": s["avg_impact_per_90"],
                "Total Impact": s["total_impact"],
                "Goals": s["total_goals"],
                "Assists": s["total_assists"],
            })
        st.dataframe(
            U.highlight_max(pd.DataFrame(bp_rows),
                            ["Avg Impact", "Avg Impact/90", "Total Impact"]),
            use_container_width=True, hide_index=True,
        )
        if len(by_pos) > 1:
            st.plotly_chart(
                U.radar_chart([s["category_avg"] for s in by_pos.values()],
                              list(by_pos.keys()),
                              title=f"{sel} — Category impact per position"),
                use_container_width=True,
            )

    # --- Problem 2: Physical Profile (selected player's own GPS data only) ---
    _render_player_physical_profile(c, pid, sel)

    # Match history
    st.subheader("Match history")
    hist_rows = []
    for r in summary["rows"]:
        imp = r["impact"]
        hist_rows.append({
            "Date": r["match_date"],
            "Opponent": r["opponent"],
            "Score": f"{r['home_score']} : {r['away_score']}",
            "Pos": r.get("effective_position") or r["position"],
            "Status": r.get("status") or M.STATUS_STARTER,
            "Min": r["minutes_played"],
            "Total Impact": imp["total_impact"],
            "Impact/90": imp["impact_per_90"],
            "Goals": int(r["stats"].get("goals") or 0),
            "Assists": int(r["stats"].get("assists") or 0),
        })
    st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Screen 4 — Player Comparison
# ---------------------------------------------------------------------------
def screen_comparison():
    st.header("⚖️ Player Comparison")
    c = conn()
    players = [p for p in db.list_players(c, _club(), team_ids=_team_ids()) if p["appearances"] > 0]
    if len(players) < 2:
        st.info("Need at least 2 players with data to compare.")
        return

    pmap = {f"{p['name']} ({p['appearances']} apps)": p["id"] for p in players}
    sel = st.multiselect("Select 2–4 players", list(pmap.keys()),
                         max_selections=4)
    if len(sel) < 2:
        st.info("Select at least 2 players.")
        return

    scorer = scoring_selector(c, key="cmp_profile")

    summaries = {}
    for label in sel:
        pid = pmap[label]
        name = next(p["name"] for p in players if p["id"] == pid)
        history = db.get_player_match_history(c, pid, _club(), team_ids=_team_ids())
        summaries[name] = career_sum(history, scorer)

    # Side-by-side table
    st.subheader("Side-by-side (career averages)")
    table = {"Metric": ["Matches", "Total minutes", "Avg Total Impact",
                        "Avg Impact/90", "Goals", "Assists",
                        *[f"Cat: {cat}" for cat in M.CATEGORIES]]}
    for name, s in summaries.items():
        table[name] = [
            s["matches"], s["total_minutes"], s["avg_impact"],
            s["avg_impact_per_90"], s["total_goals"], s["total_assists"],
            *[s["category_avg"][cat] for cat in M.CATEGORIES],
        ]
    cmp_df = pd.DataFrame(table).set_index("Metric")
    # highlight best per row (max across player columns)
    def _row_max(s):
        is_max = s == s.max()
        return ["background-color:#c6f6d5;font-weight:600" if v else "" for v in is_max]
    st.dataframe(cmp_df.style.apply(_row_max, axis=1), use_container_width=True)

    # Radar overlay
    st.subheader("Category impact — radar overlay")
    st.plotly_chart(
        U.radar_chart([s["category_avg"] for s in summaries.values()],
                      list(summaries.keys()), title="Category Impact comparison"),
        use_container_width=True,
    )

    # Impact/90 bar
    st.subheader("Average Impact / 90 comparison")
    bar_df = pd.DataFrame({
        "Player": list(summaries.keys()),
        "Impact/90": [s["avg_impact_per_90"] for s in summaries.values()],
    })
    st.plotly_chart(
        U.bar_comparison(bar_df, "Player", "Impact/90", "Player", "Avg Impact / 90"),
        use_container_width=True,
    )

    # --- Phase 9: per-position comparison ---
    pos_present = {}
    for name, s in summaries.items():
        for pos in (s.get("by_position") or {}):
            pos_present.setdefault(pos, []).append(name)
    if pos_present:
        st.subheader("📍 Per-position comparison")
        st.caption("Compare players on the same position only — useful when "
                   "two players have played different roles.")
        # default to a position shared by the most players
        ordered = sorted(pos_present.keys(),
                         key=lambda p: len(pos_present[p]), reverse=True)
        chosen_pos = st.selectbox(
            "Position", ordered,
            format_func=lambda p: f"{p}  ({len(pos_present[p])} player"
                                  f"{'s' if len(pos_present[p]) != 1 else ''})",
            key="cmp_pos_sel")
        sub = {name: s["by_position"][chosen_pos]
               for name, s in summaries.items()
               if chosen_pos in (s.get("by_position") or {})}
        if len(sub) < 1:
            st.info("No players have data on this position.")
        else:
            ptable = {"Metric": ["Matches", "Minutes", "Avg Impact",
                                 "Avg Impact/90", "Total Impact",
                                 "Goals", "Assists"]}
            for name, s in sub.items():
                ptable[name] = [s["matches"], s["total_minutes"],
                                s["avg_impact"], s["avg_impact_per_90"],
                                s["total_impact"], s["total_goals"],
                                s["total_assists"]]
            pdf_ = pd.DataFrame(ptable).set_index("Metric")

            def _row_max2(srow):
                is_max = srow == srow.max()
                return ["background-color:#c6f6d5;font-weight:600" if v else ""
                        for v in is_max]
            st.dataframe(pdf_.style.apply(_row_max2, axis=1),
                         use_container_width=True)
            if len(sub) > 1:
                st.plotly_chart(
                    U.radar_chart([s["category_avg"] for s in sub.values()],
                                  list(sub.keys()),
                                  title=f"Category impact at {chosen_pos}"),
                    use_container_width=True,
                )


# ---------------------------------------------------------------------------
# Screen 5 — Evolution Dashboard
# ---------------------------------------------------------------------------
def screen_evolution():
    st.header("📈 Evolution Dashboard")
    c = conn()
    players = [p for p in db.list_players(c, _club(), team_ids=_team_ids()) if p["appearances"] > 0]
    if not players:
        st.info("No players available. Upload PDFs first.")
        return

    pmap = {p["name"]: p["id"] for p in players}
    sel = st.selectbox("Select player", list(pmap.keys()))
    pid = pmap[sel]

    scorer = scoring_selector(c, key="evo_profile")

    history = db.get_player_match_history(c, pid, _club(), team_ids=_team_ids())
    rows = score_match_rows(history, scorer)
    if len(rows) < 1:
        st.info("No match data for this player.")
        return
    if len(rows) < 2:
        st.warning("Only one match available — evolution charts need at least 2 matches.")

    base = []
    for r in rows:
        imp = r["impact"]
        rec = {
            "Date": r["match_date"],
            "Opponent": r["opponent"],
            "Total Impact": imp["total_impact"],
            "Impact/90": imp["impact_per_90"],
        }
        for cat in M.CATEGORIES:
            rec[cat] = imp["category_impact"][cat]
        base.append(rec)
    df = pd.DataFrame(base).sort_values("Date")

    # --- Verbetering #1: rolling averages to smooth match-to-match noise ---
    show_rolling = st.checkbox(
        "Toon voortschrijdende gemiddelden (3- en 5-match)", value=True,
        help=("Voegt gladgestreken trendlijnen toe bovenop de ruwe data: "
              "3-match (kort) en 5-match (langer). Ruwe data blijft de "
              "primaire weergave.  Adds 3- and 5-match rolling averages."),
    )
    if show_rolling:
        st.plotly_chart(U.rolling_line_chart(df, "Date", "Total Impact",
                                             "Total Impact over time (met rolling averages)"),
                        use_container_width=True)
        st.plotly_chart(U.rolling_line_chart(df, "Date", "Impact/90",
                                             "Impact / 90 over time (met rolling averages)"),
                        use_container_width=True)
    else:
        st.plotly_chart(U.line_chart(df, "Date", "Total Impact",
                                     "Total Impact over time"), use_container_width=True)
        st.plotly_chart(U.line_chart(df, "Date", "Impact/90",
                                     "Impact / 90 over time"), use_container_width=True)

    st.subheader("Category breakdown over time")
    long_df = df.melt(id_vars=["Date"], value_vars=M.CATEGORIES,
                      var_name="Category", value_name="Impact")
    st.plotly_chart(U.stacked_area(long_df, "Date", "Impact", "Category",
                                   "Category impact (stacked) over time"),
                    use_container_width=True)

    st.subheader("Match-by-match progression")
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Screen 6 — Profile Editor
# ---------------------------------------------------------------------------
_SCALE_HELP = (
    "**0–10 importance scale** — 0 = not important, 1–3 = slightly, "
    "4–6 = average, 7–8 = important, 9–10 = very important. "
    "Internally an importance of 5 keeps the framework's base weight; "
    "10 doubles it and 0 removes the category for this position."
)


def screen_profile_editor():
    st.header("🛠️ Profile Editor")
    mode = st.radio(
        "What do you want to edit?",
        ["⚽ Position profile (recommended)", "🎚️ Legacy playing-style profile"],
        horizontal=True,
    )
    if mode.startswith("⚽"):
        _position_profile_editor(conn())
        return
    _legacy_profile_editor(conn())


def _position_profile_editor(c):
    st.caption("Set how important each of the 6 impact categories is **per "
               "position**. The same statistics matter differently for a "
               "goalkeeper than for a striker. " + _SCALE_HELP)

    profiles = db.list_position_profiles(c, _club())
    if not profiles:
        st.warning("No position profiles available.")
        return
    pmap = {p["name"]: p for p in profiles}
    csel1, csel2 = st.columns(2)
    sel = csel1.selectbox("Position profile", list(pmap.keys()),
                          key="pp_profile_sel")
    prof = pmap[sel]
    if prof["description"]:
        st.info(prof["description"])
    position = csel2.selectbox("Position", list(M.POSITIONS), key="pp_pos_sel")

    importances = db.get_position_profile_importances(c, prof["id"])
    current = importances.get(position, {})

    with st.form(key=f"pp_form_{prof['id']}_{position}"):
        st.markdown(f"#### {position} — category importance")
        new_vals = {}
        cols = st.columns(3)
        for i, cat in enumerate(M.CATEGORIES):
            with cols[i % 3]:
                new_vals[cat] = st.slider(
                    cat, min_value=0, max_value=10,
                    value=int(round(float(current.get(cat, 5)))),
                    key=f"pp_{prof['id']}_{position}_{cat}",
                )
        saved = st.form_submit_button("💾 Save this position", type="primary")
        if saved:
            db.update_position_profile_importances(
                c, prof["id"], {position: {k: float(v) for k, v in new_vals.items()}})
            st.success(f"Saved category importances for {position} "
                       f"in '{prof['name']}'.")

    # Overview of all positions for this profile
    with st.expander("📋 Show all positions in this profile"):
        ov = []
        for pos in M.POSITIONS:
            row = {"Position": pos}
            for cat in M.CATEGORIES:
                row[cat] = round(float(importances.get(pos, {}).get(cat, 5)), 1)
            ov.append(row)
        st.dataframe(pd.DataFrame(ov), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("↩️ Reset whole profile to defaults", key="pp_reset"):
            db.reset_position_profile_to_default(c, prof["id"])
            st.success("Reset all positions to framework defaults.")
            st.rerun()
    with col2:
        with st.popover("➕ Create new position profile (duplicate)"):
            new_name = st.text_input("New profile name", key="pp_new_name")
            new_desc = st.text_input("Description", key="pp_new_desc",
                                     value=f"Copy of {prof['name']}")
            if st.button("Create", key="pp_create_btn"):
                if not new_name.strip():
                    st.error("Please enter a name.")
                else:
                    try:
                        club_id = _club()
                        db.create_position_profile(
                            c, club_id, new_name.strip(), new_desc, importances)
                        st.success(f"Created '{new_name}'.")
                        st.rerun()
                    except Exception as e:  # noqa
                        st.error(f"Could not create: {e}")


def _legacy_profile_editor(c):
    st.caption("Tune how each statistic contributes to a player's Impact score. "
               "Higher weight = more important for this playing style.")
    profiles = get_profiles(c)
    pmap = {p["name"]: p for p in profiles}
    sel = st.selectbox("Select profile to edit", list(pmap.keys()))
    prof = pmap[sel]
    st.info(prof["description"] or "")

    weights = db.get_profile_weights(c, prof["id"])
    cats = M.metrics_by_category()

    with st.form(key=f"editor_{prof['id']}"):
        new_weights = {}
        for cat in M.CATEGORIES:
            cat_metrics = [m for m in cats[cat] if m["key"] not in M.CONTEXT_KEYS]
            if not cat_metrics:
                continue
            st.markdown(f"#### {cat}")
            cols = st.columns(3)
            for i, m in enumerate(cat_metrics):
                with cols[i % 3]:
                    new_weights[m["key"]] = st.number_input(
                        m["label"], value=float(weights.get(m["key"], 0.0)),
                        step=0.1, format="%.3f", key=f"w_{prof['id']}_{m['key']}",
                    )
        submitted = st.form_submit_button("💾 Save Profile", type="primary")
        if submitted:
            db.update_profile_weights(c, prof["id"], new_weights)
            st.success(f"Saved weights for '{prof['name']}'.")

    col1, col2 = st.columns(2)
    with col1:
        if prof["name"] in M.DEFAULT_PROFILES:
            if st.button("↩️ Reset to framework defaults"):
                db.reset_profile_to_default(c, prof["id"], prof["name"])
                st.success("Reset to default weights.")
                st.rerun()
        else:
            st.caption("Reset only available for the 4 built-in profiles.")

    with col2:
        with st.popover("➕ Create new profile (duplicate)"):
            new_name = st.text_input("New profile name", key="new_prof_name")
            new_desc = st.text_input("Description", key="new_prof_desc",
                                     value=f"Copy of {prof['name']}")
            if st.button("Create", key="create_prof_btn"):
                if not new_name.strip():
                    st.error("Please enter a name.")
                else:
                    club_id = _club()
                    try:
                        db.create_profile(c, club_id, new_name.strip(), new_desc,
                                          db.get_profile_weights(c, prof["id"]))
                        st.success(f"Created '{new_name}'.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not create: {e}")


# ---------------------------------------------------------------------------
# Screen 7 — Data Management
# ---------------------------------------------------------------------------
def _fmt_ts(ts):
    """Render an ISO timestamp as 'YYYY-MM-DD HH:MM'."""
    if not ts:
        return "—"
    return ts.replace("T", " ")[:16]


@st.dialog("Delete match")
def _confirm_delete_match(match):
    st.markdown(
        f"**Are you sure you want to delete this match?**\n\n"
        f"- **Date:** {match['match_date']}\n"
        f"- **Opponent:** {match['opponent']}\n"
        f"- **Score:** {U.fmt_score(match)}"
    )
    st.markdown(
        ":red[⚠️ This will delete all player stats for this match. "
        "Players left with no remaining matches will also be removed.]"
    )
    col_cancel, col_confirm = st.columns(2)
    if col_cancel.button("Cancel", use_container_width=True, key="dm_cancel_match"):
        st.rerun()
    if col_confirm.button("Confirm delete", type="primary",
                          use_container_width=True, key="dm_confirm_match"):
        try:
            counts = db.delete_match(conn(), match["id"], club_id=_club())
            st.cache_data.clear()
            st.session_state["_dm_flash"] = (
                "success",
                f"Deleted {counts['matches']} match, {counts['player_stats']} player "
                f"stats, {counts['stat_values']} stat values"
                + (f", {counts['players']} orphaned player(s)" if counts["players"] else "")
                + ".",
            )
        except Exception as e:  # noqa
            st.session_state["_dm_flash"] = ("error", f"Deletion failed (rolled back): {e}")
        st.rerun()


@st.dialog("Delete all matches from PDF")
def _confirm_delete_source(group):
    st.markdown(f"**Delete all matches from `{group['source_file']}`?**")
    st.markdown("The following match(es) will be deleted:")
    for m in group["matches"]:
        st.markdown(f"- {m['match_date']} vs {m['opponent']}")
    st.markdown(":red[⚠️ This cannot be undone. Orphaned players will also be removed.]")
    col_cancel, col_confirm = st.columns(2)
    if col_cancel.button("Cancel", use_container_width=True, key="dm_cancel_src"):
        st.rerun()
    if col_confirm.button("Confirm delete", type="primary",
                          use_container_width=True, key="dm_confirm_src"):
        try:
            counts = db.delete_matches_by_source(conn(), group["source_file"], club_id=_club())
            st.cache_data.clear()
            st.session_state["_dm_flash"] = (
                "success",
                f"Deleted {counts['matches']} match(es), {counts['player_stats']} player "
                f"stats, {counts['stat_values']} stat values"
                + (f", {counts['players']} orphaned player(s)" if counts["players"] else "")
                + ".",
            )
        except Exception as e:  # noqa
            st.session_state["_dm_flash"] = ("error", f"Deletion failed (rolled back): {e}")
        st.rerun()


def screen_data_management():
    st.header("🗄️ Data Management")
    st.caption("Review upload history, inspect imported matches, and remove data "
               "with full cascade clean-up. All deletions run inside a transaction.")

    c = conn()

    # Flash message from a previous deletion (survives st.rerun)
    flash = st.session_state.pop("_dm_flash", None)
    if flash:
        kind, msg = flash
        (st.success if kind == "success" else st.error)(msg)

    s = db.summary_counts(c, _club(), team_ids=_team_ids())
    history = db.list_upload_history(c, _club(), team_ids=_team_ids())
    col1, col2, col3 = st.columns(3)
    col1.metric("PDF sources", len(history))
    col2.metric("Matches", s["matches"])
    col3.metric("Players", s["players"])

    if s["matches"] == 0:
        st.info("No match data yet. Upload SciSports PDFs in the Upload & "
                "Overview screen.")
        # Physical sessions can exist independently of technical match data.
        _render_physical_sessions_management(c)
        return

    # ---------------- Section A: Upload History ----------------
    st.subheader("📂 Upload History")
    st.caption("Each row groups the matches imported from one source PDF.")
    for g in history:
        with st.container(border=True):
            cols = st.columns([4, 1.3, 1.6, 1.4])
            cols[0].markdown(f"**{g['source_file']}**")
            cols[0].caption(f"Last upload: {_fmt_ts(g['last_uploaded'])}")
            cols[1].metric("Matches", g["n_matches"])
            cols[2].markdown(
                f"<div style='padding-top:0.6rem'>📥 {g['n_matches']} match"
                f"{'es' if g['n_matches'] != 1 else ''} imported</div>",
                unsafe_allow_html=True,
            )
            if cols[3].button("🗑️ Delete all", key=f"del_src_{g['source_file']}",
                              use_container_width=True):
                _confirm_delete_source(g)

    # ---------------- Section B: Match Overview ----------------
    st.subheader("⚽ Match Overview")
    st.caption("Every imported match with its metadata and source PDF.")
    matches = db.list_matches_detailed(c, _club(), team_ids=_team_ids())
    header = st.columns([0.6, 1.4, 2, 2, 1, 1, 2.2, 1.2])
    for col, label in zip(
        header,
        ["ID", "Date", "Home Team", "Opponent", "Score", "Players", "Source PDF", ""],
    ):
        col.markdown(f"**{label}**")
    for m in matches:
        row = st.columns([0.6, 1.4, 2, 2, 1, 1, 2.2, 1.2])
        home_team = (m["team_name"] + (f" {m['age_group']}" if m["age_group"] else "")) \
            if m["is_home"] else m["opponent"]
        row[0].write(m["id"])
        row[1].write(m["match_date"])
        row[2].write(home_team)
        row[3].write(m["opponent"])
        row[4].write(U.fmt_score(m))
        row[5].write(m["player_count"])
        row[6].caption(m["source_file"] or "Unknown")
        if row[7].button("🗑️ Delete", key=f"del_match_{m['id']}",
                         use_container_width=True):
            _confirm_delete_match(m)

    # ---------------- Section C: Physical Sessions ----------------
    _render_physical_sessions_management(c)


def _render_physical_sessions_management(c):
    """Physical Sessions overview + management inside Data Management.

    Lists every unique physical session with aggregated info and offers
    per-session Delete (removes only physical_data records) and Unlink (sets
    match_id = NULL and session_type = 'unlinked') actions, each guarded by a
    confirmation step. Technical data (matches, player_match_stats, …) is never
    touched here.
    """
    st.subheader("🏃 Physical Sessions")
    st.caption("Every unique GPS/physical session. Deleting a session removes "
               "only its physical_data records — technical data (matches, "
               "player stats) is never affected. Unlinking detaches a session "
               "from its match.")

    sessions = db.get_all_physical_sessions(c, _club(), team_ids=_team_ids())
    if not sessions:
        st.info("No physical sessions yet. Upload Catapult CSV or Game Report "
                "files in the Physical Data screen.")
        return

    TYPE_LABEL = {"match": "🏆 Match", "training": "🏃 Training",
                  "unlinked": "📂 Unlinked"}

    # Overview table
    table = pd.DataFrame([{
        "Session Name": s["session_name"],
        "Type": TYPE_LABEL.get(s["session_type"], s["session_type"]),
        "Date": s["match_date"] or "—",
        "Data Source": s["data_source"] or "—",
        "Players": s["n_players"],
        "Records": s["n_rows"],
        "Linked Match": s["linked_match"] or "—",
    } for s in sessions])
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown("**Manage sessions:**")
    for s in sessions:
        stype = s["session_type"]
        skey = f"{s['session_name']}__{s['data_source']}"
        title = f"{TYPE_LABEL.get(stype, stype)} · {s['session_name']}"
        with st.expander(title, expanded=False):
            info = st.columns(3)
            info[0].write(f"**Date:** {s['match_date'] or '—'}")
            info[0].write(f"**Source:** {s['data_source'] or '—'}")
            info[1].write(f"**Players:** {s['n_players']}")
            info[1].write(f"**Records:** {s['n_rows']}")
            info[2].write(f"**Linked match:** {s['linked_match'] or '—'}")

            st.markdown("**Actions:**")
            act = st.columns([1.3, 1.3, 3])

            # Unlink only available for linked sessions
            if s["match_id"] is not None:
                if act[0].button("🔓 Unlink Session", key=f"dm_unlink_{skey}",
                                 use_container_width=True):
                    st.session_state[f"dm_confirm_unlink_{skey}"] = True
            if act[1].button("🗑️ Delete Session", key=f"dm_del_{skey}",
                             use_container_width=True):
                st.session_state[f"dm_confirm_del_{skey}"] = True

            # --- Unlink confirmation ---
            if st.session_state.get(f"dm_confirm_unlink_{skey}", False):
                st.warning(
                    "⚠️ **Unlink this session from its match?** "
                    "`match_id` will be set to NULL and the session type "
                    "becomes *unlinked*. No records are deleted.")
                uc = st.columns([1, 1, 3])
                if uc[0].button("✅ Yes, unlink", key=f"dm_dounlink_{skey}"):
                    try:
                        n = db.unlink_physical_session(c, s["session_name"], club_id=_club())
                        st.cache_data.clear()
                        st.session_state.pop(f"dm_confirm_unlink_{skey}", None)
                        st.session_state["_dm_flash"] = (
                            "success",
                            f"🔓 Session '{s['session_name']}' unlinked "
                            f"({n} record{'s' if n != 1 else ''} updated).")
                        st.rerun()
                    except Exception as e:  # pragma: no cover - defensive
                        st.session_state["_dm_flash"] = (
                            "error", f"❌ Failed to unlink: {e}")
                        st.rerun()
                if uc[1].button("❌ Cancel", key=f"dm_cancelunlink_{skey}"):
                    st.session_state.pop(f"dm_confirm_unlink_{skey}", None)
                    st.rerun()

            # --- Delete confirmation ---
            if st.session_state.get(f"dm_confirm_del_{skey}", False):
                st.warning(
                    f"⚠️ **Delete session '{s['session_name']}'?** All "
                    f"{s['n_rows']} physical_data record"
                    f"{'s' if s['n_rows'] != 1 else ''} will be permanently "
                    "removed. Technical data (matches, player stats) is NOT "
                    "affected.")
                dc = st.columns([1, 1, 3])
                if dc[0].button("✅ Yes, delete", key=f"dm_dodel_{skey}"):
                    try:
                        n = db.delete_physical_session(c, s["session_name"], club_id=_club())
                        st.cache_data.clear()
                        st.session_state.pop(f"dm_confirm_del_{skey}", None)
                        st.session_state["_dm_flash"] = (
                            "success",
                            f"🗑️ Deleted {n} record{'s' if n != 1 else ''} "
                            f"from session '{s['session_name']}'.")
                        st.rerun()
                    except Exception as e:  # pragma: no cover - defensive
                        st.session_state["_dm_flash"] = (
                            "error", f"❌ Failed to delete: {e}")
                        st.rerun()
                if dc[1].button("❌ Cancel", key=f"dm_canceldel_{skey}"):
                    st.session_state.pop(f"dm_confirm_del_{skey}", None)
                    st.rerun()


# ---------------------------------------------------------------------------
# Physical / GPS-tracking dashboard  (fully separate from impact pipeline)
# ---------------------------------------------------------------------------
def _physical_rows_to_df(rows):
    """Convert a list of sqlite Row (physical_data) to a pandas DataFrame."""
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def screen_physical():
    st.header("🏃 Physical / GPS Data")
    st.caption("Aparte pijplijn voor fysieke tracking-data (Catapult CSV & "
               "wedstrijd-XLSX). Volledig los van de impact-/SciSports-data — "
               "upload, controleer, bewaar en visualiseer.")

    c = conn()
    counts = db.physical_summary_counts(c, _club(), team_ids=_team_ids())
    h1, h2, h3 = st.columns(3)
    h1.metric("Records", counts["rows"])
    h2.metric("Sessies", counts["sessions"])
    h3.metric("Spelers", counts["players"])

    # ---------------- Section A: Upload & parse ----------------
    st.subheader("📤 Bestand uploaden")
    st.caption("Ondersteunde formaten: Catapult export (.csv) en wedstrijd-"
               "rapport (.xlsx). Kolommen worden automatisch herkend.")
    uf = st.file_uploader("Kies een CSV- of XLSX-bestand",
                          type=["csv", "xlsx"], key="phys_upload")

    if uf is not None:
        suffix = os.path.splitext(uf.name)[1] or ".dat"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uf.getbuffer())
            tmp_path = tmp.name
        try:
            df, report = PP.parse_physical_file(tmp_path, original_name=uf.name)
        except PP.PhysicalParseError as e:
            # Detailed, multi-line message (expected vs found columns) is built
            # by the parser; render it as markdown so the coach sees exactly
            # what went wrong instead of a vague one-liner.
            st.error("❌ Kon dit bestand niet verwerken.")
            st.markdown(str(e))
            df, report = None, None
        except Exception as e:  # pragma: no cover - defensive
            st.error(f"❌ Onverwachte fout bij het inlezen: {e}")
            df, report = None, None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if df is not None and report is not None:
            # ---- STAP 2: PREVIEW ----
            type_label = {"catapult_csv": "Catapult CSV",
                          "game_xlsx": "Wedstrijd-XLSX",
                          "game_csv": "Wedstrijd-CSV"}.get(
                              report["file_type"], report["file_type"])
            st.success(f"**{report['filename']}** herkend als **{type_label}** — "
                       f"{report['rows']} rijen, {report['players']} spelers.")

            # Datum uit de data (eerste record) voor wedstrijd-suggesties.
            file_date = None
            if "match_date" in df.columns:
                _dates = df["match_date"].dropna()
                if not _dates.empty:
                    file_date = str(_dates.iloc[0])[:10]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Rijen", report["rows"])
            m2.metric("Spelers", report["players"])
            m3.metric("Periodes", len(report["periods"]))
            m4.metric("Datum", file_date or "Onbekend")
            if report["periods"]:
                st.caption("Periodes: " + ", ".join(report["periods"]))

            if report["warnings"]:
                with st.expander(f"⚠️ {len(report['warnings'])} waarschuwing(en) "
                                 "— ontbrekende metrieken in dit bestand"):
                    for w in report["warnings"]:
                        st.write(f"- {w}")
            st.caption("Herkende metrieken: "
                       + ", ".join(report["found_metrics"]))

            with st.expander("📋 Voorbeeld van de ingelezen data (eerste 5 rijen)"):
                preview_cols = [col for col in df.columns if col != "raw_data"]
                st.dataframe(df[preview_cols].head(), use_container_width=True,
                             hide_index=True)

            st.divider()

            # ---- STAP 3: TYPE SELECTOR ----
            st.markdown("### 🎯 Type sessie")
            session_type_option = st.radio(
                "Wat voor sessie is dit?",
                ["🏆 Wedstrijd", "🏃 Training", "📂 Ongelinkt"],
                horizontal=True, key="phys_session_type")
            if "Wedstrijd" in session_type_option:
                selected_type = "match"
            elif "Training" in session_type_option:
                selected_type = "training"
            else:
                selected_type = "unlinked"

            st.divider()

            # ---- STAP 4: TYPE-SPECIFIEKE FLOW ----
            match_id = None
            session_name = None  # None => parser-sessienaam behouden

            # === WEDSTRIJD-FLOW ===
            if selected_type == "match":
                st.markdown("### 🏆 Wedstrijddetails")
                if file_date:
                    matches_on_date = db.get_matches_for_date(c, file_date, club_id=_club(), team_ids=_team_ids())
                    if matches_on_date:
                        st.write(f"{len(matches_on_date)} wedstrijd(en) "
                                 f"gevonden op **{file_date}**:")
                        match_options = []
                        for mm in matches_on_date:
                            ha = "Thuis" if mm["is_home"] else "Uit"
                            match_options.append(
                                f"{mm['match_date']}: vs {mm['opponent']} ({ha})")
                        NEW_OPT = "➕ Geen van deze / later koppelen"
                        match_options.append(NEW_OPT)
                        selected_match = st.selectbox(
                            "Selecteer wedstrijd:", match_options,
                            key="phys_match_selector")
                        if selected_match != NEW_OPT:
                            idx = match_options.index(selected_match)
                            match_id = matches_on_date[idx]["id"]
                            session_name = selected_match
                        else:
                            st.warning("⚠️ Geen wedstrijd geselecteerd. Data wordt "
                                       "opgeslagen als **ongelinkt** — je kunt het "
                                       "later koppelen.")
                            selected_type = "unlinked"
                    else:
                        st.info(f"ℹ️ Geen wedstrijden gevonden voor {file_date}.")
                        st.warning("Data wordt opgeslagen als **ongelinkt** — je "
                                   "kunt het later koppelen.")
                        selected_type = "unlinked"
                else:
                    st.warning("⚠️ Geen datum in het bestand gevonden; kan niet naar "
                               "wedstrijden zoeken. Data wordt **ongelinkt** "
                               "opgeslagen.")
                    selected_type = "unlinked"

            # === TRAINING-FLOW ===
            elif selected_type == "training":
                st.markdown("### 🏃 Trainingsdetails")
                default_name = (f"Training {file_date}" if file_date
                                else "Trainingssessie")
                session_name = st.text_input(
                    "Naam van de training:", value=default_name,
                    key="phys_training_name")
                st.info(f"💡 Wordt opgeslagen als: **{session_name}**")

            # === ONGELINKT-FLOW ===
            else:
                st.markdown("### 📂 Ongelinkte sessie")
                st.info("💡 Data wordt opgeslagen als **ongelinkt**. Je kunt het "
                        "later aan een wedstrijd koppelen.")

            st.divider()

            # ---- STAP 4b: TEAM-KEUZE (Phase 3 team-isolatie) ----
            # Voor wedstrijd-sessies wordt het team afgeleid van de gekoppelde
            # wedstrijd; voor training/ongelinkt kiest de gebruiker zelf een team
            # zodat de data correct toegewezen blijft.
            upload_team_id = None
            if selected_type != "match":
                _teams = _selectable_teams()
                if not _teams:
                    st.warning("⚠️ Je bent nog niet aan een team toegewezen. "
                               "Vraag je club-beheerder om je toe te wijzen "
                               "voordat je data uploadt.")
                else:
                    st.markdown("### 👥 Team")
                    _team_labels = {f"{t['name']}": t["id"] for t in _teams}
                    _team_choice = st.selectbox(
                        "Voor welk team is deze sessie?",
                        list(_team_labels.keys()), key="phys_team_selector")
                    upload_team_id = _team_labels[_team_choice]
                st.divider()

            # ---- STAP 5: CONFIRMATION ----
            st.markdown("### ✅ Bevestiging")
            display_name = session_name or report.get("session_name") \
                or os.path.splitext(uf.name)[0]
            type_disp = {"match": "🏆 Wedstrijd", "training": "🏃 Training",
                         "unlinked": "📂 Ongelinkt"}[selected_type]
            st.write(f"- Type: **{type_disp}**")
            if selected_type == "match":
                st.write(f"- Wedstrijd: **{display_name}** (match-id {match_id})")
            else:
                st.write(f"- Sessie: **{display_name}**")
            st.write(f"- Spelers: **{report['players']}**")
            st.write(f"- Rijen: **{report['rows']}**")
            st.write(f"- Periodes: **{', '.join(report['periods']) or '—'}**")
            st.write(f"- Bestand: **{uf.name}**")

            # ---- STAP 6: SAVE ----
            if st.button("💾 Fysieke data opslaan", type="primary",
                         key="phys_save_btn"):
                try:
                    res = db.save_physical_data(
                        c, _club(), df, match_id=match_id, source_filename=uf.name,
                        session_type=selected_type, session_name=session_name,
                        team_id=upload_team_id)
                    st.cache_data.clear()
                    st.success(
                        f"✅ Opgeslagen als **{type_disp}**: {res['inserted']} "
                        f"records ({res['linked']} gekoppeld aan bestaande "
                        f"spelers, {res['unlinked']} standalone).")
                    st.info("🔄 Scroll naar beneden of herlaad voor de "
                            "bijgewerkte visualisatie.")
                except Exception as e:  # pragma: no cover - defensive
                    st.error(f"❌ Fout bij opslaan: {e}")
                    st.exception(e)

    st.divider()

    # ---------------- Section B: Sessions & Visualisation ----------------
    st.subheader("📊 Sessies & Visualisatie")
    sessions = db.list_physical_sessions(c, _club(), team_ids=_team_ids())
    if not sessions:
        st.info("Nog geen fysieke data opgeslagen. Upload hierboven een "
                "Catapult-CSV of wedstrijd-XLSX om te beginnen.")
        return

    TYPE_ICON = {"match": "🏆", "training": "🏃", "unlinked": "📂"}
    TYPE_LABEL = {"match": "Wedstrijd", "training": "Training",
                  "unlinked": "Ongelinkt"}

    # Verdeling per type
    st.caption(
        f"**Verdeling:** 🏆 {counts.get('match', 0)} wedstrijd(en) · "
        f"🏃 {counts.get('training', 0)} training(s) · "
        f"📂 {counts.get('unlinked', 0)} ongelinkt")

    # Type-filter (multiselect)
    filter_choice = st.multiselect(
        "Filter op type sessie",
        ["🏆 Wedstrijden", "🏃 Trainingen", "📂 Ongelinkt"],
        default=["🏆 Wedstrijden", "🏃 Trainingen", "📂 Ongelinkt"],
        key="phys_type_filter")
    selected_types = []
    if "🏆 Wedstrijden" in filter_choice:
        selected_types.append("match")
    if "🏃 Trainingen" in filter_choice:
        selected_types.append("training")
    if "📂 Ongelinkt" in filter_choice:
        selected_types.append("unlinked")

    filtered_sessions = [s for s in sessions
                         if (s["session_type"] or "unlinked") in selected_types]
    st.write(f"**{len(filtered_sessions)} sessie(s)** zichtbaar.")

    if not filtered_sessions:
        st.info("Geen sessies voor de geselecteerde types.")
        return

    players = db.list_physical_players(c, _club(), team_ids=_team_ids())
    f1, f2, f3 = st.columns(3)
    sess_labels = {"— Alle sessies (gefilterd) —": None}
    for s in filtered_sessions:
        stype = s["session_type"] or "unlinked"
        lbl = f"{TYPE_ICON.get(stype, '📂')} {s['session_name']}"
        if s["match_date"]:
            lbl += f" ({s['match_date']})"
        lbl += f" · {s['n_players']} spelers"
        sess_labels[lbl] = s["session_name"]
    sess_choice = f1.selectbox("Sessie", list(sess_labels.keys()))
    session_name = sess_labels[sess_choice]

    player_choice = f2.selectbox("Speler", ["— Alle spelers —"] + players)
    player_name = None if player_choice.startswith("—") else player_choice

    period_choice = f3.selectbox(
        "Periode", ["— Alle periodes —", "First Half", "Second Half",
                    "Full Match"])
    period = None if period_choice.startswith("—") else period_choice

    # Wanneer geen losse sessie gekozen is, scope op de geselecteerde types
    # door de records van de gefilterde sessies samen te voegen.
    if session_name is None:
        allowed_names = {s["session_name"] for s in filtered_sessions}
        rows = [r for r in db.get_physical_data(
                    c, _club(), player_name=player_name, period=period, team_ids=_team_ids())
                if r["session_name"] in allowed_names]
    else:
        rows = db.get_physical_data(c, _club(), player_name=player_name,
                                    session_name=session_name, period=period, team_ids=_team_ids())
    pdf_ = _physical_rows_to_df(rows)
    if pdf_.empty:
        st.info("Geen records voor deze selectie.")
        return

    # KPI cards (aggregated over the current selection)
    def _sum(col):
        return float(pdf_[col].dropna().sum()) if col in pdf_ else 0.0

    def _max(col):
        s = pdf_[col].dropna() if col in pdf_ else pd.Series(dtype=float)
        return float(s.max()) if not s.empty else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Totale afstand (m)", f"{_sum('total_distance'):,.0f}")
    k2.metric("Sprintafstand (m)", f"{_sum('sprint_distance'):,.0f}")
    k3.metric("Topsnelheid (km/u)", f"{_max('top_speed'):.1f}")
    k4.metric("Versnellingen", f"{_sum('accelerations'):,.0f}")

    # Per-player aggregated table
    st.markdown("**Per speler (samengevat over selectie):**")
    agg_spec = {col: ("max" if col in ("top_speed", "max_acceleration",
                                        "percentage_max_speed") else "sum")
                for col in db.PHYSICAL_METRIC_COLS if col in pdf_}
    grouped = (pdf_.groupby("player_name", as_index=False).agg(agg_spec)
               if agg_spec else pdf_)
    nice = {
        "player_name": "Speler", "total_distance": "Afstand (m)",
        "sprint_distance": "Sprint (m)", "high_intensity_distance": "HI-afstand (m)",
        "top_speed": "Topsnelheid (km/u)", "accelerations": "Versn.",
        "decelerations": "Vertr.", "session_load": "Load",
        "distance_per_minute": "m/min", "edi_percentage": "EDI %",
    }
    show_cols = ["player_name"] + [col for col in
                 ["total_distance", "sprint_distance", "high_intensity_distance",
                  "top_speed", "distance_per_minute", "accelerations",
                  "decelerations", "session_load", "edi_percentage"]
                 if col in grouped.columns]
    tbl = grouped[show_cols].rename(columns=nice).sort_values(
        nice.get("total_distance", "Speler"),
        ascending=False) if "total_distance" in grouped.columns else \
        grouped[show_cols].rename(columns=nice)
    st.dataframe(tbl, use_container_width=True, hide_index=True,
                 column_config={c: st.column_config.NumberColumn(format="%.1f")
                                for c in tbl.columns if c != "Speler"})

    # Distance breakdown bar chart
    dist_cols = [col for col in ["total_distance", "sprint_distance",
                                 "high_intensity_distance"]
                 if col in grouped.columns]
    if dist_cols:
        long = grouped.melt(id_vars="player_name", value_vars=dist_cols,
                            var_name="Metriek", value_name="Meters")
        long["Metriek"] = long["Metriek"].map({
            "total_distance": "Totale afstand",
            "sprint_distance": "Sprintafstand",
            "high_intensity_distance": "Hoge intensiteit"})
        fig = px.bar(long, x="player_name", y="Meters", color="Metriek",
                     barmode="group", title="Afstand per speler")
        fig.update_layout(xaxis_title="", legend_title="")
        st.plotly_chart(fig, use_container_width=True)

    # Scatter: top speed vs accelerations
    if {"top_speed", "accelerations"}.issubset(grouped.columns):
        size_col = "total_distance" if "total_distance" in grouped.columns else None
        fig2 = px.scatter(
            grouped, x="accelerations", y="top_speed",
            size=size_col, color="player_name", hover_name="player_name",
            title="Topsnelheid vs. versnellingen"
            + (" (grootte = totale afstand)" if size_col else ""))
        fig2.update_layout(xaxis_title="Versnellingen", yaxis_title="Topsnelheid (km/u)",
                           legend_title="Speler")
        st.plotly_chart(fig2, use_container_width=True)

    # ---------------- Section C: Sessiebeheer (koppelen/ontkoppelen) -------
    st.divider()
    st.subheader("🗄️ Sessiebeheer")
    st.caption("Koppel ongelinkte/trainingssessies aan een wedstrijd, ontkoppel "
               "wedstrijdsessies, of verwijder een sessie volledig.")

    for s in filtered_sessions:
        stype = s["session_type"] or "unlinked"
        icon = TYPE_ICON.get(stype, "📂")
        skey = f"{s['session_name']}__{s['data_source']}"
        with st.expander(f"{icon} {s['session_name']}", expanded=False):
            mcol1, mcol2 = st.columns(2)
            with mcol1:
                st.markdown("**Sessiegegevens:**")
                st.write(f"- Type: **{TYPE_LABEL.get(stype, 'Ongelinkt')}**")
                st.write(f"- Datum: **{s['match_date'] or '—'}**")
                st.write(f"- Spelers: **{s['n_players']}**")
                st.write(f"- Records: **{s['n_rows']}**")
            with mcol2:
                st.markdown("**Data-info:**")
                st.write(f"- Periodes: **{s['periods'] or '—'}**")
                st.write(f"- Bron: **{s['data_source']}**")
                if s["match_id"]:
                    st.write(f"- Match-id: **{s['match_id']}**")

            st.divider()
            st.markdown("**Acties:**")
            act = st.columns([1.2, 1.2, 1.2, 2])

            # --- Koppelen (ongelinkt of training -> match) ---
            if stype in ("unlinked", "training"):
                if act[0].button("🔗 Koppel aan wedstrijd",
                                 key=f"link_{skey}",
                                 use_container_width=True):
                    st.session_state[f"show_link_{skey}"] = True
            # --- Ontkoppelen (match -> unlinked) ---
            elif stype == "match":
                if act[0].button("🔓 Ontkoppel", key=f"unlink_{skey}",
                                 use_container_width=True):
                    try:
                        n = db.unlink_physical_session(
                            c, s["session_name"], s["data_source"],
                            club_id=_club())
                        st.cache_data.clear()
                        st.success(f"✅ Sessie ontkoppeld ({n} records → "
                                   "ongelinkt).")
                        st.rerun()
                    except Exception as e:  # pragma: no cover - defensive
                        st.error(f"❌ Fout bij ontkoppelen: {e}")

            # --- Verwijderen ---
            if act[1].button("🗑️ Verwijder", key=f"del_{skey}",
                             use_container_width=True):
                st.session_state[f"confirm_del_{skey}"] = True

            # --- Koppel-dialoog ---
            if st.session_state.get(f"show_link_{skey}", False):
                st.markdown("---")
                st.markdown("**🔗 Koppel aan een wedstrijd:**")
                date_str = s["match_date"]
                matches = (db.get_matches_for_date(c, date_str, window_days=3, club_id=_club(), team_ids=_team_ids())
                           if date_str else db.list_matches(c, _club(), team_ids=_team_ids()))
                if matches:
                    mopts = []
                    for m in matches:
                        ha = "Thuis" if m["is_home"] else "Uit"
                        opp = m["opponent"]
                        mdate = m["match_date"]
                        mopts.append(f"{mdate}: vs {opp} ({ha})")
                    sel = st.selectbox("Selecteer wedstrijd:", mopts,
                                       key=f"linksel_{skey}")
                    lc = st.columns([1, 1, 3])
                    if lc[0].button("✅ Koppelen", key=f"dolink_{skey}"):
                        midx = mopts.index(sel)
                        match_id = matches[midx]["id"]
                        new_name = mopts[midx]
                        try:
                            n = db.link_physical_session_to_match(
                                c, s["session_name"], s["data_source"],
                                match_id, new_session_name=new_name,
                                club_id=_club())
                            st.cache_data.clear()
                            st.session_state.pop(f"show_link_{skey}", None)
                            st.success(f"✅ {n} records gekoppeld aan wedstrijd.")
                            st.rerun()
                        except Exception as e:  # pragma: no cover - defensive
                            st.error(f"❌ Fout bij koppelen: {e}")
                    if lc[1].button("❌ Annuleer", key=f"cancellink_{skey}"):
                        st.session_state.pop(f"show_link_{skey}", None)
                        st.rerun()
                else:
                    st.warning(f"⚠️ Geen wedstrijden gevonden"
                               + (f" rond {date_str}." if date_str else "."))
                    if st.button("Sluiten", key=f"closelink_{skey}"):
                        st.session_state.pop(f"show_link_{skey}", None)
                        st.rerun()

            # --- Verwijder-bevestiging ---
            if st.session_state.get(f"confirm_del_{skey}", False):
                st.markdown("---")
                st.warning("⚠️ **Weet je zeker dat je deze sessie wilt "
                           "verwijderen?** Alle fysieke records van deze sessie "
                           "worden permanent verwijderd.")
                dc = st.columns([1, 1, 3])
                if dc[0].button("✅ Ja, verwijderen", key=f"dodel_{skey}"):
                    n = db.delete_physical_session(c, s["session_name"],
                                                   s["data_source"],
                                                   club_id=_club())
                    st.cache_data.clear()
                    st.session_state.pop(f"confirm_del_{skey}", None)
                    st.success(f"{n} records verwijderd uit "
                               f"'{s['session_name']}'.")
                    st.rerun()
                if dc[1].button("❌ Annuleer", key=f"canceldel_{skey}"):
                    st.session_state.pop(f"confirm_del_{skey}", None)
                    st.rerun()


# ---------------------------------------------------------------------------
# Club Management (Phase 2) — club_admin & platform_admin
# ---------------------------------------------------------------------------
_LIMIT_MSG = ("Limiet bereikt. Upgrade nodig om meer {what} toe te voegen.")


def _role():
    return st.session_state.get("role")


def _is_platform_admin():
    return _role() == "platform_admin"


def _is_club_admin():
    return _role() == "club_admin"


def _render_club_panel(c, club_id):
    """Render the management panel (info + teams + users) for one club."""
    club = db.get_club(c, club_id)
    if club is None:
        st.error("Club not found.")
        return

    # ---- A. Club Info ----
    st.markdown(f"### 🏟️ {club['name']}")
    user_count = db.get_club_user_count(c, club_id)
    team_count = db.get_club_team_count(c, club_id)
    ci = st.columns(4)
    ci[0].metric("Abonnement", club["subscription_status"])
    ci[1].metric("Gebruikers", f"{user_count} / {club['max_users']}")
    ci[2].metric("Teams", f"{team_count} / {club['max_teams']}")
    ci[3].metric("Status", "Actief" if club["is_active"] else "Inactief")

    # ---- Platform-admin controls for this club ----
    if _is_platform_admin():
        with st.expander("⚙️ Platform-beheer (limieten & status)"):
            with st.form(f"limits_{club_id}"):
                lc = st.columns(3)
                new_max_users = lc[0].number_input(
                    "Max gebruikers", min_value=1, max_value=999,
                    value=int(club["max_users"]), step=1)
                new_max_teams = lc[1].number_input(
                    "Max teams", min_value=1, max_value=999,
                    value=int(club["max_teams"]), step=1)
                new_status = lc[2].selectbox(
                    "Abonnement",
                    ["trial", "active", "suspended", "cancelled"],
                    index=["trial", "active", "suspended", "cancelled"].index(
                        club["subscription_status"])
                    if club["subscription_status"] in
                    ["trial", "active", "suspended", "cancelled"] else 0)
                if st.form_submit_button("💾 Limieten opslaan"):
                    db.update_club_limits(c, club_id, new_max_users,
                                          new_max_teams)
                    db.update_club_subscription(c, club_id, new_status)
                    st.success("Limieten bijgewerkt.")
                    st.rerun()
            toggle_label = ("🚫 Club deactiveren" if club["is_active"]
                            else "✅ Club activeren")
            if st.button(toggle_label, key=f"toggle_club_{club_id}"):
                db.set_club_active(c, club_id, not club["is_active"])
                st.success("Clubstatus bijgewerkt.")
                st.rerun()

    st.divider()

    # ---- B. Teams Management ----
    st.markdown("#### ⚽ Teams")
    teams = db.list_teams(c, club_id)
    if teams:
        st.dataframe(
            pd.DataFrame([
                {"Team": t["name"], "Leeftijdsgroep": t["age_group"] or "—"}
                for t in teams
            ]),
            use_container_width=True, hide_index=True)
    else:
        st.info("Nog geen teams aangemaakt.")

    at_team_limit = not db.can_add_team(c, club_id)
    if at_team_limit:
        st.warning("⚠️ " + _LIMIT_MSG.format(what="teams"))
    with st.form(f"add_team_{club_id}", clear_on_submit=True):
        tc = st.columns([2, 1, 1])
        t_name = tc[0].text_input("Teamnaam")
        t_age = tc[1].text_input("Leeftijdsgroep (optioneel)")
        tc[2].markdown("&nbsp;")
        add_team = tc[2].form_submit_button("➕ Team toevoegen",
                                            disabled=at_team_limit)
    if add_team:
        try:
            db.create_team(c, club_id, t_name, t_age)
            st.success(f"Team '{t_name}' toegevoegd.")
            st.rerun()
        except ValueError as ve:
            msg = str(ve)
            if msg == "limit_reached":
                st.error(_LIMIT_MSG.format(what="teams"))
            elif msg == "duplicate":
                st.error("Er bestaat al een team met deze naam/leeftijdsgroep.")
            elif msg == "empty_name":
                st.error("Teamnaam is verplicht.")
            else:
                st.error(f"Kon team niet toevoegen: {msg}")

    st.divider()

    # ---- C. Users Management ----
    st.markdown("#### 👥 Gebruikers")
    users = db.list_users_for_club(c, club_id)
    if users:
        st.dataframe(
            pd.DataFrame([
                {"Gebruiker": u["username"],
                 "Email": u["email"] or "—",
                 "Rol": u["role"],
                 "Team": u["team_name"] or "—",
                 "Status": "Actief" if u["is_active"] else "Inactief"}
                for u in users
            ]),
            use_container_width=True, hide_index=True)
    else:
        st.info("Nog geen gebruikers.")

    # Deactivate / reactivate users (not yourself).
    me = st.session_state.get("user_id")
    for u in users:
        if u["id"] == me:
            continue
        cols = st.columns([3, 1])
        cols[0].markdown(
            f"**{u['username']}** · {u['role']} · "
            f"{'🟢 Actief' if u['is_active'] else '🔴 Inactief'}")
        btn_label = "Deactiveren" if u["is_active"] else "Activeren"
        if cols[1].button(btn_label, key=f"toggle_user_{u['id']}"):
            db.set_user_active(c, u["id"], not u["is_active"], club_id=club_id)
            st.success(f"Gebruiker '{u['username']}' bijgewerkt.")
            st.rerun()

    at_user_limit = not db.can_add_user(c, club_id)
    if at_user_limit:
        st.warning("⚠️ " + _LIMIT_MSG.format(what="users"))
    teams_for_select = db.list_teams(c, club_id)
    team_opts = {"— Geen team —": None}
    for t in teams_for_select:
        label = t["name"] + (f" ({t['age_group']})" if t["age_group"] else "")
        team_opts[label] = t["id"]
    with st.form(f"add_user_{club_id}", clear_on_submit=True):
        uc = st.columns(2)
        u_name = uc[0].text_input("Gebruikersnaam")
        u_email = uc[1].text_input("Email")
        uc2 = st.columns(3)
        u_pw = uc2[0].text_input("Wachtwoord", type="password")
        u_role = uc2[1].selectbox("Rol", list(db.CLUB_ASSIGNABLE_ROLES))
        u_team_label = uc2[2].selectbox("Team (optioneel)",
                                        list(team_opts.keys()))
        add_user = st.form_submit_button("➕ Gebruiker toevoegen",
                                         disabled=at_user_limit)
    if add_user:
        pw_problems = _password_problems(u_pw)
        if pw_problems:
            st.error("Wachtwoord moet bevatten: " + ", ".join(pw_problems) + ".")
        else:
            try:
                db.create_club_user(
                    c, club_id, u_name, u_pw, role=u_role,
                    email=u_email, team_id=team_opts[u_team_label])
                st.success(f"Gebruiker '{u_name}' toegevoegd.")
                st.rerun()
            except ValueError as ve:
                msg = str(ve)
                mapping = {
                    "limit_reached": _LIMIT_MSG.format(what="users"),
                    "username_taken": "Die gebruikersnaam bestaat al.",
                    "email_taken": "Dat emailadres is al geregistreerd.",
                    "empty": "Gebruikersnaam en wachtwoord zijn verplicht.",
                    "bad_role": "Ongeldige rol.",
                }
                st.error(mapping.get(msg, f"Kon gebruiker niet toevoegen: {msg}"))

    st.divider()

    # ---- D. Team Assignments (Phase 3) ----
    # Analysts & coaches only see data for the teams they are assigned to.
    # club_admin (and platform_admin) manage those assignments here.
    st.markdown("#### 🔐 Team-toewijzingen")
    st.caption("Analisten en coaches zien alleen data van de teams waaraan ze "
               "zijn toegewezen. Platform- en clubbeheerders zien automatisch "
               "alle teams van de club.")

    teams_for_assign = db.list_teams(c, club_id)
    assignable_users = [u for u in users
                        if u["role"] in db.CLUB_ASSIGNABLE_ROLES]

    if not teams_for_assign:
        st.info("Maak eerst een team aan voordat je toewijzingen beheert.")
    elif not assignable_users:
        st.info("Nog geen analisten of coaches om toe te wijzen.")
    else:
        # Overview table: User | Role | Assigned Teams
        team_name_by_id = {
            t["id"]: t["name"] + (f" ({t['age_group']})" if t["age_group"] else "")
            for t in teams_for_assign
        }
        overview = []
        for u in assignable_users:
            assigned = db.list_user_team_ids(c, u["id"])
            overview.append({
                "Gebruiker": u["username"],
                "Rol": u["role"],
                "Toegewezen teams": ", ".join(
                    team_name_by_id.get(tid, str(tid)) for tid in assigned
                ) or "— geen —",
            })
        st.dataframe(pd.DataFrame(overview),
                     use_container_width=True, hide_index=True)

        # Per-user multiselect editor.
        team_label_to_id = {lbl: tid for tid, lbl in team_name_by_id.items()}
        for u in assignable_users:
            current_ids = set(db.list_user_team_ids(c, u["id"]))
            current_labels = [lbl for lbl, tid in team_label_to_id.items()
                              if tid in current_ids]
            with st.form(f"assign_teams_{u['id']}", clear_on_submit=False):
                st.markdown(f"**{u['username']}** · {u['role']}")
                chosen = st.multiselect(
                    "Teams", list(team_label_to_id.keys()),
                    default=current_labels,
                    key=f"assign_ms_{u['id']}")
                if st.form_submit_button("💾 Toewijzingen opslaan"):
                    chosen_ids = [team_label_to_id[l] for l in chosen]
                    db.set_user_team_assignments(c, u["id"], chosen_ids)
                    st.success(f"Team-toewijzingen voor '{u['username']}' "
                               "bijgewerkt.")
                    st.rerun()


def screen_club_management():
    """Club management panel — club_admin (own club) / platform_admin (all)."""
    if not (_is_club_admin() or _is_platform_admin()):
        st.error("⛔ Je hebt geen toegang tot clubbeheer.")
        return

    st.title("🏛️ Clubbeheer")
    c = conn()

    if _is_platform_admin():
        clubs = db.list_clubs(c)
        # Platform-wide overview.
        with st.expander("📊 Platform-overzicht (alle clubs)", expanded=False):
            st.dataframe(
                pd.DataFrame([
                    {"Club": cl["name"],
                     "Abonnement": cl["subscription_status"],
                     "Gebruikers": f"{cl['user_count']} / {cl['max_users']}",
                     "Teams": f"{cl['team_count']} / {cl['max_teams']}",
                     "Status": "Actief" if cl["is_active"] else "Inactief"}
                    for cl in clubs
                ]),
                use_container_width=True, hide_index=True)
        # Club selector.
        label_to_id = {
            f"{cl['name']} (id={cl['id']})": cl["id"] for cl in clubs
        }
        sel = st.selectbox("Selecteer een club", list(label_to_id.keys()))
        st.divider()
        _render_club_panel(c, label_to_id[sel])
    else:
        # club_admin → own club only.
        _render_club_panel(c, _club())


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
SCREENS = {
    "📤 Upload & Overview": screen_upload,
    "📊 Match Dashboard": screen_match,
    "👤 Player Profile": screen_player,
    "⚖️ Player Comparison": screen_comparison,
    "📈 Evolution Dashboard": screen_evolution,
    "🏃 Physical / GPS": screen_physical,
    "🛠️ Profile Editor": screen_profile_editor,
    "🗄️ Data Management": screen_data_management,
}


def main():
    _init_auth_state()

    # Gate the whole application behind authentication.
    if not st.session_state.get("logged_in"):
        if st.session_state.get("auth_view") == "register":
            screen_register()
        else:
            screen_login()
        return

    st.sidebar.title("⚽ Impact Platform")
    st.sidebar.caption("Turn SciSports reports into coaching insights.")

    # Logged-in user info + logout.
    club = db.get_club(conn(), _club())
    club_name = club["name"] if club else "—"
    st.sidebar.markdown(
        f"**👤 {st.session_state.get('username')}**  \n"
        f"🏟️ {club_name}  \n"
        f"🔑 {st.session_state.get('role')}"
    )
    if st.sidebar.button("Log out", use_container_width=True):
        do_logout()
        st.rerun()
    st.sidebar.divider()

    # Build the navigation map; club admins & platform admins get Club Management.
    screens = dict(SCREENS)
    if _is_club_admin() or _is_platform_admin():
        screens["🏛️ Club Management"] = screen_club_management

    choice = st.sidebar.radio("Navigate", list(screens.keys()))
    st.sidebar.divider()
    st.sidebar.caption("Impact Framework v2.0 — 6 categories, 20 positions, "
                       "position-based profiles.")
    screens[choice]()


if __name__ == "__main__":
    main()
