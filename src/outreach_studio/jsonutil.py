"""Tolerant JSON extraction from model output."""
import json
import re


def parse_json(text: str):
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError as err:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise ValueError("model did not return JSON: " + t[:200]) from err
