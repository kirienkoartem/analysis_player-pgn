from dataclasses import dataclass, field
from typing import List, Dict, Any
from src.engine.classification import MoveAnalysisData

@dataclass
class ProblemCluster:
    cluster_id: str
    category: str  # TACTICAL, POSITIONAL, CALCULATION, OPENING, ENDGAME, or UNCLASSIFIED
    opening_or_variation: str
    occurrences: int       # number of qualifying moves (can repeat within one game)
    games_count: int       # number of DISTINCT games these moves came from
    error_rate: float
    avg_cpl: float
    median_cpl: float
    moves: List[MoveAnalysisData] = field(default_factory=list)

class ErrorClusterer:
    """Groups similar opponent mistakes into problem clusters."""
    @staticmethod
    def cluster_mistakes(move_analyses: List[MoveAnalysisData]) -> List[ProblemCluster]:
        mistakes = [m for m in move_analyses if m.classification != "GOOD"]

        # Total moves played in each error_category|opening bucket (mistakes +
        # good moves), used as the denominator for the bucket's error rate.
        # Grouping by error_category (TACTICAL/POSITIONAL/CALCULATION/OPENING/
        # ENDGAME/UNCLASSIFIED) rather than game phase, since the Markdown
        # report's "Tactical Problems"/"Positional Problems" sections filter
        # clusters by these exact category values.
        totals: Dict[str, int] = {}
        for m in move_analyses:
            key = f"{m.error_category}|{m.opening}"
            totals[key] = totals.get(key, 0) + 1

        groups: Dict[str, List[MoveAnalysisData]] = {}
        for m in mistakes:
            key = f"{m.error_category}|{m.opening}"
            if key not in groups:
                groups[key] = []
            groups[key].append(m)

        clusters: List[ProblemCluster] = []
        cid = 1

        for key, m_list in groups.items():
            category, op_name = key.split("|", 1)
            occ = len(m_list)
            total = totals.get(key, occ)
            error_rate = occ / total if total > 0 else 0.0
            cpls = [m.loss_for_player for m in m_list]
            avg_cpl = sum(cpls) / occ if occ > 0 else 0.0
            sorted_cpls = sorted(cpls)
            if occ > 0:
                mid = occ // 2
                median_cpl = sorted_cpls[mid] if occ % 2 else (sorted_cpls[mid - 1] + sorted_cpls[mid]) / 2
            else:
                median_cpl = 0.0
            games_count = len({m.game_id for m in m_list})

            clusters.append(ProblemCluster(
                cluster_id=f"PROB_{cid:03d}",
                category=category,
                opening_or_variation=op_name,
                occurrences=occ,
                games_count=games_count,
                error_rate=error_rate,
                avg_cpl=avg_cpl,
                median_cpl=median_cpl,
                moves=m_list
            ))
            cid += 1

        clusters.sort(key=lambda c: (c.occurrences, c.avg_cpl), reverse=True)
        return clusters
