import pytest
from src.aggregation.statistics import (
    StatisticsAggregator,
    SampleConfidenceLevel,
    StatisticalSummary
)

def test_sample_confidence_level():
    assert StatisticsAggregator.classify_sample_size(4) == SampleConfidenceLevel.LOW_SAMPLE
    assert StatisticsAggregator.classify_sample_size(12) == SampleConfidenceLevel.NORMAL
    assert StatisticsAggregator.classify_sample_size(25) == SampleConfidenceLevel.RELIABLE_PATTERN

def test_statistical_summary_calc():
    cpls = [10.0, 50.0, 100.0, 40.0, 0.0]
    # Results from Black perspective: "0-1" = Black win, "1-0" = Black loss, "1/2-1/2" = Draw
    results = ["0-1", "0-1", "1-0", "1/2-1/2", "0-1"]

    summary = StatisticsAggregator.compute_statistical_summary(
        cpl_list=cpls,
        results_list=results,
        baseline_mean_cpl=30.0
    )

    assert summary.sample_size == 5
    assert summary.wins == 3
    assert summary.draws == 1
    assert summary.losses == 1
    assert abs(summary.win_rate - 0.6) < 1e-5
    assert abs(summary.mean_cpl - 40.0) < 1e-5
    assert abs(summary.median_cpl - 40.0) < 1e-5
    assert abs(summary.baseline_cpl_diff - 10.0) < 1e-5
