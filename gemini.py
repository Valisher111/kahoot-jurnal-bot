"""Kahoot skrinshotini Gemini API orqali o'qish."""
import base64
import json

import requests

PROMPT = """This is a screenshot of Kahoot game results.
Extract every player visible. For each player return:
- "name": the nickname exactly as shown
- "correct": number of correct answers (integer), or null if not shown
- "total": total number of questions (integer), or null if not shown
- "percent": the "Correct answers" percentage as a number (74 for 74%), or null if not shown
Return only a JSON array, for example:
[{"name": "Madina Saidqulova", "correct": 9, "total": 12, "percent": null}]
Do not guess numbers that are not visible."""


def read_screenshot(image_bytes: bytes, api_key: str, model: str, mime: str = "image/jpeg"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    r = requests.post(url, params={"key": api_key}, json=body, timeout=90)
    if r.status_code == 429:
        raise RuntimeError("Gemini kunlik bepul limiti tugadi. Ertaga qayta yuboring yoki Excel hisobotini tashlang.")
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text)
    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        out.append({
            "name": str(item["name"]).strip(),
            "correct": item.get("correct"),
            "total": item.get("total"),
            "percent": item.get("percent"),
        })
    return out
