from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum
import chess

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
    move_number: int      # absolute ply count in the game (both colors) - internal use, e.g. opening-phase cutoffs
    fullmove_number: int  # human move number (e.g. "12" as in "12.Nf3" or "12...Nf6") - use this for display
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
    error_category: str = "NONE"  # TACTICAL/POSITIONAL/CALCULATION/OPENING/ENDGAME/UNCLASSIFIED/NONE
    clock_seconds: Optional[float] = None  # time remaining after this move (from PGN %clk), if present
    time_pressure: bool = False  # clock_seconds below the game's own time-control-relative threshold
    time_control_category: str = "unknown"  # bullet/blitz/rapid/classical/unknown

MATE_CP_EQUIVALENT = 1000.0
CP_CLAMP = 1000.0


def normalize_eval_for_player(engine_eval: EngineEvaluation, color: chess.Color = chess.BLACK) -> float:
    """
    Normalizes Stockfish evaluation to the target player's perspective (either color).
    Stockfish gives score from White perspective (+ means good for White, - means good for Black).
    For the target player's perspective: + always means good for that player.
    White_score stays as-is for White, is negated for Black.

    Both mate and cp scores are capped to +/- MATE_CP_EQUIVALENT / CP_CLAMP. This
    matters for cp too: without a ceiling, a position that goes from "White is
    up a queen" (+2500) to "White is up a rook" (+1500) after a mutual-blunder
    exchange registers as a fake 1000 cp "loss" even though both positions are
    equally, completely winning. Capping both sides of the comparison removes
    that artifact.

    IMPORTANT: mate_in must never be exactly 0 here - that value is genuinely
    ambiguous (which side just got mated cannot be recovered from the number
    alone). Callers must resolve an already-checkmate board via board state
    (see PositionEvaluator.evaluate_board) before ever constructing an
    EngineEvaluation with mate_in == 0.
    """
    if engine_eval.eval_type == "mate":
        mate_in = engine_eval.score
        if mate_in > 0:
            # White mates Black soon -> White is winning heavily
            white_cp = MATE_CP_EQUIVALENT - (mate_in * 10)
        else:
            # Black mates White soon -> White is losing heavily
            white_cp = -MATE_CP_EQUIVALENT - (mate_in * 10)
    else:
        white_cp = max(-CP_CLAMP, min(CP_CLAMP, engine_eval.score))

    return white_cp if color == chess.WHITE else -white_cp


def normalize_eval_for_black(engine_eval: EngineEvaluation) -> float:
    """Backward-compatible alias: normalizes to Black's perspective."""
    return normalize_eval_for_player(engine_eval, chess.BLACK)

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
