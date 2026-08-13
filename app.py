# -*- coding: utf-8 -*-
"""
The Gentlemen's Cup - Tournament Tracker

Changes from last year:
  1. Scramble / Alternating Shot points doubled (11/7.5/4 -> 22/15/8)
  2. Skins mechanism unchanged, now played over 18 holes instead of 9
  3. Login/access-code removed - app is open and persistent
  4. Storage moved from Google Sheets (API-rate-limited) to a local SQLite
     database - fast, free, and fine for ~15 concurrent users
  5. Every save is written to a small write-ahead log first, so a save that
     gets interrupted mid-write is automatically retried the next time the
     app loads rather than silently lost

@author: MPlantz
"""

import streamlit as st
import pandas as pd
import sqlite3
import threading
import uuid
import os
import json
import re
import time
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="The Gentlemen's Cup",
    page_icon="🏌️‍♂️",
    layout="wide"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEAMS = ["Young Guns", "OGs", "Mids"]
HOLES = list(range(1, 19))          # Day 1 - 18 holes (Scramble + Alt Shot)
DAY2_HOLES = list(range(1, 19))     # Day 2 - Skins, now 18 holes (was 9)
GROUPS = list(range(1, 6))          # 5 groups for Day 2

# Day 1 competition points, doubled from last year (was [11, 7.5, 4])
DAY1_POINT_VALUES = [22, 15, 8]

# Course information - Blue tees, from the current scorecard
# (Out 3038 / In 3201 / Total 6239, Par 36-36-72)
DAY1_COURSE = {
    1: {'par': 5, 'yardage': 500}, 2: {'par': 4, 'yardage': 340}, 3: {'par': 4, 'yardage': 278},
    4: {'par': 4, 'yardage': 314}, 5: {'par': 3, 'yardage': 127}, 6: {'par': 4, 'yardage': 375},
    7: {'par': 3, 'yardage': 191}, 8: {'par': 4, 'yardage': 407}, 9: {'par': 5, 'yardage': 506},
    10: {'par': 4, 'yardage': 379}, 11: {'par': 4, 'yardage': 402}, 12: {'par': 5, 'yardage': 479},
    13: {'par': 3, 'yardage': 168}, 14: {'par': 4, 'yardage': 345}, 15: {'par': 4, 'yardage': 406},
    16: {'par': 4, 'yardage': 409}, 17: {'par': 5, 'yardage': 448}, 18: {'par': 3, 'yardage': 165}
}

# NOTE / ASSUMPTION: Skins are now played over 18 holes instead of 9, but no
# separate 18-hole course data was provided (the old Day2 course only had 9
# holes). This defaults Day 2 to the SAME course as Day 1. If Day 2 is
# actually played on a different 18-hole course, just replace the dict below
# with the correct par/yardage per hole (same format as DAY1_COURSE).
DAY2_COURSE = DAY1_COURSE

# ---------------------------------------------------------------------------
# Storage: local SQLite database (replaces Google Sheets)
# ---------------------------------------------------------------------------
# Why SQLite: with ~15 people hitting Google Sheets at once you blow through
# its read/write API quota fast. SQLite has no API quota at all - reads and
# writes are just local disk I/O - so this removes the rate-limit problem
# entirely while keeping the same "read everything, write a row" pattern the
# rest of the app already expects.
#
# One tradeoff to know about: on Streamlit Community Cloud the app's local
# filesystem is ephemeral - it survives fine while the app is up and being
# used, but a reboot/redeploy of the app wipes it. For a single tournament
# weekend this is generally fine (don't redeploy mid-event), but use the
# "Backup & Data" panel in the sidebar to download a copy whenever you want
# extra peace of mind, and definitely right after the tournament ends.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tournament_data.db")
_db_lock = threading.Lock()  # serializes writes across concurrent users

# Past-year results live as plain JSON files checked into the repo (not the
# database), so they survive redeploys/reboots forever - see history/README.
HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")


@st.cache_resource
def get_db():
    """Create (once, shared across all users) the SQLite connection + schema."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")     # lets reads happen alongside writes
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row

    with _db_lock:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS day1_scores (
                team TEXT NOT NULL,
                hole INTEGER NOT NULL,
                scramble_score INTEGER,
                alt_shot_score INTEGER,
                timestamp TEXT,
                PRIMARY KEY (team, hole)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS day2_scores (
                group_num INTEGER NOT NULL,
                hole INTEGER NOT NULL,
                team TEXT NOT NULL,
                score INTEGER,
                timestamp TEXT,
                PRIMARY KEY (group_num, hole, team)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS day2_skins (
                group_num INTEGER NOT NULL,
                hole INTEGER NOT NULL,
                winner TEXT,
                winning_score INTEGER,
                points_value INTEGER,
                PRIMARY KEY (group_num, hole)
            )
        """)
        # Team rosters, Round 1 (Scramble/Alt Shot) partnerships, and Round 2
        # (Skins) group assignments - powers the Team Setup page.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS roster (
                team TEXT NOT NULL,
                golfer TEXT NOT NULL,
                PRIMARY KEY (team, golfer)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS day1_roles (
                team TEXT NOT NULL,
                slot TEXT NOT NULL,
                golfer TEXT,
                PRIMARY KEY (team, slot)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS day2_assignments (
                team TEXT NOT NULL,
                golfer TEXT NOT NULL,
                group_num INTEGER,
                PRIMARY KEY (team, golfer)
            )
        """)
        # Small key-value store for app-wide flags (e.g. the reveal state).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Write-ahead log (this is the "nice to have" from #4). Every save
        # attempt is recorded here BEFORE it's applied. If the save completes
        # normally it's immediately marked synced; if something interrupts it
        # mid-write (e.g. a hiccup on Streamlit Cloud), it's left unsynced and
        # gets automatically retried the next time anyone loads the app -
        # so an entry never just silently vanishes.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS write_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                action TEXT,
                payload TEXT,
                timestamp TEXT,
                synced INTEGER DEFAULT 0
            )
        """)
        conn.commit()
    return conn


def get_session_id():
    """Stable id per browser tab, used to tag write-log entries by session."""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    return st.session_state.session_id


def _log_write(action, payload):
    """Record a pending write before attempting it. Returns the log row id."""
    conn = get_db()
    ts = datetime.now().isoformat()
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO write_log (session_id, action, payload, timestamp, synced) VALUES (?, ?, ?, ?, 0)",
            (get_session_id(), action, json.dumps(payload), ts)
        )
        conn.commit()
        return cur.lastrowid


def _mark_synced(log_id):
    conn = get_db()
    with _db_lock:
        conn.execute("UPDATE write_log SET synced = 1 WHERE id = ?", (log_id,))
        conn.commit()


def _apply_day1_score(team, hole, scramble_score, alt_shot_score, timestamp):
    conn = get_db()
    with _db_lock:
        conn.execute("""
            INSERT INTO day1_scores (team, hole, scramble_score, alt_shot_score, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(team, hole) DO UPDATE SET
                scramble_score = excluded.scramble_score,
                alt_shot_score = excluded.alt_shot_score,
                timestamp = excluded.timestamp
        """, (team, hole, scramble_score, alt_shot_score, timestamp))
        conn.commit()


def _apply_day2_score(group, hole, team, score, timestamp):
    conn = get_db()
    with _db_lock:
        conn.execute("""
            INSERT INTO day2_scores (group_num, hole, team, score, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(group_num, hole, team) DO UPDATE SET
                score = excluded.score,
                timestamp = excluded.timestamp
        """, (group, hole, team, score, timestamp))
        conn.commit()


def _apply_skin_result(group, hole, winner, winning_score, points_value):
    conn = get_db()
    with _db_lock:
        if winner:
            conn.execute("""
                INSERT INTO day2_skins (group_num, hole, winner, winning_score, points_value)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_num, hole) DO UPDATE SET
                    winner = excluded.winner,
                    winning_score = excluded.winning_score,
                    points_value = excluded.points_value
            """, (group, hole, winner, winning_score, points_value))
        else:
            conn.execute("DELETE FROM day2_skins WHERE group_num = ? AND hole = ?", (group, hole))
        conn.commit()


def flush_pending_writes():
    """Retry any writes that were logged but never confirmed - run at startup."""
    conn = get_db()
    with _db_lock:
        pending = conn.execute("SELECT * FROM write_log WHERE synced = 0 ORDER BY id").fetchall()
    for row in pending:
        try:
            payload = json.loads(row['payload'])
            if row['action'] == 'day1_score':
                _apply_day1_score(**payload)
            elif row['action'] == 'day2_score':
                _apply_day2_score(**payload)
            _mark_synced(row['id'])
        except Exception:
            pass  # still unsynced - will retry again on the next load


# ---------------------------------------------------------------------------
# Save functions (public API used by the pages below)
# ---------------------------------------------------------------------------
def save_day1_score(team, hole, scramble_score, alt_shot_score):
    """Save Day 1 scores"""
    timestamp = datetime.now().isoformat()
    payload = {'team': team, 'hole': hole, 'scramble_score': scramble_score,
               'alt_shot_score': alt_shot_score, 'timestamp': timestamp}
    log_id = _log_write('day1_score', payload)
    try:
        _apply_day1_score(**payload)
        _mark_synced(log_id)

        # Update local cache for UI responsiveness
        if 'day1_scores' not in st.session_state:
            st.session_state.day1_scores = {}
        score_id = f"{team}_{hole}"
        st.session_state.day1_scores[score_id] = {
            'team': team, 'hole': hole,
            'scramble': scramble_score, 'alt_shot': alt_shot_score,
            'timestamp': timestamp
        }
    except Exception as e:
        st.error(f"Error saving score, will retry automatically: {e}")


def save_day2_score(group, hole, team, score):
    """Save Day 2 (skins) scores"""
    timestamp = datetime.now().isoformat()
    payload = {'group': group, 'hole': hole, 'team': team, 'score': score, 'timestamp': timestamp}
    log_id = _log_write('day2_score', payload)
    try:
        _apply_day2_score(**payload)
        _mark_synced(log_id)

        # Update local cache for UI responsiveness
        if 'day2_scores' not in st.session_state:
            st.session_state.day2_scores = {}
        score_id = f"{group}_{hole}_{team}"
        st.session_state.day2_scores[score_id] = {
            'group': group, 'hole': hole, 'team': team, 'score': score, 'timestamp': timestamp
        }
    except Exception as e:
        st.error(f"Error saving score, will retry automatically: {e}")

    # Calculate skins for this hole and recalculate subsequent holes if needed
    recalculate_group_skins_from_hole(group, hole)


def save_skin_result(group, hole, winner, winning_score, points_value):
    """Save skin calculation results. Skins are derived from scores, so these
    aren't write-logged individually - they get rebuilt from day2_scores
    automatically on load if anything is ever out of sync."""
    try:
        _apply_skin_result(group, hole, winner, winning_score, points_value)
    except Exception as e:
        st.error(f"Error saving skin result: {e}")


def recalculate_group_skins_from_hole(group, start_hole):
    """Recalculate all skins for a group starting from a specific hole"""
    # Clear existing team points for this group to recalculate
    if 'team_day2_points' not in st.session_state:
        st.session_state.team_day2_points = {team: 0 for team in TEAMS}

    # Remove points from this group and recalculate from scratch
    for hole in DAY2_HOLES:
        skin_key = f"{group}_{hole}"
        if skin_key in st.session_state.get('day2_skins', {}):
            old_skin = st.session_state.day2_skins[skin_key]
            if old_skin.get('winner') and not old_skin.get('tied'):
                # Remove old points
                old_points = old_skin.get('points_value', 1)
                st.session_state.team_day2_points[old_skin['winner']] -= old_points

    # Clear existing skins for this group
    for hole in DAY2_HOLES:
        skin_key = f"{group}_{hole}"
        if skin_key in st.session_state.get('day2_skins', {}):
            del st.session_state.day2_skins[skin_key]

    # Now recalculate all skins for this group in hole order
    if 'day2_skins' not in st.session_state:
        st.session_state.day2_skins = {}

    for hole in DAY2_HOLES:
        # Get all scores for this hole in this group
        hole_scores = {}
        for team in TEAMS:
            key = f"{group}_{hole}_{team}"
            if key in st.session_state.get('day2_scores', {}):
                score = st.session_state.day2_scores[key]['score']
                if score and score > 0:  # Valid score
                    hole_scores[team] = score

        # Need at least 2 scores to determine winner
        if len(hole_scores) < 2:
            continue

        # Determine winner (lowest score wins)
        min_score = min(hole_scores.values())
        winners = [team for team, score in hole_scores.items() if score == min_score]

        # Calculate points value based on carryover from previous holes in this group
        points_value = calculate_hole_points_value(group, hole)

        skin_key = f"{group}_{hole}"

        if len(winners) == 1:  # Clear winner
            winner = winners[0]
            skin_result = {
                'group': group, 'hole': hole, 'winner': winner,
                'score': min_score, 'tied': False, 'points_value': points_value
            }
            st.session_state.day2_skins[skin_key] = skin_result
            save_skin_result(group, hole, winner, min_score, points_value)

            # Award points to the winning team
            st.session_state.team_day2_points[winner] += points_value

        else:  # Tie - skin carries over
            skin_result = {
                'group': group, 'hole': hole, 'winner': None,
                'score': min_score, 'tied': True, 'points_value': points_value
            }
            st.session_state.day2_skins[skin_key] = skin_result
            # Ties aren't persisted - only wins are stored
            save_skin_result(group, hole, None, None, None)


def calculate_hole_points_value(group, hole):
    """Calculate points value for a hole based on carryover from previous ties"""
    points_value = 1  # Base value for current hole

    # Look backwards from current hole to count consecutive ties
    for prev_hole in range(hole - 1, 0, -1):  # Go backwards from hole-1 to 1
        prev_skin_key = f"{group}_{prev_hole}"
        if prev_skin_key in st.session_state.get('day2_skins', {}):
            prev_skin = st.session_state.day2_skins[prev_skin_key]
            if prev_skin.get('tied', False):
                points_value += 1  # Add 1 for each consecutive tie
            else:
                break  # Stop at first non-tie (someone won, so carryover stops)
        else:
            # If there's no skin data for previous hole, check if there are scores
            has_scores = False
            for team in TEAMS:
                score_key = f"{group}_{prev_hole}_{team}"
                if score_key in st.session_state.get('day2_scores', {}):
                    score = st.session_state.day2_scores[score_key].get('score')
                    if score and score > 0:
                        has_scores = True
                        break

            if not has_scores:
                break  # No scores for this hole, stop looking back
            else:
                break

    return points_value


def load_all_data():
    """Load all data from SQLite into session state"""
    conn = get_db()
    try:
        # Day 1 scores
        st.session_state.day1_scores = {}
        for row in conn.execute("SELECT * FROM day1_scores").fetchall():
            key = f"{row['team']}_{row['hole']}"
            st.session_state.day1_scores[key] = {
                'team': row['team'], 'hole': row['hole'],
                'scramble': row['scramble_score'], 'alt_shot': row['alt_shot_score'],
                'timestamp': row['timestamp']
            }

        # Day 2 scores
        st.session_state.day2_scores = {}
        for row in conn.execute("SELECT * FROM day2_scores").fetchall():
            key = f"{row['group_num']}_{row['hole']}_{row['team']}"
            st.session_state.day2_scores[key] = {
                'group': row['group_num'], 'hole': row['hole'], 'team': row['team'],
                'score': row['score'], 'timestamp': row['timestamp']
            }

        # Day 2 skins + recalculate team points
        st.session_state.day2_skins = {}
        st.session_state.team_day2_points = {team: 0 for team in TEAMS}
        for row in conn.execute("SELECT * FROM day2_skins WHERE winner IS NOT NULL").fetchall():
            key = f"{row['group_num']}_{row['hole']}"
            st.session_state.day2_skins[key] = {
                'group': row['group_num'], 'hole': row['hole'], 'winner': row['winner'],
                'score': row['winning_score'], 'tied': False, 'points_value': row['points_value']
            }
            st.session_state.team_day2_points[row['winner']] += row['points_value']

        # Recalculate any missing skins (e.g. scores exist but no skin row yet)
        recalculate_missing_skins()

    except Exception as e:
        st.error(f"Error loading data: {e}")


def recalculate_missing_skins():
    """Recalculate skins for any holes that have scores but no skin result"""
    if 'day2_scores' not in st.session_state:
        return

    groups_with_scores = set()
    for key, score_data in st.session_state.day2_scores.items():
        if score_data['score'] and score_data['score'] > 0:
            groups_with_scores.add(score_data['group'])

    for group in groups_with_scores:
        recalculate_group_skins_from_hole(group, 1)


def get_day1_scores():
    """Get all Day 1 scores"""
    load_all_data()
    return st.session_state.get('day1_scores', {})


def get_day2_scores():
    """Get all Day 2 scores"""
    load_all_data()
    return st.session_state.get('day2_scores', {})


# ---------------------------------------------------------------------------
# Team setup: rosters, Day 1 partnerships, Day 2 group assignments
# ---------------------------------------------------------------------------
def get_roster(team):
    """List of golfer names for a team, alphabetical."""
    conn = get_db()
    rows = conn.execute("SELECT golfer FROM roster WHERE team = ? ORDER BY golfer", (team,)).fetchall()
    return [r['golfer'] for r in rows]


def add_golfer(team, golfer):
    golfer = golfer.strip()
    if not golfer:
        return
    conn = get_db()
    with _db_lock:
        conn.execute("INSERT OR IGNORE INTO roster (team, golfer) VALUES (?, ?)", (team, golfer))
        conn.commit()


def remove_golfer(team, golfer):
    conn = get_db()
    with _db_lock:
        conn.execute("DELETE FROM roster WHERE team = ? AND golfer = ?", (team, golfer))
        conn.execute("DELETE FROM day2_assignments WHERE team = ? AND golfer = ?", (team, golfer))
        # Clear this golfer out of any Day 1 role slot they occupied
        conn.execute("UPDATE day1_roles SET golfer = NULL WHERE team = ? AND golfer = ?", (team, golfer))
        conn.commit()


# Day 1 role slots. Each team fills all five: one all-time scrambler and two pairs.
DAY1_SLOTS = ['scrambler', 'p1a', 'p1b', 'p2a', 'p2b']
SCRAMBLER_LABEL = "All-time Scrambler / Beer Drinker"


def get_day1_roles(team):
    """{slot: golfer} for a team's Day 1 role assignments (missing slots absent)."""
    conn = get_db()
    rows = conn.execute("SELECT slot, golfer FROM day1_roles WHERE team = ?", (team,)).fetchall()
    return {r['slot']: r['golfer'] for r in rows if r['golfer']}


def set_day1_role(team, slot, golfer):
    conn = get_db()
    with _db_lock:
        if golfer is None:
            conn.execute("DELETE FROM day1_roles WHERE team = ? AND slot = ?", (team, slot))
        else:
            conn.execute("""
                INSERT INTO day1_roles (team, slot, golfer) VALUES (?, ?, ?)
                ON CONFLICT(team, slot) DO UPDATE SET golfer = excluded.golfer
            """, (team, slot, golfer))
        conn.commit()


def day1_rotation(team):
    """Resolve a team's Day 1 roles into the front/back scramble & alt-shot rotation.

    Front 9: (Pair 1 + Scrambler) scramble | Pair 2 alt shot
    Back 9:  (Pair 2 + Scrambler) scramble | Pair 1 alt shot
    """
    roles = get_day1_roles(team)
    scrambler = roles.get('scrambler')
    pair1 = [roles.get('p1a'), roles.get('p1b')]
    pair2 = [roles.get('p2a'), roles.get('p2b')]
    return {
        'scrambler': scrambler,
        'pair1': [g for g in pair1 if g],
        'pair2': [g for g in pair2 if g],
        'front_scramble': [g for g in ([scrambler] + pair1) if g],
        'front_alt_shot': [g for g in pair2 if g],
        'back_scramble': [g for g in ([scrambler] + pair2) if g],
        'back_alt_shot': [g for g in pair1 if g],
    }


def day1_role_issues(team):
    """Return a list of human-readable problems with a team's Day 1 role setup."""
    roles = get_day1_roles(team)
    assigned = [g for g in roles.values() if g]
    issues = []
    # Duplicates across slots
    seen = {}
    for slot, g in roles.items():
        seen.setdefault(g, []).append(slot)
    for g, slots in seen.items():
        if len(slots) > 1:
            issues.append(f"{g} is assigned to more than one role.")
    # Completeness
    missing = [s for s in DAY1_SLOTS if not roles.get(s)]
    if missing:
        issues.append("Not all five roles are filled yet.")
    return issues


def get_day2_assignments(team):
    """{golfer: group_num} for a team."""
    conn = get_db()
    rows = conn.execute("SELECT golfer, group_num FROM day2_assignments WHERE team = ?", (team,)).fetchall()
    return {r['golfer']: r['group_num'] for r in rows}


def set_day2_assignment(team, golfer, group_num):
    conn = get_db()
    with _db_lock:
        if group_num is None:
            conn.execute("DELETE FROM day2_assignments WHERE team = ? AND golfer = ?", (team, golfer))
        else:
            conn.execute("""
                INSERT INTO day2_assignments (team, golfer, group_num)
                VALUES (?, ?, ?)
                ON CONFLICT(team, golfer) DO UPDATE SET group_num = excluded.group_num
            """, (team, golfer, group_num))
        conn.commit()


def get_golfer_for_team_group(team, group_num):
    """Which golfer on this team is playing in this Day 2 group, if assigned."""
    assignments = get_day2_assignments(team)
    for golfer, g in assignments.items():
        if g == group_num:
            return golfer
    return None


# ---------------------------------------------------------------------------
# Reveal state + access codes for the Team Setup / grand-reveal flow
# ---------------------------------------------------------------------------
# Two independent mechanisms doing two different jobs:
#   * Per-team codes gate ENTRY - before the reveal, a team can only see/edit
#     its own config, not peek at rivals'. (You need a code so the app knows
#     which team you are.)
#   * The commissioner code gates the GRAND REVEAL - only the commissioner can
#     flip everything open Thursday night, and can re-lock if clicked early.
#
# All four codes live in Streamlit secrets (secrets.toml), NOT in this file,
# so they stay out of the public GitHub repo. Expected secrets layout:
#
#   [team_codes]
#   "Young Guns" = "your-code-here"
#   "OGs"        = "your-code-here"
#   "Mids"       = "your-code-here"
#   commissioner = "your-code-here"
#
# If secrets aren't configured yet, the app falls back to obvious placeholder
# codes and shows a warning, so it still runs locally before you set them up.
_PLACEHOLDER_TEAM_CODES = {team: f"team-{i+1}" for i, team in enumerate(TEAMS)}
_PLACEHOLDER_COMMISSIONER_CODE = "commish"


def _secrets_configured():
    try:
        return "team_codes" in st.secrets and "commissioner" in st.secrets
    except Exception:
        return False


def check_team_code(team, code):
    """True if `code` matches the configured (or placeholder) code for `team`."""
    code = (code or "").strip()
    if not code:
        return False
    try:
        expected = st.secrets["team_codes"][team]
    except Exception:
        expected = _PLACEHOLDER_TEAM_CODES[team]
    return code == expected


def check_commissioner_code(code):
    code = (code or "").strip()
    if not code:
        return False
    try:
        expected = st.secrets["commissioner"]
    except Exception:
        expected = _PLACEHOLDER_COMMISSIONER_CODE
    return code == expected


def is_revealed():
    """Has the commissioner triggered the grand reveal? Persistent, app-wide."""
    conn = get_db()
    row = conn.execute("SELECT value FROM meta WHERE key = 'revealed'").fetchone()
    return bool(row and row['value'] == '1')


def set_revealed(state):
    conn = get_db()
    with _db_lock:
        conn.execute("""
            INSERT INTO meta (key, value) VALUES ('revealed', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, ('1' if state else '0',))
        conn.commit()


def unlocked_team():
    """The team the current session has unlocked for editing, if any."""
    return st.session_state.get('unlocked_team')


def _render_team_editor(team):
    """The roster / partnerships / assignments editing UI for one team."""
    roster = get_roster(team)

    # --- Roster ---------------------------------------------------
    st.markdown("#### Roster")
    col_a, col_b = st.columns([3, 1])
    with col_a:
        new_golfer = st.text_input("Add golfer:", key=f"new_golfer_{team}", label_visibility="collapsed",
                                    placeholder="Golfer name")
    with col_b:
        if st.button("Add", key=f"add_golfer_{team}", use_container_width=True):
            if new_golfer.strip():
                add_golfer(team, new_golfer)
                st.rerun()

    if roster:
        for golfer in roster:
            rcol1, rcol2 = st.columns([5, 1])
            rcol1.markdown(f"- {golfer}")
            if rcol2.button("Remove", key=f"remove_{team}_{golfer}"):
                remove_golfer(team, golfer)
                st.rerun()
    else:
        st.info("No golfers added yet.")

    st.divider()

    # --- Round 1 roles: 1 all-time scrambler + 2 pairs --------------
    st.markdown("#### Round 1 Roles (Scramble / Alt Shot)")
    st.caption(
        "Pick your **All-time Scrambler / Beer Drinker** (scrambles both nines) and "
        "two pairs. Front 9: Pair 1 + Scrambler scramble, Pair 2 alt shot. "
        "Back 9: Pair 2 + Scrambler scramble, Pair 1 alt shot."
    )
    if len(roster) < 5:
        st.info(f"Add all 5 golfers to the roster to set roles (currently {len(roster)}).")
    else:
        roles = get_day1_roles(team)
        blank = "— none —"

        def role_selectbox(slot, label):
            options = [blank] + roster
            current = roles.get(slot)
            idx = options.index(current) if current in options else 0
            chosen = st.selectbox(label, options, index=idx, key=f"role_{team}_{slot}")
            new_val = None if chosen == blank else chosen
            if new_val != roles.get(slot):
                set_day1_role(team, slot, new_val)
                st.rerun()

        role_selectbox('scrambler', SCRAMBLER_LABEL)
        pc1, pc2 = st.columns(2)
        with pc1:
            st.markdown("**Pair 1**")
            role_selectbox('p1a', "Pair 1 — Golfer A")
            role_selectbox('p1b', "Pair 1 — Golfer B")
        with pc2:
            st.markdown("**Pair 2**")
            role_selectbox('p2a', "Pair 2 — Golfer A")
            role_selectbox('p2b', "Pair 2 — Golfer B")

        for issue in day1_role_issues(team):
            st.warning(issue)

        # Show the resolved rotation so the whole picture is visible at once
        rot = day1_rotation(team)
        st.markdown("**This produces:**")
        st.markdown(
            f"- **Front 9 scramble:** {', '.join(rot['front_scramble']) or '—'}\n"
            f"- **Front 9 alt shot:** {', '.join(rot['front_alt_shot']) or '—'}\n"
            f"- **Back 9 scramble:** {', '.join(rot['back_scramble']) or '—'}\n"
            f"- **Back 9 alt shot:** {', '.join(rot['back_alt_shot']) or '—'}"
        )

    st.divider()

    # --- Round 2 group assignments -----------------------------------
    st.markdown("#### Round 2 Group Assignments (Skins)")
    if not roster:
        st.caption("Add golfers to the roster to assign them to groups.")
    else:
        assignments = get_day2_assignments(team)
        group_labels = ["Unassigned"] + [f"Group {g}" for g in GROUPS]

        for golfer in roster:
            current_group = assignments.get(golfer)
            current_index = group_labels.index(f"Group {current_group}") if current_group else 0
            acol1, acol2 = st.columns([3, 2])
            acol1.markdown(f"**{golfer}**")
            chosen = acol2.selectbox(
                "Group:", group_labels, index=current_index,
                key=f"assign_{team}_{golfer}", label_visibility="collapsed"
            )
            new_group = None if chosen == "Unassigned" else int(chosen.split(" ")[1])
            if new_group != current_group:
                if new_group is not None:
                    conflict = next((g for g, grp in assignments.items()
                                      if grp == new_group and g != golfer), None)
                    if conflict:
                        st.warning(f"{conflict} is already assigned to Group {new_group} for {team}.")
                set_day2_assignment(team, golfer, new_group)
                st.rerun()

        st.caption("Group coverage: " + ", ".join(
            f"G{g}: {get_golfer_for_team_group(team, g) or '—'}" for g in GROUPS
        ))


def _render_team_readonly(team):
    """Read-only view of a team's config, shown after the reveal."""
    roster = get_roster(team)
    rot = day1_rotation(team)

    st.markdown("#### Roster")
    if roster:
        st.markdown("\n".join(f"- {g}" for g in roster))
    else:
        st.caption("No golfers.")

    st.markdown("#### Round 1 Roles")
    st.markdown(f"- **{SCRAMBLER_LABEL}:** {rot['scrambler'] or '—'}")
    st.markdown(f"- **Pair 1:** {' & '.join(rot['pair1']) or '—'}")
    st.markdown(f"- **Pair 2:** {' & '.join(rot['pair2']) or '—'}")
    st.markdown(
        f"- Front 9 scramble: {', '.join(rot['front_scramble']) or '—'}  ·  "
        f"alt shot: {', '.join(rot['front_alt_shot']) or '—'}"
    )
    st.markdown(
        f"- Back 9 scramble: {', '.join(rot['back_scramble']) or '—'}  ·  "
        f"alt shot: {', '.join(rot['back_alt_shot']) or '—'}"
    )

    st.markdown("#### Round 2 Group Assignments (Skins)")
    st.markdown("\n".join(
        f"- Group {g}: **{get_golfer_for_team_group(team, g) or '—'}**" for g in GROUPS
    ))


def team_setup_page():
    """Configure each team's roster, Round 1 partnerships, and Round 2 (skins) group assignments.

    Before the reveal: a team must enter its own code to see/edit its config;
    rival teams stay hidden. After the commissioner reveals, everything is open
    and read-only here (see the Grand Reveal page for the fun presentation)."""
    st.title("⚙️ Team Setup")

    if not _secrets_configured():
        st.warning(
            "⚠️ Team & commissioner codes aren't configured in Streamlit secrets yet, "
            "so placeholder codes are in effect (team codes: `team-1` / `team-2` / `team-3` "
            "for the three teams in order; commissioner: `commish`). "
            "Set real codes in your app's secrets before the tournament - see the code "
            "comments for the exact format."
        )

    # After the reveal, Team Setup becomes an open read-only board.
    if is_revealed():
        st.success("🎉 Assignments have been revealed! Here's every team's config.")
        st.caption("Head to the **Grand Reveal** page for the group-by-group presentation.")
        tabs = st.tabs(TEAMS)
        for team, tab in zip(TEAMS, tabs):
            with tab:
                _render_team_readonly(team)
        return

    # Pre-reveal: entry phase. Each session unlocks exactly one team via its code.
    st.markdown(
        "Enter your **team code** to set up your roster, Round 1 roles, and "
        "Round 2 (skins) group assignments. Everything you enter stays hidden from the "
        "other teams until the commissioner's grand reveal."
    )

    current = unlocked_team()

    if current is None:
        col1, col2 = st.columns([1, 1])
        with col1:
            chosen_team = st.selectbox("Your team:", TEAMS, key="unlock_team_select")
        with col2:
            entered = st.text_input("Team code:", type="password", key="unlock_team_code")
        if st.button("Unlock my team"):
            if check_team_code(chosen_team, entered):
                st.session_state.unlocked_team = chosen_team
                st.rerun()
            else:
                st.error("That code doesn't match that team. Try again.")
        st.info("🔒 Each team's setup is private until the grand reveal.")
        return

    # A team is unlocked for this session.
    top1, top2 = st.columns([4, 1])
    with top1:
        st.markdown(f"### Editing: {current}")
        st.caption("Freely editable until the reveal - no need to 'submit'.")
    with top2:
        if st.button("Switch team", use_container_width=True):
            st.session_state.pop('unlocked_team', None)
            st.rerun()

    _render_team_editor(current)


def _render_one_team_day1(team):
    """A single team's Round 1 role breakdown, presented for the reveal."""
    rot = day1_rotation(team)
    st.markdown(f"#### 🏌️ {team}")
    st.markdown(f"🍺 **{SCRAMBLER_LABEL}:** {rot['scrambler'] or '—'}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Pair 1:** {' & '.join(rot['pair1']) or '—'}")
    with c2:
        st.markdown(f"**Pair 2:** {' & '.join(rot['pair2']) or '—'}")
    st.caption(
        f"Front 9 — scramble: {', '.join(rot['front_scramble']) or '—'}  ·  "
        f"alt shot: {', '.join(rot['front_alt_shot']) or '—'}"
    )
    st.caption(
        f"Back 9 — scramble: {', '.join(rot['back_scramble']) or '—'}  ·  "
        f"alt shot: {', '.join(rot['back_alt_shot']) or '—'}"
    )


def _render_all_day1_roles():
    """Consolidated Round 1 role rotation for all teams, side by side."""
    st.markdown("### Round 1 Roles (all teams)")
    cols = st.columns(len(TEAMS))
    for col, team in zip(cols, TEAMS):
        rot = day1_rotation(team)
        with col:
            st.markdown(f"#### {team}")
            st.markdown(f"🍺 **Scrambler:** {rot['scrambler'] or '—'}")
            st.markdown(f"**Pair 1:** {' & '.join(rot['pair1']) or '—'}")
            st.markdown(f"**Pair 2:** {' & '.join(rot['pair2']) or '—'}")
            st.caption(
                f"Front scramble: {', '.join(rot['front_scramble']) or '—'}\n\n"
                f"Front alt shot: {', '.join(rot['front_alt_shot']) or '—'}\n\n"
                f"Back scramble: {', '.join(rot['back_scramble']) or '—'}\n\n"
                f"Back alt shot: {', '.join(rot['back_alt_shot']) or '—'}"
            )


def _render_all_skins_groups():
    """Consolidated Round 2 skins groups for all teams, all at once."""
    st.markdown("### Round 2 Skins Groups (all at once)")
    rows = []
    for g in GROUPS:
        row = {'Group': f"Group {g}"}
        for team in TEAMS:
            row[team] = get_golfer_for_team_group(team, g) or '—'
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# Reveal sequence: first Round 1, team by team in this order, then the 5
# Round 2 skins groups one at a time.
R1_REVEAL_ORDER = ["Young Guns", "Mids", "OGs"]
_TOTAL_REVEAL_STEPS = len(R1_REVEAL_ORDER) + len(GROUPS)  # 3 teams + 5 groups = 8


def grand_reveal_page():
    """Commissioner-controlled grand reveal: Round 1 team by team, then Round 2 groups one at a time."""
    st.title("🎭 The Grand Reveal")

    revealed = is_revealed()

    # --- Commissioner controls -------------------------------------------
    with st.expander("🔑 Commissioner controls", expanded=not revealed):
        if not revealed:
            st.markdown("Enter the commissioner code to preview everything privately or reveal it to everyone.")
            code = st.text_input("Commissioner code:", type="password", key="commish_code_reveal")
            bcol1, bcol2 = st.columns(2)
            with bcol1:
                if st.button("👁️ Preview all (private)", use_container_width=True):
                    if check_commissioner_code(code):
                        st.session_state.commish_preview = True
                        st.rerun()
                    else:
                        st.error("Incorrect commissioner code.")
            with bcol2:
                if st.button("🎉 REVEAL TO EVERYONE", type="primary", use_container_width=True):
                    if check_commissioner_code(code):
                        set_revealed(True)
                        st.session_state.reveal_step = 0  # start the stepped walk
                        st.session_state.pop('commish_preview', None)
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("Incorrect commissioner code.")
        else:
            st.success("Groupings are revealed.")
            code = st.text_input("Commissioner code (to re-lock):", type="password", key="commish_code_relock")
            if st.button("🔒 Re-lock (hide again)"):
                if check_commissioner_code(code):
                    set_revealed(False)
                    st.session_state.pop('reveal_step', None)
                    st.rerun()
                else:
                    st.error("Incorrect commissioner code.")

    # --- Pre-reveal: sealed, unless commissioner is previewing -----------
    if not revealed:
        if st.session_state.get('commish_preview'):
            st.warning("👁️ Commissioner preview — this is private and has NOT been revealed to anyone else.")
            if st.button("Exit preview"):
                st.session_state.pop('commish_preview', None)
                st.rerun()
            _render_all_day1_roles()
            st.divider()
            _render_all_skins_groups()
            return

        st.info("🔒 The groupings are sealed. Waiting for the commissioner to reveal them Thursday night.")
        ready = sum(1 for team in TEAMS if any(
            get_golfer_for_team_group(team, g) for g in GROUPS))
        st.caption(f"{ready} of {len(TEAMS)} teams have entered assignments.")
        return

    # --- Revealed: stepped presentation ----------------------------------
    if 'reveal_step' not in st.session_state:
        st.session_state.reveal_step = _TOTAL_REVEAL_STEPS  # fully revealed on revisit

    step = st.session_state.reveal_step
    n_teams = len(R1_REVEAL_ORDER)

    # Navigation
    nav1, nav2, nav3 = st.columns([1, 1, 2])
    with nav1:
        if st.button("⬅️ Back", disabled=step <= 0):
            st.session_state.reveal_step = max(0, step - 1)
            st.rerun()
    with nav2:
        next_label = "Reveal next ➡️"
        if step < n_teams:
            next_label = f"Reveal {R1_REVEAL_ORDER[step]} ➡️"
        elif step < _TOTAL_REVEAL_STEPS:
            next_label = f"Reveal Group {GROUPS[step - n_teams]} ➡️"
        if st.button(next_label, disabled=step >= _TOTAL_REVEAL_STEPS, type="primary"):
            st.session_state.reveal_step = min(_TOTAL_REVEAL_STEPS, step + 1)
            st.rerun()
    with nav3:
        if st.button("Show all"):
            st.session_state.reveal_step = _TOTAL_REVEAL_STEPS
            st.rerun()

    st.progress(step / _TOTAL_REVEAL_STEPS,
                text=f"{step} / {_TOTAL_REVEAL_STEPS} revealed")

    teams_shown = min(step, n_teams)
    groups_shown = max(0, step - n_teams)

    # Newest reveal sits at the TOP, right under the button, so there's no
    # scrolling down to see it and back up to reveal again. Earlier reveals
    # stack below. Reveal order is R1 teams then R2 groups, so on screen the
    # most-recent (a group, once we're in phase 2) is topmost, with the
    # Round 1 teams at the bottom.

    # "Still hidden" hint always at the very top.
    if step < _TOTAL_REVEAL_STEPS:
        if step < n_teams:
            remaining = n_teams - teams_shown
            st.info(f"👀 Round 1: {remaining} team(s) still hidden — hit **{next_label}** to keep going.")
        else:
            st.info(f"👀 Round 2: {len(GROUPS) - groups_shown} group(s) still hidden — hit **{next_label}** to continue the suspense.")

    # ---- Phase 2 (on top): Round 2 skins groups, newest first ----------
    if groups_shown > 0:
        st.markdown("### Round 2 — Skins Groups")
        st.caption("Each group has one golfer from every team going head-to-head for skins.")
        for g in reversed(GROUPS[:groups_shown]):
            st.markdown(f"#### 🏌️ Group {g}")
            cols = st.columns(len(TEAMS))
            for col, team in zip(cols, TEAMS):
                golfer = get_golfer_for_team_group(team, g)
                with col:
                    st.markdown(f"**{team}**")
                    st.markdown(f"### {golfer or '—'}")
        st.divider()

    # ---- Phase 1 (below): Round 1 roles, newest first ------------------
    st.markdown("### Round 1 — Scramble / Alt Shot Roles")
    if teams_shown == 0:
        st.caption("First up: Round 1 roles, one team at a time.")
    for team in reversed(R1_REVEAL_ORDER[:teams_shown]):
        _render_one_team_day1(team)

    # ---- Everything out: consolidated recap (very bottom) --------------
    if step >= _TOTAL_REVEAL_STEPS:
        st.divider()
        st.success("🎉 That's everyone!")
        _render_all_skins_groups()


# ---------------------------------------------------------------------------
# Tournament History (past years, read from history/<year>_results.json)
# ---------------------------------------------------------------------------
def load_history():
    """Load every history/<year>_results.json file in the repo, keyed by year."""
    years = {}
    if not os.path.isdir(HISTORY_DIR):
        return years
    for fname in os.listdir(HISTORY_DIR):
        match = re.match(r"^(\d{4})_results\.json$", fname)
        if not match:
            continue
        year = int(match.group(1))
        try:
            with open(os.path.join(HISTORY_DIR, fname)) as f:
                years[year] = json.load(f)
        except Exception as e:
            st.warning(f"Couldn't read {fname}: {e}")
    return years


def load_supreme_leaders():
    """Load the Supreme Leaders head-to-head totals, if present."""
    path = os.path.join(HISTORY_DIR, "supreme_leaders.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"Couldn't read supreme_leaders.json: {e}")
        return None


def history_page():
    """Browse past years' champions and the Supreme Leaders head-to-head."""
    st.title("📜 Tournament History")

    years_data = load_history()
    if not years_data:
        st.info(
            "No past results found yet. Drop a `history/<year>_results.json` file "
            "(see `history/README.md` for the format) into the repo to see it here."
        )
        return

    sorted_years = sorted(years_data.keys(), reverse=True)

    # Champions at a glance
    st.markdown("### Champions")
    champ_rows = []
    for year in sorted_years:
        results = years_data[year].get('results', {})
        leader = results.get('supreme_leader')
        champ_rows.append({
            'Year': year,
            'Champion': results.get('champion', '—'),
            'Supreme Leader': f"Supreme Leader {leader}" if leader else '—',
        })
    st.dataframe(pd.DataFrame(champ_rows), use_container_width=True, hide_index=True)

    # Supreme Leaders head-to-head
    sl = load_supreme_leaders()
    if sl and sl.get('head_to_head'):
        st.markdown("### 👑 Supreme Leaders Head to Head")
        h2h = sorted(sl['head_to_head'], key=lambda x: x.get('wins', 0), reverse=True)
        df_h2h = pd.DataFrame(
            [{'Name': entry.get('name', '—'), 'Total Wins': entry.get('wins', 0)} for entry in h2h]
        )
        st.dataframe(df_h2h, use_container_width=True, hide_index=True)

    st.divider()

    # Full detail per year (only shows what data exists for that year)
    selected_year = st.selectbox("View details for:", sorted_years)
    year_data = years_data[selected_year]
    results = year_data.get('results', {})
    notes = year_data.get('format_notes', {})

    st.markdown(f"### {selected_year} Results")
    if notes:
        with st.expander("Format that year"):
            if notes.get('day1'):
                st.caption(f"**Day 1:** {notes['day1']}")
            if notes.get('day2'):
                st.caption(f"**Day 2:** {notes['day2']}")

    st.markdown(f"🏆 **Champion: {results.get('champion', '—')}**")
    if results.get('supreme_leader'):
        st.markdown(f"👑 **Supreme Leader {results['supreme_leader']}**")

    overall = results.get('overall_points', {})
    if overall:
        df_overall = pd.DataFrame(
            [{'Team': t, 'Overall Points': p} for t, p in overall.items()]
        ).sort_values('Overall Points', ascending=False)
        st.dataframe(df_overall, use_container_width=True, hide_index=True)

    # Detailed scoring tables only exist for years with hole-by-hole data.
    has_detail = any(results.get(k) for k in
                     ['day1_scramble_points', 'day1_alt_shot_points', 'day2_skins_points'])
    if not has_detail:
        st.caption("Only the champion was recorded for this year — no hole-by-hole detail.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Day 1 - Scramble")
        scramble_points = results.get('day1_scramble_points', {})
        team_totals = results.get('day1_team_totals', {})
        rows = []
        for team, pts in scramble_points.items():
            totals = team_totals.get(team, {})
            rows.append({
                'Team': team, 'Points': pts,
                'Score': totals.get('scramble'), 'To Par': totals.get('scramble_to_par')
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with col2:
        st.markdown("#### Day 1 - Alt Shot")
        alt_shot_points = results.get('day1_alt_shot_points', {})
        rows = []
        for team, pts in alt_shot_points.items():
            totals = team_totals.get(team, {})
            rows.append({
                'Team': team, 'Points': pts,
                'Score': totals.get('alt_shot'), 'To Par': totals.get('alt_shot_to_par')
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("#### Day 2 - Skins Points")
    skins_points = results.get('day2_skins_points', {})
    if skins_points:
        df_skins = pd.DataFrame(
            [{'Team': t, 'Skins Points': p} for t, p in skins_points.items()]
        ).sort_values('Skins Points', ascending=False)
        st.dataframe(df_skins, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Scoring calculations
# ---------------------------------------------------------------------------
def calculate_day1_points():
    """Calculate Day 1 points and current standings"""
    day1_scores = get_day1_scores()

    team_totals = {team: {'scramble': 0, 'alt_shot': 0, 'holes_completed': 0,
                           'scramble_to_par': 0, 'alt_shot_to_par': 0} for team in TEAMS}

    total_par = sum(DAY1_COURSE[hole]['par'] for hole in range(1, 19))

    for score_data in day1_scores.values():
        team = score_data['team']
        hole = score_data['hole']
        if score_data['scramble'] and score_data['alt_shot']:
            team_totals[team]['scramble'] += score_data['scramble']
            team_totals[team]['alt_shot'] += score_data['alt_shot']
            team_totals[team]['holes_completed'] += 1

            hole_par = DAY1_COURSE[hole]['par']
            team_totals[team]['scramble_to_par'] += (score_data['scramble'] - hole_par)
            team_totals[team]['alt_shot_to_par'] += (score_data['alt_shot'] - hole_par)

    for team in TEAMS:
        holes_played = team_totals[team]['holes_completed']
        if 0 < holes_played < 18:
            par_for_holes_played = sum(DAY1_COURSE[hole]['par'] for hole in range(1, holes_played + 1))
            team_totals[team]['scramble_to_par'] = team_totals[team]['scramble'] - par_for_holes_played
            team_totals[team]['alt_shot_to_par'] = team_totals[team]['alt_shot'] - par_for_holes_played
        elif holes_played == 18:
            team_totals[team]['scramble_to_par'] = team_totals[team]['scramble'] - total_par
            team_totals[team]['alt_shot_to_par'] = team_totals[team]['alt_shot'] - total_par

    complete_teams = [team for team in TEAMS if team_totals[team]['holes_completed'] == 18]

    def award_points_with_ties(scores_dict, point_values=None):
        """Award points handling ties by splitting combined position points"""
        if point_values is None:
            point_values = DAY1_POINT_VALUES
        if not scores_dict:
            return {}

        sorted_teams = sorted(scores_dict.items(), key=lambda x: x[1])

        points_awarded = {}
        i = 0
        while i < len(sorted_teams):
            current_score = sorted_teams[i][1]
            tied_teams = [team for team, score in sorted_teams[i:] if score == current_score]

            if i == 0:
                if len(tied_teams) == 1:
                    points_to_split = point_values[0]
                elif len(tied_teams) == 2:
                    points_to_split = point_values[0] + point_values[1]
                else:
                    points_to_split = sum(point_values)
            elif i == 1:
                if len(tied_teams) == 1:
                    points_to_split = point_values[1]
                else:
                    points_to_split = point_values[1] + point_values[2]
            else:
                points_to_split = point_values[2]

            points_per_team = points_to_split / len(tied_teams)
            for team in tied_teams:
                points_awarded[team] = points_per_team

            i += len(tied_teams)

        return points_awarded

    if len(complete_teams) == len(TEAMS):
        scramble_scores = {team: data['scramble'] for team, data in team_totals.items()}
        scramble_points = award_points_with_ties(scramble_scores)

        alt_shot_scores = {team: data['alt_shot'] for team, data in team_totals.items()}
        alt_shot_points = award_points_with_ties(alt_shot_scores)
    else:
        scramble_points = {}
        alt_shot_points = {}

    return {
        'scramble_points': scramble_points,
        'alt_shot_points': alt_shot_points,
        'team_totals': team_totals,
        'complete_teams': complete_teams,
        'all_teams_complete': len(complete_teams) == len(TEAMS)
    }


def calculate_leaderboard():
    """Calculate current team standings"""
    team_points = {team: 0 for team in TEAMS}

    day1_results = calculate_day1_points()
    if day1_results['all_teams_complete']:
        scramble_points = day1_results['scramble_points']
        alt_shot_points = day1_results['alt_shot_points']
        for team in TEAMS:
            team_points[team] += scramble_points.get(team, 0)
            team_points[team] += alt_shot_points.get(team, 0)

    load_all_data()

    day2_points = st.session_state.get('team_day2_points', {team: 0 for team in TEAMS})
    for team in TEAMS:
        team_points[team] += day2_points.get(team, 0)

    return team_points, day1_results


def format_score_to_par(score_to_par):
    """Format score to par display"""
    if score_to_par == 0:
        return "E"
    elif score_to_par > 0:
        return f"+{score_to_par}"
    else:
        return str(score_to_par)


# ---------------------------------------------------------------------------
# Sidebar: backup / data export
# ---------------------------------------------------------------------------
def backup_sidebar():
    """Lets anyone pull a backup copy of the data at any time."""
    with st.sidebar.expander("💾 Backup & Data"):
        st.caption(
            "Data lives locally in the app. Grab a backup anytime you want "
            "extra peace of mind (recommended right after the tournament)."
        )
        conn = get_db()
        try:
            day1_df = pd.read_sql_query("SELECT * FROM day1_scores", conn)
            day2_df = pd.read_sql_query("SELECT * FROM day2_scores", conn)
            skins_df = pd.read_sql_query("SELECT * FROM day2_skins", conn)

            st.download_button("Day 1 scores (CSV)", day1_df.to_csv(index=False),
                                "day1_scores.csv", "text/csv", use_container_width=True)
            st.download_button("Day 2 scores (CSV)", day2_df.to_csv(index=False),
                                "day2_scores.csv", "text/csv", use_container_width=True)
            st.download_button("Skins results (CSV)", skins_df.to_csv(index=False),
                                "day2_skins.csv", "text/csv", use_container_width=True)

            if os.path.exists(DB_PATH):
                with open(DB_PATH, "rb") as f:
                    st.download_button("Full database (.db)", f.read(),
                                        "tournament_data.db", use_container_width=True)
        except Exception as e:
            st.caption(f"Backup unavailable: {e}")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def day1_scoring_page():
    """Day 1 scoring interface"""
    st.title("📊 Day 1 Scoring")
    st.markdown("**Format**: Scramble + Alternating Shot for each team")

    col1, col2 = st.columns([1, 2])

    with col1:
        selected_team = st.selectbox("Select Team:", TEAMS)
        selected_hole = st.selectbox("Select Hole:", HOLES)

        if is_revealed():
            rot = day1_rotation(selected_team)
            nine = "front" if selected_hole <= 9 else "back"
            st.caption("**Roles this nine:**")
            st.caption(f"🍺 Scrambler: {rot['scrambler'] or '—'}")
            st.caption(f"Scramble: {', '.join(rot[f'{nine}_scramble']) or '—'}")
            st.caption(f"Alt shot: {', '.join(rot[f'{nine}_alt_shot']) or '—'}")

    with col2:
        hole_info = DAY1_COURSE[selected_hole]
        st.markdown(f"### {selected_team} - Hole {selected_hole}")
        st.markdown(f"**Par {hole_info['par']} • {hole_info['yardage']} yards**")

        key = f"{selected_team}_{selected_hole}"
        existing_scores = st.session_state.get('day1_scores', {}).get(key, {})

        col2a, col2b = st.columns(2)

        with col2a:
            scramble_score = st.number_input(
                "Scramble Score:", min_value=1, max_value=15,
                value=existing_scores.get('scramble', hole_info['par']),
                key=f"scramble_{selected_team}_{selected_hole}"
            )
            scramble_to_par = scramble_score - hole_info['par']
            st.markdown(f"To Par: **{format_score_to_par(scramble_to_par)}**")

        with col2b:
            alt_shot_score = st.number_input(
                "Alternating Shot Score:", min_value=1, max_value=15,
                value=existing_scores.get('alt_shot', hole_info['par']),
                key=f"alt_shot_{selected_team}_{selected_hole}"
            )
            alt_shot_to_par = alt_shot_score - hole_info['par']
            st.markdown(f"To Par: **{format_score_to_par(alt_shot_to_par)}**")

        if st.button("Save Scores", key=f"save_{selected_team}_{selected_hole}"):
            save_day1_score(selected_team, selected_hole, scramble_score, alt_shot_score)
            st.success(f"Scores saved for {selected_team} - Hole {selected_hole}")
            time.sleep(1)
            st.rerun()

    st.markdown("### Current Scores")
    day1_scores = get_day1_scores()
    team_scores = [(data['hole'], data['scramble'], data['alt_shot'],
                   DAY1_COURSE[data['hole']]['par'],
                   data['scramble'] - DAY1_COURSE[data['hole']]['par'],
                   data['alt_shot'] - DAY1_COURSE[data['hole']]['par'])
                   for data in day1_scores.values()
                   if data['team'] == selected_team]

    if team_scores:
        team_scores.sort(key=lambda x: x[0])
        df = pd.DataFrame(team_scores, columns=['Hole', 'Scramble', 'Alt Shot', 'Par', 'Scramble To Par', 'Alt Shot To Par'])
        df['Scramble To Par'] = df['Scramble To Par'].apply(format_score_to_par)
        df['Alt Shot To Par'] = df['Alt Shot To Par'].apply(format_score_to_par)
        st.dataframe(df, use_container_width=True)

        st.markdown("### Running Totals")
        scramble_total = sum(score[1] for score in team_scores)
        alt_shot_total = sum(score[2] for score in team_scores)
        holes_played = len(team_scores)
        par_total = sum(score[3] for score in team_scores)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Holes Completed", f"{holes_played}/18")
        with col2:
            st.metric("Scramble Total", f"{scramble_total} ({format_score_to_par(scramble_total - par_total)})")
        with col3:
            st.metric("Alt Shot Total", f"{alt_shot_total} ({format_score_to_par(alt_shot_total - par_total)})")
    else:
        st.info(f"No scores entered yet for {selected_team}")


def day2_scoring_page():
    """Day 2 scoring interface"""
    st.title("🎯 Day 2 Scoring - Skins Game")
    st.markdown("**Format**: Individual play, lowest score wins the skin (18 holes)")

    col1, col2 = st.columns([1, 2])

    with col1:
        selected_group = st.selectbox("Select Group:", GROUPS)
        selected_hole = st.selectbox("Select Hole:", DAY2_HOLES, key="day2_hole")

        st.caption("**Group roster:**")
        _revealed = is_revealed()
        for team in TEAMS:
            if _revealed:
                golfer = get_golfer_for_team_group(team, selected_group)
                st.caption(f"{team}: {golfer or '— unassigned —'}")
            else:
                st.caption(f"{team}: 🔒 hidden until reveal")

    with col2:
        hole_info = DAY2_COURSE[selected_hole]
        points_value = calculate_hole_points_value(selected_group, selected_hole)

        st.markdown(f"### Group {selected_group} - Hole {selected_hole}")
        st.markdown(f"**Par {hole_info['par']} • {hole_info['yardage']} yards**")
        if points_value > 1:
            st.markdown(f"**🔥 Worth {points_value} points (carryover from ties!)**")
        else:
            st.markdown(f"**Worth {points_value} point**")

        scores = {}
        cols = st.columns(3)
        for i, team in enumerate(TEAMS):
            key = f"{selected_group}_{selected_hole}_{team}"
            existing_score = st.session_state.get('day2_scores', {}).get(key, {}).get('score', hole_info['par'])
            golfer = get_golfer_for_team_group(team, selected_group) if is_revealed() else None
            label = f"{team} ({golfer}) Score:" if golfer else f"{team} Score:"

            with cols[i]:
                scores[team] = st.number_input(
                    label, min_value=1, max_value=15,
                    value=existing_score,
                    key=f"score_{selected_group}_{selected_hole}_{team}"
                )
                team_to_par = scores[team] - hole_info['par']
                st.markdown(f"To Par: **{format_score_to_par(team_to_par)}**")

        if st.button("Save Scores", key=f"save_day2_{selected_group}_{selected_hole}"):
            for team, score in scores.items():
                save_day2_score(selected_group, selected_hole, team, score)
            st.success(f"Scores saved for Group {selected_group} - Hole {selected_hole}")
            time.sleep(1)
            st.rerun()

        skin_key = f"{selected_group}_{selected_hole}"
        if skin_key in st.session_state.get('day2_skins', {}):
            skin_info = st.session_state.day2_skins[skin_key]
            if skin_info['tied']:
                st.warning(f"🤝 Hole {selected_hole}: TIE - Skin carries over to next hole!")
            else:
                st.success(f"🏆 Hole {selected_hole}: **{skin_info['winner']}** wins {skin_info.get('points_value', 1)} point(s)!")

    st.markdown(f"### Group {selected_group} Scorecard")
    display_group_scorecard(selected_group)


def display_group_scorecard(group):
    """Display scorecard for a specific group"""
    scorecard_data = []

    for hole in DAY2_HOLES:
        hole_data = {'Hole': hole, 'Par': DAY2_COURSE[hole]['par']}

        for team in TEAMS:
            key = f"{group}_{hole}_{team}"
            score = st.session_state.get('day2_scores', {}).get(key, {}).get('score', '-')
            if score != '-':
                to_par = score - DAY2_COURSE[hole]['par']
                hole_data[team] = f"{score} ({format_score_to_par(to_par)})"
            else:
                hole_data[team] = '-'

        skin_key = f"{group}_{hole}"
        if skin_key in st.session_state.get('day2_skins', {}):
            skin_info = st.session_state.day2_skins[skin_key]
            if skin_info['tied']:
                hole_data['Skin Winner'] = 'TIE'
                hole_data['Points'] = f"{skin_info.get('points_value', 1)} (carry)"
            else:
                hole_data['Skin Winner'] = skin_info['winner']
                hole_data['Points'] = skin_info.get('points_value', 1)
        else:
            hole_data['Skin Winner'] = '-'
            hole_data['Points'] = '-'

        scorecard_data.append(hole_data)

    if scorecard_data:
        df = pd.DataFrame(scorecard_data)
        st.dataframe(df, use_container_width=True)


def leaderboard_page():
    """Display live leaderboard"""
    st.title("🏆 Live Leaderboard")

    placeholder = st.empty()

    with placeholder.container():
        team_points, day1_results = calculate_leaderboard()

        st.markdown("### Overall Team Standings")
        leaderboard_data = []
        for team in TEAMS:
            if day1_results['all_teams_complete']:
                day1_scramble = day1_results['scramble_points'].get(team, 0)
                day1_alt_shot = day1_results['alt_shot_points'].get(team, 0)
                day1_total = day1_scramble + day1_alt_shot
            else:
                day1_total = 0

            day2_skins = st.session_state.get('team_day2_points', {}).get(team, 0)

            leaderboard_data.append({
                'Team': team,
                'Day 1 Points': f"{day1_total:.1f}" if day1_total > 0 else "Pending",
                'Day 2 Skins': day2_skins,
                'Total Points': f"{team_points[team]:.1f}"
            })

        leaderboard_data.sort(key=lambda x: float(x['Total Points']), reverse=True)
        df_leaderboard = pd.DataFrame(leaderboard_data)
        st.dataframe(df_leaderboard, use_container_width=True)

        if not day1_results['all_teams_complete']:
            st.info("⏳ Day 1 points will be awarded once all teams complete their rounds")

        st.markdown("### Day 1 Current Standings")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Scramble Competition")
            scramble_data = []
            for team in TEAMS:
                team_data = day1_results['team_totals'][team]
                holes_played = team_data['holes_completed']
                if holes_played > 0:
                    total_score = team_data['scramble']
                    to_par = team_data['scramble_to_par']
                    scramble_data.append({
                        'Team': team,
                        'Score': f"{total_score} ({format_score_to_par(to_par)})",
                        'Holes': f"{holes_played}/18"
                    })
                else:
                    scramble_data.append({'Team': team, 'Score': 'No scores', 'Holes': '0/18'})

            scramble_data.sort(key=lambda x: (
                -int(x['Holes'].split('/')[0]),
                int(x['Score'].split(' (')[0]) if x['Score'] != 'No scores' else 999
            ))
            df_scramble = pd.DataFrame(scramble_data)
            st.dataframe(df_scramble, use_container_width=True)

        with col2:
            st.markdown("#### Alternating Shot Competition")
            alt_shot_data = []
            for team in TEAMS:
                team_data = day1_results['team_totals'][team]
                holes_played = team_data['holes_completed']
                if holes_played > 0:
                    total_score = team_data['alt_shot']
                    to_par = team_data['alt_shot_to_par']
                    alt_shot_data.append({
                        'Team': team,
                        'Score': f"{total_score} ({format_score_to_par(to_par)})",
                        'Holes': f"{holes_played}/18"
                    })
                else:
                    alt_shot_data.append({'Team': team, 'Score': 'No scores', 'Holes': '0/18'})

            alt_shot_data.sort(key=lambda x: (
                -int(x['Holes'].split('/')[0]),
                int(x['Score'].split(' (')[0]) if x['Score'] != 'No scores' else 999
            ))
            df_alt_shot = pd.DataFrame(alt_shot_data)
            st.dataframe(df_alt_shot, use_container_width=True)

        st.markdown("### Day 2 Skins Summary")
        skins_summary = []
        for group in GROUPS:
            skins_played = sum(1 for key in st.session_state.get('day2_skins', {}).keys()
                              if key.startswith(f"{group}_"))
            group_skins = {team: 0 for team in TEAMS}

            for skin_data in st.session_state.get('day2_skins', {}).values():
                if (skin_data['group'] == group and
                    skin_data['winner'] and
                    not skin_data['tied']):
                    points = skin_data.get('points_value', 1)
                    group_skins[skin_data['winner']] += points

            skins_summary.append({
                'Group': f"Group {group}",
                'Holes Played': f"{skins_played}/18",
                'Young Guns': group_skins['Young Guns'],
                'OGs': group_skins['OGs'],
                'Mids': group_skins['Mids']
            })

        df_skins = pd.DataFrame(skins_summary)
        st.dataframe(df_skins, use_container_width=True)

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("🔄 Refresh Now"):
            st.rerun()

    with col2:
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=False)

    with col3:
        st.markdown("*Leaderboard updates automatically when scores are saved*")

    if auto_refresh:
        time.sleep(30)
        st.rerun()


def main():
    """Main application"""
    get_db()               # ensure the database + schema exist
    flush_pending_writes()  # retry anything left over from an interrupted write

    st.sidebar.title("🏌️‍♂️ The Gentlemen's Cup")
    page = st.sidebar.radio(
        "Navigate:",
        ["🏆 Leaderboard", "📊 Day 1 Scoring", "🎯 Day 2 Scoring", "⚙️ Team Setup",
         "🎭 Grand Reveal", "📜 Tournament History"]
    )

    st.sidebar.divider()
    backup_sidebar()

    if page == "🏆 Leaderboard":
        leaderboard_page()
    elif page == "📊 Day 1 Scoring":
        day1_scoring_page()
    elif page == "🎯 Day 2 Scoring":
        day2_scoring_page()
    elif page == "⚙️ Team Setup":
        team_setup_page()
    elif page == "🎭 Grand Reveal":
        grand_reveal_page()
    elif page == "📜 Tournament History":
        history_page()


if __name__ == "__main__":
    main()
