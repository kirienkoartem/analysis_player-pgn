import sys
import os

# Add root project directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
import logging
from typing import Dict, Any

from src.config import load_config, setup_logging
from src.pgn.loader import load_pgn_games
from src.engine.stockfish import StockfishEngine
from src.analysis.batch_analyzer import BatchAnalyzer
from src.analysis.opening_analyzer import OpeningAnalyzer
from src.analysis.pattern_analyzer import PatternAnalyzer
from src.report.report_generator import ReportGenerator

logger = logging.getLogger("main")

def main():
    parser = argparse.ArgumentParser(
        description="Opponent Scout: Chess PGN Statistical & Engine Analysis System for Opponent Preparation"
    )

    parser.add_argument("command", choices=["validate", "analyze", "report", "export", "all"],
                        help="Action command to execute")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML configuration file")
    parser.add_argument("--pgn", help="Path to input PGN file")
    parser.add_argument("--player", help="Target opponent name (filters Black games)")
    parser.add_argument("--depth", type=int, help="Engine main search depth")
    parser.add_argument("--critical-depth", type=int, help="Engine deep search depth for critical positions")
    parser.add_argument("--threads", type=int, help="Stockfish threads")
    parser.add_argument("--hash", type=int, help="Stockfish Hash MB")
    parser.add_argument("--limit", type=int, help="Limit maximum games to analyze (useful for dry runs)")
    parser.add_argument("--no-engine", action="store_true", help="Run statistical analysis without Stockfish engine")

    args = parser.parse_args()

    config = load_config(args.config)

    # CLI option overrides
    if args.pgn:
        config["input"]["pgn_path"] = args.pgn
    if args.player is not None:
        config["target_player"]["name"] = args.player
    if args.depth:
        config["analysis"]["main_depth"] = args.depth
    if args.critical_depth:
        config["analysis"]["critical_depth"] = args.critical_depth
    if args.threads:
        config["stockfish"]["threads"] = args.threads
    if args.hash:
        config["stockfish"]["hash_mb"] = args.hash

    setup_logging(config)

    pgn_path = config["input"]["pgn_path"]
    target_player = config["target_player"]["name"]

    print("==================================================")
    print("      OPPONENT SCOUT PGN ANALYSIS SYSTEM          ")
    print("==================================================")
    print(f"Command: {args.command.upper()}")
    print(f"Input PGN: {pgn_path}")
    print(f"Target Player (Black): {target_player if target_player else '[AUTO-DETECT]'}")

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

    if args.command == "validate":
        print("\n--- Validating PGN ---")
        if not os.path.exists(pgn_path):
            print(f"Error: File '{pgn_path}' does not exist.")
            sys.exit(1)
        res = load_pgn_games(pgn_path, target_player=target_player, limit=args.limit)
        print(f"Total games in PGN: {res.total_games_in_pgn}")
        print(f"Auto-detected Target Player: {res.target_player}")
        print(f"Filtered Black Games: {len(res.filtered_games)}")
        print(f"Skipped Games: {len(res.skipped_games)}")
        for sk in res.skipped_games[:5]:
            print(f" - Game #{sk.index}: {sk.reason}")
        print("Validation COMPLETE.")

    elif args.command in ("analyze", "report", "export", "all"):
        if not os.path.exists(pgn_path):
            print(f"Error: File '{pgn_path}' does not exist.")
            sys.exit(1)

        batch_analyzer = BatchAnalyzer(config, engine=engine)
        batch_res = batch_analyzer.analyze_batch(limit=args.limit)

        op_analyzer = OpeningAnalyzer(config)
        deviations = op_analyzer.find_opening_deviations(batch_res.move_analyses)

        pat_analyzer = PatternAnalyzer(config)
        patterns = pat_analyzer.detect_recurring_patterns(batch_res.move_analyses)

        if args.command in ("report", "export", "all"):
            report_gen = ReportGenerator(config)
            profile = report_gen.generate_all_reports(
                pgn_result=batch_res.pgn_result,
                move_analyses=batch_res.move_analyses,
                patterns=patterns,
                deviations=deviations
            )
            print("\nAnalysis & Reports Generated Successfully!")
            print(f" - Markdown Report: {config['output']['report_path']}")
            print(f" - JSON Report: {config['output']['json_path']}")
            print(f" - Critical Positions PGN: {config['output']['critical_pgn_path']}")

    if engine:
        engine.close()

if __name__ == "__main__":
    main()
