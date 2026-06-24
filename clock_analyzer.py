"""
clock_analyzer.py
-----------------
Builds the Clock Drawing Test (CDT) prompt, sends a hand-drawn clock photo to
Claude Opus 4.8 (vision, standard Messages API), and parses the model's JSON.

Scoring is grounded in established CDT frameworks (see README "References"):
MoCA clock item (0–3), Shulman 5-point, Sunderland 10-point, ACE-III clock item
(0–5), the Mendez CDIS (20-item, 0–20), and Rouleau-style qualitative error
analysis. This is a screening-awareness prototype — **not a diagnosis and not a
validated instrument**. Keep that framing in the prompt.

The ``anthropic`` SDK is imported lazily inside ``analyze_clock`` so this module
(and the test suite) imports cleanly without the SDK installed.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Optional

# Pinned per CLAUDE.md invariant #5. Opus 4.8 supports vision via Messages.
DEFAULT_MODEL = "claude-opus-4-8"

MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "You are a careful assistant that scores a photograph of a HAND-DRAWN analog "
    "clock using established Clock Drawing Test (CDT) frameworks: the MoCA clock "
    "item (0-3: closed contour, all numbers present and correctly placed, hands "
    "showing the requested time), the Shulman 5-point hierarchical scale, the "
    "Sunderland 10-point scale, the ACE-III clock item (0-5: circle, numbers, "
    "hands), the Mendez Clock Drawing Interpretation Scale (CDIS, 20 items scored "
    "0/1 each, total 0-20), and Rouleau-style qualitative error analysis "
    "(visuospatial/executive, conceptual deficit, perseveration, graphic "
    "difficulty, stimulus-bound, planning).\n\n"
    "You are NOT diagnosing anything. The CDT cannot identify Alzheimer's, "
    "dementia, Parkinson's, or any condition, and performance is affected by "
    "eyesight, motor control, education, language, and drawing medium. Frame "
    "every observation as a cautious screening observation, never a diagnosis. "
    "Subtype 'association' notes are general tendencies from the literature, not "
    "a means of identifying a condition in an individual.\n\n"
    "Reply with ONE JSON object and nothing else — no prose, no code fence."
)

# The exact shape app.py reads back: depicted_time{readable,hour,minute},
# time_matches_target, screening_flag, overall_summary, clock_detected, scales.
_SCHEMA_HINT = """Return JSON with exactly these keys:
{
  "clock_detected": true | false,
  "clock_description": "<1-2 sentences: neutral description of what is drawn (contour, numbers, hands) — only what is visible, no interpretation>",
  "depicted_time": {"readable": true | false, "hour": <int 1-12 or null>, "minute": <int 0-59 or null>},
  "time_matches_target": true | false | null,
  "moca_clock": {"contour": 0 | 1, "numbers": 0 | 1, "hands": 0 | 1, "total": <0-3>},
  "shulman_5point": {"score": <1-5>, "rationale": "<short>"},
  "sunderland_10point": {"score": <1-10>, "rationale": "<short>"},
  "ace3_clock": {"circle": 0 | 1, "numbers": 0 | 1 | 2, "hands": 0 | 1 | 2, "total": <0-5>, "rationale": "<short>"},
  "mendez_cdis": {"items": {"1": 0 | 1, "2": 0 | 1, "3": 0 | 1, "4": 0 | 1, "5": 0 | 1, "6": 0 | 1, "7": 0 | 1, "8": 0 | 1, "9": 0 | 1, "10": 0 | 1, "11": 0 | 1, "12": 0 | 1, "13": 0 | 1, "14": 0 | 1, "15": 0 | 1, "16": 0 | 1, "17": 0 | 1, "18": 0 | 1, "19": 0 | 1, "20": 0 | 1}, "total": <0-20>},
  "qualitative_errors": ["<Rouleau-style error category>", ...],
  "domain_observations": "<visuospatial / executive / graphomotor notes>",
  "literature_association_notes": "<cautious, non-diagnostic tendencies only>",
  "screening_flag": "none" | "review_suggested" | "unclear",
  "overall_summary": "<2-4 sentence plain-language, explicitly non-diagnostic>"
}"""


def build_user_prompt(target_hour: int, target_minute: int,
                      self_reported_age: str, self_reported_status: str) -> str:
    """Compose the per-request user prompt. Includes the target time the hands
    should show plus the synthetic age/status context, then the JSON schema."""
    target = f"{int(target_hour):02d}:{int(target_minute):02d}"
    return (
        "Analyze the attached photo of a hand-drawn analog clock.\n\n"
        f"The drawer was asked to set the hands to {target} (24-hour). A 12-hour "
        "clock face showing the same hour/minute counts as a match (e.g. 23:10 "
        "drawn as 11:10 is correct).\n\n"
        "Reading the hands — use hand LENGTH as the reference: the HOUR hand is "
        "always the SHORTER hand and the MINUTE hand is the LONGER hand. "
        "Identify the two hands first, take the shorter one as the hour hand and "
        "the longer one as the minute hand.\n\n"
        "Estimating the hour accurately — extend the shorter (hour) hand outward "
        "from the center to where it meets the ring of numbers:\n"
        "  - If it points directly at a number, that number is the hour.\n"
        "  - If it falls in the SPACE BETWEEN two adjacent numbers, the hour is "
        "the LOWER of the two — i.e. the number the hand has most recently "
        "PASSED going clockwise, NOT the nearer or higher number. The hour hand "
        "drifts toward the next number as the minutes advance, so partway between "
        "is still the lower hour (e.g. between 4 and 5 -> 4; just before 5 is "
        "still 4). The one exception is the gap between 12 and 1, which reads as "
        "12.\n"
        "Read the minutes from the longer hand. If the two hands are the same "
        "length, or there are not exactly two distinguishable hands, treat the "
        "time as ambiguous and set readable=false. Report the depicted "
        "hour/minute; set readable=false if the hands are ambiguous or absent.\n\n"
        "Synthetic test context (NOT to be used diagnostically): "
        f"age={self_reported_age}, self-reported cognitive status="
        f"\"{self_reported_status}\".\n\n"
        "Give clock_description: 1-2 neutral sentences on what is actually drawn "
        "(the contour, the numbers, the hands) — only what is visible, no "
        "interpretation. Then score the drawing against the MoCA clock item, the "
        "Shulman 5-point and Sunderland 10-point scales, the ACE-III clock item, "
        "and the Mendez CDIS (below), and list any Rouleau-style qualitative "
        "errors. If no clock is present, set clock_detected=false and leave the "
        "scores/time null.\n\n"
        + _ACE3_RULES
        + "\n\n"
        + _MENDEZ_RULES
        + "\n\n"
        + _SCHEMA_HINT
    )


# ACE-III clock item (0-5). Verbatim criteria from the ACE-III/M-ACE 2014 scoring
# guide. The numbers rule is what penalizes digits drawn OUTSIDE the circle.
_ACE3_RULES = (
    "ACE-III clock item (score 0-5):\n"
    "  - circle: 1 if it is a reasonable circle, else 0.\n"
    "  - numbers: 2 if all numbers 1-12 are present, INSIDE the circle, and "
    "evenly distributed (a slight overall rotation is acceptable); 1 if all "
    "numbers are present but are OUTSIDE the circle or unevenly spaced; 0 if not "
    "all numbers are present. Numbers written outside the clock face MUST cost "
    "this point (2 -> 1).\n"
    "  - hands: 2 if both hands are drawn with correct relative lengths and "
    "pointing at the correct numbers; 1 if both hands point at the correct "
    "numbers but the lengths are wrong, or only one hand is correct in both "
    "number and length; 0 otherwise (e.g. only one hand, or both lengths and "
    "numbers wrong).\n"
    "  - total = circle + numbers + hands."
)

# Mendez Clock Drawing Interpretation Scale (CDIS) — 20 items, 1 point each,
# total 0-20. Items verbatim (condensed) from Mendez, Ala & Underwood (1992).
# Items keyed to the commanded time assume "ten past eleven" (11:10): the minute
# hand points at the 2 (item 4) and the hour hand at the 11 (item 9).
_MENDEZ_RULES = (
    "Mendez CDIS — score 1 point per item that is satisfied (total 0-20). Items "
    "4-15 are scored ONLY if number symbols are present; items 16-20 ONLY if one "
    "or more hands are present:\n"
    "  1. There is an attempt to indicate a time in any way.\n"
    "  2. All marks can be classified as part of the closure figure, a hand, or a "
    "clock-number symbol.\n"
    "  3. There is a totally closed figure without gaps (the closure figure).\n"
    "  4. A '2' is present and is pointed out in some way for the time (the "
    "minute hand at 'ten past').\n"
    "  5. Most symbols are distributed as a circle without major gaps.\n"
    "  6. Three or more clock quadrants (12-3, 3-6, 6-9, 9-12) have one or more "
    "appropriate numbers.\n"
    "  7. Most symbols are ordered clockwise / rightward.\n"
    "  8. All number symbols are TOTALLY WITHIN the closure figure (numbers drawn "
    "outside the circle fail this item).\n"
    "  9. An '11' is present and is pointed out in some way for the time (the hour "
    "hand at eleven).\n"
    "  10. All numbers 1-12 are indicated.\n"
    "  11. There are no repeated or duplicated number symbols.\n"
    "  12. There are no substitutions for Arabic or Roman numerals.\n"
    "  13. The numbers do not go beyond the number 12.\n"
    "  14. All symbols lie about equally adjacent to the closure-figure edge.\n"
    "  15. Seven or more of the same symbol type are ordered sequentially.\n"
    "  16. All hands radiate from the direction of the closure-figure center.\n"
    "  17. One hand is visibly longer than another hand.\n"
    "  18. There are exactly two distinct and separable hands.\n"
    "  19. All hands are totally within the closure figure.\n"
    "  20. There is an attempt to indicate a time with one or more hands.\n"
    "Report each item as 0 or 1 under mendez_cdis.items and set total to their sum."
)


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of the model's reply.

    Tolerates plain JSON, a ```json ... ``` (or bare ```) code fence with prose
    around it, and trailing commentary after the object. Raises ValueError if no
    JSON object can be recovered.
    """
    if text is None:
        raise ValueError("no text to parse")
    s = text.strip()

    # 1) Whole string is JSON.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 2) Inside a fenced block — parse the first balanced object within it.
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        obj = _first_balanced_object(fence.group(1))
        if obj is not None:
            return obj

    # 3) First balanced {...} anywhere in the string (handles trailing noise).
    obj = _first_balanced_object(s)
    if obj is not None:
        return obj

    raise ValueError("no JSON object found in model response")


def _first_balanced_object(text: str) -> Optional[dict]:
    """Return the first brace-balanced JSON object in ``text``, or None.

    Tracks string state so braces inside string values don't throw off the count.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def analyze_clock(*, image_bytes: bytes, media_type: str, target_hour: int,
                  target_minute: int, api_key: str, self_reported_age: str,
                  self_reported_status: str) -> dict:
    """Send the drawing to Claude Opus 4.8 and return the parsed analysis dict.

    Adds ``_model`` and ``_raw_text`` keys; app.py strips ``_raw_text`` before
    display and never persists anything. The ``anthropic`` SDK is imported here
    so the module imports without it (and so tests can run SDK-free).
    """
    import anthropic  # lazy: keeps the module + tests importable without the SDK

    prompt = build_user_prompt(target_hour, target_minute,
                               self_reported_age, self_reported_status)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )

    raw_text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )

    analysis = _extract_json(raw_text)
    analysis["_model"] = DEFAULT_MODEL
    analysis["_raw_text"] = raw_text
    return analysis
