"""Typed configuration loading for the opponent scout project.

All modules receive configuration by passing an AppConfig instance
explicitly - no global config object is used anywhere in this codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TargetPlayerConfig:
    name: str = ""


@dataclass
class StockfishConfig:
    path: str = ""
    threads: int = 8
    hash_mb: int = 1024


@dataclass
class AnalysisConfig:
    main_depth: int = 18
    critical_depth: int = 24
    main_multipv: int = 1
    critical_multipv: int = 3

    inaccuracy_cp: int = 50
    mistake_cp: int = 100
    blunder_cp: int = 200
    critical_cp: int = 150

    analyze_opening_plies: int = 20

    min_sample_size: int = 8
    reliable_sample_size: int = 20


@dataclass
class PerformanceConfig:
    workers: int = 1


@dataclass
class CacheConfig:
    db_path: str = "data/cache/engine_cache.sqlite"


@dataclass
class LoggingConfig:
    log_path: str = "data/logs/app.log"
    level: str = "INFO"


@dataclass
class IOConfig:
    pgn_path: str = "data/input/opponent.pgn"
    report_path: str = "data/reports/report.md"
    json_path: str = "data/reports/report.json"
    critical_pgn_path: str = "data/reports/critical_positions.pgn"


@dataclass
class AppConfig:
    io: IOConfig = field(default_factory=IOConfig)
    target_player: TargetPlayerConfig = field(default_factory=TargetPlayerConfig)
    stockfish: StockfishConfig = field(default_factory=StockfishConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    config_dir: Path = field(default_factory=Path.cwd)

    def resolve(self, relative_path: str) -> Path:
        """Resolve a config-relative path against the config file's directory."""
        p = Path(relative_path)
        if p.is_absolute():
            return p
        return (self.config_dir / p).resolve()


def _get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def load_config(path: str | Path) -> AppConfig:
    """Load AppConfig from a YAML file, falling back to defaults for missing keys."""
    path = Path(path)
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    cfg = AppConfig(
        io=IOConfig(
            pgn_path=_get(raw, "input", "pgn_path", default=IOConfig.pgn_path),
            report_path=_get(raw, "output", "report_path", default=IOConfig.report_path),
            json_path=_get(raw, "output", "json_path", default=IOConfig.json_path),
            critical_pgn_path=_get(
                raw, "output", "critical_pgn_path", default=IOConfig.critical_pgn_path
            ),
        ),
        target_player=TargetPlayerConfig(
            name=_get(raw, "target_player", "name", default=""),
        ),
        stockfish=StockfishConfig(
            path=_get(raw, "stockfish", "path", default=""),
            threads=_get(raw, "stockfish", "threads", default=8),
            hash_mb=_get(raw, "stockfish", "hash_mb", default=1024),
        ),
        analysis=AnalysisConfig(
            main_depth=_get(raw, "analysis", "main_depth", default=18),
            critical_depth=_get(raw, "analysis", "critical_depth", default=24),
            main_multipv=_get(raw, "analysis", "main_multipv", default=1),
            critical_multipv=_get(raw, "analysis", "critical_multipv", default=3),
            inaccuracy_cp=_get(raw, "analysis", "inaccuracy_cp", default=50),
            mistake_cp=_get(raw, "analysis", "mistake_cp", default=100),
            blunder_cp=_get(raw, "analysis", "blunder_cp", default=200),
            critical_cp=_get(raw, "analysis", "critical_cp", default=150),
            analyze_opening_plies=_get(raw, "analysis", "analyze_opening_plies", default=20),
            min_sample_size=_get(raw, "analysis", "min_sample_size", default=8),
            reliable_sample_size=_get(raw, "analysis", "reliable_sample_size", default=20),
        ),
        performance=PerformanceConfig(
            workers=_get(raw, "performance", "workers", default=1),
        ),
        cache=CacheConfig(
            db_path=_get(raw, "cache", "db_path", default="data/cache/engine_cache.sqlite"),
        ),
        logging=LoggingConfig(
            log_path=_get(raw, "logging", "log_path", default="data/logs/app.log"),
            level=_get(raw, "logging", "level", default="INFO"),
        ),
        config_dir=path.resolve().parent if path.exists() else Path.cwd(),
    )
    return cfg
