import pytest
import chess
import chess.pgn
import io
from src.pgn.loader import load_pgn_games
from src.engine.evaluator import PositionEvaluator
from src.analysis.game_analyzer import GameAnalyzer
from src.analysis.error_analyzer import ErrorAnalyzer
from src.analysis.opening_analyzer import OpeningAnalyzer
from src.analysis.pattern_analyzer import PatternAnalyzer
from src.analysis.batch_analyzer import BatchAnalyzer
from src.engine.classification import MoveClassification, MoveAnalysisData, EngineEvaluation

SAMPLE_PGN = """[Event "Test Game"]
[Site "Local"]
[Date "2023.01.01"]
[Round "1"]
[White "White Player"]
[Black "Black Target"]
[Result "0-1"]
[ECO "C50"]
[Opening "Italian Game"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 0-1
"""

def test_game_analyzer(tmp_path):
    pgn_path = tmp_path / "game.pgn"
    pgn_path.write_text(SAMPLE_PGN, encoding="utf-8")

    load_res = load_pgn_games(str(pgn_path), target_player="Black Target")
    record = load_res.filtered_games[0]

    cfg = {
        "stockfish": {"path": ""},
        "analysis": {"main_depth": 10, "critical_depth": 14, "inaccuracy_cp": 50, "mistake_cp": 100, "blunder_cp": 200},
        "cache": {"db_path": str(tmp_path / "cache.sqlite")}
    }

    evaluator = PositionEvaluator(cfg)
    analyzer = GameAnalyzer(cfg, evaluator)

    analyses = analyzer.analyze_game(record)
    assert len(analyses) == 3  # 1...e5, 2...Nc6, 3...Bc5
    assert analyses[0].san == "e5"
    assert analyses[0].side == "black"
    assert analyses[0].eco == "C50"

def test_opening_and_pattern_analyzer(tmp_path):
    pgn_path = tmp_path / "game.pgn"
    pgn_path.write_text(SAMPLE_PGN, encoding="utf-8")

    cfg = {
        "input": {"pgn_path": str(pgn_path)},
        "stockfish": {"path": ""},
        "target_player": {"name": "Black Target"},
        "analysis": {"main_depth": 10, "critical_depth": 14, "inaccuracy_cp": 50, "analyze_opening_plies": 20},
        "cache": {"db_path": str(tmp_path / "cache.sqlite")}
    }

    batch_analyzer = BatchAnalyzer(cfg)
    res = batch_analyzer.analyze_batch(limit=1)

    assert res.games_processed == 1
    assert len(res.move_analyses) == 3

    op_analyzer = OpeningAnalyzer(cfg)
    devs = op_analyzer.find_opening_deviations(res.move_analyses)
    assert isinstance(devs, list)

    pat_analyzer = PatternAnalyzer(cfg)
    pats = pat_analyzer.detect_recurring_patterns(res.move_analyses)
    assert isinstance(pats, list)


def _mistake(game_id, fen, san, cpl=150.0):
    ev = EngineEvaluation("cp", 0.0, 10)
    return MoveAnalysisData(
        game_id=game_id, move_number=11, fullmove_number=6, side="white",
        san=san, uci="e1e2", fen_before=fen, fen_after=fen,
        eval_before_white_perspective=ev, eval_after_white_perspective=ev,
        eval_before_black_perspective=0.0, eval_after_black_perspective=0.0,
        loss_for_player=cpl, best_move="g1e2", classification=MoveClassification.MISTAKE,
        phase="MIDDLEGAME", eco="E70", opening="King's Indian", pv=["g1e2"],
    )


def test_pattern_analyzer_requires_two_distinct_games():
    fen = "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2NB4/PP3PPP/R1BQK1NR w KQ - 2 6"

    # Same exact position + same wrong move, but only within ONE game
    # (played twice, e.g. via repetition) -> must NOT count as "recurring".
    same_game_twice = [_mistake("game_1", fen, "Be3"), _mistake("game_1", fen, "Be3")]
    pats = PatternAnalyzer({}).detect_recurring_patterns(same_game_twice)
    assert pats == []

    # Same exact position + same wrong move, across two DIFFERENT games -> recurring.
    two_games = [_mistake("game_1", fen, "Be3", cpl=114.0), _mistake("game_9", fen, "Be3", cpl=116.0)]
    pats = PatternAnalyzer({}).detect_recurring_patterns(two_games)
    assert len(pats) == 1
    assert pats[0].occurrences == 2
    assert pats[0].played_san == "Be3"
    assert set(pats[0].sample_games) == {"game_1", "game_9"}
    assert pats[0].avg_cpl == 115.0


def test_pattern_analyzer_ignores_good_moves():
    fen = "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2NB4/PP3PPP/R1BQK1NR w KQ - 2 6"
    good = MoveAnalysisData(
        game_id="game_1", move_number=11, fullmove_number=6, side="white",
        san="Nge2", uci="g1e2", fen_before=fen, fen_after=fen,
        eval_before_white_perspective=EngineEvaluation("cp", 0.0, 10),
        eval_after_white_perspective=EngineEvaluation("cp", 0.0, 10),
        eval_before_black_perspective=0.0, eval_after_black_perspective=0.0,
        loss_for_player=0.0, best_move="g1e2", classification=MoveClassification.GOOD,
        phase="MIDDLEGAME", eco="E70", opening="King's Indian", pv=["g1e2"],
    )
    good_2 = MoveAnalysisData(**{**good.__dict__, "game_id": "game_2"})
    pats = PatternAnalyzer({}).detect_recurring_patterns([good, good_2])
    assert pats == []
