from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum

class MoveClassification(str, Enum):
    GOOD = "GOOD"
    INACCURACY = "INACCURACY"
    MISTAKE = "MISTAKE"
    BLUNDER = "BLUNDER"

@dataclass
class EngineEvaluation:
    eval_type: str  # "cp" or "mate"
    score: float    # White perspective value from Stockfish (cp or mate count)
    depth: int
    multipv: int = 1
    best_move: Optional[str] = None
    pv: List[str] = None
    wdl: Optional[List[float]] = None  # [win, draw, loss] probabilities from White perspective

    def __post_init__(self):
        if self.pv is None:
            self.pv = []

@dataclass
class MoveAnalysisData:
    game_id: str
    move_number: int
    side: str  # "black"
    san: str
    uci: str
    fen_before: str
    fen_after: str
    eval_before_white_perspective: EngineEvaluation
    eval_after_white_perspective: EngineEvaluation
    eval_before_black_perspective: float  # Normalized score where positive is good for Black
    eval_after_black_perspective: float   # Normalized score where positive is good for Black
    loss_for_player: float                # Centipawn loss (positive = drop in Black's score)
    best_move: str
    classification: MoveClassification
    phase: str
    eco: str
    opening: str
    pv: List[str]
    wdl: Optional[List[float]] = None
    is_critical: bool = False

def normalize_eval_for_black(engine_eval: EngineEvaluation) -> float:
    """
    Normalizes Stockfish evaluation to Black's perspective.
    Stockfish gives score from White perspective (+ means good for White, - means good for Black).
    For Black perspective: + means good for Black, - means good for White.
    So Black_score = - White_score.
    Mate scores are capped to +/- 10000 cp equivalents for analysis.
    """
    if engine_eval.eval_type == "mate":
        mate_in = engine_eval.score
        if mate_in > 0:
            # White mates Black -> very bad for Black (-10000 cp)
            white_cp = 10000 - (mate_in * 10)
        else:
            # Black mates White -> very good for Black (+10000 cp)
            white_cp = -10000 - (mate_in * 10)
        return -white_cp
    else:
        return -engine_eval.score

def calculate_loss_for_player(score_before_black: float, score_after_black: float) -> float:
    """
    Calculates centipawn loss for Black.
    loss_for_player = score_before_black - score_after_black.
    If position was +1.0 for Black and after move is -0.5 for Black,
    loss_for_player = +1.0 - (-0.5) = +1.5 (150 centipawns loss).
    Loss is clamped at 0 (improving move has 0 loss).
    """
    loss = score_before_black - score_after_black
    return max(0.0, loss)

def classify_move(loss_cp: float, config: Dict[str, Any]) -> MoveClassification:
    inaccuracy_cp = config.get("analysis", {}).get("inaccuracy_cp", 50)
    mistake_cp = config.get("analysis", {}).get("mistake_cp", 100)
    blunder_cp = config.get("analysis", {}).get("blunder_cp", 200)

    if loss_cp >= blunder_cp:
        return MoveClassification.BLUNDER
    elif loss_cp >= mistake_cp:
        return MoveClassification.MISTAKE
    elif loss_cp >= inaccuracy_cp:
        return MoveClassification.INACCURACY
    else:
        return MoveClassification.GOOD
