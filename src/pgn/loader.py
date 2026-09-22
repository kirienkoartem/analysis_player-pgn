import io
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
import chess.pgn
from src.pgn.validator import PGNValidator
from src.pgn.filter import PGNFilter, normalize_name

logger = logging.getLogger(__name__)

@dataclass
class GameMetadata:
    game_id: str
    white: str
    black: str
    result: str
    date: str
    event: str
    site: str
    round: str
    eco: str
    opening: str
    initial_fen: str
    time_control: str
    white_elo: Optional[int] = None
    black_elo: Optional[int] = None
    ply_count: int = 0

@dataclass
class GameRecord:
    metadata: GameMetadata
    game_node: chess.pgn.Game

@dataclass
class SkippedGame:
    index: int
    headers: Dict[str, str]
    reason: str

@dataclass
class LoadPGNResult:
    total_games_in_pgn: int
    target_player: str
    filtered_games: List[GameRecord]
    skipped_games: List[SkippedGame]
    filter_stats: Dict[str, int]

def parse_elo(elo_str: str) -> Optional[int]:
    try:
        return int(elo_str)
    except (ValueError, TypeError):
        return None

def load_pgn_games(pgn_path: str, target_player: str = "", limit: Optional[int] = None) -> LoadPGNResult:
    total_in_file = 0
    raw_games: List[chess.pgn.Game] = []
    skipped_games: List[SkippedGame] = []

    with open(pgn_path, "r", encoding="utf-8", errors="replace") as pgn_file:
        index = 0
        while True:
            try:
                game = chess.pgn.read_game(pgn_file)
            except Exception as e:
                skipped_games.append(SkippedGame(index=index, headers={}, reason=f"PGN read error: {e}"))
                logger.warning(f"Error reading game at index {index}: {e}")
                index += 1
                continue

            if game is None:
                break

            total_in_file += 1
            raw_games.append(game)
            index += 1
            if limit and len(raw_games) >= limit and not target_player:
                # If no target player specified yet and limit reached, stop
                pass

    if not target_player and raw_games:
        target_player = PGNFilter.auto_detect_black_player(raw_games)
        logger.info(f"Auto-detected target Black player: '{target_player}'")

    filtered_records: List[GameRecord] = []
    not_target_count = 0
    invalid_count = 0

    for idx, game in enumerate(raw_games):
        if limit and len(filtered_records) >= limit:
            break

        # Check target player
        if target_player and not PGNFilter.is_target_black(game, target_player):
            not_target_count += 1
            skipped_games.append(SkippedGame(
                index=idx,
                headers=dict(game.headers),
                reason=f"Black player '{game.headers.get('Black')}' != target '{target_player}'"
            ))
            continue

        # Validate game
        is_valid, error_msg = PGNValidator.validate_game(game, idx)
        if not is_valid:
            invalid_count += 1
            skipped_games.append(SkippedGame(
                index=idx,
                headers=dict(game.headers),
                reason=f"Validation error: {error_msg}"
            ))
            continue

        # Count plies
        node = game
        plies = 0
        while node.variations:
            node = node.variation(0)
            plies += 1

        headers = game.headers
        metadata = GameMetadata(
            game_id=f"game_{idx + 1}",
            white=headers.get("White", "Unknown"),
            black=headers.get("Black", "Unknown"),
            result=headers.get("Result", "*"),
            date=headers.get("Date", "????.??.??"),
            event=headers.get("Event", "Unknown"),
            site=headers.get("Site", "Unknown"),
            round=headers.get("Round", "-"),
            eco=headers.get("ECO", "???"),
            opening=headers.get("Opening", "Unknown Opening"),
            initial_fen=game.board().fen(),
            time_control=headers.get("TimeControl", "Unknown"),
            white_elo=parse_elo(headers.get("WhiteElo", "")),
            black_elo=parse_elo(headers.get("BlackElo", "")),
            ply_count=plies
        )

        filtered_records.append(GameRecord(metadata=metadata, game_node=game))

    filter_stats = {
        "total_in_pgn": total_in_file,
        "filtered_count": len(filtered_records),
        "not_target_player_count": not_target_count,
        "invalid_count": invalid_count,
        "skipped_total": len(skipped_games)
    }

    return LoadPGNResult(
        total_games_in_pgn=total_in_file,
        target_player=target_player,
        filtered_games=filtered_records,
        skipped_games=skipped_games,
        filter_stats=filter_stats
    )
