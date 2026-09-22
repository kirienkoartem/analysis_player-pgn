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
from src.engine.classification import MoveClassification

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
