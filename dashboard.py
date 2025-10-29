"""
Fantasy Football Agent - Streamlit Dashboard
Live analysis and transfer recommendations for your fantasy team
"""

import streamlit as st
import pandas as pd
from typing import Dict, List, Tuple, Optional

from fantasy_agent import FantasyAgent


# ============================================================================
# CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Fantasy Agent",
    "layout": "wide",
    "initial_sidebar_state": "collapsed"
}

CACHE_TTL = 3600  # 1 hour in seconds

TEAM_COLUMNS_ORDER = [
    "Name", "Pos", "Team", "Score", "Play Prob", "Form Arrow",
    "Fixtures", "Form (L3)", "Season", "Price", "Status", 
    "Jerarquía", "Injury Risk"
]


# ============================================================================
# DATA LOADING
# ============================================================================

@st.cache_data(ttl=CACHE_TTL)
def load_agent_data(
    team_name: str = "svendsinio"
) -> Tuple[Optional[Dict], List[Dict], Dict[str, List[str]], List[Dict]]:
    """
    Initialize agent and load all fantasy data.
    
    Returns:
        Tuple of (team_summary, team_data, fixtures_data, transfer_data)
    """
    try:
        agent = FantasyAgent(data_dir=".")
        
        team_summary = agent.initialize(
            team_name=team_name,
            enrich_current_team=True
        )
        
        if not team_summary:
            return None, [], {}, []
        
        team_data = agent.analyze_current_team()
        fixtures_data = agent.show_upcoming_fixtures()
        transfer_data = agent.suggest_transfers(
            max_suggestions=5,
            enrich_candidates=True
        )
        
        return team_summary, team_data, fixtures_data, transfer_data
        
    except Exception as e:
        st.error(f"Error initializing agent: {e}")
        return None, [], {}, []


def refresh_data():
    """Clear cache and force data refresh"""
    st.cache_data.clear()
    st.rerun()


# ============================================================================
# UI COMPONENTS
# ============================================================================

def render_header(team_summary: Dict):
    """Render page header with team metrics"""
    st.title("🤖 Fantasy Agent Dashboard")
    st.header(f"Team: {team_summary.get('name', 'N/A')}")
    
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        st.metric("Team Value", team_summary.get('value', '€0M'))
    
    with col2:
        st.metric("Budget", team_summary.get('budget', '€0M'))
    
    with col3:
        st.button(
            "🔄 Refresh Data",
            on_click=refresh_data,
            help="Clear cache and reload all data",
            use_container_width=True
        )
    
    st.divider()


def render_team_analysis(team_data: List[Dict]):
    """Render team analysis table"""
    st.subheader("📊 Team Analysis")
    
    if not team_data:
        st.warning("No team data available")
        return
    
    df = pd.DataFrame(team_data)
    
    # Reorder columns
    display_columns = [
        col for col in TEAM_COLUMNS_ORDER 
        if col in df.columns
    ]
    df = df[display_columns]
    
    # Sort by score
    df = df.sort_values('Score', ascending=False)
    
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=600
    )
    
    # Summary stats
    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        avg_score = df['Score'].mean()
        st.metric("Avg Score", f"{avg_score:.1f}")
    
    with col2:
        total_value = df['Price'].str.replace('€', '').str.replace('M', '').astype(float).sum()
        st.metric("Total Value", f"€{total_value:.1f}M")
    
    with col3:
        available = (df['Status'] == 'OK').sum()
        st.metric("Available", f"{available}/{len(df)}")
    
    with col4:
        avg_form = df['Form (L3)'].mean()
        st.metric("Avg Form", f"{avg_form:.1f}")


def render_fixtures(fixtures_data: Dict[str, List[str]]):
    """Render upcoming fixtures"""
    st.subheader("📅 Upcoming Fixtures (Next 3 Weeks)")
    
    if not fixtures_data:
        st.warning("No fixture data available")
        return
    
    # Create two-column layout
    col1, col2 = st.columns(2)
    columns = [col1, col2]
    
    for idx, (team, fixtures) in enumerate(fixtures_data.items()):
        with columns[idx % 2]:
            with st.container(border=True):
                st.markdown(f"**{team}**")
                
                for fixture in fixtures:
                    st.text(fixture)


def render_player_comparison(player_out: Dict, player_in: Dict):
    """Render side-by-side player comparison"""
    col1, col2 = st.columns(2)
    
    # Player OUT
    with col1:
        with st.container(border=True):
            st.markdown(
                f"**❌ OUT: {player_out['name']} ({player_out['team']})**"
            )
            st.text(f"Score: {player_out['score']}")
            st.text(f"Sell for: {player_out['price']}")
            st.text(f"Jerarquía: {player_out['jerarquia']}")
            st.text(f"Play Prob: {player_out['prob']}")
    
    # Player IN
    with col2:
        with st.container(border=True):
            st.markdown(
                f"**✅ IN: {player_in['name']} ({player_in['team']})**"
            )
            st.text(f"Score: {player_in['score']}")
            st.text(f"Buy for: {player_in['price']}")
            st.text(f"Source: {player_in['source']}")
            st.text(f"Jerarquía: {player_in['jerarquia']}")
            st.text(f"Play Prob: {player_in['prob']}")
            st.text(f"Form: {player_in['form']}")
            st.text(f"Injury Risk: {player_in['risk']}")


def render_transfer_financials(
    idx: int,
    net_cost: str,
    value_ratio: str,
    remaining_budget: str
):
    """Render transfer financial metrics"""
    st.markdown(f"**💰 Financial Details**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Net Cost",
            net_cost,
            help="Negative value means you make money"
        )
    
    with col2:
        st.metric(
            "Value Ratio",
            f"{value_ratio} pts/€M",
            help="Points improvement per million spent"
        )
    
    with col3:
        st.metric(
            "Remaining Budget",
            remaining_budget,
            help="Budget after this transfer"
        )


def render_transfer_suggestions(transfer_data: List[Dict]):
    """Render transfer suggestions"""
    st.subheader(f"💡 Transfer Suggestions (Top {len(transfer_data)})")
    
    if not transfer_data:
        st.success("✅ No beneficial transfers found. Team looks solid!")
        return
    
    for idx, transfer in enumerate(transfer_data, 1):
        st.markdown(
            f"### #{idx} - Improvement: {transfer['improvement']} points"
        )
        
        # Player comparison
        player_out = {
            'name': transfer['out_name'],
            'team': transfer['out_team'],
            'score': transfer['out_score'],
            'price': transfer['out_price'],
            'jerarquia': transfer['out_jerarquia'],
            'prob': transfer['out_prob']
        }
        
        player_in = {
            'name': transfer['in_name'],
            'team': transfer['in_team'],
            'score': transfer['in_score'],
            'price': transfer['in_price'],
            'source': transfer['in_source'],
            'jerarquia': transfer['in_jerarquia'],
            'prob': transfer['in_prob'],
            'form': transfer['in_form'],
            'risk': transfer['in_risk']
        }
        
        render_player_comparison(player_out, player_in)
        
        # Financial details
        render_transfer_financials(
            idx,
            transfer['net_cost'],
            transfer['value_ratio'],
            transfer['remaining_budget']
        )
        
        st.divider()


# ============================================================================
# ERROR HANDLING
# ============================================================================

def handle_missing_file_error(filename: str):
    """Display error message for missing files"""
    st.error(f"❌ Missing file: {filename}")
    st.info(
        f"Please ensure '{filename}' is in the same directory as this dashboard."
    )
    
    if filename == "name_mapping.json":
        st.info("You can create an empty mapping file with: {}")
        
        if st.button("Create empty name_mapping.json"):
            import json
            with open("name_mapping.json", "w") as f:
                json.dump({}, f)
            st.success("✅ Created empty name_mapping.json. Refresh the page.")


def handle_data_load_error():
    """Display error message for data loading failures"""
    st.error("❌ Failed to load team data")
    st.info(
        "Make sure you've run `download_pipeline.py` to fetch the latest data."
    )
    st.info(
        "Check that /equipos, /players, and /market directories contain recent JSON files."
    )


# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Main application entry point"""
    # Configure page
    st.set_page_config(**PAGE_CONFIG)
    
    # Load data
    try:
        team_summary, team_data, fixtures_data, transfer_data = load_agent_data()
    except FileNotFoundError as e:
        handle_missing_file_error(e.filename)
        st.stop()     
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")
        st.info("Please ensure all required files are present and valid.")
        st.stop()
    
    # Check if data loaded successfully
    if team_summary is None:
        handle_data_load_error()
        st.stop()
    
    # Render UI
    render_header(team_summary)

    tab1, tab2, tab3 = st.tabs([
        "📊 Team Analysis",
        "📅 Fixtures",
        "💡 Transfers"
    ])
    
    with tab1: render_team_analysis(team_data)
    
    with tab2: render_fixtures(fixtures_data)
    
    with tab3: render_transfer_suggestions(transfer_data)


if __name__ == "__main__":
    main()