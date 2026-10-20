"""Analyze one (player, color) from a PGN: writes a pickle with metadata,
per-move analyses and opening move lists. Run: worker.py PGN PLAYER COLOR OUTDIR"""
import sys, os, re, pickle, time, copy
sys.path.insert(0, "/home/user/analysis_player-pgn")
os.chdir("/home/user/analysis_player-pgn")
import chess, chess.pgn
from src.config import load_config
from src.engine.stockfish import StockfishEngine
from src.analysis.batch_analyzer import BatchAnalyzer

pgn_path, player, color, outdir = sys.argv[1:5]
BOT = re.compile(r"(lichess ai|stockfish|leela|maia|^bot|_bot$)", re.I)

# 1) strip games against engines/bots: they say nothing about human play
clean = os.path.join(outdir, f"{player}_clean.pgn")
kept = dropped = 0
with open(pgn_path, encoding="utf-8", errors="replace") as f, open(clean, "w", encoding="utf-8") as out:
    while True:
        g = chess.pgn.read_game(f)
        if g is None: break
        h = g.headers
        opp = h["Black"] if h["White"] == player else h["White"]
        if BOT.search(opp) or h.get("WhiteTitle") == "BOT" or h.get("BlackTitle") == "BOT":
            dropped += 1; continue
        print(g, file=out, end="\n\n"); kept += 1

cfg = load_config("config.yaml")
cfg["input"]["pgn_path"] = clean
cfg["target_player"].update(name=player, color=color)
cfg["stockfish"].update(threads=1, hash_mb=128)
cfg["analysis"].update(main_movetime_ms=120, critical_movetime_ms=400, critical_multipv=2)
cfg["cache"]["db_path"] = os.path.join(outdir, f"cache_{player}_{color}.sqlite")
cfg["logging"]["log_path"] = os.path.join(outdir, f"{player}_{color}.log")

eng = StockfishEngine(cfg); eng.start()
t0 = time.time()
res = BatchAnalyzer(cfg, engine=eng).analyze_batch()
eng.close()

opening_sans = {}
for rec in res.pgn_result.filtered_games:
    b = rec.game_node.board(); sans = []
    for i, mv in enumerate(rec.game_node.mainline_moves()):
        if i >= 24: break
        sans.append(b.san(mv)); b.push(mv)
    opening_sans[rec.metadata.game_id] = sans

pickle.dump({
    "player": player, "color": color, "bots_dropped": dropped,
    "metas": [r.metadata for r in res.pgn_result.filtered_games],
    "skip_counts": res.pgn_result.skip_counts(),
    "moves": res.move_analyses, "opening_sans": opening_sans,
    "seconds": time.time() - t0,
}, open(os.path.join(outdir, f"{player}_{color}.pkl"), "wb"))
print(player, color, "games", len(res.pgn_result.filtered_games), "moves", len(res.move_analyses), "sec", round(time.time()-t0))
