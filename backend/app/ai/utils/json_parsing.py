import json


def safe_parse_json_object(raw_text: str) -> dict:
    """
    Strict-first parser with a minimal salvage path when providers return
    wrapped JSON content. Raises ValueError if parsing fails.
    """
    text = raw_text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed JSON response.") from exc

    raise ValueError("No valid JSON object found.")
