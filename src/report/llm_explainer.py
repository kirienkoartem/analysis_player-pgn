"""LLM explanation layer (Gemini).

Turns already-computed, structured statistics into human-readable prose for
a human preparing to play the opponent. This layer NEVER invents chess
explanations Stockfish/the pipeline didn't produce - it only rephrases the
structured data it is given (frequencies, CPL, PV lines, sample sizes) into
readable sentences, using hedged language ("данные указывают", "часто
встречается") rather than categorical claims, per the project's core rule of
not overstating conclusions from small samples.

Called at most 3 times per full run - once for the top recurring patterns,
once for the critical positions, once for the final preparation summary -
never per move and never during mass Stage-1/Stage-2 engine analysis. If the
API key is missing, the network is unavailable, or `llm.enabled` is false in
config, every method degrades to returning `None` and the report generator
falls back to the plain structured text it already produces.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from src.aggregation.opponent_profile import OpponentProfile
from src.analysis.pattern_analyzer import RecurringPattern
from src.engine.classification import MoveAnalysisData

logger = logging.getLogger(__name__)

load_dotenv()

_SYSTEM_INSTRUCTION = (
    "You are a chess preparation assistant. You are given structured, "
    "pre-computed statistics about one chess player's recurring mistakes, "
    "derived from a Stockfish-based analysis of hundreds of games. "
    "Rewrite ONLY the given data into clear, practical prose for a human "
    "opponent preparing to play against this player. "
    "Rules you must follow strictly:\n"
    "1. Never invent a chess explanation, motif, or cause that is not "
    "directly supported by the given data (frequency, CPL, PV line, result). "
    "If the cause is not classified, say the pattern is statistical/"
    "unclassified rather than guessing why it happens.\n"
    "2. Never state a conclusion as certain when sample_size is small. Use "
    "hedged language ('data suggests', 'frequently observed', 'worth "
    "checking') rather than absolute claims ('he cannot play X').\n"
    "3. Always mention the sample size backing a claim.\n"
    "4. Be concise and practical - this is chess prep, not a chess essay.\n"
    "5. Write in Russian."
)


class LLMExplainer:
    """Generates grounded natural-language commentary via the Gemini API."""

    def __init__(self, config: Dict[str, Any]):
        llm_cfg = config.get("llm", {}) if config else {}
        self.enabled: bool = bool(llm_cfg.get("enabled", True))
        self.model: str = llm_cfg.get("model", "gemini-3.6-flash")
        self.api_key_env: str = llm_cfg.get("api_key_env", "GEMINI_API_KEY")
        self.max_patterns: int = llm_cfg.get("max_patterns", 10)
        self.max_critical_positions: int = llm_cfg.get("max_critical_positions", 20)

        self._client = None
        if self.enabled:
            self._client = self._build_client()
            if self._client is None:
                self.enabled = False

    def _build_client(self):
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            logger.info(
                "LLM explanation layer disabled: %s not set in environment/.env",
                self.api_key_env,
            )
            return None
        try:
            from google import genai
        except ImportError:
            logger.warning(
                "LLM explanation layer disabled: google-genai package not installed"
            )
            return None
        try:
            return genai.Client(api_key=api_key)
        except Exception as e:
            logger.warning("LLM explanation layer disabled: client init failed: %s", e)
            return None

    def _generate(self, prompt: str) -> Optional[str]:
        if not self.enabled or self._client is None:
            return None
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"system_instruction": _SYSTEM_INSTRUCTION},
            )
            text = getattr(response, "text", None)
            return text.strip() if text else None
        except Exception as e:
            logger.warning("LLM call failed, falling back to structured text only: %s", e)
            return None

    def explain_patterns(self, patterns: List[RecurringPattern]) -> Optional[str]:
        """One batched call covering the top recurring problem patterns."""
        if not patterns:
            return None
        items = patterns[: self.max_patterns]
        lines = ["Recurring problem patterns (JSON-like list), most frequent first:\n"]
        for p in items:
            lines.append(
                f"- pattern_id={p.pattern_id}; description={p.description}; "
                f"occurrences={p.occurrences}; mistake_rate={p.mistake_rate:.2f}; "
                f"avg_cpl={p.avg_cpl:.1f}; played_moves={p.played_moves}; "
                f"sample_games_count={len(p.sample_games)}"
            )
        lines.append(
            "\nWrite a short 'Practical Preparation' style paragraph per pattern, "
            "in the same order, explaining what this means practically for "
            "someone preparing to play this opponent. Prefix each paragraph "
            "with the pattern_id."
        )
        return self._generate("\n".join(lines))

    def explain_critical_positions(
        self, positions: List[MoveAnalysisData]
    ) -> Optional[str]:
        """One batched call covering the top critical positions."""
        if not positions:
            return None
        items = positions[: self.max_critical_positions]
        lines = ["Critical positions (JSON-like list), most significant first:\n"]
        for i, pos in enumerate(items, start=1):
            lines.append(
                f"- #{i} game={pos.game_id}; move={pos.move_number}; "
                f"opening={pos.opening} ({pos.eco}); played={pos.san}; "
                f"best_move_uci={pos.best_move}; cpl={pos.loss_for_player:.1f}; "
                f"classification={pos.classification}; pv={pos.pv[:5]}"
            )
        lines.append(
            "\nFor each position, write one or two sentences on why it is "
            "worth studying, grounded only in the CPL/classification/PV given. "
            "If the reason isn't clear from the data, say the position is "
            "flagged by engine evaluation loss without a classified cause. "
            "Prefix each note with '#<number>'."
        )
        return self._generate("\n".join(lines))

    def explain_final_summary(self, profile: OpponentProfile) -> Optional[str]:
        """One batched call producing the final 'Preparation Summary' prose."""
        lines = [
            f"Target player (Black): {profile.target_player_name}",
            f"Total games analyzed: {profile.total_games_analyzed}",
            f"Overall baseline avg CPL: {profile.overall_stats.mean_cpl:.1f} "
            f"(sample_size={profile.overall_stats.sample_size}, "
            f"confidence={profile.overall_stats.confidence_level})",
            "\nTop opening repertoire (games, mean CPL):",
        ]
        for item in profile.repertoire[:8]:
            lines.append(
                f"- {item.eco} {item.opening_name}: {item.summary.sample_size} games, "
                f"mean_cpl={item.summary.mean_cpl:.1f}, "
                f"confidence={item.summary.confidence_level}"
            )
        lines.append("\nTop problem clusters (category, occurrences, avg_cpl, error_rate):")
        for c in profile.top_problem_clusters[:10]:
            lines.append(
                f"- {c.category} / {c.opening_or_variation}: occurrences={c.occurrences}, "
                f"avg_cpl={c.avg_cpl:.1f}, error_rate={c.error_rate:.2f}"
            )
        lines.append(
            "\nWrite the 'Preparation Summary' section of a scouting report: "
            "prioritize what to study first based on frequency and sample "
            "size, using hedged language throughout ('данные указывают', "
            "'часто встречается', 'стоит проверить'), never a categorical "
            "claim like 'легко победить здесь'. End with a short numbered "
            "preparation priority list."
        )
        return self._generate("\n".join(lines))
