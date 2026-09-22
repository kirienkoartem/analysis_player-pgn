import os
import json
from typing import Dict, Any
from src.aggregation.opponent_profile import OpponentProfile

class JSONExporter:
    """Exports structured profile data to JSON format."""

    @staticmethod
    def export_json(profile: OpponentProfile, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        data = {
            "target_player_name": profile.target_player_name,
            "total_games_analyzed": profile.total_games_analyzed,
            "overall_stats": {
                "sample_size": profile.overall_stats.sample_size,
                "confidence_level": profile.overall_stats.confidence_level.value,
                "wins": profile.overall_stats.wins,
                "draws": profile.overall_stats.draws,
                "losses": profile.overall_stats.losses,
                "win_rate": profile.overall_stats.win_rate,
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
                    "win_rate": item.summary.win_rate,
                    "mean_cpl": item.summary.mean_cpl,
                    "median_cpl": item.summary.median_cpl,
                    "baseline_cpl_diff": item.summary.baseline_cpl_diff
                }
                for item in profile.repertoire
            ],
            "critical_positions": [
                {
                    "game_id": pos.game_id,
                    "move_number": pos.move_number,
                    "played_san": pos.san,
                    "uci": pos.uci,
                    "best_move": pos.best_move,
                    "cpl": pos.loss_for_player,
                    "classification": pos.classification.value,
                    "fen_before": pos.fen_before,
                    "pv": pos.pv
                }
                for pos in profile.critical_positions
            ]
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
