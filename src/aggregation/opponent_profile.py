from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from src.engine.classification import MoveAnalysisData
from src.analysis.opening_analyzer import OpeningDeviation
from src.analysis.pattern_analyzer import RecurringPattern
from src.aggregation.statistics import StatisticalSummary, StatisticsAggregator
from src.aggregation.clustering import ProblemCluster, ErrorClusterer
from src.pgn.loader import LoadPGNResult

@dataclass
class OpeningRepertoireItem:
    opening_name: str
    eco: str
    summary: StatisticalSummary

@dataclass
class OpponentProfile:
    target_player_name: str
    target_color: str
    total_games_analyzed: int
    overall_stats: StatisticalSummary
    repertoire: List[OpeningRepertoireItem]
    top_recurring_patterns: List[RecurringPattern]
    top_problem_clusters: List[ProblemCluster]
    opening_deviations: List[OpeningDeviation]
    critical_positions: List[MoveAnalysisData]
    time_trouble_summary: Optional[Dict[str, Any]] = None

class ProfileBuilder:
    @staticmethod
    def build_profile(
        config: Dict[str, Any],
        pgn_result: LoadPGNResult,
        move_analyses: List[MoveAnalysisData],
        patterns: List[RecurringPattern],
        deviations: List[OpeningDeviation]
    ) -> OpponentProfile:
        target_name = pgn_result.target_player
        color = pgn_result.color
        total_games = len(pgn_result.filtered_games)

        # Baseline CPL calculation across all Black moves
        all_cpls = [m.loss_for_player for m in move_analyses]
        game_results = [g.metadata.result for g in pgn_result.filtered_games]

        overall_stats = StatisticsAggregator.compute_statistical_summary(
            cpl_list=all_cpls,
            results_list=game_results,
            baseline_mean_cpl=0.0,
            config=config,
            color=color
        )

        baseline_mean_cpl = overall_stats.mean_cpl

        # Group games by opening
        opening_games: Dict[str, Dict[str, Any]] = {}
        for game in pgn_result.filtered_games:
            op_name = game.metadata.opening
            eco = game.metadata.eco
            key = f"{eco}|{op_name}"
            if key not in opening_games:
                opening_games[key] = {"eco": eco, "name": op_name, "results": [], "cpls": []}
            opening_games[key]["results"].append(game.metadata.result)

        for m in move_analyses:
            key = f"{m.eco}|{m.opening}"
            if key in opening_games:
                opening_games[key]["cpls"].append(m.loss_for_player)

        repertoire_items: List[OpeningRepertoireItem] = []
        for key, data in opening_games.items():
            op_summary = StatisticsAggregator.compute_statistical_summary(
                cpl_list=data["cpls"],
                results_list=data["results"],
                baseline_mean_cpl=baseline_mean_cpl,
                config=config,
                color=color
            )
            repertoire_items.append(OpeningRepertoireItem(
                opening_name=data["name"],
                eco=data["eco"],
                summary=op_summary
            ))

        repertoire_items.sort(key=lambda r: r.summary.sample_size, reverse=True)

        # Time trouble aggregate (moves with a parsed clock, split by threshold flag)
        def _bucket_stats(moves: List[MoveAnalysisData]) -> Optional[Dict[str, Any]]:
            if not moves:
                return None
            mistakes = sum(1 for m in moves if m.classification != "GOOD")
            return {
                "count": len(moves),
                "error_rate": mistakes / len(moves),
                "avg_cpl": sum(m.loss_for_player for m in moves) / len(moves),
            }

        clocked = [m for m in move_analyses if m.clock_seconds is not None]
        time_trouble_summary = {
            "time_trouble": _bucket_stats([m for m in clocked if m.time_pressure]),
            "normal_time": _bucket_stats([m for m in clocked if not m.time_pressure]),
        }

        # Clusters & Critical positions
        clusters = ErrorClusterer.cluster_mistakes(move_analyses)
        critical_pos = [m for m in move_analyses if m.is_critical]
        critical_pos.sort(key=lambda m: m.loss_for_player, reverse=True)

        return OpponentProfile(
            target_player_name=target_name,
            target_color=color,
            total_games_analyzed=total_games,
            overall_stats=overall_stats,
            repertoire=repertoire_items,
            top_recurring_patterns=patterns[:10],
            top_problem_clusters=clusters[:10],
            opening_deviations=deviations[:20],
            critical_positions=critical_pos[:20],
            time_trouble_summary=time_trouble_summary
        )
