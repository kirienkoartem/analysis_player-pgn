import os
import logging
import chess
import chess.engine
from typing import Optional, Dict, Any, List
from src.engine.classification import EngineEvaluation

logger = logging.getLogger(__name__)

class StockfishEngine:
    def __init__(self, config: Dict[str, Any]):
        stockfish_cfg = config.get("stockfish", {})
        self.path = stockfish_cfg.get("path", "").strip()
        self.threads = stockfish_cfg.get("threads", 1)
        self.hash_mb = stockfish_cfg.get("hash_mb", 256)
        self.engine_process: Optional[chess.engine.SimpleEngine] = None
        self.version_info: str = "Mock Engine (No binary)"

    def is_available(self) -> bool:
        if not self.path:
            return False
        return os.path.isfile(self.path) and os.access(self.path, os.X_OK)

    def start(self) -> bool:
        if not self.is_available():
            logger.warning(f"Stockfish executable not configured or not executable at '{self.path}'.")
            return False
        try:
            self.engine_process = chess.engine.SimpleEngine.popen_uci(self.path)
            self.engine_process.configure({
                "Threads": self.threads,
                "Hash": self.hash_mb
            })
            self.version_info = getattr(self.engine_process.id, "get", lambda k, d: "Stockfish")("name", "Stockfish")
            logger.info(f"Started Stockfish engine process: {self.version_info}")
            return True
        except Exception as e:
            logger.error(f"Failed to start Stockfish engine at '{self.path}': {e}")
            self.engine_process = None
            return False

    def close(self):
        if self.engine_process:
            try:
                self.engine_process.quit()
            except Exception:
                pass
            self.engine_process = None

    def analyze_position(
        self,
        board: chess.Board,
        depth: int = 18,
        multipv: int = 1
    ) -> EngineEvaluation:
        if not self.engine_process:
            # Fallback mock evaluation when Stockfish binary is unavailable
            return EngineEvaluation(
                eval_type="cp",
                score=0.0,
                depth=depth,
                multipv=multipv,
                best_move="",
                pv=[]
            )

        info = self.engine_process.analyse(
            board,
            limit=chess.engine.Limit(depth=depth),
            multipv=multipv
        )

        # Process primary variation
        primary_info = info[0] if isinstance(info, list) else info
        score_obj = primary_info["score"].white()

        if score_obj.is_mate():
            eval_type = "mate"
            score_val = float(score_obj.mate())
        else:
            eval_type = "cp"
            score_val = float(score_obj.score())

        pv_moves = [m.uci() for m in primary_info.get("pv", [])]
        best_move = pv_moves[0] if pv_moves else ""

        wdl_list = None
        if "wdl" in primary_info:
            wdl_obj = primary_info["wdl"].white()
            wdl_list = [wdl_obj.wins / 1000.0, wdl_obj.draws / 1000.0, wdl_obj.losses / 1000.0]

        return EngineEvaluation(
            eval_type=eval_type,
            score=score_val,
            depth=depth,
            multipv=multipv,
            best_move=best_move,
            pv=pv_moves,
            wdl=wdl_list
        )
