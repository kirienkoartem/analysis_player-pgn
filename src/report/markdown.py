import os
from typing import Dict, Any, List
from src.aggregation.opponent_profile import OpponentProfile

class MarkdownReportGenerator:
    """Generates a comprehensive Markdown Opponent Scout Report based on statistical and chess analysis."""

    @staticmethod
    def generate_report(
        profile: OpponentProfile,
        output_path: str,
        llm_notes: Dict[str, Any] = None,
        run_metadata: Dict[str, Any] = None,
    ) -> str:
        """Generate the Markdown report.

        llm_notes, when provided, holds optional AI-generated prose keyed by
        "patterns", "critical_positions", "final_summary" - produced by
        LLMExplainer from this same structured data. Any key missing or None
        (LLM disabled/unavailable) is simply skipped; the structured,
        data-only report below is always generated regardless.

        run_metadata, when provided, holds the actual engine/run parameters
        (depth, movetime, engine version, cache hit rate, wall-clock
        duration) as measured by this specific run - NEVER hand-type these
        into a report header, since they silently drift out of sync with
        whatever config/engine actually produced the numbers below them.
        """
        llm_notes = llm_notes or {}
        run_metadata = run_metadata or {}
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        lines: List[str] = []
        color_label = profile.target_color.capitalize()  # "White" or "Black"

        lines.append(f"# OPPONENT SCOUT REPORT: {profile.target_player_name.upper()} ({color_label.upper()})\n")
        lines.append("## 1. Executive Summary\n")
        lines.append(f"- **Target Player:** {profile.target_player_name}")
        lines.append(f"- **Total Games Analyzed (as {color_label}):** {profile.total_games_analyzed}")
        lines.append(f"- **Overall Results:** {profile.overall_stats.wins} Wins, {profile.overall_stats.draws} Draws, {profile.overall_stats.losses} Losses (Win Rate: {profile.overall_stats.win_rate:.1%})")
        lines.append(f"- **Overall Mean CPL:** {profile.overall_stats.mean_cpl:.1f} cp | **Median CPL:** {profile.overall_stats.median_cpl:.1f} cp")
        lines.append(f"- **Statistical Sample Confidence:** `{profile.overall_stats.confidence_level.value}`")

        if run_metadata:
            engine_ver = run_metadata.get("engine_version", "n/a")
            depth = run_metadata.get("main_depth")
            crit_depth = run_metadata.get("critical_depth")
            mvtime = run_metadata.get("main_movetime_ms")
            crit_mvtime = run_metadata.get("critical_movetime_ms")
            multipv = run_metadata.get("main_multipv")
            duration = run_metadata.get("analysis_duration_sec")
            hits = run_metadata.get("cache_hits")
            calls = run_metadata.get("engine_calls")
            search_desc = (
                f"movetime {mvtime}/{crit_mvtime}ms" if mvtime else f"depth {depth}/{crit_depth}"
            )
            lines.append(
                f"- **Engine:** {engine_ver}, {search_desc}, MultiPV={multipv}"
                + (f", {duration:.0f}s wall time" if duration is not None else "")
                + (f", cache hits {hits}/{(hits or 0) + (calls or 0)}" if hits is not None else "")
            )
            filters_applied = {k: v for k, v in (run_metadata.get("filters_applied") or {}).items() if v}
            if filters_applied:
                lines.append(f"- **Filters applied:** {filters_applied}")
        lines.append("")

        lines.append(f"## 2. {color_label} Repertoire\n")
        lines.append("| Opening (family) | ECO | Games | Win% | Draw% | Loss% | Avg CPL | Median CPL | Baseline Diff | Elo-Expected Score% | vs Expected | Sample Confidence |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for item in profile.repertoire:
            s = item.summary
            actual_score_rate = s.win_rate + 0.5 * s.draw_rate
            if item.expected_score_rate is not None:
                expected_col = f"{item.expected_score_rate:.1%} (n={item.elo_sample_size})"
                vs_expected_col = f"{(actual_score_rate - item.expected_score_rate):+.1%}"
            else:
                expected_col = "n/a"
                vs_expected_col = "n/a"
            lines.append(
                f"| {item.opening_name} | {item.eco} | {s.sample_size} | {s.win_rate:.1%} | {s.draw_rate:.1%} | {s.loss_rate:.1%} | {s.mean_cpl:.1f} | {s.median_cpl:.1f} | {s.baseline_cpl_diff:+.1f} | {expected_col} | {vs_expected_col} | `{s.confidence_level.value}` |"
            )
        lines.append(
            "\n_Elo-Expected Score% is the result this player would be expected to score in this "
            "opening based purely on the Elo gap to each opponent, ignoring chess content entirely. "
            "\"vs Expected\" = actual score rate minus that baseline: negative means he underperforms "
            "his Elo here specifically (a real weakness), not just that he faced stronger opponents in "
            "this line. `n/a` when neither side's Elo was present in the PGN for any game in this bucket.\n"
        )

        lines.append("## 3. Most Played Variations\n")
        lines.append(f"{color_label}'s most frequent opening responses and branching frequencies:\n")
        for item in profile.repertoire[:5]:
            lines.append(f"- **{item.eco} - {item.opening_name}** ({item.summary.sample_size} games, Mean CPL: {item.summary.mean_cpl:.1f})")
        lines.append("\n")

        lines.append("## 4. Biggest Statistical Weaknesses\n")
        lines.append("TOP recurring problem clusters identified across games:\n")
        if not profile.top_problem_clusters:
            lines.append("No major problem clusters detected.")
        else:
            for idx, prob in enumerate(profile.top_problem_clusters[:10], start=1):
                lines.append(f"### Problem #{idx}: {prob.category} - {prob.opening_or_variation}")
                lines.append(f"- **Occurrences:** {prob.occurrences}")
                lines.append(f"- **Average CPL:** {prob.avg_cpl:.1f} cp | **Median CPL:** {prob.median_cpl:.1f} cp")
                lines.append(f"- **Sample Size Confidence:** `{prob.games_count}` distinct games ({prob.occurrences} move occurrences)")
                lines.append("\n")

        lines.append("## 5. Opening Weak Spots\n")
        lines.append("Positions in the first ~20 plies where opponent deviated from engine recommendation:\n")
        if not profile.opening_deviations:
            lines.append("No significant opening deviations detected.")
        else:
            for dev in profile.opening_deviations[:10]:
                lines.append(f"- **Game `{dev.game_id}`** ({dev.eco} {dev.opening}, move {dev.fullmove_number}): Played `{dev.played_san}` instead of `{dev.best_san}`. CPL loss: {dev.cpl:.1f} cp.")
        lines.append("\n")

        lines.append("## 6. Tactical Problems\n")
        tactical_probs = [p for p in profile.top_problem_clusters if p.category == "TACTICAL"]
        if not tactical_probs:
            lines.append("No isolated tactical motifs met clustering thresholds.")
        else:
            for tp in tactical_probs:
                lines.append(f"- **{tp.opening_or_variation}:** {tp.occurrences} occurrences, Avg CPL: {tp.avg_cpl:.1f} cp.")
        lines.append("\n")

        lines.append("## 7. Positional Problems\n")
        positional_probs = [p for p in profile.top_problem_clusters if p.category in ("POSITIONAL", "MIDDLEGAME")]
        if not positional_probs:
            lines.append("Data indicates consistent positional play or unclassified themes.")
        else:
            for pp in positional_probs:
                lines.append(f"- **{pp.opening_or_variation}:** {pp.occurrences} occurrences, Avg CPL: {pp.avg_cpl:.1f} cp.")
        lines.append("\n")

        lines.append("## 8. Middlegame Problems\n")
        lines.append("Tendencies during middlegame transitions and pawn structure play:\n")
        for pat in profile.top_recurring_patterns[:5]:
            lines.append(f"- **{pat.description}:** Played moves: {pat.played_moves}, Avg CPL: {pat.avg_cpl:.1f} cp.")
        lines.append("\n")

        lines.append("## 9. Endgame Problems\n")
        endgame_probs = [p for p in profile.top_problem_clusters if p.category == "ENDGAME"]
        if not endgame_probs:
            lines.append("No significant endgame clusters detected in the sample.")
        else:
            for ep in endgame_probs:
                lines.append(f"- **{ep.opening_or_variation}:** {ep.occurrences} occurrences, Avg CPL: {ep.avg_cpl:.1f} cp.")
        lines.append("\n")

        lines.append("## 10. Critical Positions\n")
        lines.append("TOP critical positions with highest centipawn loss:\n")
        for idx, pos in enumerate(profile.critical_positions[:10], start=1):
            lines.append(f"### Position #{idx} (Game `{pos.game_id}`, Move {pos.fullmove_number})")
            lines.append(f"- **Played Move:** `{pos.san}` ({pos.uci})")
            lines.append(f"- **Best Engine Move:** `{pos.best_move}`")
            lines.append(f"- **Centipawn Loss:** {pos.loss_for_player:.1f} cp")
            lines.append(f"- **Engine Classification:** {pos.classification.value}")
            lines.append(f"- **FEN:** `{pos.fen_before}`")
            lines.append(f"- **PV Line:** `{' '.join(pos.pv[:5])}`")
            lines.append(f"- **Data Notes:** Stockfish evaluates played move as -{pos.loss_for_player:.1f} cp relative to top engine choice.\n")

        if llm_notes.get("critical_positions"):
            lines.append("### AI Notes on Critical Positions\n")
            lines.append(
                "_Generated from the structured data above by the LLM explanation "
                "layer; grounded only in CPL/classification/PV, never a substitute "
                "for the raw engine data._\n"
            )
            lines.append(llm_notes["critical_positions"])
            lines.append("\n")

        lines.append("## 11. Repeated Mistakes\n")
        if not profile.top_recurring_patterns:
            lines.append("No repeated pattern mistakes detected across multiple games.")
        else:
            for pat in profile.top_recurring_patterns[:5]:
                lines.append(f"- Pattern `{pat.pattern_id}` observed in {pat.occurrences} games (Sample games: {', '.join(pat.sample_games[:5])}). Moves played: {pat.played_moves}.")
        lines.append("\n")

        if llm_notes.get("patterns"):
            lines.append("### AI Notes on Recurring Patterns\n")
            lines.append(
                "_Generated from the structured pattern data above; hedged "
                "language reflects sample size, not certainty._\n"
            )
            lines.append(llm_notes["patterns"])
            lines.append("\n")

        tt = profile.time_trouble_summary
        if tt and (tt.get("time_trouble") or tt.get("normal_time")):
            lines.append("## 12. Time Trouble Analysis\n")
            lines.append(
                "Moves played below a time-control-relative \"low on time\" threshold "
                "(a fraction of that game's own base time, not one flat number across "
                "bullet/blitz/rapid/classical - see below) vs moves with more time:\n"
            )
            for label, key in [("Time trouble", "time_trouble"), ("Normal time", "normal_time")]:
                bucket = tt.get(key)
                if not bucket:
                    continue
                lines.append(
                    f"- **{label} (all controls combined):** {bucket['count']} moves, error rate {bucket['error_rate']:.1%}, avg CPL {bucket['avg_cpl']:.1f}"
                )
            lines.append("\n")

            by_cat = tt.get("by_time_control") or {}
            if by_cat:
                lines.append("### Breakdown by time control\n")
                lines.append(
                    "The combined numbers above blend different time controls together; a real "
                    "PGN export usually mixes bullet/blitz/rapid games, and \"time pressure\" "
                    "means something different in each. Per-category breakdown:\n"
                )
                for cat in ("bullet", "blitz", "rapid", "classical", "unknown"):
                    cat_data = by_cat.get(cat)
                    if not cat_data:
                        continue
                    tt_b, nt_b = cat_data.get("time_trouble"), cat_data.get("normal_time")
                    if not tt_b and not nt_b:
                        continue
                    lines.append(f"- **{cat.capitalize()}:**")
                    if tt_b:
                        lines.append(f"  - Time trouble: {tt_b['count']} moves, error rate {tt_b['error_rate']:.1%}, avg CPL {tt_b['avg_cpl']:.1f}")
                    if nt_b:
                        lines.append(f"  - Normal time: {nt_b['count']} moves, error rate {nt_b['error_rate']:.1%}, avg CPL {nt_b['avg_cpl']:.1f}")
                lines.append("\n")

        lines.append("## 13. Practical Preparation\n")
        lines.append("### Recommended Preparation Tree\n")
        lines.append(f"Based strictly on sample data, recommended focus areas when preparing against this opponent playing {color_label}:\n")
        for idx, item in enumerate(profile.repertoire[:3], start=1):
            lines.append(f"{idx}. **{item.opening_name} ({item.eco})** - Represents {item.summary.sample_size / max(1, profile.total_games_analyzed):.1%} of sample. (Sample size: {item.summary.sample_size}, Confidence: `{item.summary.confidence_level.value}`).")
            if item.summary.baseline_cpl_diff > 0:
                lines.append(f"   - *Observation:* Opponent exhibits higher centipawn loss ({item.summary.mean_cpl:.1f} cp) in this opening compared to baseline ({profile.overall_stats.mean_cpl:.1f} cp).")

        if llm_notes.get("final_summary"):
            lines.append("\n### AI Preparation Summary\n")
            lines.append(
                "_Generated from the structured statistics in this report; "
                "not a standalone conclusion - cross-check against the raw "
                "data above._\n"
            )
            lines.append(llm_notes["final_summary"])

        content = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return content
