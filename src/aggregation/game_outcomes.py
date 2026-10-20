"""How games are won and lost: decisive errors, thrown wins, saved games.

Per-move statistics say how often someone errs; this says which errors
actually cost points. For every lost game we find the decisive error - the
biggest drop in winning chances made while the position was still holdable -
and for every game that wasn't won despite a clearly winning position we find
the move that let it go. Their position tags then show which themes really
decide this player's results.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import chess

from src.engine.classification import MoveAnalysisData
from src.pgn.loader import GameRecord

WINNING_CP = 300        # "clearly winning" for thrown-win / comeback detection
HOLDABLE_CP = -150      # a decisive error must start from a not-yet-lost position
DECISIVE_WP = 15.0      # Lichess's blunder threshold in winning-chance points


@dataclass
class GameOutcome:
    game_id: str
    color: str
    result: str  # "win" | "draw" | "loss" (from the player's perspective)
    opponent: str
    opponent_elo: Optional[int]
    date: str
    link: str
    opening: str
    max_eval: float
    min_eval: float
    last_eval: float  # player's eval before their final move
    lost_on_time: bool
    decisive_move: Optional[MoveAnalysisData] = None  # losses only
    throw_move: Optional[MoveAnalysisData] = None     # wins not converted

    @property
    def blown_win(self) -> bool:
        return self.result != "win" and self.max_eval >= WINNING_CP

    @property
    def comeback(self) -> bool:
        return self.result != "loss" and self.min_eval <= -WINNING_CP


@dataclass
class OutcomeSummary:
    games: List[GameOutcome] = field(default_factory=list)
    decisive_by_tag: Dict[str, int] = field(default_factory=dict)
    decisive_by_motif: Dict[str, int] = field(default_factory=dict)

    @property
    def losses(self) -> List[GameOutcome]:
        return [g for g in self.games if g.result == "loss"]

    @property
    def blown_wins(self) -> List[GameOutcome]:
        return [g for g in self.games if g.blown_win]

    @property
    def comebacks(self) -> List[GameOutcome]:
        return [g for g in self.games if g.comeback]

    @property
    def time_losses(self) -> List[GameOutcome]:
        return [g for g in self.games if g.result == "loss" and g.lost_on_time]

    @property
    def time_losses_not_worse(self) -> List[GameOutcome]:
        """Lost on the clock while the last known position was not worse."""
        return [g for g in self.time_losses if g.last_eval > HOLDABLE_CP]


def _player_result(result: str, color: str) -> str:
    if result == "1/2-1/2":
        return "draw"
    if result == ("1-0" if color == "white" else "0-1"):
        return "win"
    if result == ("0-1" if color == "white" else "1-0"):
        return "loss"
    return "unknown"


def _lost_on_time(termination: str) -> bool:
    t = termination.lower()
    return "time" in t and "insufficient" not in t


def analyze_outcomes(records_by_color: Dict[str, List[GameRecord]],
                     moves: List[MoveAnalysisData]) -> OutcomeSummary:
    moves_by_game: Dict[str, List[MoveAnalysisData]] = {}
    for m in moves:
        moves_by_game.setdefault(m.game_id, []).append(m)

    summary = OutcomeSummary()
    tag_counter: Counter = Counter()
    motif_counter: Counter = Counter()

    for color, records in records_by_color.items():
        for rec in records:
            md = rec.metadata
            gm = sorted(moves_by_game.get(md.game_id, []), key=lambda m: m.move_number)
            if not gm:
                continue
            result = _player_result(md.result, color)
            if result == "unknown":
                continue
            evals = [m.eval_before_black_perspective for m in gm]
            outcome = GameOutcome(
                game_id=md.game_id, color=color, result=result,
                opponent=md.black if color == "white" else md.white,
                opponent_elo=md.black_elo if color == "white" else md.white_elo,
                date=md.date, link=md.link, opening=md.opening,
                max_eval=max(evals), min_eval=min(evals), last_eval=evals[-1],
                lost_on_time=_lost_on_time(md.termination),
            )

            if result == "loss":
                candidates = [m for m in gm if m.eval_before_black_perspective >= HOLDABLE_CP]
                if candidates:
                    worst = max(candidates, key=lambda m: m.wp_loss)
                    if worst.wp_loss >= DECISIVE_WP:
                        outcome.decisive_move = worst

            if outcome.blown_win:
                first_win_idx = next(i for i, m in enumerate(gm) if m.eval_before_black_perspective >= WINNING_CP)
                after = gm[first_win_idx:]
                worst = max(after, key=lambda m: m.wp_loss)
                if worst.wp_loss >= DECISIVE_WP / 3:
                    outcome.throw_move = worst

            for key_move in {id(x): x for x in (outcome.decisive_move, outcome.throw_move) if x is not None}.values():
                tag_counter.update(set(key_move.tags))
                if key_move.motif != "NONE":
                    motif_counter[key_move.motif] += 1

            summary.games.append(outcome)

    summary.decisive_by_tag = dict(tag_counter)
    summary.decisive_by_motif = dict(motif_counter)
    return summary


def turning_points(moves: List[MoveAnalysisData], limit: int = 15) -> List[MoveAnalysisData]:
    """The most instructive mistakes: big drops in winning chances from a
    position that was not already lost, at most one per game so a single
    collapse doesn't fill the whole list."""
    candidates = [m for m in moves if m.wp_loss >= DECISIVE_WP and m.eval_before_black_perspective >= HOLDABLE_CP]
    candidates.sort(key=lambda m: -m.wp_loss)
    seen = set()
    out: List[MoveAnalysisData] = []
    for m in candidates:
        if m.game_id in seen:
            continue
        seen.add(m.game_id)
        out.append(m)
        if len(out) >= limit:
            break
    return out


def uci_to_san(fen: str, uci: str) -> str:
    try:
        board = chess.Board(fen)
        return board.san(chess.Move.from_uci(uci))
    except (ValueError, AssertionError):
        return uci or "?"


def pv_to_san(fen: str, pv: List[str], max_plies: int = 6) -> str:
    try:
        board = chess.Board(fen)
        return board.variation_san([chess.Move.from_uci(u) for u in pv[:max_plies]])
    except (ValueError, AssertionError):
        return " ".join(pv[:max_plies])
