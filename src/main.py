import sys
import os
import copy
import time

# Add root project directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
import logging
from typing import Dict, Any

from src.config import load_config, setup_logging
from src.pgn.loader import load_pgn_games
from src.pgn.downloader import download_games
from src.engine.stockfish import StockfishEngine
from src.analysis.batch_analyzer import BatchAnalyzer
from src.analysis.opening_analyzer import OpeningAnalyzer
from src.analysis.pattern_analyzer import PatternAnalyzer
from src.report.report_generator import ReportGenerator

logger = logging.getLogger("main")


def _color_suffixed_path(path: str, color: str) -> str:
    """Inserts a color suffix before the file extension, e.g. report.md -> report_white.md."""
    root, ext = os.path.splitext(path)
    return f"{root}_{color}{ext}"


def run_pipeline_for_color(config: Dict[str, Any], args, engine: StockfishEngine, color: str) -> None:
    """Runs validate/analyze/report/export/all for a single color (white or black)."""
    run_config = copy.deepcopy(config)
    run_config["target_player"]["color"] = color

    if config["target_player"].get("color") == "both":
        # Keep each color's outputs in separate files so they don't clobber each other.
        for key in ("report_path", "json_path", "critical_pgn_path"):
            run_config["output"][key] = _color_suffixed_path(config["output"][key], color)

    pgn_path = run_config["input"]["pgn_path"]
    target_player = run_config["target_player"]["name"]

    print(f"\n--- Studying '{target_player or '[AUTO-DETECT]'}' as {color.upper()} ---")

    if args.command == "validate":
        if not os.path.exists(pgn_path):
            print(f"Error: File '{pgn_path}' does not exist.")
            sys.exit(1)
        filters_cfg = run_config.get("filters", {})
        res = load_pgn_games(
            pgn_path, target_player=target_player, limit=args.limit, color=color,
            time_control_category=filters_cfg.get("time_control_category"),
            date_from=filters_cfg.get("date_from"),
            date_to=filters_cfg.get("date_to"),
            min_opponent_elo=filters_cfg.get("min_opponent_elo"),
        )
        print(f"Total games in PGN: {res.total_games_in_pgn}")
        print(f"Auto-detected Target Player: {res.target_player}")
        print(f"Filtered {color.capitalize()} Games: {len(res.filtered_games)}")
        print(f"Skipped Games: {len(res.skipped_games)}")
        for sk in res.skipped_games[:5]:
            print(f" - Game #{sk.index}: {sk.reason}")
        print("Validation COMPLETE.")
        return

    if args.command in ("analyze", "report", "export", "all"):
        if not os.path.exists(pgn_path):
            print(f"Error: File '{pgn_path}' does not exist.")
            sys.exit(1)

        batch_analyzer = BatchAnalyzer(run_config, engine=engine)
        start_time = time.time()
        batch_res = batch_analyzer.analyze_batch(limit=args.limit)
        elapsed_sec = time.time() - start_time

        op_analyzer = OpeningAnalyzer(run_config)
        deviations = op_analyzer.find_opening_deviations(batch_res.move_analyses)

        pat_analyzer = PatternAnalyzer(run_config)
        patterns = pat_analyzer.detect_recurring_patterns(batch_res.move_analyses)

        if args.command in ("report", "export", "all"):
            analysis_cfg = run_config.get("analysis", {})
            stockfish_cfg = run_config.get("stockfish", {})
            run_metadata = {
                "engine_version": engine.version_info,
                "main_depth": analysis_cfg.get("main_depth"),
                "critical_depth": analysis_cfg.get("critical_depth"),
                "main_multipv": analysis_cfg.get("main_multipv"),
                "critical_multipv": analysis_cfg.get("critical_multipv"),
                "main_movetime_ms": analysis_cfg.get("main_movetime_ms"),
                "critical_movetime_ms": analysis_cfg.get("critical_movetime_ms"),
                "stockfish_threads": stockfish_cfg.get("threads"),
                "stockfish_hash_mb": stockfish_cfg.get("hash_mb"),
                "cache_hits": batch_analyzer.evaluator.cache_hits,
                "engine_calls": batch_analyzer.evaluator.engine_calls,
                "analysis_duration_sec": round(elapsed_sec, 1),
                "filters_applied": run_config.get("filters", {}),
                "pgn_path": pgn_path,
            }
            report_gen = ReportGenerator(run_config)
            report_gen.generate_all_reports(
                pgn_result=batch_res.pgn_result,
                move_analyses=batch_res.move_analyses,
                run_metadata=run_metadata,
                patterns=patterns,
                deviations=deviations
            )
            print("Analysis & Reports Generated Successfully!")
            print(f" - Markdown Report: {run_config['output']['report_path']}")
            print(f" - JSON Report: {run_config['output']['json_path']}")
            print(f" - Critical Positions PGN: {run_config['output']['critical_pgn_path']}")


def main():
    parser = argparse.ArgumentParser(
        description="Opponent Scout: Chess PGN Statistical & Engine Analysis System for Opponent Preparation"
    )

    parser.add_argument("command", choices=["validate", "analyze", "report", "export", "all"],
                        help="Action command to execute")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML configuration file")
    parser.add_argument("--pgn", help="Path to input PGN file")
    parser.add_argument("--lichess", metavar="USERNAME", help="Download this player's games from Lichess instead of reading --pgn")
    parser.add_argument("--chesscom", metavar="USERNAME", help="Download this player's games from Chess.com instead of reading --pgn")
    parser.add_argument("--download-limit", type=int, default=1000, help="Max games to download when using --lichess/--chesscom (default 1000)")
    parser.add_argument("--player", help="Target opponent name")
    parser.add_argument("--color", choices=["white", "black", "both"], help="Which color the target player is studied for")
    parser.add_argument("--depth", type=int, help="Engine main search depth")
    parser.add_argument("--critical-depth", type=int, help="Engine deep search depth for critical positions")
    parser.add_argument("--threads", type=int, help="Stockfish threads")
    parser.add_argument("--hash", type=int, help="Stockfish Hash MB")
    parser.add_argument("--limit", type=int, help="Limit maximum games to analyze (useful for dry runs)")
    parser.add_argument("--no-engine", action="store_true", help="Run statistical analysis without Stockfish engine")
    parser.add_argument("--time-control", choices=["bullet", "blitz", "rapid", "classical"],
                        help="Only include games in this time control category")
    parser.add_argument("--date-from", help="Only include games on/after this date (YYYY.MM.DD)")
    parser.add_argument("--date-to", help="Only include games on/before this date (YYYY.MM.DD)")
    parser.add_argument("--min-opponent-elo", type=int, help="Only include games where the opponent's Elo was at least this")

    args = parser.parse_args()

    config = load_config(args.config)

    if args.lichess and args.chesscom:
        print("Error: --lichess and --chesscom are mutually exclusive; pick one source.")
        sys.exit(1)

    # CLI option overrides
    if args.lichess or args.chesscom:
        source = "lichess" if args.lichess else "chesscom"
        username = args.lichess or args.chesscom
        download_path = f"data/input/{source}_{username}.pgn"
        print(f"Downloading up to {args.download_limit} games for '{username}' from {source.capitalize()}...")
        try:
            download_games(source, username, max_games=args.download_limit, output_path=download_path)
        except Exception as e:
            print(f"Error downloading games from {source.capitalize()} for '{username}': {e}")
            sys.exit(1)
        config["input"]["pgn_path"] = download_path
        if args.player is None:
            config["target_player"]["name"] = username
        print(f"Downloaded games saved to '{download_path}'.")
    elif args.pgn:
        config["input"]["pgn_path"] = args.pgn
    if args.player is not None:
        config["target_player"]["name"] = args.player
    if args.color is not None:
        config["target_player"]["color"] = args.color
    if args.depth:
        config["analysis"]["main_depth"] = args.depth
    if args.critical_depth:
        config["analysis"]["critical_depth"] = args.critical_depth
    if args.threads:
        config["stockfish"]["threads"] = args.threads
    if args.hash:
        config["stockfish"]["hash_mb"] = args.hash
    if args.time_control is not None:
        config["filters"]["time_control_category"] = args.time_control
    if args.date_from is not None:
        config["filters"]["date_from"] = args.date_from
    if args.date_to is not None:
        config["filters"]["date_to"] = args.date_to
    if args.min_opponent_elo is not None:
        config["filters"]["min_opponent_elo"] = args.min_opponent_elo

    setup_logging(config)

    pgn_path = config["input"]["pgn_path"]
    target_player = config["target_player"]["name"]
    color_cfg = config["target_player"].get("color", "black")

    print("==================================================")
    print("      OPPONENT SCOUT PGN ANALYSIS SYSTEM          ")
    print("==================================================")
    print(f"Command: {args.command.upper()}")
    print(f"Input PGN: {pgn_path}")
    print(f"Target Player: {target_player if target_player else '[AUTO-DETECT]'}")
    print(f"Color: {color_cfg}")

    # Initialize Engine
    engine = StockfishEngine(config)
    if not args.no_engine:
        if engine.is_available():
            engine.start()
            print(f"Stockfish Engine: Initialized ({engine.version_info})")
        else:
            print("Stockfish Engine: Not configured or binary not found. Running in --no-engine fallback mode.")
            print("Tip: Specify Stockfish path in config.yaml under 'stockfish.path' (e.g. /usr/games/stockfish)")
    else:
        print("Stockfish Engine: Disabled via --no-engine flag.")

    colors_to_run = ["white", "black"] if color_cfg == "both" else [color_cfg]
    for color in colors_to_run:
        run_pipeline_for_color(config, args, engine, color)

    if engine:
        engine.close()

if __name__ == "__main__":
    main()
