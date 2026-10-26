"""Kahoot natijalarini Telegram guruhdan olib, baholash jurnaliga yozadigan bot.

Ishlash tartibi:
  1. O'qituvchi fan guruhiga Kahoot hisobotini (Excel) yoki skrinshotini tashlaydi.
  2. Bot faylni o'qiydi, har talabaga 0-10 ball hisoblaydi (to'g'ri javoblar ulushi x 10).
  3. Ballni jurnalning shu guruh varag'ida, o'sha kungi dars ustuniga yozadi.
  4. Natija haqida o'qituvchiga shaxsiy xabar yuboradi.

Izohda (caption) qo'shimcha buyruqlar:
  25.10    boshqa sana ustuniga yozish
  #223     guruhni aniq ko'rsatish (guruh nomida raqam bo'lmasa)
  !        oldin qo'yilgan ball ustidan yozish
  12 savol savollar sonini ko'rsatish (skrinshotda ko'rinmasa)

Ovozli xabar (botga shaxsiy): "223-guruh, Jahona bugun juda faol bo'ldi, Sevinch uy ishini
qilmagan..." -> bot mezon.json bo'yicha ball taklif qiladi, siz tugma bilan tasdiqlaysiz.
"""
import datetime as dt
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import gemini
import kahoot
import sheets
import voice

BASE = Path(__file__).resolve().parent
STATE = BASE / "state.json"
PENDING = BASE / "pending.json"
log = logging.getLogger("bot")


def load_env():
    env = BASE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Tashkent"))
API = f"https://api.telegram.org/bot{TOKEN}"


def tg(method, **params):
    r = requests.post(f"{API}/{method}", json=params, timeout=70)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('description')}")
    return data["result"]


def download(file_id) -> bytes:
    path = tg("getFile", file_id=file_id)["file_path"]
    r = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=120)
    r.raise_for_status()
    return r.content


def parse_caption(caption: str, msg_date: dt.date):
    caption = caption or ""
    day = msg_date
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", caption)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        year = int(y) + (2000 if y and len(y) == 2 else 0) if y else msg_date.year
        day = dt.date(year, mo, d)
    total = None
    m = re.search(r"(\d{1,3})\s*(?:ta\s*)?savol", caption, re.I) or re.search(r"savol\s*=?\s*(\d{1,3})", caption, re.I)
    if m:
        total = int(m.group(1))
    return day, total, "!" in caption


def notify(admin_id, group_chat, text):
    try:
        tg("sendMessage", chat_id=admin_id, text=text)
    except RuntimeError:
        tg("sendMessage", chat_id=group_chat,
           text="Hisobotni yuborish uchun botga shaxsiy chatda /start yozing.")


def react(chat_id, message_id, emoji):
    try:
        tg("setMessageReaction", chat_id=chat_id, message_id=message_id,
           reaction=[{"type": "emoji", "emoji": emoji}])
    except Exception:  # reaksiya muhim emas
        pass


def handle_results(msg, results, source):
    chat = msg["chat"]
    caption = msg.get("caption", "")
    msg_day = dt.datetime.fromtimestamp(msg["date"], TZ).date()
    day, total_override, overwrite = parse_caption(caption, msg_day)

    book = sheets.connect(SPREADSHEET_ID)
    ws = sheets.find_tab(book, chat.get("title", ""), caption)
    if ws is None:
        return "Qaysi guruh ekanini topa olmadim. Izohga guruh raqamini yozing, masalan #106."

    dates, students = sheets.load_tab(ws)
    col = dates.get(day)
    if col is None:
        near = sorted(dates, key=lambda d: abs((d - day).days))[:3]
        near_s = ", ".join(d.strftime("%d.%m") for d in near) or "yo'q"
        return (f"{ws.title}: jurnalda {day:%d.%m} sanali dars ustuni yo'q. "
                f"Eng yaqin sanalar: {near_s}. Izohga to'g'ri sanani yozib qayta yuboring.")

    if total_override:
        for r in results:
            r["total"] = total_override
    for r in results:
        for k in ("correct", "total", "percent"):
            try:
                r[k] = float(r[k]) if r.get(k) is not None else None
            except (TypeError, ValueError):
                r[k] = None

    def usable(r):
        return r["percent"] is not None or (r["correct"] is not None and r["total"])

    incomplete = [r for r in results if not usable(r)]
    results = [r for r in results if usable(r)]

    aliases = sheets.load_aliases(book, ws.title)
    matched, unmatched = kahoot.match_students(results, students, aliases)
    items = [(row, kahoot.score10(res)) for row, _, res in matched]
    written, skipped = sheets.write_scores(ws, col, items, overwrite)

    lines = [f"{ws.title}-guruh, {day:%d.%m} ({source})",
             f"Kiritildi: {len(written)} ta talaba"]
    for row, score in written:
        lines.append(f"  {students[row]}: {score}")
    if skipped:
        lines.append(f"\nOldin ball qo'yilgan, o'zgartirmadim ({len(skipped)}):")
        for row, old in skipped:
            lines.append(f"  {students[row]}: jurnalda {old}")
        lines.append("Ustidan yozish kerak bo'lsa, izohga ! qo'shib qayta yuboring.")
    if unmatched:
        lines.append(f"\nJurnaldan topilmadi ({len(unmatched)}):")
        for r in unmatched:
            lines.append(f"  {r['name']}")
        lines.append(f"Ularni jadvaldagi '{sheets.ALIAS_SHEET}' varag'iga yozib, faylni qayta yuboring.")
    if incomplete:
        lines.append(f"\nTo'g'ri javoblar soni ko'rinmadi ({len(incomplete)}): "
                     + ", ".join(r["name"] for r in incomplete))
        lines.append("Skrinshotda savollar soni bo'lmasa, izohga masalan '12 savol' deb yozing.")
    return "\n".join(lines)


def load_pending():
    return json.loads(PENDING.read_text()) if PENDING.exists() else {}


def save_pending(p):
    PENDING.write_text(json.dumps(p, ensure_ascii=False))


def handle_voice(msg):
    """Ovozli fikrdan ball taklifi tuzadi va tasdiqlash tugmalari bilan yuboradi."""
    chat_id = msg["chat"]["id"]
    v = msg.get("voice") or msg.get("audio")
    if not GEMINI_KEY:
        tg("sendMessage", chat_id=chat_id, text="Ovozni tushunish uchun GEMINI_API_KEY sozlanmagan.")
        return
    tg("sendChatAction", chat_id=chat_id, action="typing")
    book = sheets.connect(SPREADSHEET_ID)
    tabs = {ws.title: ws for ws in sheets.group_tabs(book)}
    layouts = {t: sheets.load_tab(ws) for t, ws in tabs.items()}
    roster = {t: list(st.values()) for t, (_, st) in layouts.items()}
    today = dt.datetime.fromtimestamp(msg["date"], TZ).date()

    data = voice.understand(download(v["file_id"]), v.get("mime_type", "audio/ogg"),
                            GEMINI_KEY, GEMINI_MODEL, roster, today.strftime("%d.%m.%Y"))
    g = str(data.get("group") or "")
    m = re.search(r"\d{3}", g)
    group = m.group(0) if m else g.strip()
    if group not in tabs:
        tg("sendMessage", chat_id=chat_id,
           text=f"Qaysi guruh ekanini tushunmadim. Ovozda guruhni ayting (masalan \"223-guruh\").\n\nEshitganim: {data.get('transcript', '')}")
        return
    day = today
    if data.get("date"):
        day, _, _ = parse_caption(data["date"], today)
    dates, students = layouts[group]
    col = dates.get(day)
    if col is None:
        tg("sendMessage", chat_id=chat_id, text=f"{group}: jurnalda {day:%d.%m} sanali dars ustuni yo'q.")
        return

    stats = sheets.student_stats(tabs[group], dates, students, day, voice.MEZON["oxirgi_baholar_soni"])
    by_name = {n: r for r, n in students.items()}
    items, lines, unknown = [], [f"{group}-guruh, {day:%d.%m}. Taklif:"], []
    for s in data.get("students", []):
        row = by_name.get(s.get("student") or "")
        if row is None:
            unknown.append(s.get("heard") or "?")
            continue
        st = stats.get(row, {})
        score, why = voice.compute(s.get("category"), s.get("score"), st.get("avg"), st.get("existing"))
        if score is None:
            unknown.append(f"{students[row]} ({why})")
            continue
        old = st.get("existing")
        arrow = f"{old:g} → {score}" if isinstance(old, (int, float)) else str(score)
        lines.append(f"• {students[row]}: {arrow}  ({s.get('comment', '')}; {why})")
        items.append([row, score])
    if unknown:
        lines.append("\nTushunmadim yoki topilmadi: " + ", ".join(unknown))
    lines.append(f"\nEshitganim: {data.get('transcript', '')}")
    if not items:
        tg("sendMessage", chat_id=chat_id, text="\n".join(lines))
        return

    pid = str(msg["message_id"])
    pending = load_pending()
    pending[pid] = {"tab": group, "col": col, "items": items}
    save_pending(pending)
    tg("sendMessage", chat_id=chat_id, text="\n".join(lines),
       reply_markup={"inline_keyboard": [[{"text": "✅ Jurnalga yozish", "callback_data": f"ok:{pid}"},
                                          {"text": "❌ Bekor", "callback_data": f"no:{pid}"}]]})


def handle_callback(cq):
    if cq["from"]["id"] not in ADMIN_IDS:
        return
    action, pid = cq["data"].split(":", 1)
    pending = load_pending()
    p = pending.pop(pid, None)
    save_pending(pending)
    msg = cq["message"]
    if p is None:
        tg("answerCallbackQuery", callback_query_id=cq["id"], text="Bu taklif eskirgan")
        return
    if action == "ok":
        ws = sheets.connect(SPREADSHEET_ID).worksheet(p["tab"])
        sheets.write_cells(ws, p["col"], [tuple(x) for x in p["items"]])
        status = f"✅ Jurnalga yozildi ({len(p['items'])} ta talaba)"
    else:
        status = "❌ Bekor qilindi"
    tg("answerCallbackQuery", callback_query_id=cq["id"], text=status)
    tg("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
       text=msg.get("text", "") + "\n\n" + status)


def process(msg):
    chat_id = msg["chat"]["id"]
    sender = msg.get("from", {}).get("id")
    text = msg.get("text", "") or ""

    if text.startswith("/id"):
        tg("sendMessage", chat_id=chat_id, text=f"chat_id: {chat_id}\nsizning id: {sender}")
        return
    if text.startswith("/start") and msg["chat"]["type"] == "private":
        tg("sendMessage", chat_id=chat_id,
           text=f"Salom! Sizning id: {sender}. Kahoot hisobotlarini fan guruhiga tashlang, natijani shu yerga yuboraman.")
        return
    if sender not in ADMIN_IDS:
        return  # faqat o'qituvchi yuborgan fayllar qabul qilinadi

    if (msg.get("voice") or msg.get("audio")) and msg["chat"]["type"] == "private":
        try:
            handle_voice(msg)
        except Exception as e:  # noqa: BLE001
            log.exception("ovoz")
            tg("sendMessage", chat_id=chat_id, text=f"Xato: {e}")
        return

    doc = msg.get("document")
    photo = msg.get("photo")
    try:
        if doc and doc.get("file_name", "").lower().endswith((".xlsx", ".xls")):
            data = download(doc["file_id"])
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                f.write(data)
                tmp = f.name
            try:
                results, _ = kahoot.parse_kahoot_xlsx(tmp)
            finally:
                os.unlink(tmp)
            report = handle_results(msg, results, "Excel hisobot")
        elif photo or (doc and doc.get("mime_type", "").startswith("image/")):
            if not GEMINI_KEY:
                report = "Skrinshotni o'qish uchun GEMINI_API_KEY sozlanmagan. Excel hisobotni yuboring."
            else:
                file_id = photo[-1]["file_id"] if photo else doc["file_id"]
                mime = "image/jpeg" if photo else doc["mime_type"]
                results = gemini.read_screenshot(download(file_id), GEMINI_KEY, GEMINI_MODEL, mime)
                if not results:
                    report = "Rasmda Kahoot natijalarini topa olmadim."
                else:
                    report = handle_results(msg, results, "skrinshot")
        else:
            return
        react(chat_id, msg["message_id"], "👍")
    except Exception as e:  # noqa: BLE001
        log.exception("xato")
        report = f"Xato: {e}"
        react(chat_id, msg["message_id"], "🤔")
    notify(sender, chat_id, report)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    offset = json.loads(STATE.read_text()).get("offset", 0) if STATE.exists() else 0
    log.info("Bot ishga tushdi")
    while True:
        try:
            updates = tg("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
        except Exception as e:  # tarmoq uzilishi va h.k.
            log.warning("getUpdates: %s", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            STATE.write_text(json.dumps({"offset": offset}))
            try:
                if "message" in u:
                    process(u["message"])
                elif "callback_query" in u:
                    handle_callback(u["callback_query"])
            except Exception:  # bitta xabar xatosi botni to'xtatmasin
                log.exception("update %s", u.get("update_id"))


if __name__ == "__main__":
    main()
