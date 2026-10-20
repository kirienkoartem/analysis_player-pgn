import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Dict
import chess
import chess.pgn
from src.pgn.validator import PGNValidator
from src.pgn.filter import PGNFilter
from src.chess.positions import parse_time_control_base_seconds, classify_time_control

logger = logging.getLogger(__name__)

# A game shorter than this (in plies, both sides) carries no usable signal:
# an early resignation/abandonment/disconnect says nothing about how someone
# plays, but would still count as a full win/loss in the result statistics.
MIN_GAME_PLIES = 6

STANDARD_VARIANTS = {"", "standard", "chess", "from position"}

# Skip reason codes, summarized in the report's data-quality section.
SKIP_REASON_LABELS = {
    "read_error": "Не удалось прочитать PGN",
    "not_target": "Партия другого игрока / другим цветом",
    "invalid": "Битая партия или нет ходов",
    "variant": "Не классические шахматы (960, crazyhouse и т.п.)",
    "custom_start": "Партия с нестандартной начальной позиции",
    "too_short": f"Слишком короткая (< {MIN_GAME_PLIES} полуходов: сдача/отказ в начале)",
    "time_control": "Отсеяна фильтром по контролю времени",
    "date": "Отсеяна фильтром по датам",
    "opponent_elo": "Отсеяна фильтром по рейтингу соперника",
}


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
    link: str = ""         # URL of the game on Lichess/Chess.com, if known
    termination: str = ""  # PGN Termination header, e.g. "Time forfeit", "Normal"

@dataclass
class GameRecord:
    metadata: GameMetadata
    game_node: chess.pgn.Game

@dataclass
class SkippedGame:
    index: int
    headers: Dict[str, str]
    reason: str
    code: str = "invalid"

@dataclass
class LoadPGNResult:
    total_games_in_pgn: int
    target_player: str
    filtered_games: List[GameRecord]
    skipped_games: List[SkippedGame]
    filter_stats: Dict[str, int]
    color: str = "black"

    def skip_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for sk in self.skipped_games:
            counts[sk.code] = counts.get(sk.code, 0) + 1
        return counts


def parse_elo(elo_str: str) -> Optional[int]:
    try:
        return int(elo_str)
    except (ValueError, TypeError):
        return None


_ECO_URL_FAMILY_END = ("Defense", "Defence", "Opening", "Gambit", "Game", "Attack", "System")


def opening_from_eco_url(eco_url: str) -> Optional[str]:
    """Chess.com PGNs have no Opening header, only e.g.
    [ECOUrl "https://www.chess.com/openings/Sicilian-Defense-Najdorf-Variation-6.Be3"].
    Rebuilds "Sicilian Defense: Najdorf Variation 6.Be3" so the family
    grouping (split on ':') works the same way it does for Lichess names."""
    if not eco_url or "/openings/" not in eco_url:
        return None
    slug = eco_url.rstrip("/").split("/openings/")[-1]
    words = [w for w in slug.split("-") if w]
    if not words:
        return None
    for i, w in enumerate(words):
        if w in _ECO_URL_FAMILY_END:
            family = " ".join(words[: i + 1])
            rest = " ".join(words[i + 1:])
            return f"{family}: {rest}" if rest else family
    return " ".join(words)


def _game_link(headers) -> str:
    link = headers.get("Link", "")
    if link.startswith("http"):
        return link
    site = headers.get("Site", "")
    return site if site.startswith("http") else ""


def _skip(skipped: List[SkippedGame], idx: int, game, code: str, reason: str) -> None:
    skipped.append(SkippedGame(index=idx, headers=dict(game.headers), reason=reason, code=code))


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

    matched_for_limit = 0
    with open(pgn_path, "r", encoding="utf-8", errors="replace") as pgn_file:
        index = 0
        while True:
            try:
                game = chess.pgn.read_game(pgn_file)
            except Exception as e:
                skipped_games.append(SkippedGame(index=index, headers={}, reason=f"PGN read error: {e}", code="read_error"))
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
            # most frequent player, so it can't be short-circuited here. Counts
            # only games where the target actually has the requested color -
            # stopping after `limit` raw games would under-fill a color filter.
            if limit and target_player:
                if PGNFilter.is_target_color(game, target_player, color=color):
                    matched_for_limit += 1
                if matched_for_limit >= limit:
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

        if target_player and not PGNFilter.is_target_color(game, target_player, color=color):
            not_target_count += 1
            header_key = "White" if color == "white" else "Black"
            _skip(skipped_games, idx, game, "not_target",
                  f"{header_key} player '{game.headers.get(header_key)}' != target '{target_player}'")
            continue

        variant = game.headers.get("Variant", "").strip().lower()
        if variant not in STANDARD_VARIANTS:
            _skip(skipped_games, idx, game, "variant", f"Variant '{game.headers.get('Variant')}' is not standard chess")
            continue

        is_valid, error_msg = PGNValidator.validate_game(game, idx)
        if not is_valid:
            invalid_count += 1
            _skip(skipped_games, idx, game, "invalid", f"Validation error: {error_msg}")
            continue

        if game.board().fen() != chess.STARTING_FEN:
            _skip(skipped_games, idx, game, "custom_start", "Game starts from a non-standard position")
            continue

        plies = sum(1 for _ in game.mainline_moves())
        if plies < MIN_GAME_PLIES:
            _skip(skipped_games, idx, game, "too_short", f"Only {plies} plies")
            continue

        if time_control_category is not None:
            base_sec = parse_time_control_base_seconds(game.headers.get("TimeControl", ""))
            if classify_time_control(base_sec) != time_control_category:
                _skip(skipped_games, idx, game, "time_control", f"Time control category != '{time_control_category}'")
                continue

        if date_from is not None or date_to is not None:
            date_str = game.headers.get("Date", "")
            if "?" in date_str or not date_str:
                _skip(skipped_games, idx, game, "date", "Unknown/partial Date header, excluded by date filter")
                continue
            if date_from is not None and date_str < date_from:
                _skip(skipped_games, idx, game, "date", f"Date '{date_str}' before date_from '{date_from}'")
                continue
            if date_to is not None and date_str > date_to:
                _skip(skipped_games, idx, game, "date", f"Date '{date_str}' after date_to '{date_to}'")
                continue

        if min_opponent_elo is not None:
            opp_header = "BlackElo" if color == "white" else "WhiteElo"
            opp_elo = parse_elo(game.headers.get(opp_header, ""))
            if opp_elo is None or opp_elo < min_opponent_elo:
                _skip(skipped_games, idx, game, "opponent_elo", f"Opponent Elo {opp_elo} < min_opponent_elo {min_opponent_elo}")
                continue

        headers = game.headers
        eco = headers.get("ECO", "???")
        opening = headers.get("Opening", "")
        if not opening or opening == "?":
            opening = opening_from_eco_url(headers.get("ECOUrl", "")) or (f"ECO {eco}" if eco not in ("", "?", "???") else "Unknown Opening")
            # Written back so every downstream reader of the raw headers
            # (game analyzer, opening tracker) sees the same name.
            headers["Opening"] = opening

        metadata = GameMetadata(
            game_id=f"game_{idx + 1}",
            white=headers.get("White", "Unknown"),
            black=headers.get("Black", "Unknown"),
            result=headers.get("Result", "*"),
            date=headers.get("Date", "????.??.??"),
            event=headers.get("Event", "Unknown"),
            site=headers.get("Site", "Unknown"),
            round=headers.get("Round", "-"),
            eco=eco,
            opening=opening,
            initial_fen=game.board().fen(),
            time_control=headers.get("TimeControl", "Unknown"),
            white_elo=parse_elo(headers.get("WhiteElo", "")),
            black_elo=parse_elo(headers.get("BlackElo", "")),
            ply_count=plies,
            link=_game_link(headers),
            termination=headers.get("Termination", ""),
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
