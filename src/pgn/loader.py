import io
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
import chess.pgn
from src.pgn.validator import PGNValidator
from src.pgn.filter import PGNFilter, normalize_name
from src.chess.positions import parse_time_control_base_seconds, classify_time_control

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
    color: str = "black"

def parse_elo(elo_str: str) -> Optional[int]:
    try:
        return int(elo_str)
    except (ValueError, TypeError):
        return None

def load_pgn_games(
    pgn_path: str,
    target_player: str = "",
    limit: Optional[int] = None,
    color: str = "black",
    time_control_category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_opponent_elo: Optional[int] = None,
) -> LoadPGNResult:
    """
    time_control_category: keep only games classified as this bucket
        (bullet/blitz/rapid/classical/unknown) - see classify_time_control().
    date_from / date_to: PGN-style "YYYY.MM.DD" bounds (inclusive), compared
        lexically. A game whose Date header contains "??" segments (unknown
        exact date) is excluded whenever either bound is set, since we can't
        safely compare a partial date.
    min_opponent_elo: keep only games where the OPPONENT (not the target
        player) had at least this Elo in that game's PGN headers.
    """
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
            # Only safe to stop reading early when the target player is already
            # known: auto-detection (below) needs the full file to find the
            # most frequent Black player, so it can't be short-circuited here.
            if limit and target_player and len(raw_games) >= limit:
                break

    if not target_player and raw_games:
        target_player = PGNFilter.auto_detect_player(raw_games, color=color)
        logger.info(f"Auto-detected target {color} player: '{target_player}'")

    filtered_records: List[GameRecord] = []
    not_target_count = 0
    invalid_count = 0

    for idx, game in enumerate(raw_games):
        if limit and len(filtered_records) >= limit:
            break

        # Check target player
        if target_player and not PGNFilter.is_target_color(game, target_player, color=color):
            not_target_count += 1
            header_key = "White" if color == "white" else "Black"
            skipped_games.append(SkippedGame(
                index=idx,
                headers=dict(game.headers),
                reason=f"{header_key} player '{game.headers.get(header_key)}' != target '{target_player}'"
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

        # Time control filter
        if time_control_category is not None:
            base_sec = parse_time_control_base_seconds(game.headers.get("TimeControl", ""))
            if classify_time_control(base_sec) != time_control_category:
                skipped_games.append(SkippedGame(
                    index=idx, headers=dict(game.headers),
                    reason=f"Time control category != '{time_control_category}'"
                ))
                continue

        # Date range filter
        if date_from is not None or date_to is not None:
            date_str = game.headers.get("Date", "")
            if "?" in date_str:
                skipped_games.append(SkippedGame(
                    index=idx, headers=dict(game.headers),
                    reason="Unknown/partial Date header, excluded by date filter"
                ))
                continue
            if date_from is not None and date_str < date_from:
                skipped_games.append(SkippedGame(
                    index=idx, headers=dict(game.headers),
                    reason=f"Date '{date_str}' before date_from '{date_from}'"
                ))
                continue
            if date_to is not None and date_str > date_to:
                skipped_games.append(SkippedGame(
                    index=idx, headers=dict(game.headers),
                    reason=f"Date '{date_str}' after date_to '{date_to}'"
                ))
                continue

        # Minimum opponent Elo filter
        if min_opponent_elo is not None:
            opp_header = "BlackElo" if color == "white" else "WhiteElo"
            opp_elo = parse_elo(game.headers.get(opp_header, ""))
            if opp_elo is None or opp_elo < min_opponent_elo:
                skipped_games.append(SkippedGame(
                    index=idx, headers=dict(game.headers),
                    reason=f"Opponent Elo {opp_elo} < min_opponent_elo {min_opponent_elo}"
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
        filter_stats=filter_stats,
        color=color
    )
