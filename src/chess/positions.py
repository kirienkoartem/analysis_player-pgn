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
