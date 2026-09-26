import re
import chess
import chess.pgn
from dataclasses import dataclass
from typing import List, Optional, Tuple

_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")


def parse_clock_seconds(comment: str) -> Optional[float]:
    """Parses a lichess-style '[%clk H:MM:SS]' comment into seconds remaining."""
    if not comment:
        return None
    m = _CLK_RE.search(comment)
    if not m:
        return None
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def parse_time_control_base_seconds(time_control: str) -> Optional[int]:
    """Parses a PGN TimeControl header ('180+2', '600', '-') into base seconds.

    Returns None for unlimited/correspondence controls ('-', 'Unknown', or
    anything that doesn't start with a plain integer), since there is no
    meaningful "time pressure" concept without a clock.
    """
    if not time_control:
        return None
    base_str = time_control.split("+")[0].strip()
    if not base_str.isdigit():
        return None
    return int(base_str)


def classify_time_control(base_seconds: Optional[int]) -> str:
    """Buckets a time control into the usual online-chess categories."""
    if base_seconds is None:
        return "unknown"
    if base_seconds < 180:
        return "bullet"
    if base_seconds < 600:
        return "blitz"
    if base_seconds < 1800:
        return "rapid"
    return "classical"


def time_pressure_threshold_seconds(base_seconds: Optional[int], fraction: float = 0.10, floor_sec: float = 10.0, fallback_sec: float = 30.0) -> float:
    """A "low on time" threshold scaled to the game's own base time, instead
    of one flat number for every time control. A flat 30s threshold means
    "almost the entire clock" in bullet but a fairly ordinary moment in
    classical - scaling by a fraction of the base time (floored at floor_sec
    so bullet doesn't become trivially "always in time pressure") makes the
    comparison mean roughly the same thing across time controls. Falls back
    to fallback_sec (the old flat default) when the time control is unknown
    (correspondence, or missing TimeControl header).
    """
    if base_seconds is None:
        return fallback_sec
    return max(floor_sec, base_seconds * fraction)


@dataclass
class TargetMovePosition:
    move_number: int
    fullmove_number: int
    color: chess.Color  # chess.BLACK
    san: str
    uci: str
    fen_before: str
    fen_after: str
    board_before: chess.Board
    board_after: chess.Board
    clock_seconds: Optional[float] = None  # time remaining after this move, if present in PGN

def extract_target_player_moves(game: chess.pgn.Game, target_color: chess.Color = chess.BLACK) -> List[TargetMovePosition]:
    """
    Extracts all positions immediately before and after each move made by target_color (e.g. Black).
    """
    moves: List[TargetMovePosition] = []
    board = game.board()
    ply = 0

    node = game
    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        fen_before = board.fen()
        board_before = board.copy()

        current_color = board.turn
        fullmove_num = board.fullmove_number

        board.push(move)
        fen_after = board.fen()
        board_after = board.copy()

        ply += 1

        if current_color == target_color:
            san = board_before.san(move)
            uci = move.uci()
            moves.append(TargetMovePosition(
                move_number=ply,
                fullmove_number=fullmove_num,
                color=current_color,
                san=san,
                uci=uci,
                fen_before=fen_before,
                fen_after=fen_after,
                board_before=board_before,
                board_after=board_after,
                clock_seconds=parse_clock_seconds(next_node.comment)
            ))

        node = next_node

    return moves
