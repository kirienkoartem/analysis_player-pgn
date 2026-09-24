import pytest
import chess
from src.engine.classification import (
    EngineEvaluation,
    MoveClassification,
    normalize_eval_for_black,
    normalize_eval_for_player,
    calculate_loss_for_player,
    classify_move
)
from src.engine.evaluator import SQLiteEngineCache, PositionEvaluator
from src.engine.stockfish import StockfishEngine

def test_normalize_eval_for_black():
    # White perspective +100 cp -> Black perspective -100 cp
    eval_cp_white_plus = EngineEvaluation(eval_type="cp", score=100.0, depth=18)
    assert normalize_eval_for_black(eval_cp_white_plus) == -100.0

    # White perspective -150 cp -> Black perspective +150 cp (Good for Black)
    eval_cp_white_minus = EngineEvaluation(eval_type="cp", score=-150.0, depth=18)
    assert normalize_eval_for_black(eval_cp_white_minus) == 150.0

    # White perspective mate in +2 -> Black perspective -9980 cp
    eval_mate_white = EngineEvaluation(eval_type="mate", score=2.0, depth=18)
    assert normalize_eval_for_black(eval_mate_white) == -9980.0

    # White perspective mate in -3 (Black mates White) -> Black perspective +9970 cp
    eval_mate_black = EngineEvaluation(eval_type="mate", score=-3.0, depth=18)
    assert normalize_eval_for_black(eval_mate_black) == 9970.0

def test_normalize_eval_for_player_white():
    # White perspective +100 cp -> White perspective stays +100 cp
    eval_cp_white_plus = EngineEvaluation(eval_type="cp", score=100.0, depth=18)
    assert normalize_eval_for_player(eval_cp_white_plus, chess.WHITE) == 100.0

    # White perspective -150 cp -> White perspective stays -150 cp
    eval_cp_white_minus = EngineEvaluation(eval_type="cp", score=-150.0, depth=18)
    assert normalize_eval_for_player(eval_cp_white_minus, chess.WHITE) == -150.0

    # White mates in +2 -> great for White (+9980 cp)
    eval_mate_white = EngineEvaluation(eval_type="mate", score=2.0, depth=18)
    assert normalize_eval_for_player(eval_mate_white, chess.WHITE) == 9980.0

    # Black mates White in -3 -> terrible for White (-9970 cp)
    eval_mate_black = EngineEvaluation(eval_type="mate", score=-3.0, depth=18)
    assert normalize_eval_for_player(eval_mate_black, chess.WHITE) == -9970.0

def test_normalize_eval_for_player_matches_black_alias():
    for score, etype in [(100.0, "cp"), (-150.0, "cp"), (2.0, "mate"), (-3.0, "mate")]:
        ev = EngineEvaluation(eval_type=etype, score=score, depth=18)
        assert normalize_eval_for_player(ev, chess.BLACK) == normalize_eval_for_black(ev)

def test_normalize_eval_for_player_white_is_negation_of_black():
    for score, etype in [(100.0, "cp"), (-150.0, "cp"), (2.0, "mate"), (-3.0, "mate")]:
        ev = EngineEvaluation(eval_type=etype, score=score, depth=18)
        assert normalize_eval_for_player(ev, chess.WHITE) == -normalize_eval_for_player(ev, chess.BLACK)

def test_calculate_loss_for_player():
    # Before move: +100 cp for Black. After move: -80 cp for Black.
    # Loss = 100 - (-80) = 180 cp loss
    loss = calculate_loss_for_player(100.0, -80.0)
    assert loss == 180.0

    # Improving move: Before +50, After +100. Loss should be 0.
    loss_imp = calculate_loss_for_player(50.0, 100.0)
    assert loss_imp == 0.0

def test_classify_move():
    cfg = {"analysis": {"inaccuracy_cp": 50, "mistake_cp": 100, "blunder_cp": 200}}
    assert classify_move(20, cfg) == MoveClassification.GOOD
    assert classify_move(60, cfg) == MoveClassification.INACCURACY
    assert classify_move(120, cfg) == MoveClassification.MISTAKE
    assert classify_move(250, cfg) == MoveClassification.BLUNDER

def test_sqlite_cache_and_key(tmp_path):
    db_file = str(tmp_path / "cache.sqlite")
    cache = SQLiteEngineCache(db_file)

    fen = chess.STARTING_FEN
    key1 = cache.generate_cache_key(fen, 18, 1, "SF_v16")
    key2 = cache.generate_cache_key(fen, 18, 1, "SF_v16")
    key3 = cache.generate_cache_key(fen, 24, 1, "SF_v16")

    assert key1 == key2
    assert key1 != key3

    eval_obj = EngineEvaluation(eval_type="cp", score=25.0, depth=18, best_move="e2e4", pv=["e2e4", "e7e5"])
    cache.set(fen, 18, 1, "SF_v16", eval_obj)

    cached_obj = cache.get(fen, 18, 1, "SF_v16")
    assert cached_obj is not None
    assert cached_obj.score == 25.0
    assert cached_obj.best_move == "e2e4"
    assert cached_obj.pv == ["e2e4", "e7e5"]
