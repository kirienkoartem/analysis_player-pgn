"""Error rates by position theme, compared like-for-like.

The question this answers is "where does this player swim?" - e.g. are rook
endgames a real weak spot, or are endgames just harder for everyone? A raw
"you make X% errors in rook endgames" can't tell those apart, so each theme
is compared against a reference set from the SAME broader situation:
rook endgames vs. all other endgames, queenless middlegames vs. middlegames
with queens, conversion of an advantage vs. equal positions, and so on.

A "serious error" here is a drop of >= 10 points of winning chances
(Lichess's own "mistake" threshold), not raw centipawns - losing 200 cp in a
position that stays completely won isn't a practical mistake.

The verdicts are deliberately conservative: a theme is only called weak or
strong when the sample is big enough and the difference is both sizeable
(>= 25% relative) and statistically clear (p < 0.01). Moves inside one game
aren't independent of each other, so the p-value somewhat overstates
certainty - the strict alpha and the minimum-games rule compensate for that.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from src.engine.classification import MoveAnalysisData
from src.analysis.themes import TAGS

SERIOUS_WP = 10.0
BLUNDER_WP = 15.0
MIN_MOVES = 40
MIN_GAMES = 8
ALPHA = 0.01
MIN_RATIO_WEAK = 1.25
MAX_RATIO_STRONG = 0.80


@dataclass
class ThemeStat:
    tag: str
    label: str
    group: str
    reference_label: str
    moves: int
    games: int
    errors: int
    blunders: int
    error_rate: float
    ci_low: float
    ci_high: float
    avg_wp_loss: float
    reference_moves: int
    reference_error_rate: float
    ratio: Optional[float]
    p_value: Optional[float]
    verdict: str  # "weak" | "strong" | "neutral" | "insufficient"
    excess_errors: float  # errors beyond what the reference rate would predict
    decisive_errors: int = 0  # games lost / wins thrown where the decisive move had this tag
    example_games: List[str] = field(default_factory=list)


def wilson_interval(errors: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = errors / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def two_proportion_p_value(x1: int, n1: int, x2: int, n2: int) -> Optional[float]:
    if n1 == 0 or n2 == 0:
        return None
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (x1 / n1 - x2 / n2) / se
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def _has(tag: str) -> Callable[[MoveAnalysisData], bool]:
    return lambda m: tag in m.tags


# (group key, group label, tags, reference-set predicate factory, reference label)
# The reference for a tag is: moves matching `parent` that DON'T carry the tag,
# unless `fixed_reference` names a specific tag to compare against instead.
THEME_GROUPS = [
    ("phase", "Фазы партии",
     ["phase:opening", "phase:middlegame", "phase:endgame"], None, None, "остальные фазы"),
    ("endgame", "Типы эндшпилей",
     ["endgame:pawn", "endgame:rook", "endgame:queen", "endgame:bishop", "endgame:opposite_bishops",
      "endgame:knight", "endgame:minor", "endgame:rook_minor", "endgame:mixed"],
     _has("phase:endgame"), None, "другие эндшпили"),
    ("middlegame", "Миттельшпиль",
     ["mg:queens_on", "mg:queenless", "mg:opposite_castling", "struct:iqp_own", "struct:iqp_opp"],
     _has("phase:middlegame"), None, "остальной миттельшпиль"),
    ("transition", "Переходы",
     ["trans:after_queen_trade"],
     lambda m: "phase:opening" not in m.tags, None, "остальные ходы после дебюта"),
    ("context", "Оценка позиции",
     ["ctx:losing", "ctx:better", "ctx:winning"], None, "ctx:equal", "равные позиции"),
    ("time", "Время на часах",
     ["time:pressure"], None, "time:normal", "нормальный запас времени"),
]


def _stat_for(tag: str, group: str, moves: List[MoveAnalysisData], reference: List[MoveAnalysisData],
              reference_label: str) -> ThemeStat:
    n = len(moves)
    errors = sum(1 for m in moves if m.wp_loss >= SERIOUS_WP)
    blunders = sum(1 for m in moves if m.wp_loss >= BLUNDER_WP)
    games = len({m.game_id for m in moves})
    rate = errors / n if n else 0.0
    lo, hi = wilson_interval(errors, n)
    ref_n = len(reference)
    ref_errors = sum(1 for m in reference if m.wp_loss >= SERIOUS_WP)
    ref_rate = ref_errors / ref_n if ref_n else 0.0
    ratio = (rate / ref_rate) if ref_rate > 0 else None
    p_value = two_proportion_p_value(errors, n, ref_errors, ref_n)

    if n < MIN_MOVES or games < MIN_GAMES or ref_n < MIN_MOVES or p_value is None or ratio is None:
        verdict = "insufficient"
    elif p_value < ALPHA and ratio >= MIN_RATIO_WEAK:
        verdict = "weak"
    elif p_value < ALPHA and ratio <= MAX_RATIO_STRONG:
        verdict = "strong"
    else:
        verdict = "neutral"

    error_moves = sorted((m for m in moves if m.wp_loss >= SERIOUS_WP), key=lambda m: -m.wp_loss)
    examples: List[str] = []
    for m in error_moves:
        if m.game_id not in examples:
            examples.append(m.game_id)
        if len(examples) >= 5:
            break

    return ThemeStat(
        tag=tag, label=TAGS.get(tag, tag), group=group, reference_label=reference_label,
        moves=n, games=games, errors=errors, blunders=blunders, error_rate=rate,
        ci_low=lo, ci_high=hi,
        avg_wp_loss=(sum(m.wp_loss for m in moves) / n) if n else 0.0,
        reference_moves=ref_n, reference_error_rate=ref_rate,
        ratio=ratio, p_value=p_value, verdict=verdict,
        excess_errors=errors - n * ref_rate,
        example_games=examples,
    )


def compute_theme_stats(moves: List[MoveAnalysisData],
                        decisive_by_tag: Optional[Dict[str, int]] = None) -> Dict[str, List[ThemeStat]]:
    decisive_by_tag = decisive_by_tag or {}
    result: Dict[str, List[ThemeStat]] = {}
    for group, _label, tags, parent, fixed_ref, ref_label in THEME_GROUPS:
        stats: List[ThemeStat] = []
        pool = [m for m in moves if parent(m)] if parent else moves
        fixed_ref_moves = [m for m in moves if fixed_ref in m.tags] if fixed_ref else None
        for tag in tags:
            in_tag = [m for m in pool if tag in m.tags]
            if not in_tag:
                continue
            reference = fixed_ref_moves if fixed_ref_moves is not None else [m for m in pool if tag not in m.tags]
            st = _stat_for(tag, group, in_tag, reference, ref_label)
            st.decisive_errors = decisive_by_tag.get(tag, 0)
            stats.append(st)
        result[group] = stats
    return result


def group_labels() -> Dict[str, str]:
    return {g: label for g, label, *_ in THEME_GROUPS}


def flatten(theme_stats: Dict[str, List[ThemeStat]]) -> List[ThemeStat]:
    return [s for stats in theme_stats.values() for s in stats]


def motif_breakdown(moves: List[MoveAnalysisData]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for m in moves:
        if m.wp_loss >= SERIOUS_WP and m.motif != "NONE":
            counts[m.motif] = counts.get(m.motif, 0) + 1
    return counts
