import pytest
import io
import chess.pgn
from src.pgn.loader import load_pgn_games, parse_elo
from src.pgn.filter import PGNFilter, normalize_name
from src.pgn.validator import PGNValidator

SAMPLE_PGN = """[Event "Tournament 1"]
[Site "City A"]
[Date "2023.01.01"]
[Round "1"]
[White "Player White"]
[Black "Target Player"]
[Result "0-1"]
[ECO "C50"]
[Opening "Italian Game"]
[WhiteElo "2000"]
[BlackElo "2050"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 0-1

[Event "Tournament 2"]
[Site "City B"]
[Date "2023.01.02"]
[Round "2"]
[White "Target Player"]
[Black "Other Player"]
[Result "1-0"]
[ECO "B01"]
[Opening "Scandinavian Defense"]

1. e4 d5 2. exd5 Qxd5 1-0

[Event "Tournament 3"]
[Site "City C"]
[Date "2023.01.03"]
[Round "3"]
[White "Player White 2"]
[Black "target player"]
[Result "1/2-1/2"]
[ECO "C00"]
[Opening "French Defense"]

1. e4 e6 2. d4 d5 1/2-1/2
"""

def test_normalize_name():
    assert normalize_name("  Target Player ") == "target player"
    assert normalize_name("TARGET   PLAYER") == "target player"

def test_pgn_filter_auto_detect():
    pgn_io = io.StringIO(SAMPLE_PGN)
    games = []
    while True:
        g = chess.pgn.read_game(pgn_io)
        if g is None:
            break
        games.append(g)

    auto_player = PGNFilter.auto_detect_black_player(games)
    assert auto_player.lower() == "target player"

def test_load_pgn_games_filtering(tmp_path):
    pgn_file = tmp_path / "test.pgn"
    pgn_file.write_text(SAMPLE_PGN, encoding="utf-8")

    res = load_pgn_games(str(pgn_file), target_player="Target Player")
    assert res.total_games_in_pgn == 3
    assert len(res.filtered_games) == 2  # Games 1 and 3 where Target Player is Black
    assert res.filtered_games[0].metadata.black == "Target Player"
    assert res.filtered_games[0].metadata.black_elo == 2050
    assert res.filtered_games[1].metadata.opening == "French Defense"

def test_parse_elo():
    assert parse_elo("2100") == 2100
    assert parse_elo("?") is None
    assert parse_elo("") is None
