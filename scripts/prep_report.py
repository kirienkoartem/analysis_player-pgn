"""Builds the tournament-prep document spec (JSON) from analysed players.

Usage: prep_report.py WORKDIR OUT_JSON ME OPP1 OPP2 ...
Reads WORKDIR/<player>_{white,black}.pkl written by worker.py.
"""
import sys, os, json, pickle, statistics, math
sys.path.insert(0, "/home/user/analysis_player-pgn")
from collections import Counter, defaultdict
from types import SimpleNamespace

import chess, chess.svg, chess.engine, cairosvg

from src.aggregation.theme_stats import (
    compute_theme_stats, flatten, two_proportion_p_value, SERIOUS_WP, BLUNDER_WP,
    MIN_MOVES, wilson_interval, motif_breakdown,
)
from src.aggregation.game_outcomes import analyze_outcomes, uci_to_san
from src.analysis.themes import TAGS, MOTIFS
from src.aggregation.statistics import elo_expected_score
from src.chess.openings import OpeningTracker

WORK, OUT, ME, *OPPS = sys.argv[1:]
DIAG_DIR = os.path.join(WORK, "diagrams")
os.makedirs(DIAG_DIR, exist_ok=True)

# ----------------------------------------------------------------- loading
def load(player):
    d = {}
    for color in ("white", "black"):
        d[color] = pickle.load(open(os.path.join(WORK, f"{player}_{color}.pkl"), "rb"))
    return d

def outcome_of(meta, color):
    if meta.result == "1/2-1/2":
        return "draw"
    if meta.result == ("1-0" if color == "white" else "0-1"):
        return "win"
    if meta.result == ("0-1" if color == "white" else "1-0"):
        return "loss"
    return None

def own_opp_elo(meta, color):
    return (meta.white_elo, meta.black_elo) if color == "white" else (meta.black_elo, meta.white_elo)

def fmt_line(sans, upto=None):
    sans = sans[:upto] if upto else sans
    out = []
    for i, s in enumerate(sans):
        out.append(f"{i // 2 + 1}.{s}" if i % 2 == 0 else (s if out else f"{i // 2 + 1}...{s}"))
    return " ".join(out)

def pct(x, digits=0):
    return f"{100 * x:.{digits}f}%"

# ----------------------------------------------------------------- per-player
class P:
    pass

def build_player(name):
    d = load(name)
    p = P()
    p.name = name
    p.data = d
    p.moves = d["white"]["moves"] + d["black"]["moves"]
    p.metas = {c: d[c]["metas"] for c in d}
    p.sans = {}
    for c in d:
        p.sans.update(d[c]["opening_sans"])
    p.meta_by_id = {}
    for c in d:
        for m in d[c]["metas"]:
            p.meta_by_id[m.game_id] = (m, c)
    recs = {c: [SimpleNamespace(metadata=m) for m in d[c]["metas"]] for c in d}
    p.outcomes = analyze_outcomes(recs, p.moves)
    p.themes = compute_theme_stats(p.moves, p.outcomes.decisive_by_tag)
    p.theme_by_tag = {s.tag: s for s in flatten(p.themes)}
    p.n_games = sum(len(p.metas[c]) for c in p.metas)
    p.n_moves = len(p.moves)
    p.errors = sum(1 for m in p.moves if m.wp_loss >= SERIOUS_WP)
    p.blunders = sum(1 for m in p.moves if m.wp_loss >= BLUNDER_WP)
    p.err_rate = p.errors / max(1, p.n_moves)
    p.avg_wp = sum(m.wp_loss for m in p.moves) / max(1, p.n_moves)
    # results
    res = Counter(); exp = []
    for c in d:
        for m in d[c]["metas"]:
            r = outcome_of(m, c)
            if r:
                res[r] += 1
            o, q = own_opp_elo(m, c)
            if o and q:
                exp.append(elo_expected_score(o, q))
    p.res = res
    n = sum(res.values())
    p.score = (res["win"] + 0.5 * res["draw"]) / max(1, n)
    p.expected = sum(exp) / len(exp) if exp else None
    all_dates = sorted((m.date, own_opp_elo(m, c)[0]) for c in d for m in d[c]["metas"] if own_opp_elo(m, c)[0])
    recent = [e for _, e in all_dates[-60:]]
    p.elo = int(statistics.median(recent)) if recent else None
    opp_elos = [own_opp_elo(m, c)[1] for c in d for m in d[c]["metas"] if own_opp_elo(m, c)[1]]
    p.opp_elo = int(statistics.median(opp_elos)) if opp_elos else None
    tcs = Counter(m.time_control for c in d for m in d[c]["metas"])
    p.tc_top = tcs.most_common(3)
    cats = Counter(mv.time_control_category for mv in p.moves)
    tot = sum(cats.values())
    p.tc_share = {k: v / tot for k, v in cats.items()}
    p.avg_plies = statistics.mean(m.ply_count for c in d for m in d[c]["metas"])
    p.dates = (min(m.date for c in d for m in d[c]["metas"]), max(m.date for c in d for m in d[c]["metas"]))
    p.bots = d["white"]["bots_dropped"] + d["black"]["bots_dropped"]
    p.skips = Counter()
    for c in d:
        p.skips.update(d[c]["skip_counts"])
    return p

# ----------------------------------------------------------------- openings
def eval_after_opening(game_moves):
    """Player-perspective eval (cp) at the first own move from ply 19 on."""
    for m in game_moves:
        if m.move_number >= 19:
            return m.eval_before_black_perspective
    return None

def group_games(p, color, key_fn, filt=None):
    moves_by_game = defaultdict(list)
    for m in p.data[color]["moves"]:
        moves_by_game[m.game_id].append(m)
    groups = defaultdict(lambda: dict(n=0, w=0, d=0, l=0, exp=[], ev=[], oerr=0, omoves=0, ids=[]))
    for meta in p.metas[color]:
        sans = p.sans.get(meta.game_id, [])
        if filt and not filt(sans, meta):
            continue
        key = key_fn(sans, meta)
        if key is None:
            continue
        g = groups[key]
        g["n"] += 1
        r = outcome_of(meta, color)
        if r == "win": g["w"] += 1
        elif r == "draw": g["d"] += 1
        elif r == "loss": g["l"] += 1
        o, q = own_opp_elo(meta, color)
        if o and q:
            g["exp"].append(elo_expected_score(o, q))
        gm = sorted(moves_by_game.get(meta.game_id, []), key=lambda m: m.move_number)
        ev = eval_after_opening(gm)
        if ev is not None:
            g["ev"].append(ev)
        for m in gm:
            if m.move_number <= 24:
                g["omoves"] += 1
                g["oerr"] += m.wp_loss >= SERIOUS_WP
        g["ids"].append(meta.game_id)
    out = {}
    for k, g in groups.items():
        n = g["n"]
        out[k] = dict(
            n=n, score=(g["w"] + 0.5 * g["d"]) / n, w=g["w"], d=g["d"], l=g["l"],
            exp=(sum(g["exp"]) / len(g["exp"])) if g["exp"] else None,
            ev=(sum(g["ev"]) / len(g["ev"])) if g["ev"] else None,
            oerr=g["oerr"] / n, ids=g["ids"],
        )
    return out

def line_name(meta):
    return meta.opening.split(",")[0]

# ----------------------------------------------------------------- recurring mistakes
def epd(fen):
    return " ".join(fen.split()[:4])

_ENG = None

def punish_line(fen_after):
    """Engine's best continuation for the side to move AFTER a mistake -
    i.e. what the user should play when the opponent repeats it."""
    global _ENG
    if _ENG is None:
        _ENG = chess.engine.SimpleEngine.popen_uci("/usr/games/stockfish")
        _ENG.configure({"Threads": 2, "Hash": 256})
    b = chess.Board(fen_after)
    if b.is_game_over():
        return ""
    info = _ENG.analyse(b, chess.engine.Limit(time=0.7))
    pv = info.get("pv", [])[:3]
    return b.variation_san(pv) if pv else ""


def recurring(p, opening_only=False, limit=8, punish=False):
    groups = defaultdict(list)
    for m in p.moves:
        if m.wp_loss >= SERIOUS_WP and (not opening_only or m.move_number <= 24):
            groups[(epd(m.fen_before), m.san)].append(m)
    out = []
    for (e, san), ms in groups.items():
        games = sorted({m.game_id for m in ms})
        if len(games) < 2:
            continue
        first = ms[0]
        best_san = uci_to_san(first.fen_before, first.best_move) if first.best_move else "?"
        path = None
        if first.move_number <= 24:
            sans = p.sans.get(first.game_id)
            if sans and len(sans) >= first.move_number:
                path = fmt_line(sans, first.move_number - 1)
        out.append(dict(
            games=len(games), san=san, best=best_san, avg_wp=sum(m.wp_loss for m in ms) / len(ms),
            opening=first.opening, fullmove=first.fullmove_number, path=path,
            fen=first.fen_before, fen_after=first.fen_after, played_uci=first.uci, best_uci=first.best_move,
            side=first.side, game_ids=games[:5],
            links=[p.meta_by_id[g][0].link for g in games[:3] if p.meta_by_id[g][0].link],
            tags=first.tags,
        ))
    out.sort(key=lambda r: -(r["games"] * r["avg_wp"]))
    out = out[:limit]
    if punish:
        for r in out:
            r["punish"] = punish_line(r["fen_after"])
    return out

def diagram(r, key):
    board = chess.Board(r["fen"])
    arrows = []
    try:
        if r["best_uci"]:
            b = chess.Move.from_uci(r["best_uci"])
            arrows.append(chess.svg.Arrow(b.from_square, b.to_square, color="#1B7A3D"))
        pm = chess.Move.from_uci(r["played_uci"])
        arrows.append(chess.svg.Arrow(pm.from_square, pm.to_square, color="#B3261E"))
    except ValueError:
        pass
    svg = chess.svg.board(board, arrows=arrows, size=340, orientation=(r["side"] == "white"))
    path = os.path.join(DIAG_DIR, f"{key}.png")
    cairosvg.svg2png(bytestring=svg.encode(), write_to=path, output_width=340, output_height=340)
    return path

# ----------------------------------------------------------------- knowledge base
KB = {
    "endgame:rook": ("Ладейные эндшпили",
        ["Выучите позиции Лусены и Филидора и правило «ладья за проходной пешкой» (Тарраш).",
         "Принцип активности: отрезайте короля соперника по линии/вертикали, не пассивьте ладью ради пешки.",
         "Разбирайте по 2–3 позиции в день на Lichess → Обучение → Практика → Ладейные эндшпили."],
        "rookEndgame"),
    "endgame:pawn": ("Пешечные эндшпили",
        ["Оппозиция, правило квадрата, ключевые поля, треугольник — по одному правилу в день с проверкой на позициях.",
         "Считайте варианты до конца: в пешечном эндшпиле почти всё форсировано."],
        "pawnEndgame"),
    "endgame:queen": ("Ферзевые эндшпили",
        ["Вечные шахи — главный ресурс защиты: изучите типовые схемы и ловушки.",
         "Активность ферзя и безопасность короля важнее лишней пешки."],
        "queenEndgame"),
    "endgame:bishop": ("Слоновые эндшпили (одноцветные)",
        ["Размещайте пешки на цвет, противоположный своему слону, и ставьте слона на длинную диагональ.",
         "Практика: Lichess → Практика → слоновые эндшпили."],
        "bishopEndgame"),
    "endgame:opposite_bishops": ("Разноцветные слоны",
        ["С лишней пешкой часто ничья — не разменивайте ладьи без нужды; в защите стройте крепость на цвет слона соперника.",
         "Атакуйте вместе слоном и ладьёй/ферзём — разноцветные слоны усиливают атаку."],
        "endgame"),
    "endgame:knight": ("Коневые эндшпили",
        ["Конь слаб в борьбе с проходной на краю — считайте темпы; ставьте коня на опорные поля.",
         "Пешечные структуры с пешками на обоих флангах предпочтительнее для коня."],
        "knightEndgame"),
    "endgame:minor": ("Слон против коня",
        ["Слон сильнее при пешках на обоих флангах, конь — в закрытых позициях; выбирайте план под это."],
        "endgame"),
    "endgame:rook_minor": ("Ладья + лёгкая фигура",
        ["Следите за слабыми полями и вторжением ладьи на 7-ю горизонталь; не позволяйте разменом вывести соперника из-под удара."],
        "endgame"),
    "endgame:mixed": ("Смешанные эндшпили",
        ["Считайте материальный баланс по-новому: ферзь против ладьи+фигуры — это не «+1», а вопрос активности."],
        "endgame"),
    "mg:queens_on": ("Миттельшпиль с ферзями",
        ["Перед каждым ходом проверяйте шахи, взятия и угрозы соперника (метод «CCT»: шахи, взятия, угрозы).",
         "Тактика на ферзевых фланговых атаках: 15 мин задач в день по темам fork, pin, discoveredAttack."],
        "middlegame"),
    "mg:queenless": ("Миттельшпиль без ферзей",
        ["Планируйте активность короля и пешечные рычаги; тренируйте стратегию «хорошая фигура против плохой»."],
        "middlegame"),
    "mg:opposite_castling": ("Разносторонние рокировки",
        ["Атака побеждает защиту: двигайте пешки на вскрытие линий против короля, не обменивайте свои атакующие фигуры."],
        "kingsideAttack"),
    "struct:iqp_own": ("Изолированная пешка d (ваша)",
        ["Держите фигуры активными и избегайте размена без компенсации: изолятор слаб в эндшпиле, силён в атаке."],
        "middlegame"),
    "struct:iqp_opp": ("Играть против изолятора",
        ["Блокируйте пешку конём на d5/d4 и меняйте лёгкие фигуры — тогда слабость решает в эндшпиле."],
        "middlegame"),
    "trans:after_queen_trade": ("Ходы сразу после размена ферзей",
        ["После размена пересчитайте оценку позиции с нуля: план меняется (король в центр, пешечное большинство, активность ладей).",
         "Перед обменом спросите: «в каком эндшпиле я окажусь и нравится ли он мне?»."],
        "endgame"),
    "ctx:losing": ("Защита хуже стоящей позиции",
        ["Тренируйте оборонительные задачи: Lichess → Тактические задачи → тема defensiveMove, quietMove.",
         "Правило: в тяжёлой позиции ищите ходы, усложняющие игру и затягивающие партию, а не пассивные."],
        "defensiveMove"),
    "ctx:better": ("Реализация небольшого перевеса",
        ["Улучшайте худшую фигуру, не форсируйте; цель — безопасно прибавить, а не «найти выигрыш»."],
        "advantage"),
    "ctx:winning": ("Реализация выигранной позиции",
        ["Тема «advantage» и «crushing» в задачах; правило «упрощай и проверяй контрыгру» перед каждым ходом.",
         "Не позволяйте себе «расслабляться» при +3: перед ходом проверяйте угрозы соперника."],
        "crushing"),
    "time:pressure": ("Игра в цейтноте",
        ["Тренируйте распределение времени: 10–12 минут на дебют/план, резерв на критический момент.",
         "Играйте блиц-серии с заданным запасом (например 3+2) и разбирайте только партии, где вышли в цейтнот."],
        "mate"),
    "phase:opening": ("Дебют",
        ["Закрепите 1–2 главных схемы в каждом дебюте: понимайте план, а не заучивайте варианты.",
         "После каждой партии сверяйте первые 12 ходов с базой Lichess и отмечайте, где вышли из теории."],
        "opening"),
    "phase:middlegame": ("Миттельшпиль",
        ["Решайте задачи по темам, где вы теряли материал; 20 минут в день."],
        "middlegame"),
    "phase:endgame": ("Эндшпиль вообще",
        ["Эндшпильный минимум: Лусена, Филидор, оппозиция, правило квадрата, тема «слабая/сильная сторона»."],
        "endgame"),
}
MOTIF_ADVICE = {
    "allowed_tactic": "Зевки тактики (оставляете фигуру под боем / пропускаете удар): перед каждым ходом проверяйте «что соперник может взять или с чем пошахует после моего хода». Ежедневно 15 минут задач по темам hangingPiece, fork, pin, discoveredAttack.",
    "missed_tactic": "Упущенные тактические удары: по 10–15 задач в день на тему «найти лучший ход» (темы crushing, advantage), считайте 3–4 хода.",
    "missed_mate": "Упущенные маты: серия задач на мат в 2–3 хода (тема mate) — 10 в день.",
    "positional": "Позиционные ошибки: разбирайте партии мастеров по теме вашего дебюта и ищите плановые ходы (улучшение худшей фигуры, пешечные рычаги).",
}

# ----------------------------------------------------------------- selected comparison themes
CMP_TAGS = [
    "phase:opening", "phase:middlegame", "phase:endgame",
    "endgame:rook", "endgame:rook_minor", "endgame:minor", "endgame:bishop", "endgame:opposite_bishops",
    "endgame:knight", "endgame:queen", "endgame:pawn",
    "mg:queens_on", "mg:queenless", "mg:opposite_castling", "trans:after_queen_trade",
    "ctx:losing", "ctx:better", "ctx:winning", "time:pressure",
]

def apply_pooled(players):
    """Replaces each ThemeStat's own-baseline verdict with one against an
    EXPECTED rate: how error-prone this type of position is for the OTHER
    players in the sample (leave-one-out), scaled by how this player plays
    the reference positions. Universal difficulty (time pressure, positions
    with an advantage, rook+minor endings) then isn't read as a personal
    weakness."""
    for pl in players:
        others = [q for q in players if q is not pl]
        for tag, st in pl.theme_by_tag.items():
            st.own_ref_rate = st.reference_error_rate
            e_t = n_t = e_r = n_r = 0.0
            for q in others:
                t = q.theme_by_tag.get(tag)
                if t is None:
                    continue
                e_t += t.errors; n_t += t.moves
                e_r += t.reference_error_rate * t.reference_moves; n_r += t.reference_moves
            if n_t < 100 or n_r < 100 or e_r <= 0 or e_t <= 0:
                st.verdict, st.p_value, st.ratio = "insufficient", None, None
                continue
            pooled_ratio = (e_t / n_t) / (e_r / n_r)
            exp = min(0.95, max(1e-4, pooled_ratio * st.own_ref_rate))
            st.reference_error_rate = exp
            st.reference_label = "обычный уровень"
            st.excess_errors = st.errors - st.moves * exp
            st.ratio = st.errors / (st.moves * exp)
            z = (st.errors - st.moves * exp) / math.sqrt(st.moves * exp * (1 - exp))
            st.p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
            if st.moves < MIN_MOVES or st.games < 8:
                st.verdict = "insufficient"
            elif st.p_value < 0.01 and st.ratio >= 1.25:
                st.verdict = "weak"
            elif st.p_value < 0.01 and st.ratio <= 0.80:
                st.verdict = "strong"
            else:
                st.verdict = "neutral"


# themes a player can actually steer a game toward or away from
ACTIONABLE_TAGS = [t for t in CMP_TAGS if not t.startswith(("phase:", "ctx:", "time:"))]


def theme_rate(p, tag):
    s = p.theme_by_tag.get(tag)
    return s

def verdict_level(s):
    """confirmed weak/strong from theme_stats, plus a lower-confidence 'trend'."""
    if s is None:
        return "none"
    if s.verdict in ("weak", "strong"):
        return s.verdict
    if (s.verdict == "neutral" and s.p_value is not None and s.p_value < 0.05 and s.ratio
            and s.moves >= MIN_MOVES and s.games >= 8):
        if s.ratio >= 1.25:
            return "trend_weak"
        if s.ratio <= 0.8:
            return "trend_strong"
    return s.verdict

def describe(s):
    return (f"{s.label}: ошибок {pct(s.error_rate, 1)} ходов ({s.errors} из {s.moves}, {s.games} партий) "
            f"при ожидаемых {pct(s.reference_error_rate, 1)} для таких позиций")

def weak_list(p, levels=("weak",)):
    out = [s for s in flatten(p.themes) if verdict_level(s) in levels and not s.tag.startswith("phase:")]
    out.sort(key=lambda s: -s.excess_errors)
    return out

def strong_list(p, levels=("strong",)):
    out = [s for s in flatten(p.themes) if verdict_level(s) in levels]
    out.sort(key=lambda s: s.excess_errors)
    return out

# ================================================================= composing
doc = []
def H1(t): doc.append({"t": "h1", "text": t})
def H2(t): doc.append({"t": "h2", "text": t})
def H3(t): doc.append({"t": "h3", "text": t})
def PARA(t): doc.append({"t": "p", "text": t})
def NOTE(t): doc.append({"t": "note", "text": t})
def BUL(items): doc.append({"t": "bullets", "items": [i for i in items if i]})
def BREAK(): doc.append({"t": "break"})
def IMG(path, w=300, caption=None): doc.append({"t": "image", "path": path, "w": w, "caption": caption})
def TABLE(header, rows, widths): doc.append({"t": "table", "header": header, "rows": rows, "widths": widths})

RED, GREEN, AMBER, GREY = "FBE3E1", "DDF1E3", "FFF1CC", "EEEEEE"
def C(text, fill=None, bold=False): return {"text": str(text), "fill": fill, "bold": bold}

def vfill(level):
    return {"weak": RED, "trend_weak": AMBER, "strong": GREEN, "trend_strong": "EEF8F0",
            "insufficient": GREY}.get(level)

def vlabel(level):
    return {"weak": "слабое место", "trend_weak": "возможная слабость", "strong": "сильная сторона",
            "trend_strong": "скорее сильная сторона", "neutral": "в норме",
            "insufficient": "мало данных", "none": "нет данных"}.get(level, level)

def sc(x): return pct(x) if x is not None else "–"
def evs(x): return f"{x / 100:+.2f}" if x is not None else "–"

def opening_rows(groups, names, user_groups=None, top=8, min_n=2):
    items = sorted(groups.items(), key=lambda kv: -kv[1]["n"])
    rows = []
    for key, g in items:
        if g["n"] < min_n or len(rows) >= top:
            continue
        diff = (g["score"] - g["exp"]) if g["exp"] is not None else None
        fill = None
        if diff is not None and g["n"] >= 6:
            fill = RED if diff <= -0.12 else (GREEN if diff >= 0.12 else None)
        row = [key, names.get(key, ""), g["n"], sc(g["score"]), sc(g["exp"]), evs(g["ev"]), f"{g['oerr']:.1f}"]
        if user_groups is not None:
            ug = user_groups.get(key)
            row.append(f"{sc(ug['score'])} (n={ug['n']})" if ug else "–")
        rows.append([C(row[0]), C(row[1])] + [C(x, fill if i == 1 else None) for i, x in enumerate(row[2:])])
    return rows

def names_for(p, color, groups):
    names = {}
    for key, g in groups.items():
        c = Counter(p.meta_by_id[i][0].opening.split(",")[0] for i in g["ids"])
        names[key] = c.most_common(1)[0][0]
    return names

def theme_table(p, groups_to_show):
    rows = []
    for gkey in groups_to_show:
        for s in p.themes.get(gkey, []):
            lv = verdict_level(s)
            rows.append([C(s.label), C(f"{pct(s.error_rate, 1)}", vfill(lv)), C(f"{pct(s.reference_error_rate, 1)}"),
                         C(f"{s.ratio:.2f}×" if s.ratio else "–"), C(f"{s.moves} / {s.games}"),
                         C(vlabel(lv), vfill(lv), bold=lv in ("weak", "strong"))])
    return rows

def steer_logic(opp, me):
    steer, avoid_me, mutual, opp_strong = [], [], [], []
    for tag in ACTIONABLE_TAGS:
        so, su = opp.theme_by_tag.get(tag), me.theme_by_tag.get(tag)
        if so is None:
            continue
        vo = verdict_level(so)
        vu = verdict_level(su) if su else "none"
        if vo in ("weak", "trend_weak"):
            (mutual if vu in ("weak", "trend_weak") else steer).append((tag, so, su, vo, vu))
        if vu in ("weak", "trend_weak") and vo not in ("weak", "trend_weak"):
            avoid_me.append((tag, so, su, vo, vu))
        if vo in ("strong", "trend_strong"):
            opp_strong.append((tag, so, su, vo, vu))
    return steer, avoid_me, mutual, opp_strong

def first_move_table(p, color, me_groups=None):
    g = group_games(p, color, lambda s, m: s[0] if s else None)
    rows = []
    for k, v in sorted(g.items(), key=lambda kv: -kv[1]["n"]):
        if v["n"] < 3:
            continue
        rows.append([C(k), C(v["n"]), C(sc(v["n"] / len(p.metas[color]))), C(sc(v["score"])), C(sc(v["exp"])), C(evs(v["ev"]))])
    return rows

def dossier(p, me):
    H1(f"Досье: {p.name}")
    # ---- profile
    H2("1. Профиль")
    steer, avoid_me, mutual, opp_strong = steer_logic(p, me)
    mot = motif_breakdown(p.moves)
    mot_total = sum(mot.values()) or 1
    BUL([
        f"Рейтинг по последним партиям: ~{p.elo}; средний рейтинг его соперников {p.opp_elo}. "
        f"Ваш: ~{me.elo}. Разница: {p.elo - me.elo:+d}." if p.elo and me.elo else None,
        f"Проанализировано {p.n_games} партий ({len(p.metas['white'])} белыми, {len(p.metas['black'])} чёрными), "
        f"{p.n_moves} ходов; период {p.dates[0]} – {p.dates[1]}.",
        f"Результат: +{p.res['win']} ={p.res['draw']} −{p.res['loss']}, набрано {sc(p.score)} очков"
        + (f" при ожидаемых по рейтингам {sc(p.expected)}." if p.expected else "."),
        "Контроль времени: " + ", ".join(f"{tc} ({n})" for tc, n in p.tc_top) + ".",
        f"Серьёзных ошибок (падение шансов на победу ≥ 10 пунктов): {p.err_rate * 100:.1f} на 100 ходов "
        f"(у вас — {me.err_rate * 100:.1f}); грубых (≥ 15) — {p.blunders / max(1, p.n_moves) * 100:.1f} (у вас — {me.blunders / max(1, me.n_moves) * 100:.1f}).",
        "Структура его серьёзных ошибок: " + ", ".join(
            f"{MOTIFS[k].split(':')[0].lower()} — {pct(v / mot_total)}" for k, v in sorted(mot.items(), key=lambda kv: -kv[1])) + "."
        if mot else None,
        f"Средняя длина партии: {p.avg_plies / 2:.0f} ходов.",
    ])

    # ---- as White
    H2("2. Когда он играет белыми (вы — чёрными: c5 против 1.e4, Nf6 и e6 против 1.d4)")
    ft = first_move_table(p, "white")
    TABLE(["Первый ход", "Партий", "Доля", "Его счёт", "Ожидаемый по рейтингам", "Оценка после дебюта (для него)"], ft, [1400, 1200, 1200, 1400, 2000, 2160])
    NOTE("«Оценка после дебюта» — средняя оценка движка (в пешках, с его точки зрения) на 10-м ходу; "
         "положительная — дебют даёт ему преимущество, отрицательная — приводит к худшей позиции. Выборки в линиях небольшие: "
         "ориентируйтесь на повторяющиеся линии, а не на отдельный процент.")
    me_b = group_games(me, "black", lambda s, m: line_name(m))
    first_moves = group_games(p, "white", lambda s, m: s[0] if s else None)
    branches = [("e4", "c5", "1.e4 — вы отвечаете c5"), ("d4", "Nf6", "1.d4 — вы отвечаете Nf6")]
    for fm, v in sorted(first_moves.items(), key=lambda kv: -kv[1]["n"]):
        if fm not in ("e4", "d4") and v["n"] >= 15 and v["n"] >= 0.2 * len(p.metas["white"]):
            branches.append((fm, None, f"1.{fm} — его основной ход (ответ на него выберите заранее)"))
    for first, reply, label in branches:
        if reply is None:
            flt = lambda s, m, first=first: s[:1] == [first]
        else:
            flt = lambda s, m, first=first, reply=reply: len(s) > 1 and s[0] == first and s[1] == reply
        g_all = group_games(p, "white", lambda s, m, first=first: fmt_line(s, 6), lambda s, m, first=first: s[:1] == [first])
        n_branch = sum(g["n"] for g in g_all.values())
        if n_branch == 0:
            continue
        g_rep = group_games(p, "white", lambda s, m: fmt_line(s, 6), flt)
        n_rep = sum(g["n"] for g in g_rep.values())
        use = g_rep if n_rep >= 8 else g_all
        if n_branch < 4:
            continue
        H3(label)
        if use is g_all:
            NOTE(f"Партий именно с вашим ответом ({reply}) у него только {n_rep} — показаны все его линии после 1.{first}.")
        names = names_for(p, "white", use)
        ug = group_games(me, "black", lambda s, m: fmt_line(s, 6), lambda s, m, first=first: s[:1] == [first])
        TABLE(["Линия (6 полуходов)", "Название", "Партий", "Его счёт", "Ожид.", "Оценка", "Ошибок в дебюте/партию", "Ваш счёт в линии"],
              opening_rows(use, names, ug, top=8, min_n=2), [2300, 2000, 700, 800, 750, 750, 1000, 1060])

    # ---- as Black
    H2("3. Когда он играет чёрными против вашего 1.e4")
    flt_e4 = lambda s, m: s[:1] == ["e4"]
    rep = group_games(p, "black", lambda s, m: s[1] if len(s) > 1 else None, flt_e4)
    me_rep = group_games(me, "white", lambda s, m: s[1] if len(s) > 1 else None, flt_e4)
    n_e4 = sum(g["n"] for g in rep.values())
    n_all_black = len(p.metas["black"])
    PARA(f"Против 1.e4 сыграно {n_e4} из {n_all_black} партий чёрными (остальные — другие первые ходы белых).")
    rows = []
    plan = {"e5": "Итальянская партия: 2.Nf3 Nc6 3.Bc4", "c5": "Ваша схема против сицилианской"}
    for k, v in sorted(rep.items(), key=lambda kv: -kv[1]["n"]):
        if v["n"] < 3:
            continue
        mu = me_rep.get(k)
        rows.append([C(k), C(v["n"]), C(sc(v["n"] / n_e4)), C(sc(v["score"])), C(sc(v["exp"])), C(evs(v["ev"])),
                     C(f"{sc(mu['score'])} (n={mu['n']})" if mu else "–"), C(plan.get(k, "по ситуации"))])
    TABLE(["Ответ на 1.e4", "Партий", "Доля", "Его счёт", "Ожид.", "Оценка", "Ваш счёт в этой структуре", "Что играть"],
          rows, [1200, 800, 800, 1000, 800, 800, 1700, 2260])
    # Italian block
    ital = group_games(p, "black", lambda s, m: s[5] if len(s) > 5 else None,
                       lambda s, m: s[:5] == ["e4", "e5", "Nf3", "Nc6", "Bc4"])
    n_e5 = rep.get("e5", {}).get("n", 0)
    n_nf3 = sum(1 for m in p.metas["black"] if p.sans.get(m.game_id, [])[:3] == ["e4", "e5", "Nf3"])
    n_nc6 = sum(1 for m in p.metas["black"] if p.sans.get(m.game_id, [])[:4] == ["e4", "e5", "Nf3", "Nc6"])
    if n_e5:
        H3("Итальянская партия (1.e4 e5 2.Nf3 Nc6 3.Bc4)")
        PARA(f"После 1.e4 e5 он получал 2.Nf3 в {n_nf3} партиях, из них 2…Nc6 играл {n_nc6} раз. "
             + (f"Против 3.Bc4 его ответы: " + ", ".join(
                 f"{k} — {v['n']} (счёт {sc(v['score'])})" for k, v in sorted(ital.items(), key=lambda kv: -kv[1]["n"])) + "."
                if ital else "Против 3.Bc4 в его партиях выборки нет — готовьтесь по общим принципам дебюта."))
        deep = group_games(p, "black", lambda s, m: fmt_line(s, 8), lambda s, m: s[:5] == ["e4", "e5", "Nf3", "Nc6", "Bc4"] and len(s) >= 8)
        nm = names_for(p, "black", deep)
        TABLE(["Линия (8 полуходов)", "Название", "Партий", "Его счёт", "Ожид.", "Оценка", "Ошибок в дебюте/партию"],
              opening_rows(deep, nm, None, top=6, min_n=2), [2900, 2300, 800, 900, 800, 800, 960])
    for k in [k for k, v in sorted(rep.items(), key=lambda kv: -kv[1]["n"]) if k != "e5" and v["n"] >= 6][:2]:
        H3(f"Ответ 1…{k}: его линии")
        g6 = group_games(p, "black", lambda s, m: fmt_line(s, 6), lambda s, m, k=k: s[:2] == ["e4", k])
        nm = names_for(p, "black", g6)
        ug = group_games(me, "white", lambda s, m: fmt_line(s, 6), lambda s, m, k=k: s[:2] == ["e4", k])
        TABLE(["Линия", "Название", "Партий", "Его счёт", "Ожид.", "Оценка", "Ошибок в дебюте/партию", "Ваш счёт в линии"],
              opening_rows(g6, nm, ug, top=6, min_n=2), [2300, 2000, 700, 800, 750, 750, 1000, 1060])

    # ---- weaknesses
    H2("4. Слабые и сильные стороны по типам позиций")
    PARA("«Ожидаемо» — сколько ошибок можно ждать от этого игрока в таких позициях: исходя из того, как он играет сопоставимые позиции вообще, "
         "и из того, насколько этот тип позиций труден для остальных игроков выборки. Так универсальная сложность (цейтнот, позиции с перевесом, "
         "эндшпили с ладьёй и фигурой) не выдаётся за личную слабость.")
    rows = theme_table(p, ["phase", "endgame", "middlegame", "transition", "context", "time"])
    TABLE(["Тема", "Ошибок в ходах", "Ожидаемо", "Факт / ожидание", "Ходов / партий", "Вывод"], rows, [2700, 1300, 1100, 1100, 1300, 1860])
    NOTE("Красное — ошибается заметно чаще ожидаемого (достаточная выборка, p < 0,01, превышение ≥ 25 %); жёлтое — тенденция (p < 0,05); "
         "зелёное — заметно реже ожидаемого; серое — слишком мало данных для вывода.")
    weak = weak_list(p, ("weak", "trend_weak"))
    PARA("Главное по эндшпилям:")
    eg = [s for s in p.themes.get("endgame", []) if s.moves >= 15]
    egl = []
    for s in eg:
        lv = verdict_level(s)
        egl.append(f"{s.label}: {pct(s.error_rate, 1)} ошибок на {s.moves} ходов ({s.games} партий) — {vlabel(lv)}")
    BUL(egl or ["Эндшпилей в выборке почти нет — выводов о типах эндшпилей сделать нельзя."])
    eg_ok = [s for s in eg if verdict_level(s) not in ("insufficient", "none")]
    if eg_ok:
        worst = max(eg_ok, key=lambda s: s.ratio or 0)
        best = min(eg_ok, key=lambda s: s.ratio or 9)
        PARA(f"Итог по эндшпилям: относительно ожидаемого хуже всего — {worst.label.lower()} ({worst.ratio:.1f}× ожидаемых ошибок), "
             f"лучше всего — {best.label.lower()} ({best.ratio:.1f}×)." if worst is not best else "Типов эндшпилей с достаточной выборкой мало для сравнения.")
    if weak:
        PARA("Подтверждённые и вероятные слабости (по убыванию «лишних» ошибок):")
        BUL([describe(s) + f" — {vlabel(verdict_level(s))}." for s in weak[:6]])
    else:
        PARA("Статистически значимых слабостей по типам позиций не обнаружено — игра ровная; лучше всего искать конкретные повторяющиеся ошибки (раздел 6).")

    # ---- outcomes
    H2("5. Как он теряет очки")
    oc = p.outcomes
    losses, blown, comebacks, tl = oc.losses, oc.blown_wins, oc.comebacks, oc.time_losses
    wins_total = p.res["win"]
    tag_names = {k: TAGS[k] for k in TAGS}
    dec = Counter({k: v for k, v in oc.decisive_by_tag.items() if k.split(":")[0] in ("phase", "endgame", "mg", "trans", "ctx", "time", "struct")})
    top_dec = [(k, v) for k, v in dec.most_common() if k.startswith(("endgame", "mg", "trans")) or k in ("time:pressure",)][:4]
    BUL([
        f"Проиграно {len(losses)} партий; решающая ошибка (падение шансов ≥ 15 пунктов из ещё не проигранной позиции) найдена в "
        f"{sum(1 for g in losses if g.decisive_move)}.",
        "Чаще всего решающая ошибка приходилась на: " + ", ".join(f"{TAGS[k]} ({v})" for k, v in top_dec) + "." if top_dec else None,
        f"Выигранная позиция (оценка ≥ +3) была в {sum(1 for g in oc.games if g.max_eval >= 300)} партиях, "
        f"не реализовано (ничья/поражение) — {len(blown)}.",
        f"Спасённые безнадёжные позиции (оценка ≤ −3): {len(comebacks)} партий (из них побед: "
        f"{sum(1 for g in comebacks if g.result == 'win')}) — насколько он цепкий в защите.",
        f"Поражений по времени: {len(tl)}; из них в не худшей позиции — {len(oc.time_losses_not_worse)}.",
    ])
    if blown:
        PARA("Примеры упущенных побед (можно давить на реализацию):")
        BUL([f"{g.opponent} ({g.opponent_elo or '?'}), {g.date}: {g.link or ''}" for g in blown[:3]])

    # ---- recurring mistakes
    H2("6. Повторяющиеся ошибки (одна и та же позиция, один и тот же неверный ход)")
    rec = recurring(p, limit=8, punish=True)
    p.rec = rec
    if not rec:
        PARA("Позиций, где он повторял бы одну и ту же серьёзную ошибку в разных партиях, не найдено.")
    else:
        rows = []
        for r in rec:
            where = f"{r['opening']}, ход {r['fullmove']}" + (f"\n{r['path']}" if r['path'] else "")
            rows.append([C(where.replace("\n", " — ")), C(r["san"], bold=True), C(r["best"]), C(r["games"]),
                         C(f"{r['avg_wp']:.0f}"), C(r.get("punish") or "–", bold=True)])
        TABLE(["Где", "Он играет", "Надо было", "Партий", "Потеря шансов", "Ваш ответ (по движку)"], rows, [3300, 900, 900, 800, 1000, 2460])
        NOTE("Потеря шансов — среднее падение вероятности победы в пунктах (из 100). Стрелки на диаграммах: красная — его ход, зелёная — ход движка.")
        for i, r in enumerate(rec[:3]):
            IMG(diagram(r, f"{p.name}_{i}"), 250,
                f"{p.name}: {r['opening']}, ход {r['fullmove']} — играет {r['san']}, лучше {r['best']} ({r['games']} партий)")

    # ---- plan
    H2("7. План игры против него")
    items = []
    if rep.get("e5") and rep["e5"]["n"] >= 5:
        items.append("Дебют белыми: на 1.e4 e5 идите в итальянскую партию — он встречал её "
                     f"{n_nc6 and sum(g['n'] for g in ital.values()) or 0} раз; играйте по плану, не гонитесь за теорией.")
    for tag, so, su, vo, vu in steer[:4]:
        items.append(f"ВЕСТИ ПАРТИЮ В: {TAGS[tag].lower()} — у него {pct(so.error_rate, 1)} ошибок при ожидаемых {pct(so.reference_error_rate, 1)}"
                     + ((f"; у вас здесь {pct(su.error_rate, 1)}" + (" — выше, чем у него, поэтому играйте здесь внимательно, побеждает тот, кто аккуратнее." if su.error_rate > so.error_rate * 1.1 else " — не хуже, чем у него.")) if su else "."))
    for tag, so, su, vo, vu in opp_strong[:3]:
        items.append(f"ИЗБЕГАТЬ: {TAGS[tag].lower()} — это его сильная сторона ({pct(so.error_rate, 1)} ошибок при ожидаемых {pct(so.reference_error_rate, 1)}).")
    for tag, so, su, vo, vu in avoid_me[:3]:
        items.append(f"ИЗБЕГАТЬ ДЛЯ СЕБЯ: {TAGS[tag].lower()} — ваша слабость ({pct(su.error_rate, 1)} ошибок при ожидаемых {pct(su.reference_error_rate, 1)}), а у него по этой теме проблем нет.")
    for tag, so, su, vo, vu in mutual[:2]:
        items.append(f"ОБОЮДНАЯ СЛАБОСТЬ: {TAGS[tag].lower()} — слабо у обоих; исход зависит от того, кто аккуратнее считает.")
    for rk, rv in sorted(rep.items(), key=lambda kv: -kv[1]["n"])[:2]:
        mu = me_rep.get(rk)
        if mu and mu["n"] >= 10 and rv["n"] >= 10:
            if mu["score"] < 0.45:
                items.append(f"Ответ 1…{rk} — его основной против 1.e4 ({pct(rv['n'] / max(1, n_e4))} партий). Ваш счёт белыми против него всего "
                             f"{sc(mu['score'])} (n={mu['n']}) — потратьте на эту структуру основное время подготовки.")
            elif mu["score"] >= 0.6:
                items.append(f"Ответ 1…{rk} — его основной против 1.e4; ваш счёт белыми против него хороший: {sc(mu['score'])} (n={mu['n']}) — держите этот путь.")
    me_first = group_games(me, "black", lambda s, m: s[0] if s else None)
    for fm, v in sorted(first_moves.items(), key=lambda kv: -kv[1]["n"])[:2]:
        mu = me_first.get(fm)
        if mu and mu["n"] >= 10 and v["n"] >= 15:
            if mu["score"] < 0.45:
                items.append(f"Первый ход 1.{fm} — его основной ({pct(v['n'] / len(p.metas['white']))} партий). Ваш счёт чёрными против 1.{fm} — {sc(mu['score'])} (n={mu['n']}): повторите эту структуру заранее.")
            elif mu["score"] >= 0.6:
                items.append(f"Первый ход 1.{fm} — его основной; ваш счёт чёрными против него хороший: {sc(mu['score'])} (n={mu['n']}).")
    for tag, text in (
        ("ctx:losing", "Если он окажется хуже, защищается слабее ожидаемого — наращивайте давление и не спешите упрощать."),
        ("ctx:better", "Не всегда реализует небольшой перевес — если вы немного хуже, держитесь и усложняйте: шанс на возврат реален."),
        ("ctx:winning", "Не доводит выигранные позиции — не сдавайтесь, пока на доске есть фигуры."),
    ):
        cs = p.theme_by_tag.get(tag)
        if cs and verdict_level(cs) in ("weak", "trend_weak"):
            items.append(text + f" ({pct(cs.error_rate, 1)} ошибок при ожидаемых {pct(cs.reference_error_rate, 1)}, {cs.moves} ходов.)")
    if len(tl) >= 5 and len(tl) >= 0.15 * max(1, len(losses)):
        items.append(f"Часто проигрывает по времени: {len(tl)} из {len(losses)} поражений, из них {len(oc.time_losses_not_worse)} — в не худшей позиции. "
                     "Играйте в своём темпе и не тратьте время на ранних ходах — запас часов часто решает.")
    tp = p.theme_by_tag.get("time:pressure")
    if tp and tp.moves >= 20:
        items.append(f"Часы: в цейтноте он ошибается в {pct(tp.error_rate, 1)} ходов (в нормальное время — {pct(tp.reference_error_rate, 1)}). "
                     + ("Играйте быстро и ставьте задачи — цейтнот ему вредит." if tp.ratio and tp.ratio >= 1.25 else "Цейтнот на него действует слабо — не рассчитывайте на «долгую игру»."))
    if mot:
        top_m = max(mot.items(), key=lambda kv: kv[1])
        items.append("Характер ошибок: чаще всего — «" + MOTIFS[top_m[0]].split(":")[0].lower() + f"» ({pct(top_m[1] / mot_total)}). "
                     + ("Играйте остро: создавайте угрозы, он их пропускает." if top_m[0] == "allowed_tactic" else
                        "Держите позицию, давите планово: простых тактических зевков у него меньше." if top_m[0] == "positional" else ""))
    BUL(items)
    p.plan_items = items
    p.steer = steer; p.avoid_me = avoid_me; p.mutual = mutual; p.opp_strong = opp_strong
    BREAK()

def opp_pool(opps, tag):
    e = n = 0
    for o in opps:
        t = o.theme_by_tag.get(tag)
        if t:
            e += t.errors; n += t.moves
    return e, n


def abs_gap(me, opps, tag):
    """Your absolute error rate in a theme vs the opponents' pooled rate."""
    t = me.theme_by_tag.get(tag)
    if not t or t.moves < 100:
        return None
    e, n = opp_pool(opps, tag)
    if n < 200 or e == 0:
        return None
    oe = sum(o.errors for o in opps); on = sum(o.n_moves for o in opps)
    overall_ratio = me.err_rate / (oe / on)
    rate_o = e / n
    ratio = t.error_rate / rate_o
    return dict(t=t, rate_me=t.error_rate, rate_opp=rate_o, ratio=ratio, rel=ratio / overall_ratio,
                p=two_proportion_p_value(t.errors, t.moves, e, n), excess=t.errors - t.moves * rate_o)


def conv_rate(p):
    won = sum(1 for g in p.outcomes.games if g.max_eval >= 300)
    return (len(p.outcomes.blown_wins) / won if won else 0.0), won


# ----------------------------------------------------------------- self analysis
def self_section(me, opps):
    H1(f"Ваш профиль: {me.name}")
    H2("1. Общая картина")
    mot = motif_breakdown(me.moves)
    mot_total = sum(mot.values()) or 1
    BUL([
        f"Проанализировано {me.n_games} партий ({len(me.metas['white'])} белыми, {len(me.metas['black'])} чёрными), {me.n_moves} ходов; "
        f"период {me.dates[0]} – {me.dates[1]}. Против ботов Lichess/движков партии исключены ({me.bots}).",
        f"Рейтинг по последним партиям: ~{me.elo}; соперники: ~{me.opp_elo}. Результат: +{me.res['win']} ={me.res['draw']} −{me.res['loss']}, "
        f"{sc(me.score)} очков (ожидаемо по рейтингам {sc(me.expected)}).",
        f"Серьёзных ошибок: {me.err_rate * 100:.1f} на 100 ходов; грубых: {me.blunders / me.n_moves * 100:.1f}. "
        f"Для сравнения, у соперников: " + ", ".join(f"{o.name} — {o.err_rate * 100:.1f}" for o in opps) + ".",
        "Из чего состоят ваши серьёзные ошибки: " + ", ".join(
            f"{MOTIFS[k].split(':')[0].lower()} — {pct(v / mot_total)}" for k, v in sorted(mot.items(), key=lambda kv: -kv[1])) + "." if mot else None,
    ])
    top = max(mot.items(), key=lambda kv: kv[1])[0] if mot else None
    if top:
        PARA("Что это значит: " + MOTIF_ADVICE[top])

    H2("2. Где вы «плывёте»: типы позиций")
    TABLE(["Тема", "Ошибок в ходах", "Ожидаемо", "Факт / ожидание", "Ходов / партий", "Вывод"],
          theme_table(me, ["phase", "endgame", "middlegame", "transition", "context", "time"]), [2700, 1300, 1100, 1100, 1300, 1860])
    NOTE("Ожидаемо — обычный уровень ошибок для таких позиций с поправкой на вашу игру в сопоставимых позициях (подробности — в приложении).")
    weak = weak_list(me, ("weak", "trend_weak"))
    strong = strong_list(me, ("strong", "trend_strong"))
    if weak:
        PARA("Подтверждённые и вероятные слабости:")
        BUL([describe(s) + f" — {vlabel(verdict_level(s))}." for s in weak])
    else:
        PARA("Профиль ваших ошибок по типам позиций примерно повторяет профиль соперников: ошибок больше везде, а не в одном месте, поэтому «провала» "
             "в одной теме нет — резерв в общей точности, тактике и времени (разделы 5–6 и сравнение с соперниками).")
    if strong:
        PARA("Сильные стороны (можно сознательно вести туда партии):")
        BUL([describe(s) for s in strong[:5]])

    H2("3. Дебюты: где вы теряете очки")
    for color, label, rep_filter in (("white", "Белыми (1.e4)", None), ("black", "Чёрными", None)):
        H3(label)
        g = group_games(me, color, lambda s, m: line_name(m))
        names = {k: k for k in g}
        rows = opening_rows(g, names, None, top=10, min_n=5)
        for r in rows:
            r.pop(1)
        TABLE(["Дебют", "Партий", "Ваш счёт", "Ожид. по рейтингам", "Оценка после дебюта", "Ошибок в дебюте/партию"],
              rows, [3100, 900, 1100, 1500, 1500, 1260])
    NOTE("Красный счёт — вы набираете заметно меньше ожидаемого по рейтингам (≥ 12 пунктов) при выборке от 6 партий; зелёный — заметно больше.")
    # opening-phase weakness vs other phases
    po = me.theme_by_tag.get("phase:opening")
    if po:
        PARA(f"Дебютная фаза (первые 10 ходов): ошибок {pct(po.error_rate, 1)} ходов при ожидаемых {pct(po.reference_error_rate, 1)} — {vlabel(verdict_level(po))}.")

    H2("4. Ваши повторяющиеся ошибки")
    rec = recurring(me, limit=10)
    me.rec = rec
    if rec:
        rows = [[C((f"{r['opening']}, ход {r['fullmove']}" + (f" — {r['path']}" if r['path'] else ""))), C(r["san"], bold=True),
                 C(r["best"], bold=True), C(r["games"]), C(f"{r['avg_wp']:.0f}")] for r in rec]
        TABLE(["Где", "Вы играете", "Лучше", "В скольких партиях", "Потеря шансов"], rows, [4300, 1100, 1100, 1500, 1360])
        for i, r in enumerate(rec[:4]):
            IMG(diagram(r, f"me_{i}"), 250, f"{r['opening']}, ход {r['fullmove']}: вы играете {r['san']}, лучше {r['best']} ({r['games']} партий)")
    else:
        PARA("Одинаковых серьёзных ошибок в разных партиях не найдено.")

    H2("5. Как вы теряете очки")
    oc = me.outcomes
    dec = Counter({k: v for k, v in oc.decisive_by_tag.items() if k.startswith(("endgame", "mg", "trans")) or k in ("time:pressure",)})
    BUL([
        f"Проиграно {len(oc.losses)} партий; решающая ошибка найдена в {sum(1 for g in oc.losses if g.decisive_move)}.",
        "Чаще решающая ошибка в: " + ", ".join(f"{TAGS[k]} ({v})" for k, v in dec.most_common(4)) + "." if dec else None,
        f"Выигранная позиция (≥ +3) была в {sum(1 for g in oc.games if g.max_eval >= 300)} партиях; не доведено до победы — {len(oc.blown_wins)}.",
        f"Поражений по времени: {len(oc.time_losses)}; в не худшей позиции — {len(oc.time_losses_not_worse)}.",
        f"Спасённые безнадёжные позиции: {len(oc.comebacks)}.",
    ])
    if oc.blown_wins:
        PARA("Партии, где выигрыш был упущен (разберите первыми):")
        BUL([f"{g.opponent} ({g.opponent_elo or '?'}), {g.date}, {g.opening}: {g.link or ''}" for g in oc.blown_wins[:5]])

    # training plan
    H2("6. Что тренировать в первую очередь")
    prio, seen = [], set()
    for st in weak_list(me, ("weak", "trend_weak")):
        if st.tag in KB:
            prio.append((st.tag, st.excess_errors, f"{describe(st)}."))
            seen.add(st.tag)
    for tag in KB:
        if tag in seen or tag.startswith("phase:"):
            continue
        g = abs_gap(me, opps, tag)
        if g and g["rel"] >= 1.25 and g["p"] is not None and g["p"] < 0.01:
            prio.append((tag, g["excess"] * 0.8,
                         f"{TAGS[tag]}: у вас {pct(g['rate_me'], 1)} серьёзных ошибок на ход против {pct(g['rate_opp'], 1)} у соперников в среднем "
                         f"({g['t'].moves} ходов; с поправкой на ваш общий уровень вы хуже в {g['rel']:.1f} раза)."))
            seen.add(tag)
    oc2 = me.outcomes
    n_g = me.n_games
    if len(oc2.time_losses) >= 8 and len(oc2.time_losses) / n_g >= 0.07:
        prio.append(("outcome:time", len(oc2.time_losses) * 1.0,
                     f"По времени проиграно {len(oc2.time_losses)} партий из {n_g} ({pct(len(oc2.time_losses) / n_g)}), "
                     f"из них {len(oc2.time_losses_not_worse)} — в не худшей позиции."))
    my_conv, won = conv_rate(me)
    opp_conv = statistics.mean(conv_rate(o)[0] for o in opps)
    if won >= 40 and my_conv >= opp_conv + 0.04:
        prio.append(("outcome:conv", (my_conv - opp_conv) * won,
                     f"Выигранная позиция (≥ +3) не доведена до победы в {pct(my_conv)} случаев ({len(oc2.blown_wins)} из {won}); "
                     f"у соперников в среднем {pct(opp_conv)}."))
    tact = (mot.get("allowed_tactic", 0) + mot.get("missed_tactic", 0)) / mot_total
    if tact >= 0.4:
        prio.append(("outcome:tactics", tact * 60,
                     f"{pct(tact)} ваших серьёзных ошибок — тактические: зевок фигуры или удара — {pct(mot.get('allowed_tactic', 0) / mot_total)}, "
                     f"упущенный удар — {pct(mot.get('missed_tactic', 0) / mot_total)}."))
    elif top == "positional":
        prio.append(("motif:positional", max(1, mot["positional"] * 0.25), f"{MOTIFS['positional']} — {pct(mot['positional'] / mot_total)} серьёзных ошибок."))
    prio.sort(key=lambda t: -t[1])
    me.prio = prio
    n = 0
    for key, ex, evidence in prio[:6]:
        n += 1
        if key == "outcome:time":
            H3(f"Приоритет {n}: управление временем")
            BUL([f"Основание: {evidence}"] + KB["time:pressure"][1])
        elif key == "outcome:conv":
            H3(f"Приоритет {n}: реализация преимущества")
            BUL([f"Основание: {evidence}"] + KB["ctx:winning"][1] + ["Задачи Lichess по теме «crushing» и «advantage»: 10–15 в день."])
        elif key == "outcome:tactics":
            H3(f"Приоритет {n}: тактическая внимательность")
            BUL([f"Основание: {evidence}", MOTIF_ADVICE["allowed_tactic"], MOTIF_ADVICE["missed_tactic"]])
        elif key.startswith("motif:"):
            H3(f"Приоритет {n}: позиционное понимание и планирование")
            BUL([f"Основание: {evidence}", MOTIF_ADVICE["positional"]])
        else:
            title, steps, theme = KB[key]
            H3(f"Приоритет {n}: {title}")
            BUL([f"Основание: {evidence}"] + steps + [f"Задачи Lichess по теме «{theme}»: 10–15 в день."])
    if not prio:
        PARA("Явных провалов нет. Приоритеты: тактическая внимательность (проверка шахов/взятий/угроз), расчёт 3–4 ходов и разбор своих проигрышей.")
    H3("План на 14 дней")
    rows = [[C("Каждый день"), C("15 мин"), C("Тактика: задачи на проверку «шахи–взятия–угрозы», 10–15 задач по слабым темам")],
            [C("Пн / Ср / Пт"), C("30 мин"), C("Приоритеты 1, 2, 3 из списка выше — по одному на занятие: теория 10 минут + 20 минут практики (задачи/позиции в Lichess-практике)")],
            [C("Вт / Чт"), C("40 мин"), C("Разбор 2 своих партий: найти решающую ошибку, записать причину; сверить дебют с базой")],
            [C("Сб"), C("45 мин"), C("Дебют: прогнать главные линии против соперников турнира (см. досье), проверить план в итальянской/сицилианской")],
            [C("Вс"), C("60 мин"), C("2–3 партии с контролем 10+0 как репетиция; после — разбор только критических моментов")]]
    TABLE(["Когда", "Время", "Что делать"], rows, [1800, 1200, 6360])
    BREAK()

# ----------------------------------------------------------------- comparison
def comparison_section(me, opps):
    H1("Вы против них: сравнение ошибок")
    PARA("Таблица показывает долю серьёзных ошибок по типам позиций у вас и у каждого соперника. Цвет — вывод по самому игроку "
         "(относительно ожидаемого для таких позиций уровня): красный — слабость, зелёный — сила, жёлтый — тенденция.")
    people = [me] + opps
    header = ["Тема"] + [("Вы" if p is me else p.name) for p in people]
    rows = []
    for tag in CMP_TAGS:
        row = [C(TAGS[tag])]
        for p in people:
            s = p.theme_by_tag.get(tag)
            if s is None or s.moves == 0:
                row.append(C("–", GREY)); continue
            lv = verdict_level(s)
            row.append(C(f"{pct(s.error_rate, 1)} ({s.moves})", vfill(lv)))
        rows.append(row)
    w = [2800] + [int(6560 / len(people))] * len(people)
    TABLE(header, rows, w)
    NOTE("В скобках — число ходов в выборке. Абсолютные числа не сравнивайте напрямую между игроками разного рейтинга и контроля времени: "
         "соперники сильнее вас, поэтому их общий уровень ошибок ниже; смотрите на цвет.")
    H2("Где вы ошибаетесь чаще соперников")
    oe = sum(o.errors for o in opps); on = sum(o.n_moves for o in opps)
    PARA(f"Ваш общий уровень — {me.err_rate * 100:.1f} серьёзных ошибок на 100 ходов против {oe / on * 100:.1f} у соперников в среднем "
         f"(в {me.err_rate / (oe / on):.2f} раза чаще). Колонка «С поправкой» показывает, насколько тема хуже для вас, чем следует из этой общей разницы: "
         "значения выше 1,25 — ваша относительная слабость.")
    rows = []
    for tag in CMP_TAGS:
        g = abs_gap(me, opps, tag)
        if not g:
            continue
        bad = g["rel"] >= 1.25 and g["p"] is not None and g["p"] < 0.01
        good = g["rel"] <= 0.8 and g["p"] is not None and g["p"] < 0.05
        fill = RED if bad else (GREEN if good else None)
        rows.append([C(TAGS[tag]), C(f"{pct(g['rate_me'], 1)} ({g['t'].moves})"), C(pct(g["rate_opp"], 1)), C(f"{g['ratio']:.2f}×"),
                     C(f"{g['rel']:.2f}", fill, bold=bool(fill)), C("хуже" if bad else ("лучше" if good else "—"), fill)])
    TABLE(["Тема", "Вы (ходов)", "Соперники в среднем", "Во сколько раз чаще", "С поправкой", "Вывод"], rows, [3300, 1400, 1500, 1200, 1100, 860])
    H2("Общий уровень точности")
    rows = []
    for p in people:
        tp = p.theme_by_tag.get("time:pressure")
        rows.append([C("Вы" if p is me else p.name, bold=p is me), C(p.elo or "–"), C(f"{p.err_rate * 100:.1f}"),
                     C(f"{p.blunders / p.n_moves * 100:.1f}"), C(f"{p.avg_wp:.2f}"), C(sc(p.score)), C(sc(p.expected))])
    TABLE(["Игрок", "Рейтинг", "Серьёзных ошибок на 100 ходов", "Грубых на 100 ходов", "Средняя потеря шансов за ход", "Счёт", "Ожид. счёт"],
          rows, [1800, 1000, 1700, 1300, 1700, 900, 960])
    H2("Итог для турнира")
    mine_weak = {s.tag for s in weak_list(me, ("weak", "trend_weak"))}
    for o in opps:
        steer, avoid_me, mutual, opp_strong = o.steer, o.avoid_me, o.mutual, o.opp_strong
        H3(o.name)
        BUL([
            "Вести игру в: " + (", ".join(TAGS[t[0]].lower() for t in steer[:4]) or "явных точек нет — играйте по дебютному плану и ждите ошибок"),
            "Избегать: " + (", ".join(sorted({TAGS[t[0]].lower() for t in opp_strong + avoid_me})) or "специальных ограничений нет"),
            "Обоюдные слабые места (лотерея): " + (", ".join(TAGS[t[0]].lower() for t in mutual) or "нет"),
        ])

# ----------------------------------------------------------------- front matter & appendix
def cover(me, opps):
    doc.append({"t": "title", "text": "Подготовка к турниру", "sub": ", ".join(o.name for o in opps)})
    PARA(f"Профиль игрока для сравнения: {me.name} (определён по репертуару: 1.e4 и итальянская партия белыми, c5 против 1.e4 и Nf6/e6 против 1.d4 чёрными).")
    PARA("Отчёт построен на реальных партиях Lichess: ходы проанализированы Stockfish 16, для каждого игрока выделены повторяющиеся ошибки, "
         "слабые типы позиций (включая типы эндшпилей), дебютный репертуар и результаты относительно ожидаемых по рейтингам.")

def summary(me, opps):
    H1("Краткая сводка")
    rows = []
    for o in opps:
        wf = group_games(o, "white", lambda s, m: s[0] if s else None)
        top_w = max(wf.items(), key=lambda kv: kv[1]["n"]) if wf else ("-", {"n": 0})
        rb = group_games(o, "black", lambda s, m: s[1] if len(s) > 1 else None, lambda s, m: s[:1] == ["e4"])
        top_b = max(rb.items(), key=lambda kv: kv[1]["n"]) if rb else ("-", {"n": 0})
        nb = sum(g["n"] for g in rb.values()) or 1
        weak = weak_list(o, ("weak",)) or weak_list(o, ("weak", "trend_weak"))
        adv = []
        if o.steer: adv.append("вести: " + TAGS[o.steer[0][0]].lower())
        if o.opp_strong: adv.append("избегать: " + TAGS[o.opp_strong[0][0]].lower())
        rows.append([C(o.name, bold=True), C(o.elo or "–"),
                     C(f"{top_w[0]} ({pct(top_w[1]['n'] / len(o.metas['white']))})"),
                     C(f"{top_b[0]} ({pct(top_b[1]['n'] / nb)})"),
                     C("; ".join(f"{s.label.lower()}" for s in weak[:2]) or "явных нет"),
                     C("; ".join(adv) or "играть в дебютный план")])
    TABLE(["Соперник", "Рейтинг", "Белыми: 1-й ход", "Против 1.e4", "Слабые зоны", "Совет"], rows, [1500, 800, 1300, 1300, 2600, 1860])
    PARA(f"Ваш уровень: ~{me.elo} против ~{min(o.elo for o in opps)}–{max(o.elo for o in opps)} у соперников — по рейтингу вы в роли аутсайдера. "
         "Поэтому главный принцип: не вступать в теоретические дуэли, а вести игру в тех типах позиций, где соперник статистически ошибается чаще вас.")

def appendix(me, opps):
    H1("Приложение: данные и методика")
    rows = []
    for p in [me] + opps:
        sk = ", ".join(f"{k}: {v}" for k, v in p.skips.items()) or "–"
        rows.append([C(p.name), C(len(p.metas["white"])), C(len(p.metas["black"])), C(p.bots), C(sk), C(f"{p.dates[0]} – {p.dates[1]}")])
    TABLE(["Игрок", "Белыми", "Чёрными", "Партий с ботами исключено", "Пропущено при загрузке", "Период"], rows, [1800, 900, 900, 1500, 2860, 1400])
    NOTE("Пропущенные: not_target — партия другого цвета/игрока (нормально для раздельных проходов белыми и чёрными), variant — не классические шахматы, "
         "custom_start — партия из нестандартной позиции, too_short — менее 6 полуходов.")
    H2("Как читать цифры")
    BUL([
        "Серьёзная ошибка — ход, после которого вероятность победы (по шкале Lichess) падает на 10+ пунктов; грубая — на 15+.",
        "«Ожидаемый» уровень ошибок для типа позиции: берётся частота ошибок в таких позициях у остальных игроков выборки относительно их же сопоставимых позиций "
        "(например, ладейные эндшпили относительно прочих эндшпилей) и применяется к тому, как данный игрок играет сопоставимые позиции. "
        "Вывод «слабость/сила» делается только при выборке не меньше 40 ходов из 8 партий, p < 0,01 и отличии от ожидаемого не менее чем на 25 %. "
        "Жёлтая «тенденция» — p < 0,05 при тех же условиях на выборку.",
        "«Ожидаемый счёт» считается по формуле Эло из рейтингов сторон в каждой партии; «Оценка после дебюта» — оценка движка на 10-м ходу с точки зрения исследуемого игрока.",
        "Повторяющаяся ошибка — один и тот же ход в одной и той же позиции не менее чем в двух разных партиях.",
        "Движок: Stockfish 16, 0,12 с на позицию, 1 поток (глубина порядка 13–16); критические позиции — 0,4 с. Для блица и рейтингов 1500–2000 этого достаточно, "
        "но отдельные оценки могут отличаться от глубокого анализа.",
    ])
    H2("Ограничения")
    BUL([
        "Это онлайн-партии (в основном блиц 3+2 и 5+0). В очном турнире со временем побольше стиль и ошибки могут отличаться.",
        "В отдельных дебютных линиях выборка мала — смотрите на повторяющиеся линии и ошибки, а не на единичные проценты.",
        "Названия дебютов берутся из заголовков PGN Lichess и описывают позицию целиком (то есть выбор обеих сторон).",
        "Игроки могли поменять репертуар после периода выборки.",
    ])

def main():
    me = build_player(ME)
    opps = [build_player(n) for n in OPPS]
    apply_pooled([me] + opps)
    cover(me, opps)
    for o in opps:
        pass
    # dossiers need steer data for summary: build dossiers into a temp doc first
    global doc
    front = list(doc)
    doc = []
    for o in opps:
        dossier(o, me)
    dossiers = doc
    doc = []
    summary(me, opps)
    BREAK()
    summary_blocks = doc
    doc = []
    self_section(me, opps)
    self_blocks = doc
    doc = []
    comparison_section(me, opps)
    cmp_blocks = doc
    doc = []
    appendix(me, opps)
    app_blocks = doc
    full = front + summary_blocks + dossiers + self_blocks + cmp_blocks + app_blocks
    if _ENG is not None:
        _ENG.quit()
    json.dump(full, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("blocks", len(full))

main()
