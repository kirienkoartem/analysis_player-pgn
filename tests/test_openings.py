import pytest
import chess
import chess.pgn
import io
from src.chess.positions import extract_target_player_moves
from src.chess.openings import OpeningTracker
from src.chess.phases import phase_detector, GamePhase
from src.chess.patterns import PatternDetector

SAMPLE_PGN = """[Event "Test"]
[Site "Local"]
[Date "2023.01.01"]
[Round "1"]
[White "W"]
[Black "B"]
[Result "0-1"]
[ECO "B20"]
[Opening "Sicilian Defense"]

1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 0-1
"""

def test_extract_target_player_moves():
    game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
    moves = extract_target_player_moves(game, chess.BLACK)

    assert len(moves) == 5
    assert moves[0].san == "c5"
    assert moves[0].uci == "c7c5"
    assert moves[0].color == chess.BLACK
    assert moves[1].san == "d6"

def test_opening_tracker():
    game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
    eco, op = OpeningTracker.get_eco_and_opening(game)
    assert eco == "B20"
    assert op == "Sicilian Defense"

    seq, move_list = OpeningTracker.extract_opening_moves(game, plies=6)
    assert len(move_list) == 6
    assert seq == "1.e4 c5 2.Nf3 d6 3.d4 cxd4"

def test_phase_detector():
    board = chess.Board()
    assert phase_detector(board, ply_number=10) == GamePhase.OPENING
    assert phase_detector(board, ply_number=28) == GamePhase.EARLY_MIDDLEGAME

    # Endgame board with just kings and pawns
    eg_board = chess.Board("8/8/4k3/8/8/4K3/4P3/8 w - - 0 1")
    assert phase_detector(eg_board, ply_number=40) == GamePhase.ENDGAME

def test_pattern_detector():
    board = chess.Board()
    fp = PatternDetector.create_fingerprint(board)
    assert "P" in fp.material_key
    assert "p" in fp.material_key
    assert fp.pawn_structure_fen is not None
