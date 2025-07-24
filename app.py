# -*- coding: utf-8 -*-
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
ACCESS_CODE = "gentlemen2024"  # Change this to your preferred code
HOLES = list(range(1, 19))  # 18 holes
GROUPS = list(range(1, 6))  # 5 groups for Day 2

# Google Sheets setup with full integration
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
        
        # Open the spreadsheet (you'll need to create this and share it with your service account)
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
        st.error("Using local session storage as fallback...")
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
            # Add headers
            day1_sheet.update('A1:F1', [['Team', 'Hole', 'Scramble_Score', 'Alt_Shot_Score', 'Timestamp', 'ID']])
            st.success("Created Day1_Scores sheet")
        
        # Create Day 2 scores sheet
        try:
            day2_sheet = spreadsheet.worksheet("Day2_Scores")
            st.success("Found existing Day2_Scores sheet")
        except:
            st.info("Creating Day2_Scores sheet...")
            day2_sheet = spreadsheet.add_worksheet(title="Day2_Scores", rows="500", cols="10")
            # Add headers
            day2_sheet.update('A1:F1', [['Group', 'Hole', 'Team', 'Score', 'Timestamp', 'ID']])
            st.success("Created Day2_Scores sheet")
        
        # Create Day 2 skins sheet
        try:
            skins_sheet = spreadsheet.worksheet("Day2_Skins")
            st.success("Found existing Day2_Skins sheet")
        except:
            st.info("Creating Day2_Skins sheet...")
            skins_sheet = spreadsheet.add_worksheet(title="Day2_Skins", rows="200", cols="10")
            # Add headers
            skins_sheet.update('A1:G1', [['Group', 'Hole', 'Winner', 'Winning_Score', 'Tied', 'Tied_Teams', 'ID']])
            st.success("Created Day2_Skins sheet")
        
        st.success("✅ All sheets setup successfully!")
        return day1_sheet, day2_sheet, skins_sheet
    
    except Exception as e:
        st.error(f"Error setting up sheets structure: {e}")
        st.error("This might be a permissions issue. Check that your service account has Editor access.")
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
            st.session_state.using_sheets = False
            # Initialize local storage as fallback
            if 'day1_scores' not in st.session_state:
                st.session_state.day1_scores = {}
            if 'day2_scores' not in st.session_state:
                st.session_state.day2_scores = {}
            if 'day2_skins' not in st.session_state:
                st.session_state.day2_skins = {}
    
    return st.session_state.get('using_sheets', False)

def save_day1_score(team, hole, scramble_score, alt_shot_score):
    """Save Day 1 scores"""
    timestamp = datetime.now().isoformat()
    score_id = f"{team}_{hole}"
    
    if st.session_state.get('using_sheets', False):
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
            
            # Also update local cache
            st.session_state.day1_scores[score_id] = {
                'team': team,
                'hole': hole,
                'scramble': scramble_score,
                'alt_shot': alt_shot_score,
                'timestamp': timestamp
            }
            
        except Exception as e:
            st.error(f"Error saving to Google Sheets: {e}")
            # Fallback to local storage
            if 'day1_scores' not in st.session_state:
                st.session_state.day1_scores = {}
            st.session_state.day1_scores[score_id] = {
                'team': team,
                'hole': hole,
                'scramble': scramble_score,
                'alt_shot': alt_shot_score,
                'timestamp': timestamp
            }
    else:
        # Local storage fallback
        if 'day1_scores' not in st.session_state:
            st.session_state.day1_scores = {}
        st.session_state.day1_scores[score_id] = {
            'team': team,
            'hole': hole,
            'scramble': scramble_score,
            'alt_shot': alt_shot_score,
            'timestamp': timestamp
        }

def save_day2_score(group, hole, team, score):
    """Save Day 2 scores"""
    timestamp = datetime.now().isoformat()
    score_id = f"{group}_{hole}_{team}"
    
    if st.session_state.get('using_sheets', False):
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
            
            # Also update local cache
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
            # Fallback to local storage
            if 'day2_scores' not in st.session_state:
                st.session_state.day2_scores = {}
            st.session_state.day2_scores[score_id] = {
                'group': group,
                'hole': hole,
                'team': team,
                'score': score,
                'timestamp': timestamp
            }
    else:
        # Local storage fallback
        if 'day2_scores' not in st.session_state:
            st.session_state.day2_scores = {}
        st.session_state.day2_scores[score_id] = {
            'group': group,
            'hole': hole,
            'team': team,
            'score': score,
            'timestamp': timestamp
        }
    
    # Calculate skins for this hole
    calculate_skins(group, hole)

def save_skin_result(group, hole, winner, winning_score, tied, tied_teams=None):
    """Save skin calculation results to Google Sheets"""
    if st.session_state.get('using_sheets', False):
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
            
            # Prepare data
            tied_teams_str = ','.join(tied_teams) if tied_teams else ''
            row_data = [group, hole, winner or '', winning_score, tied, tied_teams_str, skin_id]
            
            if existing_row:
                # Update existing row
                skins_sheet.update(f'A{existing_row}:G{existing_row}', [row_data])
            else:
                # Append new row
                skins_sheet.append_row(row_data)
                
        except Exception as e:
            st.error(f"Error saving skin result to Google Sheets: {e}")

def calculate_skins(group, hole):
    """Calculate skins for a specific hole"""
    if 'day2_skins' not in st.session_state:
        st.session_state.day2_skins = {}
    
    # Get all scores for this hole in this group
    hole_scores = {}
    for team in TEAMS:
        key = f"{group}_{hole}_{team}"
        if key in st.session_state.day2_scores:
            score = st.session_state.day2_scores[key]['score']
            if score and score > 0:  # Valid score
                hole_scores[team] = score
    
    # Determine winner (lowest score wins)
    if len(hole_scores) >= 2:  # Need at least 2 scores to determine winner
        min_score = min(hole_scores.values())
        winners = [team for team, score in hole_scores.items() if score == min_score]
        
        skin_key = f"{group}_{hole}"
        if len(winners) == 1:  # Clear winner
            skin_result = {
                'group': group,
                'hole': hole,
                'winner': winners[0],
                'score': min_score,
                'tied': False
            }
            st.session_state.day2_skins[skin_key] = skin_result
            save_skin_result(group, hole, winners[0], min_score, False)
        else:  # Tie
            skin_result = {
                'group': group,
                'hole': hole,
                'winner': None,
                'score': min_score,
                'tied': True,
                'tied_teams': winners
            }
            st.session_state.day2_skins[skin_key] = skin_result
            save_skin_result(group, hole, None, min_score, True, winners)

def load_data_from_sheets():
    """Load all data from Google Sheets into session state"""
    if not st.session_state.get('using_sheets', False):
        return
    
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
        
        # Load Day 2 skins
        skins_data = st.session_state.skins_sheet.get_all_records()
        st.session_state.day2_skins = {}
        for record in skins_data:
            if record['Group'] and record['Hole']:  # Valid record
                key = f"{record['Group']}_{record['Hole']}"
                tied_teams = record.get('Tied_Teams', '').split(',') if record.get('Tied_Teams') else []
                st.session_state.day2_skins[key] = {
                    'group': record['Group'],
                    'hole': record['Hole'],
                    'winner': record.get('Winner') or None,
                    'score': record.get('Winning_Score'),
                    'tied': record.get('Tied', False),
                    'tied_teams': tied_teams if tied_teams != [''] else []
                }
        
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {e}")

def get_day1_scores():
    """Get all Day 1 scores"""
    # Load fresh data from sheets if available
    if st.session_state.get('using_sheets', False):
        load_data_from_sheets()
    
    return st.session_state.get('day1_scores', {})

def get_day2_scores():
    """Get all Day 2 scores"""
    # Load fresh data from sheets if available
    if st.session_state.get('using_sheets', False):
        load_data_from_sheets()
    
    return st.session_state.get('day2_scores', {})

def calculate_day1_points():
    """Calculate Day 1 points for scramble and alternating shot competitions"""
    day1_scores = get_day1_scores()
    
    # Initialize team totals
    team_totals = {team: {'scramble': 0, 'alt_shot': 0, 'holes_completed': 0} for team in TEAMS}
    
    # Sum up scores for each team
    for score_data in day1_scores.values():
        team = score_data['team']
        if score_data['scramble'] and score_data['alt_shot']:
            team_totals[team]['scramble'] += score_data['scramble']
            team_totals[team]['alt_shot'] += score_data['alt_shot']
            team_totals[team]['holes_completed'] += 1
    
    # Only rank teams that have completed all 18 holes
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
    
    # Calculate points for scramble competition
    scramble_scores = {team: data['scramble'] for team, data in team_totals.items() if team in complete_teams}
    scramble_points = award_points_with_ties(scramble_scores)
    
    # Calculate points for alternating shot competition
    alt_shot_scores = {team: data['alt_shot'] for team, data in team_totals.items() if team in complete_teams}
    alt_shot_points = award_points_with_ties(alt_shot_scores)
    
    return {
        'scramble_points': scramble_points,
        'alt_shot_points': alt_shot_points,
        'team_totals': team_totals,
        'complete_teams': complete_teams
    }

def calculate_leaderboard():
    """Calculate current team standings"""
    team_points = {team: 0 for team in TEAMS}
    
    # Day 1 points
    day1_results = calculate_day1_points()
    scramble_points = day1_results['scramble_points']
    alt_shot_points = day1_results['alt_shot_points']
    
    # Add Day 1 points
    for team in TEAMS:
        team_points[team] += scramble_points.get(team, 0)
        team_points[team] += alt_shot_points.get(team, 0)
    
    # Day 2 points (skins)
    if 'day2_skins' not in st.session_state:
        st.session_state.day2_skins = {}
    
    for skin_data in st.session_state.day2_skins.values():
        if skin_data['winner'] and not skin_data['tied']:
            team_points[skin_data['winner']] += 1
    
    return team_points, day1_results

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
        st.markdown(f"### {selected_team} - Hole {selected_hole}")
        
        # Get existing scores
        key = f"{selected_team}_{selected_hole}"
        existing_scores = st.session_state.day1_scores.get(key, {})
        
        scramble_score = st.number_input(
            "Scramble Score:", 
            min_value=1, 
            max_value=15, 
            value=existing_scores.get('scramble', 4),
            key=f"scramble_{selected_team}_{selected_hole}"
        )
        
        alt_shot_score = st.number_input(
            "Alternating Shot Score:", 
            min_value=1, 
            max_value=15, 
            value=existing_scores.get('alt_shot', 4),
            key=f"alt_shot_{selected_team}_{selected_hole}"
        )
        
        if st.button("Save Scores", key=f"save_{selected_team}_{selected_hole}"):
            save_day1_score(selected_team, selected_hole, scramble_score, alt_shot_score)
            st.success(f"Scores saved for {selected_team} - Hole {selected_hole}")
            time.sleep(1)
            st.rerun()
    
    # Display current scores for selected team
    st.markdown("### Current Scores")
    day1_scores = get_day1_scores()
    team_scores = [(data['hole'], data['scramble'], data['alt_shot']) 
                   for data in day1_scores.values() 
                   if data['team'] == selected_team]
    
    if team_scores:
        team_scores.sort(key=lambda x: x[0])  # Sort by hole number
        df = pd.DataFrame(team_scores, columns=['Hole', 'Scramble', 'Alt Shot'])
        st.dataframe(df, use_container_width=True)
    else:
        st.info(f"No scores entered yet for {selected_team}")

def day2_scoring_page():
    """Day 2 scoring interface"""
    st.title("🎯 Day 2 Scoring - Skins Game")
    st.markdown("**Format**: Individual play, lowest score wins the skin")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        selected_group = st.selectbox("Select Group:", GROUPS)
        selected_hole = st.selectbox("Select Hole:", HOLES, key="day2_hole")
    
    with col2:
        st.markdown(f"### Group {selected_group} - Hole {selected_hole}")
        
        # Score inputs for each team
        scores = {}
        for team in TEAMS:
            key = f"{selected_group}_{selected_hole}_{team}"
            existing_score = st.session_state.day2_scores.get(key, {}).get('score', 4)
            
            scores[team] = st.number_input(
                f"{team} Score:", 
                min_value=1, 
                max_value=15, 
                value=existing_score,
                key=f"score_{selected_group}_{selected_hole}_{team}"
            )
        
        if st.button("Save Scores", key=f"save_day2_{selected_group}_{selected_hole}"):
            for team, score in scores.items():
                save_day2_score(selected_group, selected_hole, team, score)
            st.success(f"Scores saved for Group {selected_group} - Hole {selected_hole}")
            time.sleep(1)
            st.rerun()
        
        # Show skin winner for this hole
        skin_key = f"{selected_group}_{selected_hole}"
        if skin_key in st.session_state.day2_skins:
            skin_info = st.session_state.day2_skins[skin_key]
            if skin_info['tied']:
                st.warning(f"Hole {selected_hole}: TIE - Skin carries over")
            else:
                st.success(f"Hole {selected_hole}: {skin_info['winner']} wins the skin!")
    
    # Display group scorecard
    st.markdown(f"### Group {selected_group} Scorecard")
    display_group_scorecard(selected_group)

def display_group_scorecard(group):
    """Display scorecard for a specific group"""
    scorecard_data = []
    
    for hole in HOLES:
        hole_data = {'Hole': hole}
        for team in TEAMS:
            key = f"{group}_{hole}_{team}"
            score = st.session_state.day2_scores.get(key, {}).get('score', '-')
            hole_data[team] = score
        
        # Add skin winner
        skin_key = f"{group}_{hole}"
        if skin_key in st.session_state.day2_skins:
            skin_info = st.session_state.day2_skins[skin_key]
            if skin_info['tied']:
                hole_data['Skin Winner'] = 'TIE'
            else:
                hole_data['Skin Winner'] = skin_info['winner']
        else:
            hole_data['Skin Winner'] = '-'
        
        scorecard_data.append(hole_data)
    
    if scorecard_data:
        df = pd.DataFrame(scorecard_data)
        st.dataframe(df, use_container_width=True)

def leaderboard_page():
    """Display live leaderboard"""
    st.title("🏆 Live Leaderboard")
    
    team_points, day1_results = calculate_leaderboard()
    
    # Overall standings
    st.markdown("### Overall Team Standings")
    leaderboard_data = []
    for team in TEAMS:
        day1_scramble = day1_results['scramble_points'].get(team, 0)
        day1_alt_shot = day1_results['alt_shot_points'].get(team, 0)
        day1_total = day1_scramble + day1_alt_shot
        
        day2_skins = sum(1 for skin in st.session_state.day2_skins.values() 
                        if skin.get('winner') == team and not skin.get('tied'))
        
        leaderboard_data.append({
            'Team': team,
            'Day 1 Points': f"{day1_total:.1f}",
            'Day 2 Skins': day2_skins,
            'Total Points': f"{team_points[team]:.1f}"
        })
    
    # Sort by total points
    leaderboard_data.sort(key=lambda x: float(x['Total Points']), reverse=True)
    df_leaderboard = pd.DataFrame(leaderboard_data)
    st.dataframe(df_leaderboard, use_container_width=True)
    
    # Day 1 Detailed Results
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Day 1 - Scramble Competition")
        if day1_results['complete_teams']:
            scramble_data = []
            for team in TEAMS:
                if team in day1_results['complete_teams']:
                    total_score = day1_results['team_totals'][team]['scramble']
                    points = day1_results['scramble_points'].get(team, 0)
                    scramble_data.append({
                        'Team': team,
                        'Total Score': total_score,
                        'Points': f"{points:.1f}"
                    })
            
            # Sort by score (lowest first)
            scramble_data.sort(key=lambda x: x['Total Score'])
            df_scramble = pd.DataFrame(scramble_data)
            st.dataframe(df_scramble, use_container_width=True)
        else:
            st.info("No completed rounds yet")
    
    with col2:
        st.markdown("### Day 1 - Alternating Shot Competition")
        if day1_results['complete_teams']:
            alt_shot_data = []
            for team in TEAMS:
                if team in day1_results['complete_teams']:
                    total_score = day1_results['team_totals'][team]['alt_shot']
                    points = day1_results['alt_shot_points'].get(team, 0)
                    alt_shot_data.append({
                        'Team': team,
                        'Total Score': total_score,
                        'Points': f"{points:.1f}"
                    })
            
            # Sort by score (lowest first)
            alt_shot_data.sort(key=lambda x: x['Total Score'])
            df_alt_shot = pd.DataFrame(alt_shot_data)
            st.dataframe(df_alt_shot, use_container_width=True)
        else:
            st.info("No completed rounds yet")
    
    # Day 1 Progress
    st.markdown("### Day 1 Progress")
    progress_data = []
    for team in TEAMS:
        holes_played = day1_results['team_totals'][team]['holes_completed']
        progress_data.append({
            'Team': team,
            'Holes Completed': f"{holes_played}/18",
            'Status': "✅ Complete" if holes_played == 18 else f"🏌️ In Progress ({holes_played}/18)"
        })
    
    df_progress = pd.DataFrame(progress_data)
    st.dataframe(df_progress, use_container_width=True)
    
    # Day 2 Summary
    st.markdown("### Day 2 Skins Summary")
    skins_summary = []
    for group in GROUPS:
        skins_played = sum(1 for key in st.session_state.day2_skins.keys() 
                          if key.startswith(f"{group}_"))
        group_skins = {team: 0 for team in TEAMS}
        
        for skin_data in st.session_state.day2_skins.values():
            if (skin_data['group'] == group and 
                skin_data['winner'] and 
                not skin_data['tied']):
                group_skins[skin_data['winner']] += 1
        
        skins_summary.append({
            'Group': f"Group {group}",
            'Holes Played': f"{skins_played}/18",
            'Young Guns': group_skins['Young Guns'],
            'OGs': group_skins['OGs'],
            'Mids': group_skins['Mids']
        })
    
    df_skins = pd.DataFrame(skins_summary)
    st.dataframe(df_skins, use_container_width=True)
    
    # Auto-refresh every 30 seconds
    if st.button("🔄 Refresh Leaderboard"):
        st.rerun()

def main():
    """Main application"""
    # Initialize Google Sheets connection
    using_sheets = get_sheets()
    
    if using_sheets:
        st.sidebar.success("✅ Connected to Google Sheets")
    else:
        st.sidebar.warning("⚠️ Using local storage (data will reset on restart)")
    
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
