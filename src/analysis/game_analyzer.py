import logging
import chess
from typing import Dict, Any, List, Optional, Tuple
from src.pgn.loader import GameRecord
from src.chess.positions import extract_target_player_moves, TargetMovePosition
from src.chess.openings import OpeningTracker
from src.chess.phases import phase_detector
from src.engine.evaluator import PositionEvaluator
from src.engine.classification import (
    MoveClassification,
    MoveAnalysisData,
    normalize_eval_for_player,
    calculate_loss_for_player,
    classify_move
)
from src.analysis.error_analyzer import ErrorAnalyzer

logger = logging.getLogger(__name__)

class GameAnalyzer:
    def __init__(self, config: Dict[str, Any], evaluator: PositionEvaluator):
        self.config = config
        self.evaluator = evaluator
        color_str = config.get("target_player", {}).get("color", "black")
        self.target_color: chess.Color = chess.WHITE if color_str == "white" else chess.BLACK
        self.side_label = "white" if self.target_color == chess.WHITE else "black"
        analysis_cfg = config.get("analysis", {})
        self.main_depth = analysis_cfg.get("main_depth", 18)
        self.critical_depth = analysis_cfg.get("critical_depth", 24)
        self.main_multipv = analysis_cfg.get("main_multipv", 1)
        self.critical_multipv = analysis_cfg.get("critical_multipv", 3)
        self.critical_cp = analysis_cfg.get("critical_cp", 150)
        # Optional time-bounded search (ms). When set, overrides fixed-depth
        # search so total batch run time is predictable regardless of host
        # CPU speed - depth becomes just a cache-key/reporting label.
        self.main_movetime_ms = analysis_cfg.get("main_movetime_ms")
        self.critical_movetime_ms = analysis_cfg.get("critical_movetime_ms")
        # Absolute seconds-remaining threshold for flagging a move as played
        # under time pressure. Absolute (not %-of-base-time) because it's a
        # simple, comparable "how little time was left" signal across the
        # mixed time controls in a real PGN export (180+2, 300+0, etc.).
        self.time_pressure_threshold_sec = analysis_cfg.get("time_pressure_threshold_sec", 30)

    def analyze_game(self, record: GameRecord) -> List[MoveAnalysisData]:
        game_id = record.metadata.game_id
        eco, opening = OpeningTracker.get_eco_and_opening(record.game_node)
        target_moves = extract_target_player_moves(record.game_node, target_color=self.target_color)

        move_analyses: List[MoveAnalysisData] = []

        for item in target_moves:
            board_before = item.board_before
            board_after = item.board_after

            # Stage 1: Mass analysis
            eval_before_stage1 = self.evaluator.evaluate_board(
                board_before, depth=self.main_depth, multipv=self.main_multipv,
                movetime_ms=self.main_movetime_ms
            )
            eval_after_stage1 = self.evaluator.evaluate_board(
                board_after, depth=self.main_depth, multipv=self.main_multipv,
                movetime_ms=self.main_movetime_ms
            )

            score_before_black = normalize_eval_for_player(eval_before_stage1, self.target_color)
            score_after_black = normalize_eval_for_player(eval_after_stage1, self.target_color)

            loss_cp = calculate_loss_for_player(score_before_black, score_after_black)
            classification = classify_move(loss_cp, self.config)
            phase = phase_detector(board_after, item.move_number).value

            is_critical = (loss_cp >= self.critical_cp)

            best_move = eval_before_stage1.best_move or ""
            pv = eval_before_stage1.pv
            wdl = eval_before_stage1.wdl

            # Stage 2: Deep analysis for critical positions
            if is_critical and self.evaluator.engine.is_available():
                eval_before_stage2 = self.evaluator.evaluate_board(
                    board_before, depth=self.critical_depth, multipv=self.critical_multipv,
                    movetime_ms=self.critical_movetime_ms
                )
                eval_after_stage2 = self.evaluator.evaluate_board(
                    board_after, depth=self.critical_depth, multipv=1,
                    movetime_ms=self.critical_movetime_ms
                )

                score_before_black_d2 = normalize_eval_for_player(eval_before_stage2, self.target_color)
                score_after_black_d2 = normalize_eval_for_player(eval_after_stage2, self.target_color)
                loss_cp_d2 = calculate_loss_for_player(score_before_black_d2, score_after_black_d2)

                score_before_black = score_before_black_d2
                score_after_black = score_after_black_d2
                loss_cp = loss_cp_d2
                classification = classify_move(loss_cp, self.config)
                best_move = eval_before_stage2.best_move or best_move
                pv = eval_before_stage2.pv
                wdl = eval_before_stage2.wdl

            analysis_data = MoveAnalysisData(
                game_id=game_id,
                move_number=item.move_number,
                side=self.side_label,
                san=item.san,
                uci=item.uci,
                fen_before=item.fen_before,
                fen_after=item.fen_after,
                eval_before_white_perspective=eval_before_stage1,
                eval_after_white_perspective=eval_after_stage1,
                eval_before_black_perspective=score_before_black,
                eval_after_black_perspective=score_after_black,
                loss_for_player=loss_cp,
                best_move=best_move,
                classification=classification,
                phase=phase,
                eco=eco,
                opening=opening,
                pv=pv,
                wdl=wdl,
                is_critical=is_critical,
                error_category="NONE",
                clock_seconds=item.clock_seconds,
                time_pressure=(item.clock_seconds is not None and item.clock_seconds <= self.time_pressure_threshold_sec)
            )
            analysis_data.error_category = ErrorAnalyzer.categorize_mistake(
                analysis_data, board_before, board_after, self.target_color
            )

            move_analyses.append(analysis_data)

        return move_analyses
