from typing import Dict, Any, List
from src.aggregation.opponent_profile import OpponentProfile

class LLMExplainer:
    """
    LLM Explanation Layer stub.
    Prepares structured JSON payloads for critical positions or recurring patterns
    that can be passed to an LLM provider for natural language chess explanations.
    """
    @staticmethod
    def prepare_llm_payload(profile: OpponentProfile) -> List[Dict[str, Any]]:
        payloads = []
        for pos in profile.critical_positions[:5]:
            payloads.append({
                "game_id": pos.game_id,
                "opening": pos.opening,
                "move_number": pos.move_number,
                "played_san": pos.san,
                "best_move": pos.best_move,
                "cpl": pos.loss_for_player,
                "eval_after_black": pos.eval_after_black_perspective,
                "pv": pos.pv
            })
        return payloads
