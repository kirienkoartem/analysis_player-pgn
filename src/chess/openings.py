import chess
import chess.pgn
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

@dataclass
class VariationNode:
    san_move: str
    move_sequence: str  # e.g. "1.e4 c5 2.Nf3"
    fullmove_number: int
    side: str  # "white" or "black" - whoever made san_move
    games_count: int = 0
    wins: int = 0    # from the TARGET player's perspective
    draws: int = 0
    losses: int = 0
    children: Dict[str, 'VariationNode'] = field(default_factory=dict)

def _tally(node: VariationNode, result: str, win_result: str, loss_result: str) -> None:
    if result == win_result:
        node.wins += 1
    elif result == loss_result:
        node.losses += 1
    elif result == "1/2-1/2":
        node.draws += 1


class OpeningTracker:
    @staticmethod
    def get_eco_and_opening(game: chess.pgn.Game) -> Tuple[str, str]:
        headers = game.headers
        eco = headers.get("ECO", "???")
        opening = headers.get("Opening", "Unknown Opening")
        return eco, opening

    @staticmethod
    def family_name(opening_name: str) -> str:
        """Collapses a specific opening/variation name to its family, e.g.
        "King's Indian Defense: Normal Variation" and "King's Indian Defense,
        Fianchetto Variation" both collapse to "King's Indian Defense". This
        groups sub-variations of the same opening (which PGN exports label
        with many distinct ECO codes/variation names) so a report doesn't
        have to manually re-sum e.g. E61+E70 to see the whole King's Indian.
        """
        if not opening_name:
            return "Unknown Opening"
        name = opening_name.split(":")[0].split(",")[0].strip()
        return name or opening_name

    @staticmethod
    def build_variation_tree(
        games: List['GameRecord'],
        target_color: chess.Color,
        max_plies: int = 12,
    ) -> VariationNode:
        """Builds a tree of the target player's OWN moves (skipping the
        opponent's replies) within the first max_plies, with win/draw/loss
        tallies for the games that passed through each node.

        Kept to a shallow max_plies by default: branching collapses fast in
        practice (most games diverge from each other within a handful of the
        target player's own opening moves), so this stays small without
        needing artificial pruning that would silently drop data from
        whichever game happens to first establish a branch.
        """
        root = VariationNode(san_move="<start>", move_sequence="", fullmove_number=0, side="")

        for record in games:
            game = record.game_node
            result = record.metadata.result
            win_result = "1-0" if target_color == chess.WHITE else "0-1"
            loss_result = "0-1" if target_color == chess.WHITE else "1-0"

            board = game.board()
            node = game
            ply = 0
            current = root
            seq_parts: List[str] = []

            current.games_count += 1
            _tally(current, result, win_result, loss_result)

            while node.variations and ply < max_plies:
                next_node = node.variation(0)
                move = next_node.move
                san = board.san(move)
                fullmove = board.fullmove_number
                mover_color = board.turn
                board.push(move)
                node = next_node
                ply += 1

                if mover_color != target_color:
                    continue  # only branch on the target player's own moves

                seq_parts.append(f"{fullmove}.{san}" if mover_color == chess.WHITE else f"{fullmove}...{san}")

                if san not in current.children:
                    current.children[san] = VariationNode(
                        san_move=san,
                        move_sequence=" ".join(seq_parts),
                        fullmove_number=fullmove,
                        side="white" if mover_color == chess.WHITE else "black",
                    )
                current = current.children[san]
                current.games_count += 1
                _tally(current, result, win_result, loss_result)

        return root

    @staticmethod
    def extract_opening_moves(game: chess.pgn.Game, plies: int = 20) -> Tuple[str, List[str]]:
        """Extracts opening SAN move sequence up to specified plies."""
        moves: List[str] = []
        board = game.board()
        node = game
        count = 0
        while node.variations and count < plies:
            next_node = node.variation(0)
            move = next_node.move
            san = board.san(move)
            moves.append(san)
            board.push(move)
            node = next_node
            count += 1

        formatted_seq = []
        for i in range(0, len(moves), 2):
            fullmove = (i // 2) + 1
            w_move = moves[i]
            if i + 1 < len(moves):
                b_move = moves[i+1]
                formatted_seq.append(f"{fullmove}.{w_move} {b_move}")
            else:
                formatted_seq.append(f"{fullmove}.{w_move}")

        return " ".join(formatted_seq), moves
