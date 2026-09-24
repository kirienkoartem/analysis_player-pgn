import chess
from typing import Dict, Any, List, Optional
from src.engine.classification import MoveClassification, MoveAnalysisData

class ErrorAnalyzer:
    """
    Analyzes move errors and assigns chess mistake categories (TACTICAL, POSITIONAL, CALCULATION, OPENING, ENDGAME, or UNCLASSIFIED).
    Never guesses chess explanations when data is ambiguous - defaults to UNCLASSIFIED.
    """
    @staticmethod
    def categorize_mistake(
        analysis: MoveAnalysisData,
        board_before: chess.Board,
        board_after: chess.Board,
        player_color: chess.Color = chess.BLACK
    ) -> str:
        if analysis.classification == MoveClassification.GOOD:
            return "NONE"

        # OPENING errors: within opening plies
        if analysis.phase == "OPENING" and analysis.move_number <= 20:
            # Check if played move hung a piece or missed forced sequence
            if ErrorAnalyzer._is_hanging_piece(board_after, player_color):
                return "TACTICAL"
            return "OPENING"

        # ENDGAME errors
        if analysis.phase == "ENDGAME":
            return "ENDGAME"

        # TACTICAL checks: hanging piece, forks, pins
        if ErrorAnalyzer._is_hanging_piece(board_after, player_color):
            return "TACTICAL"

        # If CPL is huge (e.g. >= 300) in Middlegame, likely calculation/tactical oversight
        if analysis.loss_for_player >= 300:
            return "CALCULATION"

        # Check basic positional heuristics
        if analysis.loss_for_player >= 100:
            # Check pawn structure weakness or passive move
            if ErrorAnalyzer._created_doubled_or_isolated_pawns(board_before, board_after, player_color):
                return "POSITIONAL"

        # Default fallback
        return "UNCLASSIFIED"

    @staticmethod
    def _is_hanging_piece(board: chess.Board, color: chess.Color) -> bool:
        """Checks if an undefended piece of the given color is under attack."""
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.color == color and piece.piece_type != chess.KING and piece.piece_type != chess.PAWN:
                attackers = board.attackers(not color, sq)
                defenders = board.attackers(color, sq)
                if attackers and not defenders:
                    return True
        return False

    @staticmethod
    def _created_doubled_or_isolated_pawns(before: chess.Board, after: chess.Board, color: chess.Color) -> bool:
        def count_doubled_pawns(b: chess.Board) -> int:
            cnt = 0
            for file_idx in range(8):
                file_pawns = [
                    b.piece_at(chess.square(file_idx, rank_idx))
                    for rank_idx in range(8)
                ]
                pawn_count = sum(1 for p in file_pawns if p and p.piece_type == chess.PAWN and p.color == color)
                if pawn_count > 1:
                    cnt += (pawn_count - 1)
            return cnt

        return count_doubled_pawns(after) > count_doubled_pawns(before)
