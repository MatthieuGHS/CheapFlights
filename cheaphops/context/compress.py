"""Compresseurs déterministes (§12.1) : le LLM ne voit jamais de réponse brute."""

from typing import Any

MAX_STR = 40


def json_skeleton(value: Any, max_str: int = MAX_STR) -> Any:
    """Types + une valeur d'exemple ; un tableau est réduit à son premier élément et sa taille."""
    if isinstance(value, dict):
        return {k: json_skeleton(v, max_str) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [json_skeleton(value[0], max_str), f"… {len(value)} items"]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return f"num {value}"
    text = str(value)
    return f"str {text[:max_str]!r}" + ("…" if len(text) > max_str else "")
