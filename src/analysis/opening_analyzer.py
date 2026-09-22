from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import chess
from src.engine.classification import MoveAnalysisData

@dataclass
class OpeningDeviation:
    game_id: str
    eco: str
    opening: str
    move_number: int
    played_san: str
    best_san: str
    fen_before: str
    cpl: float
    eval_after_black: float

@dataclass
class OpeningBranchSummary:
    eco: str
    opening_name: str
    move_sequence: str
    games_count: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    total_cpl: float = 0.0
    mistakes_count: int = 0
    deviations: List[OpeningDeviation] = field(default_factory=list)

class OpeningAnalyzer:
    """Analyzes opening performance, move branches, deviations from engine top moves, and early CPL loss."""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.opening_plies = config.get("analysis", {}).get("analyze_opening_plies", 20)

    def find_opening_deviations(self, analyses: List[MoveAnalysisData]) -> List[OpeningDeviation]:
        deviations: List[OpeningDeviation] = []
        inaccuracy_threshold = self.config.get("analysis", {}).get("inaccuracy_cp", 50)

        for item in analyses:
            if item.move_number <= self.opening_plies:
                # Check if move deviates from engine top move with meaningful loss
                if item.best_move and item.uci != item.best_move and item.loss_for_player >= inaccuracy_threshold:
                    deviations.append(OpeningDeviation(
                        game_id=item.game_id,
                        eco=item.eco,
                        opening=item.opening,
                        move_number=item.move_number,
                        played_san=item.san,
                        best_san=self._uci_to_san(item.fen_before, item.best_move),
                        fen_before=item.fen_before,
                        cpl=item.loss_for_player,
                        eval_after_black=item.eval_after_black_perspective
                    ))

        return deviations

    @staticmethod
    def _uci_to_san(fen_before: str, best_move_uci: str) -> str:
        """Convert the engine's UCI best move to SAN for the given position.

        Falls back to the raw UCI string if the position/move can't be parsed
        (e.g. malformed data), rather than raising and aborting the report.
        """
        try:
            board = chess.Board(fen_before)
            move = chess.Move.from_uci(best_move_uci)
            return board.san(move)
        except (ValueError, AssertionError):
            return best_move_uci
