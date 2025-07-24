# Auto-refresh controls
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("🔄 Refresh Now"):
            st.rerun()
    
    with col2:
        st.markdown("*Leaderboard updates automatically when scores are saved*")# -*- coding: utf-8 -*-
"""
Created on Thu Jul 24 13:32:12 2025

@author: MPlantz
"""

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import time
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="The Gentlemen's Cup",
    page_icon="🏌️‍♂️",
    layout="wide"
)

# Constants
TEAMS = ["Young Guns", "OGs", "Mids"]
ACCESS_CODE = "gentlemen2025"  # Change this to your preferred code
HOLES = list(range(1, 19))  # 18 holes for Day 1
DAY2_HOLES = list(range(1, 10))  # 9 holes for Day 2
GROUPS = list(range(1, 6))  # 5 groups for Day 2

# Course information
DAY1_COURSE = {
    1: {'par': 4, 'yardage': 322}, 2: {'par': 4, 'yardage': 359}, 3: {'par': 3, 'yardage': 119},
    4: {'par': 4, 'yardage': 361}, 5: {'par': 5, 'yardage': 486}, 6: {'par': 3, 'yardage': 197},
    7: {'par': 5, 'yardage': 517}, 8: {'par': 4, 'yardage': 167}, 9: {'par': 4, 'yardage': 353},
    10: {'par': 4, 'yardage': 284}, 11: {'par': 3, 'yardage': 192}, 12: {'par': 4, 'yardage': 326},
    13: {'par': 5, 'yardage': 497}, 14: {'par': 4, 'yardage': 314}, 15: {'par': 3, 'yardage': 135},
    16: {'par': 4, 'yardage': 322}, 17: {'par': 3, 'yardage': 308}, 18: {'par': 5, 'yardage': 424}
}

DAY2_COURSE = {
    1: {'par': 4, 'yardage': 327}, 2: {'par': 3, 'yardage': 153}, 3: {'par': 5, 'yardage': 536},
    4: {'par': 3, 'yardage': 135}, 5: {'par': 4, 'yardage': 434}, 6: {'par': 3, 'yardage': 167},
    7: {'par': 4, 'yardage': 386}, 8: {'par': 5, 'yardage': 501}, 9: {'par': 4, 'yardage': 253}
}

# Google Sheets setup
@st.cache_resource
def init_google_sheets():
    """Initialize Google Sheets connection"""
    try:
        # Get credentials from Streamlit secrets
        credentials_dict = {
            "type": st.secrets["gcp_service_account"]["type"],
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"],
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
            "token_uri": st.secrets["gcp_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"]
        }
        
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        
        credentials = Credentials.from_service_account_info(credentials_dict, scopes=scope)
        client = gspread.authorize(credentials)
        
        # Open the spreadsheet
        try:
            spreadsheet = client.open("Gentlemens Cup Tournament Data")
            st.success(f"Successfully connected to spreadsheet: {spreadsheet.title}")
            return client, spreadsheet
        except Exception as sheet_error:
            st.error(f"Could not open spreadsheet 'Gentlemens Cup Tournament Data': {sheet_error}")
            st.error("Make sure:")
            st.error("1. You created a Google Sheet with exactly this name: 'Gentlemens Cup Tournament Data'")
            st.error(f"2. You shared it with: {credentials_dict.get('client_email', 'YOUR_SERVICE_ACCOUNT_EMAIL')}")
            st.error("3. You gave the service account 'Editor' permissions")
            return None, None
    
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        return None, None

def setup_sheets_structure(spreadsheet):
    """Setup the initial sheet structure"""
    try:
        st.info("Setting up sheet structure...")
        
        # Create Day 1 scores sheet
        try:
            day1_sheet = spreadsheet.worksheet("Day1_Scores")
            st.success("Found existing Day1_Scores sheet")
        except:
            st.info("Creating Day1_Scores sheet...")
            day1_sheet = spreadsheet.add_worksheet(title="Day1_Scores", rows="200", cols="10")
            day1_sheet.update('A1:F1', [['Team', 'Hole', 'Scramble_Score', 'Alt_Shot_Score', 'Timestamp', 'ID']])
            st.success("Created Day1_Scores sheet")
        
        # Create Day 2 scores sheet
        try:
            day2_sheet = spreadsheet.worksheet("Day2_Scores")
            st.success("Found existing Day2_Scores sheet")
        except:
            st.info("Creating Day2_Scores sheet...")
            day2_sheet = spreadsheet.add_worksheet(title="Day2_Scores", rows="500", cols="10")
            day2_sheet.update('A1:F1', [['Group', 'Hole', 'Team', 'Score', 'Timestamp', 'ID']])
            st.success("Created Day2_Scores sheet")
        
        # Create Day 2 skins sheet
        try:
            skins_sheet = spreadsheet.worksheet("Day2_Skins")
            st.success("Found existing Day2_Skins sheet")
        except:
            st.info("Creating Day2_Skins sheet...")
            skins_sheet = spreadsheet.add_worksheet(title="Day2_Skins", rows="200", cols="10")
            skins_sheet.update('A1:F1', [['Group', 'Hole', 'Winner', 'Winning_Score', 'Points_Value', 'ID']])
            st.success("Created Day2_Skins sheet")
        
        st.success("✅ All sheets setup successfully!")
        return day1_sheet, day2_sheet, skins_sheet
    
    except Exception as e:
        st.error(f"Error setting up sheets structure: {e}")
        return None, None, None

def get_sheets():
    """Get or initialize sheets connection"""
    if 'sheets_client' not in st.session_state:
        client, spreadsheet = init_google_sheets()
        if client and spreadsheet:
            day1_sheet, day2_sheet, skins_sheet = setup_sheets_structure(spreadsheet)
            st.session_state.sheets_client = client
            st.session_state.spreadsheet = spreadsheet
            st.session_state.day1_sheet = day1_sheet
            st.session_state.day2_sheet = day2_sheet
            st.session_state.skins_sheet = skins_sheet
            st.session_state.using_sheets = True
        else:
            st.error("❌ Google Sheets connection failed. Please check your configuration.")
            st.stop()
    
    return st.session_state.get('using_sheets', False)

def save_day1_score(team, hole, scramble_score, alt_shot_score):
    """Save Day 1 scores to Google Sheets"""
    timestamp = datetime.now().isoformat()
    score_id = f"{team}_{hole}"
    
    try:
        day1_sheet = st.session_state.day1_sheet
        
        # Check if score already exists
        existing_data = day1_sheet.get_all_records()
        existing_row = None
        for i, record in enumerate(existing_data):
            if record['Team'] == team and record['Hole'] == hole:
                existing_row = i + 2  # +2 because sheets are 1-indexed and we have headers
                break
        
        # Prepare data
        row_data = [team, hole, scramble_score, alt_shot_score, timestamp, score_id]
        
        if existing_row:
            # Update existing row
            day1_sheet.update(f'A{existing_row}:F{existing_row}', [row_data])
        else:
            # Append new row
            day1_sheet.append_row(row_data)
        
        # Update local cache for UI responsiveness
        if 'day1_scores' not in st.session_state:
            st.session_state.day1_scores = {}
        st.session_state.day1_scores[score_id] = {
            'team': team,
            'hole': hole,
            'scramble': scramble_score,
            'alt_shot': alt_shot_score,
            'timestamp': timestamp
        }
        
    except Exception as e:
        st.error(f"Error saving to Google Sheets: {e}")

def save_day2_score(group, hole, team, score):
    """Save Day 2 scores to Google Sheets"""
    timestamp = datetime.now().isoformat()
    score_id = f"{group}_{hole}_{team}"
    
    try:
        day2_sheet = st.session_state.day2_sheet
        
        # Check if score already exists
        existing_data = day2_sheet.get_all_records()
        existing_row = None
        for i, record in enumerate(existing_data):
            if (record['Group'] == group and 
                record['Hole'] == hole and 
                record['Team'] == team):
                existing_row = i + 2  # +2 because sheets are 1-indexed and we have headers
                break
        
        # Prepare data
        row_data = [group, hole, team, score, timestamp, score_id]
        
        if existing_row:
            # Update existing row
            day2_sheet.update(f'A{existing_row}:F{existing_row}', [row_data])
        else:
            # Append new row
            day2_sheet.append_row(row_data)
        
        # Update local cache for UI responsiveness
        if 'day2_scores' not in st.session_state:
            st.session_state.day2_scores = {}
        st.session_state.day2_scores[score_id] = {
            'group': group,
            'hole': hole,
            'team': team,
            'score': score,
            'timestamp': timestamp
        }
        
    except Exception as e:
        st.error(f"Error saving to Google Sheets: {e}")
    
    # Calculate skins for this hole and recalculate subsequent holes if needed
    recalculate_group_skins_from_hole(group, hole)

def save_skin_result(group, hole, winner, winning_score, points_value):
    """Save skin calculation results to Google Sheets"""
    try:
        skins_sheet = st.session_state.skins_sheet
        skin_id = f"{group}_{hole}"
        
        # Check if skin result already exists
        existing_data = skins_sheet.get_all_records()
        existing_row = None
        for i, record in enumerate(existing_data):
            if record['Group'] == group and record['Hole'] == hole:
                existing_row = i + 2  # +2 because sheets are 1-indexed and we have headers
                break
        
        # Only save if there's a winner (no ties saved to sheets)
        if winner:
            row_data = [group, hole, winner, winning_score, points_value, skin_id]
            
            if existing_row:
                # Update existing row
                skins_sheet.update(f'A{existing_row}:F{existing_row}', [row_data])
            else:
                # Append new row
                skins_sheet.append_row(row_data)
        elif existing_row:
            # If this was previously a win but now it's a tie, delete the row
            skins_sheet.delete_rows(existing_row)
            
    except Exception as e:
        st.error(f"Error saving skin result to Google Sheets: {e}")

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
                'group': group,
                'hole': hole,
                'winner': winner,
                'score': min_score,
                'tied': False,
                'points_value': points_value
            }
            st.session_state.day2_skins[skin_key] = skin_result
            save_skin_result(group, hole, winner, min_score, points_value)
            
            # Award points to the winning team
            st.session_state.team_day2_points[winner] += points_value
            
        else:  # Tie - skin carries over
            skin_result = {
                'group': group,
                'hole': hole,
                'winner': None,
                'score': min_score,
                'tied': True,
                'points_value': points_value
            }
            st.session_state.day2_skins[skin_key] = skin_result
            # Don't save ties to Google Sheets - we only care about wins

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
            # If there are scores but no skin data, we need to calculate it first
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
                # We have scores but no skin result - this shouldn't happen in our new logic
                # but if it does, assume it needs to be calculated
                break
    
    return points_value

def update_team_points(team, points):
    """Update team points in session state for immediate leaderboard updates"""
    if 'team_day2_points' not in st.session_state:
        st.session_state.team_day2_points = {team: 0 for team in TEAMS}
    
    st.session_state.team_day2_points[team] = st.session_state.team_day2_points.get(team, 0) + points

def load_data_from_sheets():
    """Load all data from Google Sheets into session state"""
    try:
        # Load Day 1 scores
        day1_data = st.session_state.day1_sheet.get_all_records()
        st.session_state.day1_scores = {}
        for record in day1_data:
            if record['Team'] and record['Hole']:  # Valid record
                key = f"{record['Team']}_{record['Hole']}"
                st.session_state.day1_scores[key] = {
                    'team': record['Team'],
                    'hole': record['Hole'],
                    'scramble': record['Scramble_Score'],
                    'alt_shot': record['Alt_Shot_Score'],
                    'timestamp': record.get('Timestamp', '')
                }
        
        # Load Day 2 scores
        day2_data = st.session_state.day2_sheet.get_all_records()
        st.session_state.day2_scores = {}
        for record in day2_data:
            if record['Group'] and record['Hole'] and record['Team']:  # Valid record
                key = f"{record['Group']}_{record['Hole']}_{record['Team']}"
                st.session_state.day2_scores[key] = {
                    'group': record['Group'],
                    'hole': record['Hole'],
                    'team': record['Team'],
                    'score': record['Score'],
                    'timestamp': record.get('Timestamp', '')
                }
        
        # Load Day 2 skins and recalculate team points
        skins_data = st.session_state.skins_sheet.get_all_records()
        st.session_state.day2_skins = {}
        st.session_state.team_day2_points = {team: 0 for team in TEAMS}
        
        # First, load all the wins from Google Sheets
        for record in skins_data:
            if record['Group'] and record['Hole'] and record.get('Winner'):  # Only load records with winners
                key = f"{record['Group']}_{record['Hole']}"
                points_value = record.get('Points_Value', 1)
                
                skin_result = {
                    'group': record['Group'],
                    'hole': record['Hole'],
                    'winner': record['Winner'],
                    'score': record.get('Winning_Score'),
                    'tied': False,
                    'points_value': points_value
                }
                st.session_state.day2_skins[key] = skin_result
                
                # Add points to winning team
                st.session_state.team_day2_points[record['Winner']] += points_value
        
        # Recalculate any missing skins
        recalculate_missing_skins()
        
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {e}")

def recalculate_missing_skins():
    """Recalculate skins for any holes that have scores but no skin result"""
    if 'day2_scores' not in st.session_state:
        return
    
    # Get all unique groups that have scores
    groups_with_scores = set()
    for key, score_data in st.session_state.day2_scores.items():
        if score_data['score'] and score_data['score'] > 0:
            groups_with_scores.add(score_data['group'])
    
    # Recalculate skins for each group
    for group in groups_with_scores:
        recalculate_group_skins_from_hole(group, 1)

def get_day1_scores():
    """Get all Day 1 scores"""
    load_data_from_sheets()
    return st.session_state.get('day1_scores', {})

def get_day2_scores():
    """Get all Day 2 scores"""
    load_data_from_sheets()
    return st.session_state.get('day2_scores', {})

def calculate_day1_points():
    """Calculate Day 1 points and current standings"""
    day1_scores = get_day1_scores()
    
    # Initialize team totals
    team_totals = {team: {'scramble': 0, 'alt_shot': 0, 'holes_completed': 0, 'scramble_to_par': 0, 'alt_shot_to_par': 0} for team in TEAMS}
    
    # Calculate par total for 18 holes
    total_par = sum(DAY1_COURSE[hole]['par'] for hole in range(1, 19))
    
    # Sum up scores for each team
    for score_data in day1_scores.values():
        team = score_data['team']
        hole = score_data['hole']
        if score_data['scramble'] and score_data['alt_shot']:
            team_totals[team]['scramble'] += score_data['scramble']
            team_totals[team]['alt_shot'] += score_data['alt_shot']
            team_totals[team]['holes_completed'] += 1
            
            # Calculate to par for individual holes
            hole_par = DAY1_COURSE[hole]['par']
            team_totals[team]['scramble_to_par'] += (score_data['scramble'] - hole_par)
            team_totals[team]['alt_shot_to_par'] += (score_data['alt_shot'] - hole_par)
    
    # Calculate current to-par for incomplete rounds
    for team in TEAMS:
        holes_played = team_totals[team]['holes_completed']
        if holes_played > 0 and holes_played < 18:
            # Current to par based on holes played
            par_for_holes_played = sum(DAY1_COURSE[hole]['par'] for hole in range(1, holes_played + 1))
            team_totals[team]['scramble_to_par'] = team_totals[team]['scramble'] - par_for_holes_played
            team_totals[team]['alt_shot_to_par'] = team_totals[team]['alt_shot'] - par_for_holes_played
        elif holes_played == 18:
            # Full round to par
            team_totals[team]['scramble_to_par'] = team_totals[team]['scramble'] - total_par
            team_totals[team]['alt_shot_to_par'] = team_totals[team]['alt_shot'] - total_par
    
    # Only award points to teams that have completed all 18 holes
    complete_teams = [team for team in TEAMS if team_totals[team]['holes_completed'] == 18]
    
    def award_points_with_ties(scores_dict, point_values=[11, 7.5, 4]):
        """Award points handling ties by splitting combined position points"""
        if not scores_dict:
            return {}
        
        # Sort teams by score (lowest first)
        sorted_teams = sorted(scores_dict.items(), key=lambda x: x[1])
        
        points_awarded = {}
        i = 0
        
        while i < len(sorted_teams):
            current_score = sorted_teams[i][1]
            tied_teams = [team for team, score in sorted_teams[i:] if score == current_score]
            
            # Calculate points to split
            if i == 0:  # First place (or tied for first)
                if len(tied_teams) == 1:
                    points_to_split = point_values[0]  # 11
                elif len(tied_teams) == 2:
                    points_to_split = point_values[0] + point_values[1]  # 11 + 7.5 = 18.5
                else:  # All three tied for first
                    points_to_split = sum(point_values)  # 11 + 7.5 + 4 = 22.5
            elif i == 1:  # Second place (or tied for second)
                if len(tied_teams) == 1:
                    points_to_split = point_values[1]  # 7.5
                else:  # Tied for second and third
                    points_to_split = point_values[1] + point_values[2]  # 7.5 + 4 = 11.5
            else:  # Third place
                points_to_split = point_values[2]  # 4
            
            # Award split points to each tied team
            points_per_team = points_to_split / len(tied_teams)
            for team in tied_teams:
                points_awarded[team] = points_per_team
            
            i += len(tied_teams)
        
        return points_awarded
    
    # Only award points if ALL teams have completed Day 1
    if len(complete_teams) == len(TEAMS):
        # Calculate points for scramble competition
        scramble_scores = {team: data['scramble'] for team, data in team_totals.items()}
        scramble_points = award_points_with_ties(scramble_scores)
        
        # Calculate points for alternating shot competition
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
    
    # Day 1 points (only if all teams complete)
    day1_results = calculate_day1_points()
    if day1_results['all_teams_complete']:
        scramble_points = day1_results['scramble_points']
        alt_shot_points = day1_results['alt_shot_points']
        
        # Add Day 1 points
        for team in TEAMS:
            team_points[team] += scramble_points.get(team, 0)
            team_points[team] += alt_shot_points.get(team, 0)
    
    # Day 2 points (skins) - ensure we have fresh data and calculations
    load_data_from_sheets()
    
    # Add Day 2 skins points
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

def login_page():
    """Display login page"""
    st.title("🏌️‍♂️ The Gentlemen's Cup")
    st.markdown("### Enter Access Code")
    
    code = st.text_input("Access Code:", type="password")
    
    if st.button("Enter Tournament"):
        if code == ACCESS_CODE:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid access code. Please try again.")

def day1_scoring_page():
    """Day 1 scoring interface"""
    st.title("📊 Day 1 Scoring")
    st.markdown("**Format**: Scramble + Alternating Shot for each team")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        selected_team = st.selectbox("Select Team:", TEAMS)
        selected_hole = st.selectbox("Select Hole:", HOLES)
    
    with col2:
        # Display hole information
        hole_info = DAY1_COURSE[selected_hole]
        st.markdown(f"### {selected_team} - Hole {selected_hole}")
        st.markdown(f"**Par {hole_info['par']} • {hole_info['yardage']} yards**")
        
        # Get existing scores
        key = f"{selected_team}_{selected_hole}"
        existing_scores = st.session_state.get('day1_scores', {}).get(key, {})
        
        col2a, col2b = st.columns(2)
        
        with col2a:
            scramble_score = st.number_input(
                "Scramble Score:", 
                min_value=1, 
                max_value=15, 
                value=existing_scores.get('scramble', hole_info['par']),
                key=f"scramble_{selected_team}_{selected_hole}"
            )
            scramble_to_par = scramble_score - hole_info['par']
            st.markdown(f"To Par: **{format_score_to_par(scramble_to_par)}**")
        
        with col2b:
            alt_shot_score = st.number_input(
                "Alternating Shot Score:", 
                min_value=1, 
                max_value=15, 
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
    
    # Display current scores for selected team
    st.markdown("### Current Scores")
    day1_scores = get_day1_scores()
    team_scores = [(data['hole'], data['scramble'], data['alt_shot'], 
                   DAY1_COURSE[data['hole']]['par'],
                   data['scramble'] - DAY1_COURSE[data['hole']]['par'],
                   data['alt_shot'] - DAY1_COURSE[data['hole']]['par']) 
                   for data in day1_scores.values() 
                   if data['team'] == selected_team]
    
    if team_scores:
        team_scores.sort(key=lambda x: x[0])  # Sort by hole number
        df = pd.DataFrame(team_scores, columns=['Hole', 'Scramble', 'Alt Shot', 'Par', 'Scramble To Par', 'Alt Shot To Par'])
        df['Scramble To Par'] = df['Scramble To Par'].apply(format_score_to_par)
        df['Alt Shot To Par'] = df['Alt Shot To Par'].apply(format_score_to_par)
        st.dataframe(df, use_container_width=True)
        
        # Show running totals
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
    st.markdown("**Format**: Individual play, lowest score wins the skin (9 holes)")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        selected_group = st.selectbox("Select Group:", GROUPS)
        selected_hole = st.selectbox("Select Hole:", DAY2_HOLES, key="day2_hole")
    
    with col2:
        # Display hole information
        hole_info = DAY2_COURSE[selected_hole]
        points_value = calculate_hole_points_value(selected_group, selected_hole)
        
        st.markdown(f"### Group {selected_group} - Hole {selected_hole}")
        st.markdown(f"**Par {hole_info['par']} • {hole_info['yardage']} yards**")
        if points_value > 1:
            st.markdown(f"**🔥 Worth {points_value} points (carryover from ties!)**")
        else:
            st.markdown(f"**Worth {points_value} point**")
        
        # Score inputs for each team
        scores = {}
        cols = st.columns(3)
        for i, team in enumerate(TEAMS):
            key = f"{selected_group}_{selected_hole}_{team}"
            existing_score = st.session_state.get('day2_scores', {}).get(key, {}).get('score', hole_info['par'])
            
            with cols[i]:
                scores[team] = st.number_input(
                    f"{team} Score:", 
                    min_value=1, 
                    max_value=15, 
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
        
        # Show skin winner for this hole
        skin_key = f"{selected_group}_{selected_hole}"
        if skin_key in st.session_state.get('day2_skins', {}):
            skin_info = st.session_state.day2_skins[skin_key]
            if skin_info['tied']:
                st.warning(f"🤝 Hole {selected_hole}: TIE - Skin carries over to next hole!")
            else:
                st.success(f"🏆 Hole {selected_hole}: **{skin_info['winner']}** wins {skin_info.get('points_value', 1)} point(s)!")
    
    # Display group scorecard
    st.markdown(f"### Group {selected_group} Scorecard")
    display_group_scorecard(selected_group)

def display_group_scorecard(group):
    """Display scorecard for a specific group"""
    scorecard_data = []
    
    for hole in DAY2_HOLES:
        hole_data = {'Hole': hole, 'Par': DAY2_COURSE[hole]['par']}
        
        # Add scores for each team
        for team in TEAMS:
            key = f"{group}_{hole}_{team}"
            score = st.session_state.get('day2_scores', {}).get(key, {}).get('score', '-')
            if score != '-':
                to_par = score - DAY2_COURSE[hole]['par']
                hole_data[team] = f"{score} ({format_score_to_par(to_par)})"
            else:
                hole_data[team] = '-'
        
        # Add skin winner and points
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
    
    # Auto-refresh container
    placeholder = st.empty()
    
    with placeholder.container():
        team_points, day1_results = calculate_leaderboard()
        
        # Overall standings
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
        
        # Sort by total points
        leaderboard_data.sort(key=lambda x: float(x['Total Points']), reverse=True)
        df_leaderboard = pd.DataFrame(leaderboard_data)
        st.dataframe(df_leaderboard, use_container_width=True)
        
        if not day1_results['all_teams_complete']:
            st.info("⏳ Day 1 points will be awarded once all teams complete their rounds")
        
        # Day 1 Current Standings (always show)
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
                    scramble_data.append({
                        'Team': team,
                        'Score': 'No scores',
                        'Holes': '0/18'
                    })
            
            # Sort by to par (best first) for teams with same holes played
            scramble_data.sort(key=lambda x: (
                -int(x['Holes'].split('/')[0]),  # More holes played first
                int(x['Score'].split(' (')[0]) if x['Score'] != 'No scores' else 999  # Lower score first
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
                    alt_shot_data.append({
                        'Team': team,
                        'Score': 'No scores',
                        'Holes': '0/18'
                    })
            
            # Sort by to par (best first) for teams with same holes played
            alt_shot_data.sort(key=lambda x: (
                -int(x['Holes'].split('/')[0]),  # More holes played first
                int(x['Score'].split(' (')[0]) if x['Score'] != 'No scores' else 999  # Lower score first
            ))
            df_alt_shot = pd.DataFrame(alt_shot_data)
            st.dataframe(df_alt_shot, use_container_width=True)
        
        # Day 2 Summary
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
                'Holes Played': f"{skins_played}/9",
                'Young Guns': group_skins['Young Guns'],
                'OGs': group_skins['OGs'],
                'Mids': group_skins['Mids']
            })
        
        df_skins = pd.DataFrame(skins_summary)
        st.dataframe(df_skins, use_container_width=True)
    
    # Auto-refresh controls
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("🔄 Refresh Now"):
            st.rerun()
    
    with col2:
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=False)
    
    with col3:
        st.markdown("*Leaderboard updates automatically when scores are saved*")
    
    # Auto-refresh functionality
    if auto_refresh:
        time.sleep(30)
        st.rerun()

def main():
    """Main application"""
    # Initialize Google Sheets connection
    using_sheets = get_sheets()
    
    if using_sheets:
        st.sidebar.success("✅ Connected to Google Sheets")
    else:
        st.sidebar.error("❌ Google Sheets connection required")
        return
    
    # Check authentication
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        login_page()
        return
    
    # Navigation
    st.sidebar.title("🏌️‍♂️ The Gentlemen's Cup")
    page = st.sidebar.radio(
        "Navigate:",
        ["🏆 Leaderboard", "📊 Day 1 Scoring", "🎯 Day 2 Scoring"]
    )
    
    # Logout button
    if st.sidebar.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.rerun()
    
    # Display selected page
    if page == "🏆 Leaderboard":
        leaderboard_page()
    elif page == "📊 Day 1 Scoring":
        day1_scoring_page()
    elif page == "🎯 Day 2 Scoring":
        day2_scoring_page()

if __name__ == "__main__":
    main()
