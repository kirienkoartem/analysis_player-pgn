import pytest
from unittest.mock import patch, MagicMock
from src.pgn.downloader import download_lichess_games, download_chesscom_games, download_games


def _mock_response(text=None, json_data=None, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    if text is not None:
        resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def test_download_lichess_games_requests_pgn_with_clocks_and_opening():
    fake_pgn = "[Event \"Test\"]\n\n1. e4 e5 *\n"
    with patch("src.pgn.downloader.requests.get", return_value=_mock_response(text=fake_pgn)) as mock_get:
        result = download_lichess_games("someuser", max_games=50)

    assert result == fake_pgn
    args, kwargs = mock_get.call_args
    assert "someuser" in args[0]
    assert kwargs["params"]["max"] == 50
    assert kwargs["params"]["clocks"] == "true"
    assert kwargs["params"]["opening"] == "true"
    assert kwargs["headers"]["Accept"] == "application/x-chess-pgn"


def test_download_chesscom_games_walks_archives_newest_first():
    archives_json = {"archives": [
        "https://api.chess.com/pub/player/u/games/2023/01",
        "https://api.chess.com/pub/player/u/games/2023/02",
    ]}
    jan_games = {"games": [{"pgn": "[Event \"Jan1\"]\n1. e4 *\n"}, {"pgn": "[Event \"Jan2\"]\n1. d4 *\n"}]}
    feb_games = {"games": [{"pgn": "[Event \"Feb1\"]\n1. c4 *\n"}]}

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("archives"):
            return _mock_response(json_data=archives_json)
        if url.endswith("2023/02"):
            return _mock_response(json_data=feb_games)
        if url.endswith("2023/01"):
            return _mock_response(json_data=jan_games)
        raise AssertionError(f"unexpected url {url}")

    with patch("src.pgn.downloader.requests.get", side_effect=fake_get):
        result = download_chesscom_games("u", max_games=2)

    # Most recent month (Feb) first, then Jan - stops once max_games reached.
    assert result.count("[Event") == 2
    assert result.index("Feb1") < result.index("Jan2")


def test_download_games_writes_output_file(tmp_path):
    fake_pgn = "[Event \"Test\"]\n\n1. e4 e5 *\n"
    out_path = tmp_path / "nested" / "games.pgn"
    with patch("src.pgn.downloader.requests.get", return_value=_mock_response(text=fake_pgn)):
        result = download_games("lichess", "someuser", max_games=10, output_path=str(out_path))

    assert result == fake_pgn
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == fake_pgn


def test_download_games_rejects_unknown_source():
    with pytest.raises(ValueError):
        download_games("carlsenbase", "u")
