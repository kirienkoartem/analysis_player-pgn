import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

class SampleConfidenceLevel(str, Enum):
    LOW_SAMPLE = "LOW_SAMPLE"            # sample_size < 8
    NORMAL = "NORMAL"                    # sample_size >= 8
    RELIABLE_PATTERN = "RELIABLE_PATTERN"  # sample_size >= 20

@dataclass
class StatisticalSummary:
    sample_size: int
    confidence_level: SampleConfidenceLevel
    wins: int
    draws: int
    losses: int
    win_rate: float
    draw_rate: float
    loss_rate: float
    mean_cpl: float
    median_cpl: float
    std_cpl: float
    baseline_cpl_diff: float  # Difference from overall baseline mean CPL

class StatisticsAggregator:
    @staticmethod
    def classify_sample_size(sample_size: int, config: Optional[Dict[str, Any]] = None) -> SampleConfidenceLevel:
        min_size = 8
        reliable_size = 20
        if config:
            analysis_cfg = config.get("analysis", {})
            min_size = analysis_cfg.get("min_sample_size", min_size)
            reliable_size = analysis_cfg.get("reliable_sample_size", reliable_size)

        if sample_size < min_size:
            return SampleConfidenceLevel.LOW_SAMPLE
        elif sample_size >= reliable_size:
            return SampleConfidenceLevel.RELIABLE_PATTERN
        else:
            return SampleConfidenceLevel.NORMAL

    @staticmethod
    def calculate_cpl_stats(cpl_list: List[float], baseline_mean_cpl: float = 0.0) -> Dict[str, float]:
        if not cpl_list:
            return {"mean": 0.0, "median": 0.0, "std": 0.0, "baseline_diff": 0.0}

        arr = np.array(cpl_list)
        mean_v = float(np.mean(arr))
        median_v = float(np.median(arr))
        std_v = float(np.std(arr)) if len(arr) > 1 else 0.0
        diff_v = mean_v - baseline_mean_cpl

        return {
            "mean": mean_v,
            "median": median_v,
            "std": std_v,
            "baseline_diff": diff_v
        }

    @staticmethod
    def compute_statistical_summary(
        cpl_list: List[float],
        results_list: List[str],  # list of "1-0", "0-1", "1/2-1/2" (from Black perspective: "0-1" is Black win, "1-0" is Black loss)
        baseline_mean_cpl: float = 0.0,
        config: Optional[Dict[str, Any]] = None
    ) -> StatisticalSummary:
        sample_size = len(results_list)
        conf_level = StatisticsAggregator.classify_sample_size(sample_size, config)

        wins = sum(1 for r in results_list if r == "0-1")
        draws = sum(1 for r in results_list if r == "1/2-1/2")
        losses = sum(1 for r in results_list if r == "1-0")

        w_rate = wins / sample_size if sample_size > 0 else 0.0
        d_rate = draws / sample_size if sample_size > 0 else 0.0
        l_rate = losses / sample_size if sample_size > 0 else 0.0

        cpl_stats = StatisticsAggregator.calculate_cpl_stats(cpl_list, baseline_mean_cpl)

        return StatisticalSummary(
            sample_size=sample_size,
            confidence_level=conf_level,
            wins=wins,
            draws=draws,
            losses=losses,
            win_rate=w_rate,
            draw_rate=d_rate,
            loss_rate=l_rate,
            mean_cpl=cpl_stats["mean"],
            median_cpl=cpl_stats["median"],
            std_cpl=cpl_stats["std"],
            baseline_cpl_diff=cpl_stats["baseline_diff"]
        )
