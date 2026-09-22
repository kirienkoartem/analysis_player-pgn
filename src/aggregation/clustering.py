from dataclasses import dataclass, field
from typing import List, Dict, Any
from src.engine.classification import MoveAnalysisData

@dataclass
class ProblemCluster:
    cluster_id: str
    category: str  # e.g., OPENING, TACTICAL, POSITIONAL, MIDDLEGAME, ENDGAME
    opening_or_variation: str
    occurrences: int
    error_rate: float
    avg_cpl: float
    median_cpl: float
    moves: List[MoveAnalysisData] = field(default_factory=list)

class ErrorClusterer:
    """Groups similar opponent mistakes into problem clusters."""
    @staticmethod
    def cluster_mistakes(move_analyses: List[MoveAnalysisData]) -> List[ProblemCluster]:
        mistakes = [m for m in move_analyses if m.classification != "GOOD"]

        groups: Dict[str, List[MoveAnalysisData]] = {}
        for m in mistakes:
            key = f"{m.phase}|{m.opening}"
            if key not in groups:
                groups[key] = []
            groups[key].append(m)

        clusters: List[ProblemCluster] = []
        cid = 1

        for key, m_list in groups.items():
            phase, op_name = key.split("|", 1)
            occ = len(m_list)
            cpls = [m.loss_for_player for m in m_list]
            avg_cpl = sum(cpls) / occ if occ > 0 else 0.0
            sorted_cpls = sorted(cpls)
            median_cpl = sorted_cpls[occ // 2] if occ > 0 else 0.0

            clusters.append(ProblemCluster(
                cluster_id=f"PROB_{cid:03d}",
                category=phase,
                opening_or_variation=op_name,
                occurrences=occ,
                error_rate=1.0,
                avg_cpl=avg_cpl,
                median_cpl=median_cpl,
                moves=m_list
            ))
            cid += 1

        clusters.sort(key=lambda c: (c.occurrences, c.avg_cpl), reverse=True)
        return clusters
