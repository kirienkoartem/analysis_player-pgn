import os
import chess
import chess.pgn
from typing import List
from src.aggregation.opponent_profile import OpponentProfile

class PGNExporter:
    """Exports critical positions as PGN puzzles/training tasks."""

    @staticmethod
    def export_critical_positions_pgn(profile: OpponentProfile, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for idx, pos in enumerate(profile.critical_positions, start=1):
                game = chess.pgn.Game()
                game.headers["Event"] = f"Opponent Scout Critical Position #{idx}"
                game.headers["Site"] = "Local Analysis"
                game.headers["Date"] = "????.??.??"
                game.headers["Round"] = str(idx)
                if profile.target_color == "white":
                    game.headers["White"] = profile.target_player_name
                    game.headers["Black"] = "Opponent Scout"
                else:
                    game.headers["White"] = "Opponent Scout"
                    game.headers["Black"] = profile.target_player_name
                game.headers["Result"] = "*"
                game.headers["SetUp"] = "1"
                game.headers["FEN"] = pos.fen_before

                move_prefix = f"{pos.fullmove_number}." if pos.side == "white" else f"{pos.fullmove_number}..."
                comment = (
                    f"Game: {pos.game_id}\n"
                    f"Move: {move_prefix} {pos.san}\n"
                    f"Played: {pos.san} ({pos.uci})\n"
                    f"Best Move: {pos.best_move}\n"
                    f"Centipawn Loss: {pos.loss_for_player:.1f} cp\n"
                    f"Classification: {pos.classification.value}\n"
                    f"PV: {' '.join(pos.pv[:5])}"
                )

                # Add main node variation move if playable
                try:
                    board = chess.Board(pos.fen_before)
                    move = chess.Move.from_uci(pos.uci)
                    if move in board.legal_moves:
                        node = game.add_main_variation(move)
                        node.comment = comment
                    else:
                        game.comment = comment
                except Exception:
                    game.comment = comment

                exporter = chess.pgn.FileExporter(f)
                game.accept(exporter)
                f.write("\n\n")
