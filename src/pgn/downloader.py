"""Downloads a player's games from Lichess or Chess.com public APIs into a
single PGN text blob, so the pipeline can be pointed at a username instead of
requiring a pre-exported PGN file.

Only standard chess is requested/kept: variants (960, crazyhouse, ...) can't
be analysed by the same engine/opening logic and would skew the statistics.

NOTE: the request shapes follow each API's public documentation. The sandbox
this was written in blocks both hosts by egress policy, so the first real
run against a live username should be watched for API changes.
"""
import logging
import os
import time
from typing import Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

LICHESS_API_BASE = "https://lichess.org/api/games/user/"
CHESSCOM_API_BASE = "https://api.chess.com/pub/player/"

# Chess.com's API asks callers to identify themselves with a descriptive
# User-Agent (contact info) rather than a generic browser string - replace
# the contact placeholder with a real one before using this in production.
DEFAULT_USER_AGENT = "OpponentScout/1.0 (contact: replace-with-real-contact-email)"

# Lichess perf types that are standard chess (everything else is a variant).
LICHESS_STANDARD_PERFS = ["ultraBullet", "bullet", "blitz", "rapid", "classical", "correspondence"]
_LICHESS_PERFS_BY_CATEGORY = {
    "bullet": ["ultraBullet", "bullet"],
    "blitz": ["blitz"],
    "rapid": ["rapid"],
    "classical": ["classical"],
}


class DownloadError(Exception):
    """Raised with a human-readable message when a download can't proceed."""


def _get_with_retry(url: str, retries: int = 2, wait_sec: int = 60, **kwargs) -> requests.Response:
    """GET with one polite retry on HTTP 429 - both APIs rate-limit
    anonymous callers, and Lichess explicitly asks clients to wait a full
    minute after a 429 before trying again."""
    for attempt in range(retries + 1):
        resp = requests.get(url, **kwargs)
        if resp.status_code == 429 and attempt < retries:
            logger.warning(f"Rate limited by {url}, waiting {wait_sec}s before retrying...")
            time.sleep(wait_sec)
            continue
        if resp.status_code == 404:
            raise DownloadError(f"Игрок не найден (404): {url}")
        resp.raise_for_status()
        return resp
    raise DownloadError(f"Слишком много запросов (429) к {url}, попробуйте позже")


def download_lichess_games(username: str, max_games: int = 1000, timeout: int = 60,
                           time_control_category: Optional[str] = None) -> str:
    """Downloads up to max_games of a Lichess player's standard-chess games
    as PGN text, newest first. Requests clock comments (needed for the
    time-pressure analysis) and Opening/ECO headers (needed for the
    repertoire breakdown) explicitly. Streams the response: an anonymous
    Lichess export runs at roughly 20 games/s, so 1000 games can take close
    to a minute - a single whole-response timeout would cut it off.
    """
    perfs = _LICHESS_PERFS_BY_CATEGORY.get(time_control_category, LICHESS_STANDARD_PERFS)
    params = {
        "max": max_games, "clocks": "true", "opening": "true",
        "pgnInJson": "false", "perfType": ",".join(perfs),
    }
    headers = {"Accept": "application/x-chess-pgn"}
    resp = _get_with_retry(f"{LICHESS_API_BASE}{username}", params=params, headers=headers,
                           timeout=(15, timeout), stream=True)
    resp.encoding = "utf-8"
    chunks: List[str] = []
    for chunk in resp.iter_content(chunk_size=65536, decode_unicode=True):
        if chunk:
            chunks.append(chunk)
    return "".join(chunks)


def _chesscom_standard_pgns(games: Iterable[dict]) -> Iterable[str]:
    for g in games:
        if g.get("rules", "chess") != "chess":
            continue
        pgn = g.get("pgn")
        if pgn:
            yield pgn


def download_chesscom_games(username: str, max_games: int = 1000, timeout: int = 60,
                            user_agent: str = DEFAULT_USER_AGENT,
                            time_control_category: Optional[str] = None) -> str:
    """Downloads up to max_games of a Chess.com player's standard-chess
    games as PGN text, newest first.

    Chess.com's public API only exposes whole monthly archives - there is no
    "give me the last N games" endpoint - so this walks archive months from
    most recent backwards until max_games is reached.
    """
    headers = {"User-Agent": user_agent}
    username = username.lower()  # the chess.com API path is lowercase-only
    archives_resp = _get_with_retry(f"{CHESSCOM_API_BASE}{username}/games/archives", headers=headers, timeout=timeout)
    archive_urls: List[str] = archives_resp.json().get("archives", [])
    if not archive_urls:
        raise DownloadError(f"У игрока '{username}' на Chess.com нет сыгранных партий")

    pgns: List[str] = []
    for archive_url in reversed(archive_urls):  # most recent month first
        if len(pgns) >= max_games:
            break
        month_resp = _get_with_retry(archive_url, headers=headers, timeout=timeout)
        games = month_resp.json().get("games", [])
        if time_control_category:
            games = [g for g in games if _chesscom_time_class_matches(g, time_control_category)]
        for pgn in _chesscom_standard_pgns(reversed(games)):  # most recent game first
            pgns.append(pgn)
            if len(pgns) >= max_games:
                break

    return "\n\n".join(pgns)


def _chesscom_time_class_matches(game: dict, category: str) -> bool:
    # Chess.com's own time_class uses the same bullet/blitz/rapid buckets;
    # its "daily" is correspondence, which our classifier calls "unknown".
    tc = game.get("time_class", "")
    return tc == category or (category == "unknown" and tc == "daily")


def download_games(source: str, username: str, max_games: int = 1000, output_path: Optional[str] = None,
                   time_control_category: Optional[str] = None) -> str:
    """source: "lichess" or "chesscom". Returns the PGN text, and writes it
    to output_path if given (creating parent directories as needed)."""
    if source == "lichess":
        pgn_text = download_lichess_games(username, max_games=max_games, time_control_category=time_control_category)
    elif source == "chesscom":
        pgn_text = download_chesscom_games(username, max_games=max_games, time_control_category=time_control_category)
    else:
        raise ValueError(f"Unknown source '{source}', expected 'lichess' or 'chesscom'")

    if not pgn_text.strip():
        raise DownloadError(f"{source}: для '{username}' не найдено ни одной партии (с учётом фильтров)")

    if output_path:
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(pgn_text)
        logger.info(f"Downloaded {source} games for '{username}' to '{output_path}'")

    return pgn_text
