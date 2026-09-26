import logging
from typing import Dict, Any, List
from src.aggregation.opponent_profile import OpponentProfile, ProfileBuilder
from src.report.markdown import MarkdownReportGenerator
from src.report.json_export import JSONExporter
from src.report.pgn_export import PGNExporter
from src.report.llm_explainer import LLMExplainer
from src.pgn.loader import LoadPGNResult
from src.engine.classification import MoveAnalysisData
from src.analysis.opening_analyzer import OpeningDeviation
from src.analysis.pattern_analyzer import RecurringPattern

logger = logging.getLogger(__name__)

class ReportGenerator:
    """Master report generator orchestrating Markdown, JSON, and PGN outputs."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        out_cfg = config.get("output", {})
        self.report_path = out_cfg.get("report_path", "data/reports/report.md")
        self.json_path = out_cfg.get("json_path", "data/reports/report.json")
        self.critical_pgn_path = out_cfg.get("critical_pgn_path", "data/reports/critical_positions.pgn")

    def generate_all_reports(
        self,
        pgn_result: LoadPGNResult,
        move_analyses: List[MoveAnalysisData],
        patterns: List[RecurringPattern],
        deviations: List[OpeningDeviation],
        run_metadata: Dict[str, Any] = None,
    ) -> OpponentProfile:
        logger.info("Building opponent profile from statistical analysis...")
        profile = ProfileBuilder.build_profile(
            self.config,
            pgn_result,
            move_analyses,
            patterns,
            deviations
        )

        logger.info("Generating AI explanation layer notes (patterns, critical positions, summary)...")
        explainer = LLMExplainer(self.config)
        llm_notes = {
            "patterns": explainer.explain_patterns(profile.top_recurring_patterns),
            "critical_positions": explainer.explain_critical_positions(profile.critical_positions),
            "final_summary": explainer.explain_final_summary(profile),
        }

        logger.info(f"Generating Markdown report at '{self.report_path}'...")
        MarkdownReportGenerator.generate_report(profile, self.report_path, llm_notes=llm_notes, run_metadata=run_metadata)

        logger.info(f"Exporting JSON statistics to '{self.json_path}'...")
        JSONExporter.export_json(profile, self.json_path, run_metadata=run_metadata)

        logger.info(f"Exporting critical positions PGN to '{self.critical_pgn_path}'...")
        PGNExporter.export_critical_positions_pgn(profile, self.critical_pgn_path)

        return profile
