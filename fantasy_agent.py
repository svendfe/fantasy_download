"""
Enhanced Fantasy Football Agent
Analyzes team performance, suggests transfers, and provides fixture analysis
"""

import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

import fantasy_scrapper
from download_pipeline import main as data_downloader


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ScrapedPlayerData:
    """Web-scraped player data from fantasy sources"""
    jerarquia: Optional[int] = None
    play_probability: Optional[float] = None
    form_arrow: Optional[int] = None
    injury_risk: Optional[str] = None
    
    INJURY_RISK_SCORES = {
        "Ironman": 1.3,
        "Bajo": 1.0,
        "Medio": 0.5,
        "Alto": 0.1
    }
    
    def get_injury_risk_score(self) -> float:
        """Convert injury risk to numeric score (higher is better)"""
        if not self.injury_risk:
            return 0.7
        return self.INJURY_RISK_SCORES.get(self.injury_risk, 0.7)
    
    def get_jerarquia_score(self) -> float:
        """Normalize hierarchy score to 0-1 range"""
        if not self.jerarquia:
            return 0.5
        return (7 - self.jerarquia) / 6.0
    
    def get_form_score(self) -> float:
        """Normalize form arrow to 0-1 range"""
        if not self.form_arrow:
            return 0.5
        return 5.0 - (self.form_arrow / 5.0)


@dataclass
class Player:
    """Player model with stats and market information"""
    id: str
    nickname: str
    position_id: int
    team_id: str
    team_name: str
    points: int
    average_points: float
    last_season_points: Optional[int]
    market_value: int
    player_status: str
    last_3_weeks: List[int] = field(default_factory=list)
    minutes_last_3: List[int] = field(default_factory=list)
    is_on_market: bool = False
    owned_by: Optional[str] = None
    buyout_clause: Optional[int] = None
    buyout_locked_until: Optional[datetime] = None
    sale_price: Optional[int] = None
    scraped_data: Optional[ScrapedPlayerData] = None
    _slug: Optional[str] = None
    
    POSITION_NAMES = {1: "GK", 2: "DF", 3: "MF", 4: "FW", 5: "COACH"}
    
    def get_slug(self) -> str:
        """Generate URL-friendly slug from player name"""
        if self._slug:
            return self._slug
            
        try:
            mapper = PlayerMapper("name_mapping.json")
            full_name = mapper.get_real_name(self.nickname)
        except FileNotFoundError:
            print("⚠️  name_mapping.json not found. Using nickname fallback.")
            full_name = self.nickname
            
        if full_name is None:
            full_name = self.nickname
            
        slug = (full_name.lower()
                .replace(' ', '-')
                .replace('á', 'a').replace('é', 'e')
                .replace('í', 'i').replace('ó', 'o')
                .replace('ú', 'u').replace('ñ', 'n')
                .replace('.', '').replace("'", ''))
        
        self._slug = slug
        return slug
    
    def price_in_millions(self) -> float:
        """Convert market value to millions"""
        return self.market_value / 1_000_000
    
    def points_per_game(self) -> float:
        """Average points per game"""
        return self.average_points
    
    def form_last_3(self) -> float:
        """Recent form based on last 3 matches"""
        if not self.last_3_weeks:
            return self.average_points
        return sum(self.last_3_weeks) / len(self.last_3_weeks)
    
    def minutes_reliability(self) -> float:
        """Playing time reliability (0-1 scale)"""
        if not self.minutes_last_3:
            return 0.5
        avg_minutes = sum(self.minutes_last_3) / len(self.minutes_last_3)
        return min(avg_minutes / 90.0, 1.0)
    
    def is_available(self) -> bool:
        """Check if player is available (not injured/suspended)"""
        return self.player_status == "ok"
    
    def is_transferable(self, current_time: datetime = None) -> bool:
        """Check if player can be transferred"""
        if current_time is None:
            current_time = datetime.now(timezone.utc)
            
        if self.is_on_market:
            return True
            
        if self.buyout_locked_until and self.buyout_locked_until < current_time:
            return True
            
        return False
    
    def get_acquisition_cost(self) -> float:
        """Get cost to acquire player in millions"""
        if self.is_on_market and self.sale_price:
            return self.sale_price / 1_000_000
            
        if self.buyout_clause:
            return self.buyout_clause / 1_000_000
            
        return float('inf')


@dataclass
class Fixture:
    """Match fixture information"""
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
    """Fantasy team model"""
    team_id: str
    manager_name: str
    players: List[Player]
    team_value: int
    team_points: int
    team_money: Optional[int]
    position: int
    
    def total_value_millions(self) -> float:
        """Total team value in millions"""
        return self.team_value / 1_000_000
    
    def budget_millions(self) -> float:
        """Available budget in millions"""
        if self.team_money is None:
            return 0.0
        return self.team_money / 1_000_000


# ============================================================================
# UTILITIES
# ============================================================================

class PlayerMapper:
    """Maps fantasy nicknames to real player names"""
    
    def __init__(self, mapping_path: str):
        self.mapping_path = Path(mapping_path)
        
        if not self.mapping_path.exists():
            raise FileNotFoundError(
                f"Missing {mapping_path}. Create it with empty JSON {{}}"
            )
            
        with open(self.mapping_path, "r", encoding="utf-8") as f:
            self.name_mapping = json.load(f)
    
    def get_real_name(self, fantasy_name: str) -> Optional[str]:
        """Get real name from fantasy nickname"""
        return self.name_mapping.get(fantasy_name)


class ScraperManager:
    """Manages web scraping for player data"""
    
    def __init__(self, cache_dir: str = "./scrapper"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self._failed_scrapes = set()
    
    @lru_cache(maxsize=100)
    def get_player_data(self, player_slug: str) -> Optional[ScrapedPlayerData]:
        """Fetch and cache player data from web"""
        if player_slug in self._failed_scrapes:
            return None
            
        try:
            scraper = fantasy_scrapper.FantasyScraper(player_slug)
            data = scraper.get_player_info()
            
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
        """Add scraped data to player object"""
        if player.position_id == 5:  # Skip coaches
            return player
            
        slug = player.get_slug()
        scraped = self.get_player_data(slug)
        
        if scraped:
            player.scraped_data = scraped
            
        return player
    
    def enrich_players_batch(
        self,
        players: List[Player],
        max_to_scrape: int = 1000
    ) -> List[Player]:
        """Enrich multiple players with web data"""
        print(f"\n🔍 Enriching player data (max {max_to_scrape})...")
        
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


# ============================================================================
# DATA LOADING
# ============================================================================

class DataLoader:
    """Loads data from JSON files"""
    
    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.calendar_dir = self.data_dir / "calendar"
        self.equipos_dir = self.data_dir / "equipos"
        self.market_dir = self.data_dir / "market"
        self.players_dir = self.data_dir / "players"
    
    def load_latest_file(self, directory: Path, prefix: str) -> Optional[Dict]:
        """Load most recent file matching prefix"""
        if not directory.exists():
            print(f"⚠️  Directory not found: {directory}")
            return None
            
        files = sorted(directory.glob(f"{prefix}*.json"), reverse=True)
        
        if not files:
            print(f"⚠️  No files found matching: {prefix}")
            return None
            
        latest = files[0]
        with open(latest, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_latest_date(self, directory: Path) -> Optional[str]:
        """Extract date from latest file in directory"""
        if not directory.exists():
            return None
            
        files = sorted(directory.glob("*.json"), reverse=True)
        
        if not files:
            return None
            
        latest = files[0].name
        date_str = latest.split("_")[1].split(".")[0]
        return date_str
    
    def load_calendar(self, week: int) -> List[Fixture]:
        """Load fixtures for specific week"""
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
        """Load user's fantasy team"""
        data = self.load_latest_file(
            self.equipos_dir,
            team_name if team_name else ""
        )
        
        if not data:
            return None
        
        players = self._parse_team_players(data.get('players', []))
        
        return Team(
            team_id=data['id'],
            manager_name=data['manager']['managerName'],
            players=players,
            team_value=data['teamValue'],
            team_points=data['teamPoints'],
            team_money=data.get('teamMoney'),
            position=data['position']
        )
    
    def _parse_team_players(self, players_data: List[Dict]) -> List[Player]:
        """Parse player data from team JSON"""
        players = []
        
        for p in players_data:
            pm = p.get('playerMaster', {})
            last_stats = pm.get('lastStats', [])[-3:]
            
            last_3_points = [s['totalPoints'] for s in last_stats]
            last_3_mins = [
                s.get('stats', {}).get('mins_played', [0])[0]
                for s in last_stats
            ]
            
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
        
        return players
    
    def load_all_players(self) -> List[Player]:
        """Load all players with market and ownership data"""
        data = self.load_latest_file(self.players_dir, "players")
        
        if not data:
            return []
        
        # Create base player objects
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
                last_season_points=(
                    int(p.get('lastSeasonPoints', 0))
                    if p.get('lastSeasonPoints') else None
                ),
                market_value=int(p.get('marketValue', 0)),
                player_status=p.get('playerStatus', 'ok')
            )
        
        # Enrich with market data
        self._enrich_market_data(all_players)
        
        # Enrich with ownership data
        self._enrich_ownership_data(all_players)
        
        return list(all_players.values())
    
    def _enrich_market_data(self, all_players: Dict[str, Player]) -> None:
        """Add market listing data to players"""
        market_data = self.load_latest_file(self.market_dir, "market")
        
        if not market_data:
            return
        
        for market_entry in market_data:
            pm = market_entry.get('playerMaster', {})
            player_id = pm.get('id')
            
            if player_id not in all_players:
                continue
            
            player = all_players[player_id]
            
            if market_entry.get('discr') != "marketPlayerTeam":
                player.is_on_market = True
                
            player.sale_price = market_entry.get('salePrice')
    
    def _enrich_ownership_data(self, all_players: Dict[str, Player]) -> None:
        """Add ownership and buyout data to players"""
        if not self.equipos_dir.exists():
            return
        
        latest_date = self.load_latest_date(self.equipos_dir)
        
        if not latest_date:
            return
        
        for team_file in self.equipos_dir.glob(f"*{latest_date}.json"):
            with open(team_file, 'r', encoding='utf-8') as f:
                team_data = json.load(f)
            
            manager_name = team_data['manager']['managerName']
            
            for p in team_data.get('players', []):
                pm = p.get('playerMaster', {})
                player_id = pm.get('id')
                
                if player_id not in all_players:
                    continue
                
                player = all_players[player_id]
                player.owned_by = manager_name
                player.buyout_clause = p.get('buyoutClause')
                
                lock_time_str = p.get('buyoutClauseLockedEndTime')
                if lock_time_str:
                    try:
                        player.buyout_locked_until = datetime.fromisoformat(
                            lock_time_str
                        )
                    except Exception:
                        pass
    
    def load_current_week(self) -> int:
        """Load current gameweek number"""
        try:
            file_path = list(self.data_dir.glob("current_week.json"))[0]
        except IndexError:
            print("⚠️  current_week.json not found. Defaulting to week 1.")
            return 1
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return data.get('weekNumber', 1)


# ============================================================================
# FIXTURE ANALYSIS
# ============================================================================

class FixtureAnalyzer:
    """Analyzes fixture difficulty and schedules"""
    
    # Team strength ratings (attack, defense)
    TEAM_STRENGTHS = {
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
    
    DEFAULT_STRENGTH = {"attack": 3.0, "defense": 3.0}
    
    def __init__(self, fixtures: List[Fixture]):
        self.fixtures = fixtures
    
    def get_fixture_difficulty(
        self,
        team_id: str,
        team_name: str,
        next_n_weeks: int = 3
    ) -> List[Dict]:
        """Calculate fixture difficulty for a team"""
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
            
            difficulty = self._calculate_match_difficulty(opponent, is_home)
            
            team_fixtures.append({
                'opponent': opponent,
                'is_home': is_home,
                'difficulty': difficulty,
                'date': fixture.match_date
            })
            
            if len(team_fixtures) >= next_n_weeks:
                break
        
        return team_fixtures
    
    def _calculate_match_difficulty(
        self,
        opponent: str,
        is_home: bool
    ) -> float:
        """Calculate difficulty score for a match (1-5 scale)"""
        opp_strength = self.TEAM_STRENGTHS.get(
            opponent,
            self.DEFAULT_STRENGTH
        )
        
        avg_opponent_strength = (
            opp_strength['attack'] + opp_strength['defense']
        ) / 2
        
        # Invert: stronger opponent = higher difficulty
        difficulty = 6 - avg_opponent_strength
        
        # Home advantage
        if is_home:
            difficulty -= 0.5
        else:
            difficulty += 0.2
        
        # Clamp to 1-5 range
        return max(1, min(5, difficulty))
    
    def calculate_fixture_score(
        self,
        player: Player,
        next_weeks: int = 3
    ) -> float:
        """Calculate weighted fixture difficulty score (2-10 scale)"""
        fixtures = self.get_fixture_difficulty(
            player.team_id,
            player.team_name,
            next_weeks
        )
        
        if not fixtures:
            return 5.0
        
        # Weight more recent fixtures higher
        weights = [1.0, 0.8, 0.6][:len(fixtures)]
        scores = [f['difficulty'] * 2 for f in fixtures]  # Scale to 2-10
        
        weighted_avg = sum(
            s * w for s, w in zip(scores, weights)
        ) / sum(weights)
        
        return weighted_avg


# ============================================================================
# PLAYER EVALUATION
# ============================================================================

class PlayerEvaluator:
    """Evaluates players using multiple metrics"""
    
    # Score weights (total = 100)
    WEIGHTS = {
        'form': 15,
        'fixtures': 20,
        'ppg': 15,
        'value': 10,
        'jerarquia': 15,
        'probability': 10,
        'injury': 5
    }
    
    def __init__(self, fixture_analyzer: FixtureAnalyzer):
        self.fixture_analyzer = fixture_analyzer
    
    def evaluate_player(self, player: Player) -> Dict:
        """Comprehensive player evaluation"""
        # Calculate individual scores
        form_score = self._calculate_form_score(player)
        fixture_score = self._calculate_fixture_score(player)
        ppg_score = self._calculate_ppg_score(player)
        value_score = self._calculate_value_score(player)
        jerarquia_score = self._calculate_jerarquia_score(player)
        probability_score = self._calculate_probability_score(player)
        injury_score = self._calculate_injury_score(player)
        
        # Calculate total score
        total_score = (
            form_score + fixture_score + ppg_score + value_score +
            jerarquia_score + probability_score + injury_score
        )
        
        # Apply penalties
        total_score = self._apply_penalties(player, total_score)
        
        return {
            'total_score': total_score,
            'form': player.form_last_3(),
            'form_score': form_score,
            'fixtures': self.fixture_analyzer.calculate_fixture_score(player),
            'fixture_score': fixture_score,
            'ppg': player.points_per_game(),
            'ppg_score': ppg_score,
            'value': player.points_per_game() / max(player.price_in_millions(), 0.1),
            'value_score': value_score,
            'jerarquia_score': jerarquia_score,
            'probability_score': probability_score,
            'injury_score': injury_score,
            'minutes_reliability': player.minutes_reliability(),
            'is_available': player.is_available(),
            'scraped_jerarquia': (
                player.scraped_data.jerarquia if player.scraped_data else None
            ),
            'scraped_probability': (
                player.scraped_data.play_probability if player.scraped_data else None
            ),
            'scraped_form_arrow': (
                player.scraped_data.form_arrow if player.scraped_data else None
            ),
            'scraped_injury_risk': (
                player.scraped_data.injury_risk if player.scraped_data else None
            ),
        }
    
    def _calculate_form_score(self, player: Player) -> float:
        """Calculate form score (max 15 points)"""
        form_raw = player.form_last_3()
        form_score = min(form_raw / 10.0, 1.0) * self.WEIGHTS['form']
        
        # Add web-scraped form data
        if player.scraped_data and player.scraped_data.form_arrow:
            form_score += player.scraped_data.get_form_score() * 10
        else:
            form_score += 5
        
        return form_score
    
    def _calculate_fixture_score(self, player: Player) -> float:
        """Calculate fixture difficulty score (max 20 points)"""
        fixture_raw = self.fixture_analyzer.calculate_fixture_score(player)
        
        # Invert: easier fixtures = higher score
        fixture_score = (10 - (fixture_raw - 2)) / 8 * self.WEIGHTS['fixtures']
        
        return fixture_score
    
    def _calculate_ppg_score(self, player: Player) -> float:
        """Calculate points per game score (max 15 points)"""
        ppg_raw = player.points_per_game()
        return min(ppg_raw / 10.0, 1.0) * self.WEIGHTS['ppg']
    
    def _calculate_value_score(self, player: Player) -> float:
        """Calculate value for money score (max 10 points)"""
        value_raw = player.points_per_game() / max(player.price_in_millions(), 0.1)
        return min(value_raw / 2.0, 1.0) * self.WEIGHTS['value']
    
    def _calculate_jerarquia_score(self, player: Player) -> float:
        """Calculate team hierarchy score (max 15 points)"""
        if player.scraped_data and player.scraped_data.jerarquia:
            return player.scraped_data.get_jerarquia_score() * self.WEIGHTS['jerarquia']
        return self.WEIGHTS['jerarquia'] / 2  # Default to 50%
    
    def _calculate_probability_score(self, player: Player) -> float:
        """Calculate play probability score (max 10 points)"""
        if player.scraped_data and player.scraped_data.play_probability:
            return player.scraped_data.play_probability * self.WEIGHTS['probability']
        return self.WEIGHTS['probability'] * 0.7  # Default to 70%
    
    def _calculate_injury_score(self, player: Player) -> float:
        """Calculate injury risk score (max 5 points)"""
        if player.scraped_data and player.scraped_data.injury_risk:
            return player.scraped_data.get_injury_risk_score() * self.WEIGHTS['injury']
        return self.WEIGHTS['injury'] * 0.7  # Default to 70%
    
    def _apply_penalties(self, player: Player, score: float) -> float:
        """Apply penalties for low minutes or injury"""
        if player.minutes_reliability() < 0.6:
            score *= 0.7
        
        if player.player_status != "ok":
            score *= 0.5
        
        return score
    
    def find_best_transfers(
        self,
        current_team: Team,
        available_players: List[Player],
        budget: float,
        max_suggestions: int = 5
    ) -> List[Dict]:
        """Find optimal transfer suggestions"""
        current_time = datetime.now(timezone.utc)
        
        # Evaluate current squad
        current_scores = {}
        for player in current_team.players:
            if player.position_id == 5:  # Skip coaches
                continue
            current_scores[player.id] = self.evaluate_player(player)
        
        # Find transfer opportunities
        transfer_suggestions = []
        
        for current_player in current_team.players:
            if current_player.position_id == 5:
                continue
            
            current_eval = current_scores[current_player.id]
            
            # Filter candidates
            candidates = [
                p for p in available_players
                if (p.id not in [cp.id for cp in current_team.players] and
                    p.is_available() and
                    p.is_transferable(current_time))
            ]
            
            # Evaluate each candidate
            for candidate in candidates:
                acquisition_cost = candidate.get_acquisition_cost()
                net_cost = acquisition_cost - current_player.price_in_millions()
                
                if net_cost > budget:
                    continue
                
                candidate_eval = self.evaluate_player(candidate)
                score_improvement = (
                    candidate_eval['total_score'] - current_eval['total_score']
                )
                
                # Only suggest if significant improvement
                if score_improvement > 3:
                    acq_type = self._get_acquisition_type(
                        candidate, current_time
                    )
                    
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
    
    def _get_acquisition_type(
        self,
        player: Player,
        current_time: datetime
    ) -> str:
        """Determine how a player can be acquired"""
        if player.is_on_market:
            return "Market"
        
        if player.buyout_locked_until and player.buyout_locked_until < current_time:
            return f"Buyout (from {player.owned_by})"
        
        return "Unknown"


# ============================================================================
# MAIN AGENT
# ============================================================================

class FantasyAgent:
    """Main agent for fantasy team analysis and recommendations"""
    
    def __init__(self, data_dir: str = "."):
        try:
            data_downloader()
        except:
            print("Failed to refresh data")
        self.loader = DataLoader(data_dir)
        self.scraper_manager = ScraperManager()
        self.current_week = -1
        self.my_team = None
        self.all_players = []
        self.fixture_analyzer = None
        self.evaluator = None
    
    def initialize(
        self,
        team_name: str = None,
        enrich_current_team: bool = True
    ) -> Optional[Dict]:
        """Initialize agent with data from files"""
        print("🤖 Initializing Fantasy Agent...")
        print("=" * 60)
        
        try:
            self.current_week = self.loader.load_current_week()
            self.my_team = self.loader.load_my_team(team_name)
        except Exception as e:
            print(f"❌ CRITICAL ERROR: {e}")
            print("   Ensure JSON files exist in: /equipos, /players, /market")
            print("   Run download_pipeline.py to fetch data.")
            return None
        
        if not self.my_team:
            print("❌ Could not load team! Check 'equipos' directory.")
            return None
        
        print(f"✅ Loaded team: {self.my_team.manager_name}")
        print(f"   Players: {len(self.my_team.players)}")
        print(f"   Team Value: €{self.my_team.total_value_millions():.1f}M")
        print(f"   Budget: €{self.my_team.budget_millions():.1f}M")
        
        if enrich_current_team:
            print(f"\n🔍 Enriching team with web data...")
            for player in self.my_team.players:
                self.scraper_manager.enrich_player(player)
        
        self.all_players = self.loader.load_all_players()
        print(f"\n✅ Loaded {len(self.all_players)} total players")
        
        fixtures = self.loader.load_calendar(self.current_week)
        self.fixture_analyzer = FixtureAnalyzer(fixtures)
        self.evaluator = PlayerEvaluator(self.fixture_analyzer)
        
        print("✅ Agent ready!")
        print("=" * 60)
        
        return {
            "name": self.my_team.manager_name,
            "value": f"€{self.my_team.total_value_millions():.1f}M",
            "budget": f"€{self.my_team.budget_millions():.1f}M"
        }
    
    def analyze_current_team(self) -> List[Dict]:
        """Analyze current team performance"""
        if not self.my_team:
            print("❌ No team loaded")
            return []
        
        print("\n📊 Analyzing Team...")
        team_analysis = []
        
        for player in self.my_team.players:
            if player.position_id == 5:  # Skip coaches
                continue
            
            eval_result = self.evaluator.evaluate_player(player)
            
            # Extract scraped data safely
            scraped = player.scraped_data
            web_jerarquia = scraped.jerarquia if scraped else None
            web_prob = scraped.play_probability if scraped else None
            web_form = scraped.form_arrow if scraped else None
            web_risk = scraped.injury_risk if scraped else None
            
            player_dict = {
                "Name": player.nickname,
                "Pos": Player.POSITION_NAMES.get(player.position_id, '?'),
                "Team": player.team_name,
                "Score": round(eval_result['total_score'], 1),
                "Form (L3)": round(eval_result['form'], 1),
                "Season": round(eval_result['ppg'], 1),
                "Fixtures": round(eval_result['fixtures'], 1),
                "Price": f"€{player.price_in_millions():.1f}M",
                "Status": player.player_status.upper(),
                "Jerarquía": f"{web_jerarquia}/6" if web_jerarquia else "N/A",
                "Play Prob": f"{web_prob*100:.0f}%" if web_prob is not None else "N/A",
                "Form Arrow": f"{'🔥' * web_form}" if web_form else "N/A",
                "Injury Risk": web_risk if web_risk else "N/A"
            }
            team_analysis.append(player_dict)
        
        return team_analysis
    
    def suggest_transfers(
        self,
        max_suggestions: int = 5,
        enrich_candidates: bool = True
    ) -> List[Dict]:
        """Generate transfer suggestions"""
        if not self.my_team or not self.evaluator:
            print("❌ Agent not initialized")
            return []
        
        budget = self.my_team.budget_millions()
        print(f"\n💡 Finding Transfers (Budget: €{budget:.1f}M)...")
        
        # Get transferable players
        transferable = [
            p for p in self.all_players
            if p.is_transferable()
        ]
        
        # Pre-filter top candidates by position
        top_candidates = self._filter_top_candidates(transferable)
        print(f"   - Filtered to {len(top_candidates)} top candidates")
        
        # Enrich candidate data
        if enrich_candidates and top_candidates:
            self.scraper_manager.enrich_players_batch(top_candidates)
        
        # Get transfer suggestions
        suggestions = self.evaluator.find_best_transfers(
            self.my_team,
            self.all_players,
            budget,
            max_suggestions
        )
        
        if not suggestions:
            print("\n✅ No beneficial transfers found. Team looks solid!")
            return []
        
        # Format for dashboard
        return self._format_transfer_suggestions(suggestions, budget)
    
    def _filter_top_candidates(
        self,
        players: List[Player],
        top_n_per_position: int = 15
    ) -> List[Player]:
        """Filter top players by position"""
        candidates_by_position = {1: [], 2: [], 3: [], 4: []}
        
        for player in players:
            if player.position_id in candidates_by_position:
                candidates_by_position[player.position_id].append(player)
        
        # Sort by average points and take top N
        for pos in candidates_by_position:
            candidates_by_position[pos].sort(
                key=lambda p: p.average_points,
                reverse=True
            )
            candidates_by_position[pos] = (
                candidates_by_position[pos][:top_n_per_position]
            )
        
        # Flatten list
        return [
            p for pos_candidates in candidates_by_position.values()
            for p in pos_candidates
        ]
    
    def _format_transfer_suggestions(
        self,
        suggestions: List[Dict],
        budget: float
    ) -> List[Dict]:
        """Format transfer suggestions for dashboard"""
        formatted = []
        
        for transfer in suggestions:
            in_eval = transfer['player_in_eval']
            out_eval = transfer['player_out_eval']
            
            # Format incoming player data
            in_form_arrow = in_eval.get('scraped_form_arrow')
            in_form_str = (
                f"{'🔥' * in_form_arrow} ({in_form_arrow}/5)"
                if in_form_arrow else "N/A"
            )
            
            in_risk = in_eval.get('scraped_injury_risk')
            risk_emoji = {"Bajo": "✅", "Medio": "⚠️", "Alto": "🚨"}
            in_risk_str = (
                f"{in_risk} {risk_emoji.get(in_risk, '❓')}"
                if in_risk else "N/A"
            )
            
            in_prob = in_eval.get('scraped_probability')
            prob_emoji = (
                '✅' if in_prob and in_prob > 0.7
                else '⚠️' if in_prob and in_prob > 0.4
                else '🚨'
            )
            in_prob_str = (
                f"{in_prob*100:.0f}% {prob_emoji}"
                if in_prob is not None else "N/A"
            )
            
            in_jerarquia = in_eval.get('scraped_jerarquia')
            in_jerarquia_str = (
                f"{in_jerarquia}/6 {'⭐' if in_jerarquia and in_jerarquia <= 2 else ''}"
                if in_jerarquia else "N/A"
            )
            
            formatted.append({
                "improvement": f"{transfer['improvement']:.1f}",
                "out_name": transfer['player_out'].nickname,
                "out_team": transfer['player_out'].team_name,
                "out_score": f"{transfer['player_out_score']:.1f}/100",
                "out_price": f"€{transfer['player_out'].price_in_millions():.1f}M",
                "out_jerarquia": f"{out_eval.get('scraped_jerarquia', 'N/A')}/6",
                "out_prob": f"{out_eval.get('scraped_probability', 0)*100:.0f}%",
                "in_name": transfer['player_in'].nickname,
                "in_team": transfer['player_in'].team_name,
                "in_score": f"{transfer['player_in_score']:.1f}/100",
                "in_price": f"€{transfer['acquisition_cost']:.1f}M",
                "in_source": transfer['acquisition_type'],
                "in_jerarquia": in_jerarquia_str,
                "in_prob": in_prob_str,
                "in_form": in_form_str,
                "in_risk": in_risk_str,
                "net_cost": f"€{transfer['net_cost']:.1f}M",
                "value_ratio": f"{transfer['value_ratio']:.2f}",
                "remaining_budget": f"€{budget - transfer['net_cost']:.1f}M"
            })
        
        return formatted
    
    def show_upcoming_fixtures(self) -> Dict[str, List[str]]:
        """Show upcoming fixtures for teams in squad"""
        if not self.my_team or not self.fixture_analyzer:
            print("❌ Agent not initialized")
            return {}
        
        print(f"\n📅 Analyzing Fixtures...")
        fixture_data = {}
        teams_shown = set()
        
        for player in self.my_team.players:
            if player.team_id in teams_shown or player.position_id == 5:
                continue
            
            fixtures = self.fixture_analyzer.get_fixture_difficulty(
                player.team_id,
                player.team_name,
                3
            )
            
            if fixtures:
                fixture_strings = []
                for fix in fixtures:
                    home = "🏠" if fix['is_home'] else "✈️ "
                    difficulty_stars = "★" * int(fix['difficulty'])
                    
                    fix_str = (
                        f"{home} vs {fix['opponent']} - "
                        f"{difficulty_stars} ({fix['difficulty']:.1f}/5)"
                    )
                    fixture_strings.append(fix_str)
                
                fixture_data[player.team_name] = fixture_strings
            
            teams_shown.add(player.team_id)
        
        return fixture_data


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    agent = FantasyAgent(data_dir=".")
    
    team_summary = agent.initialize(
        team_name="svendsinio",
        enrich_current_team=True
    )
    
    if not team_summary:
        print("Failed to initialize agent")
        return
    
    print("\n" + "=" * 60)
    print("TEAM SUMMARY")
    print("=" * 60)
    for key, value in team_summary.items():
        print(f"{key.title()}: {value}")
    
    # Team Analysis
    team_analysis = agent.analyze_current_team()
    print("\n" + "=" * 60)
    print("TEAM ANALYSIS")
    print("=" * 60)
    
    if team_analysis:
        # Print header
        headers = list(team_analysis[0].keys())
        header_row = " | ".join(f"{h:12}" for h in headers[:5])
        print(header_row)
        print("-" * len(header_row))
        
        # Print rows
        for player in sorted(team_analysis, key=lambda x: x['Score'], reverse=True):
            row = " | ".join(f"{str(player[h]):12}" for h in headers[:5])
            print(row)
    
    # Fixtures
    fixtures = agent.show_upcoming_fixtures()
    print("\n" + "=" * 60)
    print("UPCOMING FIXTURES")
    print("=" * 60)
    
    for team, fix_list in fixtures.items():
        print(f"\n{team}:")
        for fixture in fix_list:
            print(f"  {fixture}")
    
    # Transfer Suggestions
    transfers = agent.suggest_transfers(
        max_suggestions=5,
        enrich_candidates=True
    )
    print("\n" + "=" * 60)
    print("TRANSFER SUGGESTIONS")
    print("=" * 60)
    
    if transfers:
        for i, transfer in enumerate(transfers, 1):
            print(f"\n{i}. Improvement: {transfer['improvement']} points")
            print(f"   OUT: {transfer['out_name']} ({transfer['out_team']}) - {transfer['out_score']}")
            print(f"   IN:  {transfer['in_name']} ({transfer['in_team']}) - {transfer['in_score']}")
            print(f"   Cost: {transfer['net_cost']} ({transfer['in_source']})")
            print(f"   Value Ratio: {transfer['value_ratio']}")
    
    print("\n" + "=" * 60)
    print("✅ Analysis complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()