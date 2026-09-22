import chess
from dataclasses import dataclass
from typing import List, Set, Optional

@dataclass
class PositionFingerprint:
    pawn_structure_fen: str  # FEN with only pawns and kings
    material_key: str        # e.g., "rnbqkp-rnbqkp"
    king_safety_key: str     # King castling / position key
    pawn_skeleton_hash: str  # Pawn pawn structure description (e.g., e4-c5-d6)

class PatternDetector:
    @staticmethod
    def get_pawn_structure_fen(board: chess.Board) -> str:
        """Returns a simplified FEN containing only Kings and Pawns."""
        pawn_board = board.copy()
        for sq in chess.SQUARES:
            p = pawn_board.piece_at(sq)
            if p and p.piece_type not in (chess.PAWN, chess.KING):
                pawn_board.remove_piece_at(sq)
        return pawn_board.board_fen()

    @staticmethod
    def get_material_key(board: chess.Board) -> str:
        """Returns a sorted string representation of remaining pieces for White and Black."""
        white_pieces = []
        black_pieces = []
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p:
                char = p.symbol()
                if p.color == chess.WHITE:
                    white_pieces.append(char.upper())
                else:
                    black_pieces.append(char.lower())
        white_pieces.sort()
        black_pieces.sort()
        return f"{''.join(white_pieces)}-{''.join(black_pieces)}"

    @staticmethod
    def create_fingerprint(board: chess.Board) -> PositionFingerprint:
        pawn_fen = PatternDetector.get_pawn_structure_fen(board)
        mat_key = PatternDetector.get_material_key(board)
        w_king_sq = board.king(chess.WHITE)
        b_king_sq = board.king(chess.BLACK)
        king_key = f"wK:{w_king_sq}-bK:{b_king_sq}"

        return PositionFingerprint(
            pawn_structure_fen=pawn_fen,
            material_key=mat_key,
            king_safety_key=king_key,
            pawn_skeleton_hash=f"{pawn_fen}|{mat_key}"
        )
