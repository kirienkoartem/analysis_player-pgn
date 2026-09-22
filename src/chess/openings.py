import chess
import chess.pgn
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

@dataclass
class VariationNode:
    san_move: str
    move_sequence: str  # e.g. "1.e4 c5 2.Nf3"
    eco: str
    opening_name: str
    games_count: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    total_cpl: float = 0.0
    children: Dict[str, 'VariationNode'] = field(default_factory=dict)

class OpeningTracker:
    @staticmethod
    def get_eco_and_opening(game: chess.pgn.Game) -> Tuple[str, str]:
        headers = game.headers
        eco = headers.get("ECO", "???")
        opening = headers.get("Opening", "Unknown Opening")
        return eco, opening

    @staticmethod
    def extract_opening_moves(game: chess.pgn.Game, plies: int = 20) -> Tuple[str, List[str]]:
        """Extracts opening SAN move sequence up to specified plies."""
        moves: List[str] = []
        board = game.board()
        node = game
        count = 0
        while node.variations and count < plies:
            next_node = node.variation(0)
            move = next_node.move
            san = board.san(move)
            moves.append(san)
            board.push(move)
            node = next_node
            count += 1

        formatted_seq = []
        for i in range(0, len(moves), 2):
            fullmove = (i // 2) + 1
            w_move = moves[i]
            if i + 1 < len(moves):
                b_move = moves[i+1]
                formatted_seq.append(f"{fullmove}.{w_move} {b_move}")
            else:
                formatted_seq.append(f"{fullmove}.{w_move}")

        return " ".join(formatted_seq), moves
