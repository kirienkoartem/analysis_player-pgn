import os
import json
from typing import Dict, Any, Optional
from src.aggregation.opponent_profile import OpponentProfile
from src.chess.openings import VariationNode


def _variation_node_to_dict(node: VariationNode, max_depth: int = 6, _depth: int = 0) -> Dict[str, Any]:
    """Recursively serializes a VariationNode tree. Depth-limited (rather
    than just relying on build_variation_tree's own max_plies) so a
    hand-built or future deeper tree can't blow up JSON output size."""
    total = node.wins + node.draws + node.losses
    return {
        "san": node.san_move,
        "move_sequence": node.move_sequence,
        "fullmove_number": node.fullmove_number,
        "side": node.side,
        "games_count": node.games_count,
        "wins": node.wins,
        "draws": node.draws,
        "losses": node.losses,
        "win_rate": (node.wins / total) if total else None,
        "children": (
            {san: _variation_node_to_dict(child, max_depth, _depth + 1) for san, child in node.children.items()}
            if _depth < max_depth else {}
        ),
    }


class JSONExporter:
    """Exports structured profile data to JSON format - the single source of
    truth for anything a downstream report (Markdown here, a branded DOCX
    brief built separately) needs, so that document never has to hand-type
    a number the pipeline already computed."""

    @staticmethod
    def export_json(profile: OpponentProfile, output_path: str, run_metadata: Optional[Dict[str, Any]] = None):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        data = {
            "target_player_name": profile.target_player_name,
            "target_color": profile.target_color,
            "total_games_analyzed": profile.total_games_analyzed,
            "run_metadata": run_metadata or {},
            "overall_stats": {
                "sample_size": profile.overall_stats.sample_size,
                "confidence_level": profile.overall_stats.confidence_level.value,
                "wins": profile.overall_stats.wins,
                "draws": profile.overall_stats.draws,
                "losses": profile.overall_stats.losses,
                "win_rate": profile.overall_stats.win_rate,
                "draw_rate": profile.overall_stats.draw_rate,
                "loss_rate": profile.overall_stats.loss_rate,
                "mean_cpl": profile.overall_stats.mean_cpl,
                "median_cpl": profile.overall_stats.median_cpl,
                "std_cpl": profile.overall_stats.std_cpl
            },
            "repertoire": [
                {
                    "opening_name": item.opening_name,
                    "eco": item.eco,
                    "sample_size": item.summary.sample_size,
                    "confidence_level": item.summary.confidence_level.value,
                    "wins": item.summary.wins,
                    "draws": item.summary.draws,
                    "losses": item.summary.losses,
                    "win_rate": item.summary.win_rate,
                    "draw_rate": item.summary.draw_rate,
                    "loss_rate": item.summary.loss_rate,
                    "mean_cpl": item.summary.mean_cpl,
                    "median_cpl": item.summary.median_cpl,
                    "baseline_cpl_diff": item.summary.baseline_cpl_diff,
                    "expected_score_rate": item.expected_score_rate,
                    "elo_sample_size": item.elo_sample_size,
                }
                for item in profile.repertoire
            ],
            "recurring_patterns": [
                {
                    "pattern_id": pat.pattern_id,
                    "description": pat.description,
                    "fen_before": pat.fen_before,
                    "played_san": pat.played_san,
                    "best_move": pat.best_move,
                    "eco": pat.eco,
                    "opening": pat.opening,
                    "games_count": pat.occurrences,
                    "avg_cpl": pat.avg_cpl,
                    "median_cpl": pat.median_cpl,
                    "sample_games": pat.sample_games,
                }
                for pat in profile.top_recurring_patterns
            ],
            "problem_clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "category": c.category,
                    "opening_or_variation": c.opening_or_variation,
                    "occurrences": c.occurrences,
                    "games_count": c.games_count,
                    "error_rate": c.error_rate,
                    "avg_cpl": c.avg_cpl,
                    "median_cpl": c.median_cpl,
                }
                for c in profile.top_problem_clusters
            ],
            "opening_deviations": [
                {
                    "game_id": dev.game_id,
                    "eco": dev.eco,
                    "opening": dev.opening,
                    "move_number": dev.fullmove_number,
                    "played_san": dev.played_san,
                    "best_san": dev.best_san,
                    "fen_before": dev.fen_before,
                    "cpl": dev.cpl,
                }
                for dev in profile.opening_deviations
            ],
            "critical_positions": [
                {
                    "game_id": pos.game_id,
                    "move_number": pos.fullmove_number,
                    "ply": pos.move_number,
                    "played_san": pos.san,
                    "uci": pos.uci,
                    "best_move": pos.best_move,
                    "cpl": pos.loss_for_player,
                    "classification": pos.classification.value,
                    "fen_before": pos.fen_before,
                    "pv": pos.pv
                }
                for pos in profile.critical_positions
            ],
            "time_trouble_summary": profile.time_trouble_summary or {},
            "opening_tree": _variation_node_to_dict(profile.opening_tree) if profile.opening_tree else None,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
