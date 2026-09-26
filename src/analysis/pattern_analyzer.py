from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple
from src.engine.classification import MoveAnalysisData


@dataclass
class RecurringPattern:
    pattern_id: str
    description: str
    fen_before: str
    played_san: str
    best_move: str
    eco: str
    opening: str
    occurrences: int  # == distinct games this exact position+move repeat was found in
    played_moves: Dict[str, int]  # kept for report/LLM-prompt compatibility: {played_san: occurrences}
    avg_cpl: float
    median_cpl: float
    mistake_rate: float  # always 1.0 - this dataclass only ever holds confirmed mistakes
    sample_games: List[str]
    critical_positions: List[MoveAnalysisData] = field(default_factory=list)


class PatternAnalyzer:
    """Detects a genuinely repeated mistake: the exact same position (FEN) met
    on multiple, DIFFERENT occasions, with the exact same (wrong) move chosen
    each time.

    This is deliberately narrower than grouping by loose pawn-structure/material
    similarity: that approach also matched the natural, mistake-free overlap
    between games that reach the same opening tabiya (everyone reaches the
    Nimzo tabiya - that's not a "pattern", it's just the opening), and counted
    the same game's own moves against itself as "recurring". Exact-position
    dedup is the standard a claim like "he played X ply/move N twice, in two
    different games, and lost Y cp both times" needs to hold up.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def detect_recurring_patterns(self, all_move_analyses: List[MoveAnalysisData]) -> List[RecurringPattern]:
        mistakes = [m for m in all_move_analyses if m.classification != "GOOD"]

        groups: Dict[Tuple[str, str], List[MoveAnalysisData]] = {}
        for m in mistakes:
            key = (m.fen_before, m.san)
            groups.setdefault(key, []).append(m)

        recurring: List[RecurringPattern] = []
        pid = 1

        for (fen, san), moves_list in groups.items():
            distinct_games = sorted({m.game_id for m in moves_list})
            games_count = len(distinct_games)
            if games_count < 2:  # Must occur in at least 2 DIFFERENT games
                continue

            cpls = [m.loss_for_player for m in moves_list]
            avg_cpl = sum(cpls) / len(cpls)
            sorted_cpls = sorted(cpls)
            n = len(sorted_cpls)
            median_cpl = (
                sorted_cpls[n // 2] if n % 2 else (sorted_cpls[n // 2 - 1] + sorted_cpls[n // 2]) / 2
            )
            critical_pos = [m for m in moves_list if m.is_critical]

            first = moves_list[0]
            desc = (
                f"{first.opening} ({first.eco}), move {first.fullmove_number}: "
                f"played {san} in {games_count} different games "
                f"(engine best: {first.best_move or 'n/a'}), avg loss {avg_cpl:.0f} cp"
            )

            recurring.append(RecurringPattern(
                pattern_id=f"PAT_{pid:03d}",
                description=desc,
                fen_before=fen,
                played_san=san,
                best_move=first.best_move,
                eco=first.eco,
                opening=first.opening,
                occurrences=games_count,
                played_moves={san: games_count},
                avg_cpl=avg_cpl,
                median_cpl=median_cpl,
                mistake_rate=1.0,
                sample_games=distinct_games[:10],
                critical_positions=critical_pos,
            ))
            pid += 1

        # Sort by how many different games it showed up in, then by severity.
        recurring.sort(key=lambda p: (p.occurrences, p.avg_cpl), reverse=True)
        return recurring
