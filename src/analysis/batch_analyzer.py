import logging
import os
import json
import sqlite3
from typing import Dict, Any, List, Optional
from tqdm import tqdm

from src.pgn.loader import load_pgn_games, LoadPGNResult, GameRecord
from src.engine.evaluator import PositionEvaluator
from src.engine.stockfish import StockfishEngine
from src.analysis.game_analyzer import GameAnalyzer
from src.analysis.opening_analyzer import OpeningAnalyzer, OpeningDeviation
from src.analysis.pattern_analyzer import PatternAnalyzer, RecurringPattern
from src.engine.classification import MoveAnalysisData, EngineEvaluation, MoveClassification

logger = logging.getLogger(__name__)

class BatchAnalyzerResult:
    def __init__(self, pgn_result: LoadPGNResult, move_analyses: List[MoveAnalysisData]):
        self.pgn_result = pgn_result
        self.move_analyses = move_analyses
        self.games_processed = len(pgn_result.filtered_games)
        self.positions_analyzed = len(move_analyses)
        self.critical_positions_count = sum(1 for m in move_analyses if m.is_critical)

class BatchAnalyzer:
    def __init__(self, config: Dict[str, Any], engine: Optional[StockfishEngine] = None):
        self.config = config
        self.evaluator = PositionEvaluator(config, engine=engine)
        self.game_analyzer = GameAnalyzer(config, self.evaluator)
        self.opening_analyzer = OpeningAnalyzer(config)
        self.pattern_analyzer = PatternAnalyzer(config)

    def analyze_batch(
        self,
        pgn_path: Optional[str] = None,
        target_player: Optional[str] = None,
        limit: Optional[int] = None
    ) -> BatchAnalyzerResult:
        pgn_path = pgn_path or self.config.get("input", {}).get("pgn_path", "data/input/opponent.pgn")
        cfg_target = self.config.get("target_player", {}).get("name", "")
        target_player = target_player if target_player is not None else cfg_target
        color = self.config.get("target_player", {}).get("color", "black")

        logger.info(f"Starting batch analysis on '{pgn_path}' for player '{target_player}' (color={color})...")

        pgn_load_res = load_pgn_games(pgn_path, target_player=target_player, limit=limit, color=color)
        filtered_games = pgn_load_res.filtered_games

        logger.info(f"Loaded {pgn_load_res.total_games_in_pgn} total games. Filtered {len(filtered_games)} games where '{pgn_load_res.target_player}' played {color}.")

        all_move_analyses: List[MoveAnalysisData] = []

        # Process with tqdm progress bar
        with tqdm(total=len(filtered_games), desc="Analyzing games", unit="game") as pbar:
            for record in filtered_games:
                moves_data = self.game_analyzer.analyze_game(record)
                all_move_analyses.extend(moves_data)
                pbar.update(1)
                pbar.set_postfix({
                    "pos": len(all_move_analyses),
                    "cache_hits": self.evaluator.cache_hits,
                    "engine_calls": self.evaluator.engine_calls
                })

        return BatchAnalyzerResult(pgn_result=pgn_load_res, move_analyses=all_move_analyses)
