import chess.pgn
from typing import Tuple, Optional

class PGNValidator:
    @staticmethod
    def validate_game(game: chess.pgn.Game, index: int) -> Tuple[bool, Optional[str]]:
        if game is None:
            return False, "Null or unparseable game"

        # Check moves
        try:
            node = game
            ply_count = 0
            while node.variations:
                next_node = node.variation(0)
                ply_count += 1
                node = next_node
        except Exception as e:
            return False, f"Corrupted move sequence: {e}"

        if ply_count == 0:
            return False, "Empty game (no moves)"

        return True, None
