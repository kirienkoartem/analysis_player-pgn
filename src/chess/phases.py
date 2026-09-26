import chess
from enum import Enum

class GamePhase(str, Enum):
    OPENING = "OPENING"
    EARLY_MIDDLEGAME = "EARLY_MIDDLEGAME"
    MIDDLEGAME = "MIDDLEGAME"
    ENDGAME = "ENDGAME"

# Piece values for material calculation
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0
}

def phase_detector(board: chess.Board, ply_number: int) -> GamePhase:
    """
    Detects game phase based on ply number and remaining non-pawn material.

    Opening: ply <= 20 (10 full moves).
    Early Middlegame: ply 21 to 32.
    Middlegame: ply > 32 (with sufficient material still on the board).
    Endgame: total non-pawn material <= 12, or no queens and <= 18.
    """
    if ply_number <= 20:
        return GamePhase.OPENING

    total_non_pawn_material = 0
    has_queens = False

    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece and piece.piece_type != chess.KING and piece.piece_type != chess.PAWN:
            total_non_pawn_material += PIECE_VALUES[piece.piece_type]
            if piece.piece_type == chess.QUEEN:
                has_queens = True

    if total_non_pawn_material <= 12 or (not has_queens and total_non_pawn_material <= 18):
        return GamePhase.ENDGAME

    if ply_number <= 32:
        return GamePhase.EARLY_MIDDLEGAME

    return GamePhase.MIDDLEGAME
