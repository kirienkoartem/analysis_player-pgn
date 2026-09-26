import pytest
import io
import chess.pgn
from src.pgn.loader import load_pgn_games, parse_elo
from src.pgn.filter import PGNFilter, normalize_name
from src.pgn.validator import PGNValidator
from src.chess.positions import (
    parse_time_control_base_seconds,
    classify_time_control,
    time_pressure_threshold_seconds,
)

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

def test_load_pgn_games_date_filter(tmp_path):
    pgn_file = tmp_path / "test.pgn"
    pgn_file.write_text(SAMPLE_PGN, encoding="utf-8")

    # Game 1 (2023.01.01) excluded, game 3 (2023.01.03) kept.
    res = load_pgn_games(str(pgn_file), target_player="Target Player", date_from="2023.01.02")
    assert len(res.filtered_games) == 1
    assert res.filtered_games[0].metadata.opening == "French Defense"

def test_load_pgn_games_min_opponent_elo_filter(tmp_path):
    pgn_file = tmp_path / "test.pgn"
    pgn_file.write_text(SAMPLE_PGN, encoding="utf-8")

    # Target plays Black in games 1 & 3 -> opponent Elo = WhiteElo.
    # Game 1 WhiteElo=2000, game 3 has no Elo headers at all (None).
    res = load_pgn_games(str(pgn_file), target_player="Target Player", min_opponent_elo=1900)
    assert len(res.filtered_games) == 1
    assert res.filtered_games[0].metadata.white == "Player White"

    res_none = load_pgn_games(str(pgn_file), target_player="Target Player", min_opponent_elo=2050)
    assert len(res_none.filtered_games) == 0

def test_load_pgn_games_time_control_filter(tmp_path):
    pgn_file = tmp_path / "test.pgn"
    pgn_file.write_text(SAMPLE_PGN, encoding="utf-8")

    # SAMPLE_PGN has no TimeControl header at all -> classified "unknown".
    res_unknown = load_pgn_games(str(pgn_file), target_player="Target Player", time_control_category="unknown")
    assert len(res_unknown.filtered_games) == 2

    res_blitz = load_pgn_games(str(pgn_file), target_player="Target Player", time_control_category="blitz")
    assert len(res_blitz.filtered_games) == 0

def test_parse_time_control_base_seconds():
    assert parse_time_control_base_seconds("180+2") == 180
    assert parse_time_control_base_seconds("600") == 600
    assert parse_time_control_base_seconds("-") is None
    assert parse_time_control_base_seconds("") is None
    assert parse_time_control_base_seconds("?") is None

def test_classify_time_control():
    assert classify_time_control(60) == "bullet"
    assert classify_time_control(300) == "blitz"
    assert classify_time_control(900) == "rapid"
    assert classify_time_control(3600) == "classical"
    assert classify_time_control(None) == "unknown"

def test_time_pressure_threshold_scales_with_base_time():
    # Bullet (60s base): 10% = 6s, floored up to 10s.
    assert time_pressure_threshold_seconds(60) == 10.0
    # Blitz (300s base): 10% = 30s (matches the old flat default, by design).
    assert time_pressure_threshold_seconds(300) == 30.0
    # Classical (1800s base): 10% = 180s - a very different situation from
    # blitz, which a single flat 30s threshold would have missed entirely.
    assert time_pressure_threshold_seconds(1800) == 180.0
    # Unknown/correspondence -> falls back to the flat default.
    assert time_pressure_threshold_seconds(None) == 30.0
