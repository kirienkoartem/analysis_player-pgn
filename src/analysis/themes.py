"""Position themes: what kind of position a move was played in, and what kind
of error it was.

Every move the target player makes gets a set of string tags (see TAGS) so
that error rates can later be compared between position types - e.g. "rook
endgames" vs. all endgames, or "first moves after the queens came off" vs.
the rest of the game. Tags are deliberately derived only from the board and
the engine's own lines, never from guesswork about intent.
"""
import math
from typing import List, Optional

import chess

PIECE_VALUES = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}

# Human-readable (Russian) labels for every tag the pipeline can emit.
TAGS = {
    "phase:opening": "Дебют (ходы 1-10)",
    "phase:middlegame": "Миттельшпиль",
    "phase:endgame": "Эндшпиль",
    "endgame:pawn": "Пешечный эндшпиль",
    "endgame:rook": "Ладейный эндшпиль",
    "endgame:queen": "Ферзевый эндшпиль",
    "endgame:bishop": "Слоновый эндшпиль (одноцветные)",
    "endgame:opposite_bishops": "Разноцветные слоны",
    "endgame:knight": "Коневой эндшпиль",
    "endgame:minor": "Лёгкофигурный эндшпиль (слон против коня и т.п.)",
    "endgame:rook_minor": "Ладья + лёгкие фигуры",
    "endgame:mixed": "Прочие эндшпили (ферзь против ладьи и т.п.)",
    "mg:queens_on": "Миттельшпиль с ферзями",
    "mg:queenless": "Миттельшпиль без ферзей",
    "mg:opposite_castling": "Разносторонние рокировки",
    "struct:iqp_own": "Свой изолированный d-пешка (изолятор)",
    "struct:iqp_opp": "Изолятор у соперника",
    "trans:after_queen_trade": "Первые 5 ходов после размена ферзей",
    "ctx:losing": "Худшая позиция (защита)",
    "ctx:equal": "Равная позиция",
    "ctx:better": "Перевес (реализация преимущества)",
    "ctx:winning": "Выигранная позиция (добивание)",
    "time:pressure": "Цейтнот",
    "time:normal": "Нормальный запас времени",
}

MOTIFS = {
    "allowed_tactic": "Зевок: допустил тактический удар / оставил фигуру под боем",
    "missed_tactic": "Упустил тактику: был выигрывающий удар/взятие",
    "missed_mate": "Упустил форсированный мат",
    "positional": "Позиционная / стратегическая ошибка (без прямой тактики)",
}

OPENING_PLY_LIMIT = 20


def win_percent(cp_player: float) -> float:
    """Lichess's centipawn -> winning-chance mapping (0..100) from the
    player's perspective. Used instead of raw cp for "was this a real
    mistake" decisions: dropping from +700 to +500 changes nothing practical,
    dropping from +50 to -150 does, and raw cp loss treats both the same."""
    cp = max(-1000.0, min(1000.0, cp_player))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def win_percent_loss(cp_before_player: float, cp_after_player: float) -> float:
    return max(0.0, win_percent(cp_before_player) - win_percent(cp_after_player))


def _non_pawn_material(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.pieces(pt, color)) * v for pt, v in PIECE_VALUES.items())


def is_endgame(board: chess.Board) -> bool:
    """Material-based endgame test (independent of move number).

    Queenless: each side has at most 10 points of pieces (two rooks, rook +
    minor, up to three minors). With queens: each side at most 9 points,
    i.e. queen-only endings or queen against rook + minor.
    """
    w = _non_pawn_material(board, chess.WHITE)
    b = _non_pawn_material(board, chess.BLACK)
    queens = board.pieces(chess.QUEEN, chess.WHITE) or board.pieces(chess.QUEEN, chess.BLACK)
    if not queens:
        return max(w, b) <= 10
    return max(w, b) <= 9


def endgame_type(board: chess.Board) -> str:
    types = set()
    for color in (chess.WHITE, chess.BLACK):
        for pt in PIECE_VALUES:
            if board.pieces(pt, color):
                types.add(pt)

    if not types:
        return "pawn"
    if types == {chess.ROOK}:
        return "rook"
    if types == {chess.QUEEN}:
        return "queen"
    if types == {chess.BISHOP}:
        wb = board.pieces(chess.BISHOP, chess.WHITE)
        bb = board.pieces(chess.BISHOP, chess.BLACK)
        if len(wb) == 1 and len(bb) == 1:
            w_sq, b_sq = next(iter(wb)), next(iter(bb))
            if (chess.square_file(w_sq) + chess.square_rank(w_sq)) % 2 != (chess.square_file(b_sq) + chess.square_rank(b_sq)) % 2:
                return "opposite_bishops"
        return "bishop"
    if types == {chess.KNIGHT}:
        return "knight"
    if types <= {chess.BISHOP, chess.KNIGHT}:
        return "minor"
    if chess.ROOK in types and chess.QUEEN not in types:
        return "rook_minor"
    return "mixed"


def game_phase(board: chess.Board, ply: int) -> str:
    if is_endgame(board):
        return "endgame"
    if ply <= OPENING_PLY_LIMIT:
        return "opening"
    return "middlegame"


def _has_opposite_castling(board: chess.Board) -> bool:
    wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
    if wk is None or bk is None:
        return False
    if chess.square_rank(wk) > 1 or chess.square_rank(bk) < 6:
        return False  # kings not sheltered on their home ranks
    wf, bf = chess.square_file(wk), chess.square_file(bk)
    queenside = lambda f: f <= 2
    kingside = lambda f: f >= 5
    return (queenside(wf) and kingside(bf)) or (kingside(wf) and queenside(bf))


def _has_iqp(board: chess.Board, color: chess.Color) -> bool:
    pawns = board.pieces(chess.PAWN, color)
    files = {chess.square_file(sq) for sq in pawns}
    return 3 in files and 2 not in files and 4 not in files


def eval_context(cp_before_player: float) -> str:
    if cp_before_player <= -150:
        return "losing"
    if cp_before_player < 150:
        return "equal"
    if cp_before_player < 500:
        return "better"
    return "winning"


def position_tags(
    board_before: chess.Board,
    player: chess.Color,
    ply: int,
    cp_before_player: float,
    clock_known: bool,
    time_pressure: bool,
) -> List[str]:
    phase = game_phase(board_before, ply)
    tags = [f"phase:{phase}", f"ctx:{eval_context(cp_before_player)}"]

    if phase == "endgame":
        tags.append(f"endgame:{endgame_type(board_before)}")
    elif phase == "middlegame":
        queens = board_before.pieces(chess.QUEEN, chess.WHITE) or board_before.pieces(chess.QUEEN, chess.BLACK)
        tags.append("mg:queens_on" if queens else "mg:queenless")
        if _has_opposite_castling(board_before):
            tags.append("mg:opposite_castling")
        if _has_iqp(board_before, player):
            tags.append("struct:iqp_own")
        if _has_iqp(board_before, not player):
            tags.append("struct:iqp_opp")

    if clock_known:
        tags.append("time:pressure" if time_pressure else "time:normal")
    return tags


def _is_tactical_capture_or_check(board: chess.Board, move: chess.Move) -> bool:
    """A check, a promotion, or a capture that wins material outright: the
    captured piece is worth more than the capturer, or isn't defended. Plain
    even trades/recaptures are excluded - they're not "tactics"."""
    if move not in board.legal_moves:
        return False
    if move.promotion or board.gives_check(move):
        return True
    if not board.is_capture(move):
        return False
    if board.is_en_passant(move):
        return False
    victim = board.piece_at(move.to_square)
    attacker = board.piece_at(move.from_square)
    if victim is None or attacker is None:
        return False
    victim_val = PIECE_VALUES.get(victim.piece_type, 1)
    attacker_val = PIECE_VALUES.get(attacker.piece_type, 1 if attacker.piece_type == chess.PAWN else 100)
    if victim_val > attacker_val:
        return True
    return not board.attackers(victim.color, move.to_square)


def error_motif(
    board_before: chess.Board,
    board_after: chess.Board,
    player: chess.Color,
    played_uci: str,
    best_uci: str,
    opponent_reply_uci: Optional[str],
    had_mate_before: bool,
    has_mate_after: bool,
) -> str:
    """Heuristic nature of a (serious) error. Labels are a best-effort reading
    of the engine lines, not a certainty - the report says so."""
    if had_mate_before and not has_mate_after:
        return "missed_mate"
    if opponent_reply_uci:
        try:
            reply = chess.Move.from_uci(opponent_reply_uci)
            if _is_tactical_capture_or_check(board_after, reply):
                return "allowed_tactic"
        except ValueError:
            pass
    if best_uci and best_uci != played_uci:
        try:
            best = chess.Move.from_uci(best_uci)
            if _is_tactical_capture_or_check(board_before, best):
                return "missed_tactic"
        except ValueError:
            pass
    return "positional"


def mark_after_queen_trade(tag_lists: List[List[str]], queens_present: List[bool], window: int = 5) -> None:
    """Second pass over one game's target-player moves (in order): tags the
    first `window` moves played after the queens left the board, if they
    were on the board at some earlier move of this game."""
    seen_queens = False
    remaining = 0
    for i, q in enumerate(queens_present):
        if q:
            seen_queens = True
            remaining = 0
            continue
        if seen_queens and remaining == 0 and queens_present[i - 1]:
            remaining = window
        if remaining > 0:
            tag_lists[i].append("trans:after_queen_trade")
            remaining -= 1
