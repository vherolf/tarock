from enum import Enum
from datetime import datetime, date
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from uuid import uuid4

class PlayerStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class TournamentStatus(Enum):
    PENDING = "pending"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class GameType(Enum):
    TRICKS = "tricks"
    POINTS = "points"
    SCORE = "score"
    CUSTOM = "custom"

class RoundStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

@dataclass
class Player:
    player_id: str = field(default_factory=lambda: str(uuid4()))
    name: str
    email: str
    status: PlayerStatus = PlayerStatus.ACTIVE
    registration_date: datetime = field(default_factory=datetime.now)
    rating: float = 0.0
    tournaments_played: int = 0

@dataclass
class Tournament:
    tournament_id: str = field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    start_date: date
    end_date: date
    status: TournamentStatus = TournamentStatus.PENDING
    game_type: GameType = GameType.TRICKS
    max_players: int
    min_players: int = 2
    registration_deadline: Optional[date] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    players: List[str] = field(default_factory=list)  # player_ids
    rounds: List['Round'] = field(default_factory=list)

@dataclass
class Round:
    round_id: str = field(default_factory=lambda: str(uuid4()))
    tournament_id: str
    round_number: int
    status: RoundStatus = RoundStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    matches: List['Match'] = field(default_factory=list)

@dataclass
class Match:
    match_id: str = field(default_factory=lambda: str(uuid4()))
    round_id: str
    player1_id: str
    player2_id: str
    player1_score: int = 0
    player2_score: int = 0
    winner_id: Optional[str] = None  # Will be set after match completion
    status: RoundStatus = RoundStatus.PENDING
    played_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class TournamentStats:
    tournament_id: str
    total_players: int = 0
    completed_rounds: int = 0
    total_matches: int = 0
    average_rating: float = 0.0
    last_updated: datetime = field(default_factory=datetime.now)

@dataclass
class TournamentResult:
    player_id: str
    tournament_id: str
    rank: int
    points: int
    games_played: int
    win_rate: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)

class TournamentManager:
    def __init__(self):
        self.players: Dict[str, Player] = {}
        self.tournaments: Dict[str, Tournament] = {}
        self.results: Dict[str, List[TournamentResult]] = {}  # tournament_id -> results
    
    def create_player(self, name: str, email: str) -> Player:
        player = Player(name=name, email=email)
        self.players[player.player_id] = player
        return player
    
    def create_tournament(self, 
                         name: str, 
                         description: str,
                         start_date: date,
                         end_date: date,
                         max_players: int,
                         game_type: GameType = GameType.TRICKS) -> Tournament:
        tournament = Tournament(
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            max_players=max_players,
            game_type=game_type
        )
        self.tournaments[tournament.tournament_id] = tournament
        return tournament
    
    def register_player(self, player_id: str, tournament_id: str) -> bool:
        if player_id not in self.players or tournament_id not in self.tournaments:
            return False
        
        tournament = self.tournaments[tournament_id]
        if (tournament.status != TournamentStatus.REGISTRATION_OPEN or 
            len(tournament.players) >= tournament.max_players):
            return False
        
        # Check if player is already registered
        if player_id in tournament.players:
            return True
            
        tournament.players.append(player_id)
        self.players[player_id].tournaments_played += 1
        return True
    
    def start_tournament(self, tournament_id: str) -> bool:
        if tournament_id not in self.tournaments:
            return False
        
        tournament = self.tournaments[tournament_id]
        if tournament.status != TournamentStatus.PENDING:
            return False
            
        tournament.status = TournamentStatus.REGISTRATION_CLOSED
        tournament.updated_at = datetime.now()
        return True
    
    def get_tournament_results(self, tournament_id: str) -> List[TournamentResult]:
        return self.results.get(tournament_id, [])
    
    def calculate_tournament_rankings(self, tournament_id: str) -> List[TournamentResult]:
        if tournament_id not in self.tournaments:
            return []
        
        tournament = self.tournaments[tournament_id]
        player_scores = {}
        
        # Aggregate scores from all matches
        for round_obj in tournament.rounds:
            for match in round_obj.matches:
                if match.player1_id in player_scores:
                    player_scores[match.player1_id] += match.player1_score
                else:
                    player_scores[match.player1_id] = match.player1_score
                    
                if match.player2_id in player_scores:
                    player_scores[match.player2_id] += match.player2_score
                else:
                    player_scores[match.player2_id] = match.player2_score
        
        # Create results and sort by score (descending)
        results = [
            TournamentResult(
                player_id=player_id,
                tournament_id=tournament_id,
                rank=0,  # Will be set later
                points=score,
                games_played=1  # Simplified - in reality would count matches
            )
            for player_id, score in player_scores.items()
        ]
        
        results.sort(key=lambda x: x.points, reverse=True)
        
        # Set ranks
        for i, result in enumerate(results):
            result.rank = i + 1
            
        self.results[tournament_id] = results
        return results

# Example usage:
if __name__ == "__main__":
    manager = TournamentManager()
    
    # Create players
    player1 = manager.create_player("Alice", "alice@example.com")
    player2 = manager.create_player("Bob", "bob@example.com")
    player3 = manager.create_player("Charlie", "charlie@example.com")
    
    # Create tournament
    tournament = manager.create_tournament(
        name="Tarock Championship",
        description="Annual tarock tournament",
        start_date=date(2023, 10, 1),
        end_date=date(2023, 10, 7),
        max_players=8,
        game_type=GameType.TRICKS
    )
    
    # Register players
    manager.register_player(player1.player_id, tournament.tournament_id)
    manager.register_player(player2.player_id, tournament.tournament_id)
    manager.register_player(player3.player_id, tournament.tournament_id)
    
    # Start tournament
    manager.start_tournament(tournament.tournament_id)
    
    print(f"Created tournament: {tournament.name}")
    print(f"Registered players: {len(tournament.players)}")
