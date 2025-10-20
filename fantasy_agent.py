"""
La Liga Fantasy Football Agent - Enhanced with Web Scraping
============================================================

Now includes real-time player data from futbolfantasy.com:
- Jerarquía (team importance): 1-6 (1=best)
- Playing probability: 0-1 (chance to play next game)
- Form arrows: 1-5 (recent form, 5=best)
- Injury risk: Bajo/Medio/Alto (low/medium/high)
"""

import json
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache
import fantasy_scrapper

# ============================================================================
# DATA MODELS
# ============================================================================
@dataclass
class ScrapedPlayerData:
    """Data scraped from futbolfantasy.com"""
    jerarquia: Optional[int] = None  # 1-6, where 1 is most important
    play_probability: Optional[float] = None  # 0-1
    form_arrow: Optional[int] = None  # 1-5, where 5 is best form
    injury_risk: Optional[str] = None  # "Bajo", "Medio", "Alto"
    
    def get_injury_risk_score(self) -> float:
        """Convert injury risk to 0-1 score (1=safe, 0=high risk)"""
        if not self.injury_risk:
            return 0.7  # Neutral default
        
        risk_map = {
            "Ironman": 1.3,
            "Bajo": 1.0,
            "Medio": 0.5,
            "Alto": 0.1
        }
        return risk_map.get(self.injury_risk, 0.7)
    
    def get_jerarquia_score(self) -> float:
        """Convert jerarquía to 0-1 score (1=best)"""
        if not self.jerarquia:
            return 0.5  # Neutral default
        # Invert: 1 becomes 1.0, 6 becomes 0.0
        return (7 - self.jerarquia) / 6.0
    
    def get_form_score(self) -> float:
        """Convert form arrow to 0-1 score"""
        if not self.form_arrow:
            return 0.5  # Neutral default
        return self.form_arrow / 5.0


@dataclass
class Player:
    """Player model matching La Liga Fantasy API structure"""
    id: str
    nickname: str
    position_id: int  # 1=GK, 2=DF, 3=MF, 4=FW, 5=Coach
    team_id: str
    team_name: str
    
    # Performance
    points: int
    average_points: float
    last_season_points: Optional[int]
    
    # Market
    market_value: int
    
    # Status
    player_status: str
    
    # Weekly stats
    last_3_weeks: List[int] = field(default_factory=list)
    minutes_last_3: List[int] = field(default_factory=list)
    
    # Transfer availability
    is_on_market: bool = False
    owned_by: Optional[str] = None
    buyout_clause: Optional[int] = None
    buyout_locked_until: Optional[datetime] = None
    sale_price: Optional[int] = None
    
    # NEW: Scraped data
    scraped_data: Optional[ScrapedPlayerData] = None
    
    # For slug generation
    _slug: Optional[str] = None
    
    def get_slug(self) -> str:
        """Generate URL slug from nickname"""
        if self._slug:
            return self._slug
        
        mapper = PlayerMapper("name_mapping.json")
        full_name = mapper.get_real_name(self.nickname)

        if full_name is None:
            full_name = self.nickname

        # Simple slug generation - can be enhanced
        slug = full_name.lower()
        slug = slug.replace(' ', '-')
        slug = slug.replace('á', 'a').replace('é', 'e').replace('í', 'i')
        slug = slug.replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
        slug = slug.replace('.', '').replace("'", '')
        

        self._slug = slug
        return slug
    
    def price_in_millions(self) -> float:
        return self.market_value / 1_000_000
    
    def points_per_game(self) -> float:
        return self.average_points
    
    def form_last_3(self) -> float:
        if not self.last_3_weeks:
            return self.average_points
        return sum(self.last_3_weeks) / len(self.last_3_weeks)
    
    def minutes_reliability(self) -> float:
        if not self.minutes_last_3:
            return 0.5
        avg_mins = sum(self.minutes_last_3) / len(self.minutes_last_3)
        return min(avg_mins / 90.0, 1.0)
    
    def is_available(self) -> bool:
        return self.player_status == "ok"
    
    def is_transferable(self, current_time: datetime = None) -> bool:
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        if self.is_on_market:
            return True
        
        if self.buyout_locked_until and self.buyout_locked_until < current_time:
            return True
        
        return False
    
    def get_acquisition_cost(self) -> float:
        if self.is_on_market and self.sale_price:
            return self.sale_price / 1_000_000
        
        if self.buyout_clause:
            return self.buyout_clause / 1_000_000
        
        return float('inf')


@dataclass
class Fixture:
    """Match fixture"""
    match_id: str
    match_date: datetime
    home_team_id: str
    home_team_name: str
    away_team_id: str
    away_team_name: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    match_state: int = 0


@dataclass
class Team:
    """User's fantasy team"""
    team_id: str
    manager_name: str
    players: List[Player]
    team_value: int
    team_points: int
    team_money: Optional[int]
    position: int
    
    def total_value_millions(self) -> float:
        return self.team_value / 1_000_000
    
    def budget_millions(self) -> float:
        if self.team_money is None:
            return 0.0
        return self.team_money / 1_000_000


# ============================================================================
# SCRAPER MANAGER
# ============================================================================

class ScraperManager:
    """Manages web scraping with caching and error handling"""
    
    def __init__(self, cache_dir: str = "./scrapper"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self._failed_scrapes = set()  # Track failed attempts
    
    @lru_cache(maxsize=100)
    def get_player_data(self, player_slug: str) -> Optional[ScrapedPlayerData]:
        """
        Get scraped data for a player with caching.
        Returns None if scraping fails.
        """
        # Skip if already failed in this session
        if player_slug in self._failed_scrapes:
            return None
        
        try:
            scraper = fantasy_scrapper.FantasyScraper(player_slug)
            data = scraper.get_player_info()
            
            # Parse the data
            jerarquia = None
            if data.get('jerarquia'):
                try:
                    jerarquia = int(data['jerarquia'])
                except (ValueError, TypeError):
                    pass
            
            return ScrapedPlayerData(
                jerarquia=jerarquia,
                play_probability=data.get('probabilities'),
                form_arrow=data.get('arrow_numbers'),
                injury_risk=data.get('rs_cuadros_phone')
            )
            
        except Exception as e:
            print(f"⚠️  Failed to scrape {player_slug}: {str(e)}")
            self._failed_scrapes.add(player_slug)
            return None
    
    def enrich_player(self, player: Player) -> Player:
        """
        Enrich a player with scraped data.
        Modifies player in-place and returns it.
        """
        if player.position_id == 5:  # Skip coaches
            return player
        
        slug = player.get_slug()
        scraped = self.get_player_data(slug)
        
        if scraped:
            player.scraped_data = scraped
            print(f"  ✅ Enriched: {player.nickname}")
        
        return player
    
    def enrich_players_batch(self, players: List[Player], 
                            max_to_scrape: int = 1000) -> List[Player]:
        """
        Enrich multiple players with rate limiting.
        Only scrapes top candidates to avoid overwhelming the server.
        """
        print(f"\n🔍 Enriching player data from web (max {max_to_scrape})...")
        
        scraped_count = 0
        for player in players:
            if player.position_id == 5:
                continue
            
            if scraped_count >= max_to_scrape:
                break
            
            self.enrich_player(player)
            scraped_count += 1
        
        print(f"✅ Enriched {scraped_count} players\n")
        return players

class PlayerMapper:
    def __init__(self, mapping_path: str):
        self.mapping_path = Path(mapping_path)
        with open(self.mapping_path, "r", encoding="utf-8") as f:
            self.name_mapping = json.load(f)

    def get_real_name(self, fantasy_name: str):
        """Return the real/full name corresponding to a fantasy name."""
        return self.name_mapping.get(fantasy_name)
    


# ============================================================================
# DATA LOADER
# ============================================================================
class DataLoader:
    """Loads data from local JSON files"""
    
    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.calendar_dir = self.data_dir / "calendar"
        self.equipos_dir = self.data_dir / "equipos"
        self.market_dir = self.data_dir / "market"
        self.players_dir = self.data_dir / "players"
    
    def load_latest_file(self, directory: Path, prefix: str) -> Optional[Dict]:
        if not directory.exists():
            print(f"⚠️  Directory not found: {directory}")
            return None
        
        files = sorted(directory.glob(f"{prefix}*.json"), reverse=True)
        if not files:
            print(f"⚠️  No files found matching: {prefix}")
            return None
        
        latest = files[0]
        print(f"📂 Loading: {latest.name}")
        with open(latest, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_latest_date(self, directory: Path) -> str:
        if not directory.exists():
            return None
        
        files = sorted(directory.glob(f"*.json"), reverse=True)
        if not files:
            return None
        
        latest = files[0].name
        date_str = latest.split("_")[1].split(".")[0]
        return date_str
    
    def load_calendar(self, week: int) -> List[Fixture]:
        file_path = self.calendar_dir / f"week_{week}.json"
        if not file_path.exists():
            print(f"⚠️  Calendar file not found: week_{week}.json")
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        fixtures = []
        for match in data:
            fixtures.append(Fixture(
                match_id=match['id'],
                match_date=datetime.fromisoformat(match['matchDate']),
                home_team_id=match['local']['id'],
                home_team_name=match['local']['name'],
                away_team_id=match['visitor']['id'],
                away_team_name=match['visitor']['name'],
                home_score=match.get('localScore'),
                away_score=match.get('visitorScore'),
                match_state=match.get('matchState', 0)
            ))
        
        return fixtures
    
    def load_my_team(self, team_name: str = None) -> Optional[Team]:
        data = self.load_latest_file(self.equipos_dir, team_name if team_name else "")
        if not data:
            return None
        
        players = []
        for p in data.get('players', []):
            pm = p.get('playerMaster', {})
            
            last_stats = pm.get('lastStats', [])[-3:]
            last_3_points = [s['totalPoints'] for s in last_stats]
            last_3_mins = [s['stats']['mins_played'][0] for s in last_stats]
            
            players.append(Player(
                id=pm['id'],
                nickname=pm['nickname'],
                position_id=pm['positionId'],
                team_id=pm['team']['id'],
                team_name=pm['team']['name'],
                points=pm.get('points', 0),
                average_points=pm.get('averagePoints', 0.0),
                last_season_points=pm.get('lastSeasonPoints'),
                market_value=pm.get('marketValue', 0),
                player_status=pm.get('playerStatus', 'ok'),
                last_3_weeks=last_3_points,
                minutes_last_3=last_3_mins
            ))
        
        return Team(
            team_id=data['id'],
            manager_name=data['manager']['managerName'],
            players=players,
            team_value=data['teamValue'],
            team_points=data['teamPoints'],
            team_money=data.get('teamMoney'),
            position=data['position']
        )
    
    def load_all_players(self) -> List[Player]:
        data = self.load_latest_file(self.players_dir, "players")
        if not data:
            return []
        
        all_players = {}
        for p in data:
            all_players[p['id']] = Player(
                id=p['id'],
                nickname=p['nickname'],
                position_id=int(p['positionId']),
                team_id=p['team']['id'],
                team_name=p['team']['name'],
                points=p.get('points', 0),
                average_points=p.get('averagePoints', 0.0),
                last_season_points=int(p.get('lastSeasonPoints', 0)) if p.get('lastSeasonPoints') else None,
                market_value=int(p.get('marketValue', 0)),
                player_status=p.get('playerStatus', 'ok')
            )
        
        market_data = self.load_latest_file(self.market_dir, "market")
        if market_data:
            for market_entry in market_data:
                pm = market_entry.get('playerMaster', {})
                player_id = pm.get('id')
                
                if player_id in all_players:
                    player = all_players[player_id]
                    if market_entry.get('discr') != "marketPlayerTeam":
                        player.is_on_market = True
                    player.sale_price = market_entry.get('salePrice')
        
        if self.equipos_dir.exists():
            latest_date = self.load_latest_date(self.equipos_dir)
            if latest_date:
                for team_file in self.equipos_dir.glob(f"*{latest_date}.json"):
                    with open(team_file, 'r', encoding='utf-8') as f:
                        team_data = json.load(f)
                    
                    manager_name = team_data['manager']['managerName']
                    
                    for p in team_data.get('players', []):
                        pm = p.get('playerMaster', {})
                        player_id = pm.get('id')
                        
                        if player_id in all_players:
                            player = all_players[player_id]
                            player.owned_by = manager_name
                            player.buyout_clause = p.get('buyoutClause')
                            
                            lock_time_str = p.get('buyoutClauseLockedEndTime')
                            if lock_time_str:
                                try:
                                    player.buyout_locked_until = datetime.fromisoformat(lock_time_str)
                                except:
                                    pass
        
        return list(all_players.values())

    def load_current_week(self) -> int:

        file_path = list(self.data_dir.glob("current_week.json"))[0]
        if not file_path:
            raise FileNotFoundError("No file matching current_week.json found in data_dir")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return data['weekNumber']
# ============================================================================
# FIXTURE ANALYZER
# ============================================================================

class FixtureAnalyzer:
    """Analyzes upcoming fixtures for difficulty"""
    
    def __init__(self, fixtures: List[Fixture], historical_weeks: List[int] = None):
        self.fixtures = fixtures
        self.team_strengths = self._calculate_team_strengths(historical_weeks or [])
    
    def _calculate_team_strengths(self, past_weeks: List[int]) -> Dict[str, Dict]:
        # TODO calculate strength based on last x weeks results
        strengths = {
            "Real Madrid": {"attack": 5.0, "defense": 4.5},
            "FC Barcelona": {"attack": 4.8, "defense": 4.2},
            "Atlético de Madrid": {"attack": 4.0, "defense": 4.8},
            "Athletic Club": {"attack": 4.2, "defense": 4.0},
            "Real Sociedad": {"attack": 4.0, "defense": 3.8},
            "Villarreal CF": {"attack": 3.8, "defense": 3.8},
            "Real Betis": {"attack": 3.8, "defense": 3.5},
            "Valencia CF": {"attack": 3.5, "defense": 3.5},
            "Sevilla FC": {"attack": 3.5, "defense": 3.8},
            "Girona FC": {"attack": 3.5, "defense": 3.3},
            "RC Celta": {"attack": 3.5, "defense": 3.0},
            "RCD Mallorca": {"attack": 3.3, "defense": 3.5},
            "Rayo Vallecano": {"attack": 3.3, "defense": 3.2},
            "C.A. Osasuna": {"attack": 3.2, "defense": 3.5},
            "Getafe CF": {"attack": 2.8, "defense": 3.8},
            "UD Las Palmas": {"attack": 3.0, "defense": 2.8},
            "Deportivo Alavés": {"attack": 2.8, "defense": 3.0},
            "RCD Espanyol": {"attack": 2.8, "defense": 3.0},
            "CD Leganés": {"attack": 2.5, "defense": 3.2},
            "Real Valladolid": {"attack": 2.5, "defense": 2.8},
        }
        return strengths
    
    def get_fixture_difficulty(self, team_id: str, team_name: str, 
                               next_n_weeks: int = 3) -> List[Dict]:
        team_fixtures = []
        
        for fixture in self.fixtures:
            if fixture.home_team_id == team_id:
                opponent = fixture.away_team_name
                is_home = True
            elif fixture.away_team_id == team_id:
                opponent = fixture.home_team_name
                is_home = False
            else:
                continue
            
            opp_strength = self.team_strengths.get(opponent, {"attack": 3.5, "defense": 3.5})
            avg_opponent_strength = (opp_strength['attack'] + opp_strength['defense']) / 2
            difficulty = 6 - avg_opponent_strength
            
            if is_home:
                difficulty += 0.5
            
            difficulty = max(1, min(5, difficulty))
            
            team_fixtures.append({
                'opponent': opponent,
                'is_home': is_home,
                'difficulty': difficulty,
                'date': fixture.match_date
            })
            
            if len(team_fixtures) >= next_n_weeks:
                break
        
        return team_fixtures
    
    def calculate_fixture_score(self, player: Player, next_weeks: int = 3) -> float:
        fixtures = self.get_fixture_difficulty(player.team_id, player.team_name, next_weeks)
        
        if not fixtures:
            return 5.0
        
        weights = [1.0, 0.8, 0.6][:len(fixtures)]
        scores = [f['difficulty'] * 2 for f in fixtures]
        
        weighted_avg = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
        return weighted_avg

# ============================================================================
# ENHANCED PLAYER EVALUATOR
# ============================================================================

class EnhancedPlayerEvaluator:
    """
    Enhanced evaluator that incorporates scraped data.
    
    Scoring weights:
    - Form (25%) - Recent performance + form arrows
    - Fixtures (20%) - Upcoming difficulty
    - Season Performance (15%) - Consistency
    - Value (10%) - Points per million
    - Jerarquía (15%) - Team importance
    - Play Probability (10%) - Chance to play
    - Injury Risk (5%) - Safety factor
    """
    
    def __init__(self, fixture_analyzer: FixtureAnalyzer):
        self.fixture_analyzer = fixture_analyzer
    
    def evaluate_player(self, player: Player) -> Dict:
        """Enhanced evaluation with scraped data"""
        
        # 1. Form (25%) - Combine stats + scraped arrows
        form_raw = player.form_last_3()
        form_score = min(form_raw / 10.0, 1.0) * 15  # Base form: 15%
        
        # Add form arrows bonus (10%)
        if player.scraped_data and player.scraped_data.form_arrow:
            arrow_score = player.scraped_data.get_form_score() * 10
            form_score += arrow_score
        else:
            form_score += 5  # Neutral if no data
        
        # 2. Fixtures (20%)
        fixture_raw = self.fixture_analyzer.calculate_fixture_score(player)
        fixture_score = (fixture_raw / 10.0) * 20
        
        # 3. Season Performance (15%)
        ppg_raw = player.points_per_game()
        ppg_score = min(ppg_raw / 10.0, 1.0) * 15
        
        # 4. Value (10%)
        value_raw = ppg_raw / max(player.price_in_millions(), 0.1)
        value_score = min(value_raw / 2.0, 1.0) * 10
        
        # 5. Jerarquía (15%)
        if player.scraped_data and player.scraped_data.jerarquia:
            jerarquia_score = player.scraped_data.get_jerarquia_score() * 15
        else:
            jerarquia_score = 7.5  # Neutral default
        
        # 6. Play Probability (10%)
        if player.scraped_data and player.scraped_data.play_probability:
            probability_score = player.scraped_data.play_probability * 10
        else:
            probability_score = 7.0  # Assume likely to play
        
        # 7. Injury Risk (5%)
        if player.scraped_data and player.scraped_data.injury_risk:
            injury_score = player.scraped_data.get_injury_risk_score() * 5
        else:
            injury_score = 3.5  # Neutral
        
        # Sum up
        total_score = (form_score + fixture_score + ppg_score + value_score + 
                      jerarquia_score + probability_score + injury_score)
        
        # Existing penalties
        if player.minutes_reliability() < 0.6:
            total_score *= 0.7
        
        if player.player_status != "ok":
            total_score *= 0.5
        
        # Position multiplier
        #position_mult = {1: 0.85, 2: 1.05, 3: 1.20, 4: 1.10, 5: 0.0}
        #total_score *= position_mult.get(player.position_id, 1.0)
        
        return {
            'total_score': total_score,
            'form': form_raw,
            'form_score': form_score,
            'fixtures': fixture_raw,
            'fixture_score': fixture_score,
            'ppg': ppg_raw,
            'ppg_score': ppg_score,
            'value': value_raw,
            'value_score': value_score,
            'jerarquia_score': jerarquia_score,
            'probability_score': probability_score,
            'injury_score': injury_score,
            'minutes_reliability': player.minutes_reliability(),
            'is_available': player.is_available(),
            'scraped_jerarquia': player.scraped_data.jerarquia if player.scraped_data else None,
            'scraped_probability': player.scraped_data.play_probability if player.scraped_data else None,
            'scraped_form_arrow': player.scraped_data.form_arrow if player.scraped_data else None,
            'scraped_injury_risk': player.scraped_data.injury_risk if player.scraped_data else None,
        }
    
    def find_best_transfers(self, current_team: Team, available_players: List[Player],
                           budget: float, max_suggestions: int = 5) -> List[Dict]:
        """Find best transfers with enhanced scoring"""
        
        current_time = datetime.now(timezone.utc)
        
        # Evaluate current team
        current_scores = {}
        for player in current_team.players:
            if player.position_id == 5:
                continue
            current_scores[player.id] = self.evaluate_player(player)
        
        # Find potential upgrades
        transfer_suggestions = []
        
        for current_player in current_team.players:
            if current_player.position_id == 5:
                continue
            
            current_eval = current_scores[current_player.id]
            
            # Find better players
            candidates = [p for p in available_players 
                         #if p.position_id == current_player.position_id
                         if p.id not in [cp.id for cp in current_team.players]
                         and p.is_available()
                         and p.is_transferable(current_time)]
            
            for candidate in candidates:
                acquisition_cost = candidate.get_acquisition_cost()
                net_cost = acquisition_cost - current_player.price_in_millions()
                
                if net_cost > budget:
                    continue
                
                candidate_eval = self.evaluate_player(candidate)
                score_improvement = candidate_eval['total_score'] - current_eval['total_score']
                
                # Only suggest if significant improvement
                if score_improvement > 3:  # Lower threshold due to better scoring
                    if candidate.is_on_market:
                        acq_type = "Market"
                    elif candidate.buyout_locked_until and candidate.buyout_locked_until < current_time:
                        acq_type = f"Buyout (from {candidate.owned_by})"
                    else:
                        acq_type = "Unknown"
                    
                    transfer_suggestions.append({
                        'player_out': current_player,
                        'player_out_score': current_eval['total_score'],
                        'player_out_eval': current_eval,
                        'player_in': candidate,
                        'player_in_score': candidate_eval['total_score'],
                        'player_in_eval': candidate_eval,
                        'improvement': score_improvement,
                        'acquisition_cost': acquisition_cost,
                        'net_cost': net_cost,
                        'value_ratio': score_improvement / max(abs(net_cost), 0.1),
                        'acquisition_type': acq_type
                    })
        
        # Sort by value ratio
        transfer_suggestions.sort(key=lambda x: x['value_ratio'], reverse=True)
        
        return transfer_suggestions[:max_suggestions]


# ============================================================================
# ENHANCED MAIN AGENT
# ============================================================================

class EnhancedFantasyAgent:
    """Enhanced agent with web scraping capabilities"""
    
    def __init__(self, data_dir: str = "."):
        self.loader = DataLoader(data_dir)
        self.scraper_manager = ScraperManager()
        self.current_week = -1
        self.my_team = None
        self.all_players = []
        self.fixture_analyzer = None
        self.evaluator = None
    
    def initialize(self, team_name: str = None, enrich_current_team: bool = True):
        """Load data and optionally enrich with web scraping"""
        print("🤖 Initializing Enhanced Fantasy Agent...")
        print("="*60)
        
        self.current_week = self.loader.load_current_week()

        self.my_team = self.loader.load_my_team(team_name)
        if not self.my_team:
            print("❌ Could not load your team!")
            return False
        
        print(f"✅ Loaded team: {self.my_team.manager_name}")
        print(f"   Players: {len(self.my_team.players)}")
        print(f"   Team Value: €{self.my_team.total_value_millions():.1f}M")
        print(f"   Budget: €{self.my_team.budget_millions():.1f}M")
        
        # Enrich current team with scraped data
        if enrich_current_team:
            print(f"\n🔍 Enriching your team with latest web data...")
            for player in self.my_team.players:
                self.scraper_manager.enrich_player(player)
        
        self.all_players = self.loader.load_all_players()
        print(f"\n✅ Loaded {len(self.all_players)} total players")
        
        fixtures = self.loader.load_calendar(self.current_week)
        self.fixture_analyzer = FixtureAnalyzer(fixtures)
        self.evaluator = EnhancedPlayerEvaluator(self.fixture_analyzer)
        
        print("✅ Agent ready!")
        print("="*60)
        return True
    
    def analyze_current_team(self):
        """Enhanced team analysis with scraped data"""
        if not self.my_team:
            print("❌ No team loaded")
            return
        
        print("\n📊 ENHANCED TEAM ANALYSIS")
        print("="*60)
        
        for player in self.my_team.players:
            if player.position_id == 5:
                continue
            
            eval_result = self.evaluator.evaluate_player(player)
            pos_names = {1: "GK", 2: "DF", 3: "MF", 4: "FW"}
            
            print(f"\n{player.nickname} ({pos_names.get(player.position_id, '?')})")
            print(f"  Team: {player.team_name}")
            print(f"  Overall Score: {eval_result['total_score']:.1f}/100")
            print(f"  Form (L3): {eval_result['form']:.1f} pts/game")
            print(f"  Season: {eval_result['ppg']:.1f} pts/game")
            print(f"  Fixtures: {eval_result['fixtures']:.1f}/10")
            print(f"  Price: €{player.price_in_millions():.1f}M")
            print(f"  Status: {player.player_status.upper()}")
            
            # Show scraped data if available
            if player.scraped_data:
                print(f"  🌐 Web Data:")
                if eval_result['scraped_jerarquia']:
                    print(f"     • Jerarquía: {eval_result['scraped_jerarquia']}/6 (lower=better)")
                if eval_result['scraped_probability']:
                    print(f"     • Play Probability: {eval_result['scraped_probability']*100:.0f}%")
                if eval_result['scraped_form_arrow']:
                    print(f"     • Form Arrow: {eval_result['scraped_form_arrow']}/5 ({'🔥' * eval_result['scraped_form_arrow']})")
                if eval_result['scraped_injury_risk']:
                    risk_emoji = {"Bajo": "✅", "Medio": "⚠️", "Alto": "🚨"}
                    emoji = risk_emoji.get(eval_result['scraped_injury_risk'], "❓")
                    print(f"     • Injury Risk: {eval_result['scraped_injury_risk']} {emoji}")
    
    def suggest_transfers(self, max_suggestions: int = 5, enrich_candidates: bool = True):
        """Enhanced transfer suggestions with web scraping"""
        if not self.my_team or not self.evaluator:
            print("❌ Agent not initialized")
            return
        
        budget = self.my_team.budget_millions()
        
        print(f"\n💡 ENHANCED TRANSFER SUGGESTIONS (Budget: €{budget:.1f}M)")
        print("="*60)
        
        # Count transferable players
        transferable = [p for p in self.all_players if p.is_transferable()]
        on_market = [p for p in transferable if p.is_on_market]
        
        print(f"📊 Transfer Market Stats:")
        print(f"   - Players on market: {len(on_market)}")
        print(f"   - Total transferable: {len(transferable)}")
        
        # Pre-filter candidates by position and budget
        print(f"\n🔍 Filtering candidates...")
        position_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for player in self.my_team.players:
            if player.position_id != 5:
                position_counts[player.position_id] += 1
        
        # Get candidates per position
        candidates_by_position = {1: [], 2: [], 3: [], 4: []}
        for player in transferable:
            if player.position_id in candidates_by_position:
                # Quick budget filter
                acq_cost = player.get_acquisition_cost()
                #if acq_cost < budget + 20:  # Allow some flexibility
                candidates_by_position[player.position_id].append(player)
        
        # Sort each position by average points and take top candidates
        for pos in candidates_by_position:
            candidates_by_position[pos].sort(key=lambda p: p.average_points, reverse=True)
            candidates_by_position[pos] = candidates_by_position[pos][:15]  # Top 15 per position
        
        # Flatten and enrich
        top_candidates = []
        for pos_candidates in candidates_by_position.values():
            top_candidates.extend(pos_candidates)
        
        print(f"   - Filtered to {len(top_candidates)} top candidates")
        
        if enrich_candidates and top_candidates:
            self.scraper_manager.enrich_players_batch(top_candidates)
        
        # Find best transfers
        suggestions = self.evaluator.find_best_transfers(
            self.my_team,
            self.all_players,
            budget,
            max_suggestions
        )
        
        if not suggestions:
            print("\n✅ No beneficial transfers found. Team looks solid!")
            return
        
        # Display suggestions with detailed info
        for i, transfer in enumerate(suggestions, 1):
            print(f"\n{'='*60}")
            print(f"#{i} - IMPROVEMENT: +{transfer['improvement']:.1f} points")
            print(f"{'='*60}")
            
            # Player OUT
            print(f"\n❌ OUT: {transfer['player_out'].nickname} ({transfer['player_out'].team_name})")
            print(f"   Score: {transfer['player_out_score']:.1f}/100")
            print(f"   Sell for: €{transfer['player_out'].price_in_millions():.1f}M")
            
            out_eval = transfer['player_out_eval']
            if out_eval.get('scraped_jerarquia'):
                print(f"   Jerarquía: {out_eval['scraped_jerarquia']}/6")
            if out_eval.get('scraped_probability'):
                print(f"   Play Prob: {out_eval['scraped_probability']*100:.0f}%")
            
            # Player IN
            print(f"\n✅ IN:  {transfer['player_in'].nickname} ({transfer['player_in'].team_name})")
            print(f"   Score: {transfer['player_in_score']:.1f}/100")
            print(f"   Buy for: €{transfer['acquisition_cost']:.1f}M")
            print(f"   Source: {transfer['acquisition_type']}")
            
            in_eval = transfer['player_in_eval']
            if in_eval.get('scraped_jerarquia'):
                print(f"   Jerarquía: {in_eval['scraped_jerarquia']}/6 {'⭐' if in_eval['scraped_jerarquia'] <= 2 else ''}")
            if in_eval.get('scraped_probability'):
                prob = in_eval['scraped_probability']
                print(f"   Play Prob: {prob*100:.0f}% {'✅' if prob > 0.7 else '⚠️' if prob > 0.4 else '🚨'}")
            if in_eval.get('scraped_form_arrow'):
                arrows = in_eval['scraped_form_arrow']
                print(f"   Form: {'🔥' * arrows} ({arrows}/5)")
            if in_eval.get('scraped_injury_risk'):
                risk = in_eval['scraped_injury_risk']
                risk_emoji = {"Bajo": "✅", "Medio": "⚠️", "Alto": "🚨"}
                print(f"   Injury Risk: {risk} {risk_emoji.get(risk, '❓')}")
            
            # Financial summary
            print(f"\n💰 FINANCIALS:")
            print(f"   Net Cost: €{transfer['net_cost']:.1f}M")
            print(f"   Value Ratio: {transfer['value_ratio']:.2f} (pts per €M)")
            print(f"   Remaining Budget: €{budget - transfer['net_cost']:.1f}M")
    
    def show_upcoming_fixtures(self):
        """Show fixtures for current team's players"""
        if not self.my_team or not self.fixture_analyzer:
            print("❌ Agent not initialized")
            return
        
        print(f"\n📅 UPCOMING FIXTURES (Next 3 weeks)")
        print("="*60)
        
        teams_shown = set()
        for player in self.my_team.players:
            if player.team_id in teams_shown or player.position_id == 5:
                continue
            
            fixtures = self.fixture_analyzer.get_fixture_difficulty(
                player.team_id, player.team_name, 3
            )
            
            if fixtures:
                print(f"\n{player.team_name}:")
                for fix in fixtures:
                    home = "🏠" if fix['is_home'] else "✈️ "
                    difficulty_stars = "★" * int(fix['difficulty'])
                    print(f"  {home} vs {fix['opponent']} - {difficulty_stars} ({fix['difficulty']:.1f}/5)")
            
            teams_shown.add(player.team_id)
    
    def deep_analyze_player(self, player_name: str):
        """Deep analysis of a specific player with web scraping"""
        # Find player
        player = None
        for p in self.all_players:
            if player_name.lower() in p.nickname.lower():
                player = p
                break
        
        if not player:
            print(f"❌ Player '{player_name}' not found")
            return
        
        print(f"\n🔍 DEEP ANALYSIS: {player.nickname}")
        print("="*60)
        
        # Enrich with web data
        self.scraper_manager.enrich_player(player)
        
        # Evaluate
        eval_result = self.evaluator.evaluate_player(player)
        
        print(f"\n📊 Overall Score: {eval_result['total_score']:.1f}/100")
        print(f"\n📈 Performance:")
        print(f"   Season Average: {eval_result['ppg']:.1f} pts/game")
        print(f"   Last 3 Games: {eval_result['form']:.1f} pts/game")
        print(f"   Minutes Reliability: {eval_result['minutes_reliability']*100:.0f}%")
        
        print(f"\n💰 Market:")
        print(f"   Price: €{player.price_in_millions():.1f}M")
        print(f"   Value: {eval_result['value']:.2f} pts/€M")
        print(f"   Status: {player.player_status.upper()}")
        
        if player.is_on_market:
            print(f"   📍 Available on Market!")
        elif player.owned_by:
            print(f"   👤 Owned by: {player.owned_by}")
            if player.buyout_clause:
                print(f"   💵 Buyout: €{player.buyout_clause/1_000_000:.1f}M")
        
        print(f"\n🌐 Web Intelligence:")
        if player.scraped_data:
            if player.scraped_data.jerarquia:
                importance = "Key Player" if player.scraped_data.jerarquia <= 2 else "Rotation Risk" if player.scraped_data.jerarquia >= 5 else "Regular"
                print(f"   Jerarquía: {player.scraped_data.jerarquia}/6 ({importance})")
            
            if player.scraped_data.play_probability:
                prob = player.scraped_data.play_probability
                status = "Likely Starter" if prob > 0.7 else "Doubt" if prob > 0.4 else "Unlikely"
                print(f"   Play Probability: {prob*100:.0f}% ({status})")
            
            if player.scraped_data.form_arrow:
                arrows = player.scraped_data.form_arrow
                form_text = "Excellent" if arrows >= 4 else "Good" if arrows >= 3 else "Poor"
                print(f"   Recent Form: {'🔥' * arrows} ({form_text})")
            
            if player.scraped_data.injury_risk:
                risk_emoji = {"Bajo": "✅", "Medio": "⚠️", "Alto": "🚨"}
                print(f"   Injury Risk: {player.scraped_data.injury_risk} {risk_emoji.get(player.scraped_data.injury_risk, '❓')}")
        else:
            print("   ⚠️  Could not fetch web data")
        
        print(f"\n📅 Upcoming Fixtures:")
        fixtures = self.fixture_analyzer.get_fixture_difficulty(player.team_id, player.team_name, 5)
        for fix in fixtures[:5]:
            home = "🏠" if fix['is_home'] else "✈️ "
            stars = "★" * int(fix['difficulty'])
            print(f"   {home} vs {fix['opponent']} - {stars}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    # Initialize enhanced agent
    agent = EnhancedFantasyAgent(data_dir=".")
    
    # Load and enrich your team
    if agent.initialize(team_name="svendsinio", enrich_current_team=True):
        
        # Analyze current team with web data
        agent.analyze_current_team()
        
        # Show upcoming fixtures
        agent.show_upcoming_fixtures()
        
        # Get enhanced transfer suggestions with web scraping
        agent.suggest_transfers(max_suggestions=5, enrich_candidates=True)
        
        # Optional: Deep dive into a specific player
        # agent.deep_analyze_player("Lamine Yamal")
        
        print("\n" + "="*60)
        print("✅ Enhanced analysis complete!")