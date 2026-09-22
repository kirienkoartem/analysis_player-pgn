import pytest
import os
import json
import chess
import chess.pgn
from src.aggregation.opponent_profile import OpponentProfile
from src.aggregation.statistics import StatisticsAggregator
from src.engine.classification import MoveAnalysisData, EngineEvaluation, MoveClassification
from src.report.markdown import MarkdownReportGenerator
from src.report.json_export import JSONExporter
from src.report.pgn_export import PGNExporter

def test_reports_generation(tmp_path):
    md_file = str(tmp_path / "report.md")
    json_file = str(tmp_path / "report.json")
    pgn_file = str(tmp_path / "critical.pgn")

    summary = StatisticsAggregator.compute_statistical_summary([20.0, 100.0], ["0-1", "1-0"])

    mock_eval = EngineEvaluation("cp", 0.0, 10)
    mock_pos = MoveAnalysisData(
        game_id="g1", move_number=5, side="black", san="Nf6", uci="g8f6",
        fen_before=chess.STARTING_FEN, fen_after=chess.STARTING_FEN,
        eval_before_white_perspective=mock_eval, eval_after_white_perspective=mock_eval,
        eval_before_black_perspective=0.0, eval_after_black_perspective=-100.0,
        loss_for_player=100.0, best_move="e7e5", classification=MoveClassification.MISTAKE,
        phase="OPENING", eco="C50", opening="Italian", pv=["e7e5"]
    )

    profile = OpponentProfile(
        target_player_name="Test Opponent",
        total_games_analyzed=2,
        overall_stats=summary,
        repertoire=[],
        top_recurring_patterns=[],
        top_problem_clusters=[],
        opening_deviations=[],
        critical_positions=[mock_pos]
    )

    md_content = MarkdownReportGenerator.generate_report(profile, md_file)
    assert "# OPPONENT SCOUT REPORT: TEST OPPONENT" in md_content
    assert os.path.exists(md_file)

    JSONExporter.export_json(profile, json_file)
    assert os.path.exists(json_file)
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["target_player_name"] == "Test Opponent"

    PGNExporter.export_critical_positions_pgn(profile, pgn_file)
    assert os.path.exists(pgn_file)
