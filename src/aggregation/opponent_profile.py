import chess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from src.engine.classification import MoveAnalysisData
from src.analysis.opening_analyzer import OpeningDeviation
from src.analysis.pattern_analyzer import RecurringPattern
from src.aggregation.statistics import StatisticalSummary, StatisticsAggregator, elo_expected_score
from src.aggregation.clustering import ProblemCluster, ErrorClusterer
from src.pgn.loader import LoadPGNResult
from src.chess.openings import OpeningTracker, VariationNode

@dataclass
class OpeningRepertoireItem:
    opening_name: str  # family name (sub-variations collapsed together)
    eco: str           # all contributing ECO codes, e.g. "E61/E70"
    summary: StatisticalSummary
    expected_score_rate: Optional[float] = None  # Elo-expected score (0..1), if Elo data available
    elo_sample_size: int = 0                     # games where both players' Elo were known

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
    opening_tree: Optional[VariationNode] = None

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

        # Group games by opening FAMILY (e.g. "King's Indian Defense" rather
        # than each of its ECO sub-variations E61/E70/... separately) so a
        # report doesn't need manual re-summing to see the whole opening.
        win_result = "1-0" if color == "white" else "0-1"
        loss_result = "0-1" if color == "white" else "1-0"

        opening_games: Dict[str, Dict[str, Any]] = {}
        for game in pgn_result.filtered_games:
            family = OpeningTracker.family_name(game.metadata.opening)
            if family not in opening_games:
                opening_games[family] = {"ecos": set(), "results": [], "cpls": [], "elo_pairs": []}
            bucket = opening_games[family]
            bucket["ecos"].add(game.metadata.eco)
            bucket["results"].append(game.metadata.result)

            own_elo = game.metadata.white_elo if color == "white" else game.metadata.black_elo
            opp_elo = game.metadata.black_elo if color == "white" else game.metadata.white_elo
            if own_elo is not None and opp_elo is not None:
                actual = 1.0 if game.metadata.result == win_result else (0.5 if game.metadata.result == "1/2-1/2" else 0.0)
                bucket["elo_pairs"].append((actual, elo_expected_score(own_elo, opp_elo)))

        for m in move_analyses:
            family = OpeningTracker.family_name(m.opening)
            if family in opening_games:
                opening_games[family]["cpls"].append(m.loss_for_player)

        repertoire_items: List[OpeningRepertoireItem] = []
        for family, data in opening_games.items():
            op_summary = StatisticsAggregator.compute_statistical_summary(
                cpl_list=data["cpls"],
                results_list=data["results"],
                baseline_mean_cpl=baseline_mean_cpl,
                config=config,
                color=color
            )
            elo_pairs = data["elo_pairs"]
            expected_rate = (sum(e for _, e in elo_pairs) / len(elo_pairs)) if elo_pairs else None
            repertoire_items.append(OpeningRepertoireItem(
                opening_name=family,
                eco="/".join(sorted(data["ecos"])),
                summary=op_summary,
                expected_score_rate=expected_rate,
                elo_sample_size=len(elo_pairs),
            ))

        repertoire_items.sort(key=lambda r: r.summary.sample_size, reverse=True)

        opening_tree = OpeningTracker.build_variation_tree(
            pgn_result.filtered_games,
            target_color=chess.WHITE if color == "white" else chess.BLACK,
        )

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
        # Same breakdown, but split further by time control category: a
        # blended "time trouble" number across mixed bullet/blitz/rapid
        # games (a real PGN export usually has all three) hides that e.g.
        # bullet time pressure and classical time pressure are very
        # different situations for a human preparing to play this opponent.
        by_category: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}
        for cat in {m.time_control_category for m in clocked}:
            cat_moves = [m for m in clocked if m.time_control_category == cat]
            by_category[cat] = {
                "time_trouble": _bucket_stats([m for m in cat_moves if m.time_pressure]),
                "normal_time": _bucket_stats([m for m in cat_moves if not m.time_pressure]),
            }
        time_trouble_summary["by_time_control"] = by_category

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
            time_trouble_summary=time_trouble_summary,
            opening_tree=opening_tree,
        )
