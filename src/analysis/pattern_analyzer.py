from dataclasses import dataclass, field
from typing import List, Dict, Any
import chess
from src.engine.classification import MoveAnalysisData
from src.chess.patterns import PatternDetector

@dataclass
class RecurringPattern:
    pattern_id: str
    description: str
    pawn_structure_fen: str
    material_key: str
    occurrences: int
    played_moves: Dict[str, int]
    avg_cpl: float
    mistake_rate: float
    sample_games: List[str]
    critical_positions: List[MoveAnalysisData] = field(default_factory=list)

class PatternAnalyzer:
    """Detects recurring positional structures and decision patterns where opponent repeated similar mistakes."""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def detect_recurring_patterns(self, all_move_analyses: List[MoveAnalysisData]) -> List[RecurringPattern]:
        # Group moves by pawn structure and material
        structure_groups: Dict[str, List[MoveAnalysisData]] = {}

        for item in all_move_analyses:
            try:
                board = chess.Board(item.fen_before)
                fp = PatternDetector.create_fingerprint(board)
                key = fp.pawn_skeleton_hash
                if key not in structure_groups:
                    structure_groups[key] = []
                structure_groups[key].append(item)
            except Exception:
                continue

        recurring: List[RecurringPattern] = []
        pid = 1

        for struct_key, moves_list in structure_groups.items():
            if len(moves_list) < 2:  # Must occur at least twice across games
                continue

            parts = struct_key.split("|")
            pawn_fen = parts[0] if len(parts) > 0 else ""
            mat_key = parts[1] if len(parts) > 1 else ""

            played_moves_counter: Dict[str, int] = {}
            total_cpl = 0.0
            mistakes_cnt = 0
            sample_games = []
            critical_pos = []

            for m in moves_list:
                played_moves_counter[m.san] = played_moves_counter.get(m.san, 0) + 1
                total_cpl += m.loss_for_player
                if m.classification != "GOOD":
                    mistakes_cnt += 1
                if m.game_id not in sample_games:
                    sample_games.append(m.game_id)
                if m.is_critical:
                    critical_pos.append(m)

            occ = len(moves_list)
            avg_cpl = total_cpl / occ
            mistake_rate = mistakes_cnt / occ

            desc = f"Structure ({mat_key}) - {occ} occurrences, {mistake_rate:.0%} error rate"

            pattern_obj = RecurringPattern(
                pattern_id=f"PAT_{pid:03d}",
                description=desc,
                pawn_structure_fen=pawn_fen,
                material_key=mat_key,
                occurrences=occ,
                played_moves=played_moves_counter,
                avg_cpl=avg_cpl,
                mistake_rate=mistake_rate,
                sample_games=sample_games[:10],
                critical_positions=critical_pos
            )
            recurring.append(pattern_obj)
            pid += 1

        # Sort by occurrences and mistake rate
        recurring.sort(key=lambda p: (p.occurrences, p.avg_cpl), reverse=True)
        return recurring
