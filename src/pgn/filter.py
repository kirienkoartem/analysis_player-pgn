from collections import Counter
import re
from typing import List
import chess.pgn

def normalize_name(name: str) -> str:
    """Normalizes player name for matching (lowercased, stripped, whitespace collapsed)."""
    if not name:
        return ""
    name = name.strip().lower()
    return re.sub(r'\s+', ' ', name)

class PGNFilter:
    @staticmethod
    def auto_detect_black_player(raw_games: List[chess.pgn.Game]) -> str:
        """Finds the most frequent Black player name in the given games list."""
        counter: Counter = Counter()
        for game in raw_games:
            if game and "Black" in game.headers:
                b_name = game.headers["Black"].strip()
                if b_name and b_name != "?":
                    counter[b_name] += 1
        if not counter:
            return ""
        most_common = counter.most_common(1)[0][0]
        return most_common

    @staticmethod
    def is_target_black(game: chess.pgn.Game, target_name: str) -> bool:
        if not target_name:
            return True
        black_header = game.headers.get("Black", "")
        return normalize_name(black_header) == normalize_name(target_name)
