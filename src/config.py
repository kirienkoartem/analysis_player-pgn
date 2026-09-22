import os
import yaml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Dict[str, Any] = {
    "input": {
        "pgn_path": "data/input/opponent.pgn"
    },
    "output": {
        "report_path": "data/reports/report.md",
        "json_path": "data/reports/report.json",
        "critical_pgn_path": "data/reports/critical_positions.pgn"
    },
    "target_player": {
        "name": ""
    },
    "stockfish": {
        "path": "",
        "threads": 4,
        "hash_mb": 512
    },
    "analysis": {
        "main_depth": 18,
        "critical_depth": 24,
        "main_multipv": 1,
        "critical_multipv": 3,
        "inaccuracy_cp": 50,
        "mistake_cp": 100,
        "blunder_cp": 200,
        "critical_cp": 150,
        "analyze_opening_plies": 20,
        "min_sample_size": 8,
        "reliable_sample_size": 20
    },
    "performance": {
        "workers": 1
    },
    "cache": {
        "db_path": "data/cache/engine_cache.sqlite"
    },
    "logging": {
        "log_path": "data/logs/app.log",
        "level": "INFO"
    }
}

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    config = DEFAULT_CONFIG.copy()

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f)
                if user_cfg and isinstance(user_cfg, dict):
                    # Deep merge config dicts
                    for k, v in user_cfg.items():
                        if isinstance(v, dict) and k in config and isinstance(config[k], dict):
                            config[k].update(v)
                        else:
                            config[k] = v
        except Exception as e:
            logger.warning(f"Error loading config file '{config_path}': {e}. Using defaults.")

    return config

def setup_logging(config: Dict[str, Any]):
    log_cfg = config.get("logging", {})
    log_path = log_cfg.get("log_path", "data/logs/app.log")
    log_level_str = log_cfg.get("level", "INFO").upper()

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
