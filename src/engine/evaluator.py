import sqlite3
import hashlib
import json
import logging
import os
import chess
from typing import Dict, Any, Optional, List
from src.engine.stockfish import StockfishEngine
from src.engine.classification import EngineEvaluation

logger = logging.getLogger(__name__)

class SQLiteEngineCache:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # One persistent connection, reused across every get()/set() call for
        # this cache's lifetime. The previous version opened a brand new
        # sqlite3.Connection on every single call (get AND set, so twice per
        # position analyzed) and never closed it - `with conn:` only commits/
        # rolls back the transaction, it does not close the connection - so a
        # full 1000+-game run leaked several thousand open connection objects,
        # relying on garbage collection to eventually clean them up.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def close(self):
        self._conn.close()

    def _init_db(self):
        with self._conn as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    cache_key TEXT PRIMARY KEY,
                    fen TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    multipv INTEGER NOT NULL,
                    stockfish_version TEXT,
                    eval_type TEXT NOT NULL,
                    score REAL NOT NULL,
                    best_move TEXT,
                    pv TEXT,
                    wdl TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    @staticmethod
    def generate_cache_key(
        fen: str, depth: int, multipv: int, engine_version: str, movetime_ms: Optional[int] = None
    ) -> str:
        # movetime_ms is part of the key: a time-bounded search and a
        # depth-bounded search at the "same" depth label are not the same
        # result, and must never share a cache entry.
        raw_str = f"{fen}|depth:{depth}|multipv:{multipv}|ver:{engine_version}|mt:{movetime_ms or 0}"
        return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

    def get(
        self, fen: str, depth: int, multipv: int, engine_version: str, movetime_ms: Optional[int] = None
    ) -> Optional[EngineEvaluation]:
        cache_key = self.generate_cache_key(fen, depth, multipv, engine_version, movetime_ms)
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT eval_type, score, best_move, pv, wdl FROM positions WHERE cache_key = ?",
            (cache_key,)
        )
        row = cursor.fetchone()
        if row:
            eval_type, score, best_move, pv_json, wdl_json = row
            pv = json.loads(pv_json) if pv_json else []
            wdl = json.loads(wdl_json) if wdl_json else None
            return EngineEvaluation(
                eval_type=eval_type,
                score=score,
                depth=depth,
                multipv=multipv,
                best_move=best_move,
                pv=pv,
                wdl=wdl
            )
        return None

    def set(
        self,
        fen: str,
        depth: int,
        multipv: int,
        engine_version: str,
        eval_obj: EngineEvaluation,
        movetime_ms: Optional[int] = None,
    ):
        cache_key = self.generate_cache_key(fen, depth, multipv, engine_version, movetime_ms)
        pv_json = json.dumps(eval_obj.pv)
        wdl_json = json.dumps(eval_obj.wdl) if eval_obj.wdl is not None else None

        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO positions
                (cache_key, fen, depth, multipv, stockfish_version, eval_type, score, best_move, pv, wdl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cache_key, fen, depth, multipv, engine_version, eval_obj.eval_type, eval_obj.score, eval_obj.best_move, pv_json, wdl_json)
            )

class PositionEvaluator:
    def __init__(self, config: Dict[str, Any], engine: Optional[StockfishEngine] = None):
        self.config = config
        self.engine = engine if engine else StockfishEngine(config)
        db_path = config.get("cache", {}).get("db_path", "data/cache/engine_cache.sqlite")
        self.cache = SQLiteEngineCache(db_path)
        self.cache_hits = 0
        self.engine_calls = 0

    @staticmethod
    def _terminal_evaluation(board: chess.Board) -> Optional[EngineEvaluation]:
        """Returns a synthetic evaluation for a game-over board, or None otherwise.

        A board with no legal moves must never be sent to the engine: Stockfish
        (via python-chess) reports this back as "mate in 0", and the sign of
        that value alone cannot say which side was actually mated - a past bug
        here mislabeled every checkmating move as a game-losing blunder. We
        resolve it directly from board.turn instead: the side to move with no
        moves while in check is the one who just got mated.
        """
        if board.is_checkmate():
            mated_side_is_white = board.turn == chess.WHITE
            mate_sign = -1.0 if mated_side_is_white else 1.0
            return EngineEvaluation(eval_type="mate", score=mate_sign, depth=0, multipv=1, best_move="", pv=[])
        if board.is_stalemate() or board.is_insufficient_material():
            return EngineEvaluation(eval_type="cp", score=0.0, depth=0, multipv=1, best_move="", pv=[])
        return None

    def evaluate_board(
        self,
        board: chess.Board,
        depth: int = 18,
        multipv: int = 1,
        movetime_ms: Optional[int] = None,
    ) -> EngineEvaluation:
        terminal = self._terminal_evaluation(board)
        if terminal is not None:
            return terminal

        fen = board.fen()
        engine_ver = self.engine.version_info

        cached = self.cache.get(fen, depth, multipv, engine_ver, movetime_ms)
        if cached:
            self.cache_hits += 1
            return cached

        self.engine_calls += 1
        result = self.engine.analyze_position(board, depth=depth, multipv=multipv, movetime_ms=movetime_ms)
        self.cache.set(fen, depth, multipv, engine_ver, result, movetime_ms)
        return result
