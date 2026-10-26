"""O'qituvchining ovozli fikridan talabalarga kunlik ball taklif qilish.

1. Gemini ovozni tinglaydi: qaysi guruh, qaysi kun, kim haqida nima deyilgan.
   Har bir fikrni mezon.json dagi toifalardan biriga ajratadi (yoki aniq aytilgan ballni oladi).
2. Ballni AI emas, shu fayldagi kod mezon bo'yicha hisoblaydi:
   toifa + talabaning oxirgi baholari o'rtachasi (+ o'sha kungi Kahoot bali bo'lsa, o'rtachasi).
   Shu tufayli bir xil fikrga hamma talabaga bir xil qoida ishlaydi.
"""
import base64
import json
from pathlib import Path

import requests

MEZON = json.loads((Path(__file__).resolve().parent / "mezon.json").read_text(encoding="utf-8"))

PROMPT = """You are helping an English teacher in Uzbekistan fill in a gradebook.
Listen to the teacher's voice message (Uzbek, may mix Russian/English) about today's lesson.

Groups and their students:
{roster}

Feedback categories:
{categories}
- "kelmadi": the student was absent
- "aniq": the teacher said an explicit score out of 10

Return JSON:
{{
  "transcript": "what the teacher said, in Uzbek",
  "group": "group name from the list above, or null if not said",
  "date": "DD.MM if the teacher named another day (kecha = yesterday relative to {today}), else null",
  "students": [
    {{"student": "full name exactly as in the list", "heard": "name as spoken",
      "category": "one of the category keys", "score": number or null, "comment": "short Uzbek summary"}}
  ]
}}
Rules: choose the student only from the given group's list; if a spoken name fits two students or none, set "student" to null and keep "heard".
Only include students the teacher actually mentioned."""


def understand(audio: bytes, mime: str, api_key: str, model: str, roster: dict, today: str):
    cats = "\n".join(f'- "{k}": {v["tavsif"]}' for k, v in MEZON["toifalar"].items())
    ros = "\n".join(f"{g}: " + "; ".join(names) for g, names in roster.items())
    body = {
        "contents": [{"parts": [
            {"text": PROMPT.format(roster=ros, categories=cats, today=today)},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(url, params={"key": api_key}, json=body, timeout=120)
    if r.status_code == 429:
        raise RuntimeError("Gemini kunlik bepul limiti tugadi. Keyinroq qayta yuboring.")
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def compute(category: str, explicit, avg, existing):
    """Mezon bo'yicha ball. Qaytaradi: (ball yoki "nb", izoh)."""
    lo, hi = MEZON["min"], MEZON["max"]
    if category == "kelmadi":
        return "nb", "kelmadi"
    if category == "aniq" and explicit is not None:
        return max(0.0, min(hi, float(explicit))), "o'qituvchi aytgan ball"
    rule = MEZON["toifalar"].get(category)
    if rule is None:
        return None, f"toifa noma'lum: {category}"
    if avg is None:
        score, why = rule["bahosiz"], "oldingi baho yo'q"
    else:
        score = max(rule["kamida"], min(rule["oshmasin"], avg + rule["ortacha_qoshimcha"]))
        why = f"o'rtacha {avg:.1f}"
    score = max(lo, min(hi, score))
    if MEZON.get("kahoot_bilan_ortacha") and isinstance(existing, (int, float)):
        score = (score + existing) / 2
        why += f", jurnaldagi {existing:g} bilan o'rtacha"
    return round(score, 1), why
