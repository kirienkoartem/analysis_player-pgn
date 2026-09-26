"""Downloads a player's games from Lichess or Chess.com public APIs into a
single PGN text blob, so the pipeline can be pointed at a username instead of
requiring a pre-exported PGN file.

NOTE: this module's network calls could not be exercised end-to-end inside
the sandbox this was written in - its outbound egress proxy blocks
lichess.org/chess.com by policy. The request shapes follow each API's
published public documentation, but the first real run against a live
username should be watched for API changes.
"""
import logging
import os
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

LICHESS_API_BASE = "https://lichess.org/api/games/user/"
CHESSCOM_API_BASE = "https://api.chess.com/pub/player/"

# Chess.com's API asks callers to identify themselves with a descriptive
# User-Agent (contact info) rather than a generic browser string - replace
# the contact placeholder with a real one before using this in production.
DEFAULT_USER_AGENT = "OpponentScout/1.0 (contact: replace-with-real-contact-email)"


def download_lichess_games(username: str, max_games: int = 1000, timeout: int = 120) -> str:
    """Downloads up to max_games of a Lichess player's games as PGN text,
    newest first. Requests clock comments (needed for time-pressure
    analysis) and Opening/ECO headers (needed for the opening repertoire
    breakdown) explicitly, since neither is in Lichess's default PGN export.
    """
    url = f"{LICHESS_API_BASE}{username}"
    params = {"max": max_games, "clocks": "true", "opening": "true", "pgnInJson": "false"}
    headers = {"Accept": "application/x-chess-pgn"}
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def download_chesscom_games(username: str, max_games: int = 1000, timeout: int = 60,
                             user_agent: str = DEFAULT_USER_AGENT) -> str:
    """Downloads up to max_games of a Chess.com player's games as PGN text,
    newest first.

    Chess.com's public API only exposes whole monthly archives - there is no
    "give me the last N games" endpoint, and no server-side clocks/opening
    filter - so this walks archive months from most recent backwards,
    collecting games until max_games is reached (which may mean pulling one
    extra month's worth of games and then trimming).
    """
    headers = {"User-Agent": user_agent}
    archives_resp = requests.get(f"{CHESSCOM_API_BASE}{username}/games/archives", headers=headers, timeout=timeout)
    archives_resp.raise_for_status()
    archive_urls: List[str] = archives_resp.json().get("archives", [])

    pgns: List[str] = []
    for archive_url in reversed(archive_urls):  # most recent month first
        if len(pgns) >= max_games:
            break
        month_resp = requests.get(archive_url, headers=headers, timeout=timeout)
        month_resp.raise_for_status()
        games = month_resp.json().get("games", [])
        for g in reversed(games):  # most recent game in the month first
            pgn = g.get("pgn")
            if not pgn:
                continue
            pgns.append(pgn)
            if len(pgns) >= max_games:
                break

    return "\n\n".join(pgns)


def download_games(source: str, username: str, max_games: int = 1000, output_path: Optional[str] = None) -> str:
    """source: "lichess" or "chesscom". Returns the PGN text, and writes it
    to output_path if given (creating parent directories as needed)."""
    if source == "lichess":
        pgn_text = download_lichess_games(username, max_games=max_games)
    elif source == "chesscom":
        pgn_text = download_chesscom_games(username, max_games=max_games)
    else:
        raise ValueError(f"Unknown source '{source}', expected 'lichess' or 'chesscom'")

    if output_path:
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(pgn_text)
        logger.info(f"Downloaded {source} games for '{username}' to '{output_path}'")

    return pgn_text
