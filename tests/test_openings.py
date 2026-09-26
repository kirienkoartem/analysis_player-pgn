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

def test_family_name_collapses_subvariations():
    assert OpeningTracker.family_name("King's Indian Defense: Normal Variation") == "King's Indian Defense"
    assert OpeningTracker.family_name("King's Indian Defense, Fianchetto Variation") == "King's Indian Defense"
    assert OpeningTracker.family_name("Nimzo-Indian Defense") == "Nimzo-Indian Defense"
    assert OpeningTracker.family_name("") == "Unknown Opening"

def test_build_variation_tree_counts_target_player_moves_only():
    from src.pgn.loader import load_pgn_games
    import tempfile

    pgn_text = (
        "[White \"W\"]\n[Black \"B\"]\n[Result \"1-0\"]\n\n"
        "1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 1-0\n\n"
        "[White \"W\"]\n[Black \"B2\"]\n[Result \"0-1\"]\n\n"
        "1. d4 Nf6 2. c4 g6 3. Nc3 Bg7 0-1\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pgn", delete=False) as f:
        f.write(pgn_text)
        path = f.name

    res = load_pgn_games(path, target_player="W", color="white")
    tree = OpeningTracker.build_variation_tree(res.filtered_games, chess.WHITE, max_plies=6)

    # Both games share 1.d4 Nf6(opponent)2.c4 - root -> "d4" -> "c4"
    assert "d4" in tree.children
    d4_node = tree.children["d4"]
    assert d4_node.games_count == 2
    assert "c4" in d4_node.children
    c4_node = d4_node.children["c4"]
    assert c4_node.games_count == 2
    # They diverge on White's 3rd move: both play Nc3 (same for White here),
    # opponent's reply (Bb4 vs Bg7) isn't in the tree since that's not White's move.
    assert "Nc3" in c4_node.children
    nc3_node = c4_node.children["Nc3"]
    assert nc3_node.games_count == 2
    assert nc3_node.wins == 1
    assert nc3_node.losses == 1

def test_elo_expected_score():
    from src.aggregation.statistics import elo_expected_score
    # Equal Elo -> 50/50 expected score
    assert abs(elo_expected_score(1800, 1800) - 0.5) < 1e-6
    # 400 Elo above opponent -> ~90.9% expected score
    assert abs(elo_expected_score(2200, 1800) - 0.90909) < 1e-4
    # 400 Elo below opponent -> ~9.1% expected score
    assert abs(elo_expected_score(1800, 2200) - 0.09091) < 1e-4
