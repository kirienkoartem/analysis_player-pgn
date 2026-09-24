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
    def auto_detect_player(raw_games: List[chess.pgn.Game], color: str = "black") -> str:
        """Finds the most frequent player name for the given color (white/black) in the games list."""
        header_key = "White" if color == "white" else "Black"
        counter: Counter = Counter()
        for game in raw_games:
            if game and header_key in game.headers:
                name = game.headers[header_key].strip()
                if name and name != "?":
                    counter[name] += 1
        if not counter:
            return ""
        most_common = counter.most_common(1)[0][0]
        return most_common

    @staticmethod
    def auto_detect_black_player(raw_games: List[chess.pgn.Game]) -> str:
        """Backward-compatible alias for auto_detect_player(raw_games, 'black')."""
        return PGNFilter.auto_detect_player(raw_games, "black")

    @staticmethod
    def is_target_color(game: chess.pgn.Game, target_name: str, color: str = "black") -> bool:
        if not target_name:
            return True
        header_key = "White" if color == "white" else "Black"
        header_val = game.headers.get(header_key, "")
        return normalize_name(header_val) == normalize_name(target_name)

    @staticmethod
    def is_target_black(game: chess.pgn.Game, target_name: str) -> bool:
        """Backward-compatible alias for is_target_color(game, target_name, 'black')."""
        return PGNFilter.is_target_color(game, target_name, "black")
