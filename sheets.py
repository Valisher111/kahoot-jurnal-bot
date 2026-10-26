"""Baholash jurnali (Google Sheets) bilan ishlash.

Jurnal tuzilishi: 3-qatorda dars sanalari, 4-qatordan pastda B ustunida talabalar.
"""
import datetime as dt

import google.auth
import gspread
from gspread.utils import rowcol_to_a1

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
ALIAS_SHEET = "Kahoot taxalluslar"
HEADER_ROW = 3
FIRST_STUDENT_ROW = 4
EPOCH = dt.date(1899, 12, 30)


def connect(spreadsheet_id: str):
    # Serverda (Google Cloud VM) kalit fayl kerak emas: VM'ning o'z hisobi ishlatiladi.
    creds, _ = google.auth.default(scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(spreadsheet_id)


def find_tab(book, chat_title: str, caption: str = ""):
    """Guruh nomi yoki izohdagi #106 kabi belgidan jurnal varag'ini topadi."""
    titles = [ws.title for ws in book.worksheets() if ws.title not in (ALIAS_SHEET, "Ko'rsatma")]
    for text in (caption or "", chat_title or ""):
        for t in sorted(titles, key=len, reverse=True):
            if f"#{t}" in text:
                return book.worksheet(t)
    for t in sorted(titles, key=len, reverse=True):
        if t in (chat_title or ""):
            return book.worksheet(t)
    return None


def load_tab(ws):
    """Sanalar ustunlari va talabalar ro'yxatini qaytaradi."""
    header = ws.row_values(HEADER_ROW, value_render_option="UNFORMATTED_VALUE")
    dates = {}
    for col, v in enumerate(header, start=1):
        if isinstance(v, (int, float)) and 40000 < v < 60000:
            dates[EPOCH + dt.timedelta(days=int(v))] = col
    names = ws.col_values(2)
    students = {}
    for row in range(FIRST_STUDENT_ROW, len(names) + 1):
        n = names[row - 1].strip()
        if n:
            students[row] = n
    return dates, students


def load_aliases(book, group: str):
    """'Kahoot taxalluslar' varag'i: Guruh | Taxallus | Talaba."""
    from kahoot import normalize
    try:
        ws = book.worksheet(ALIAS_SHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(ALIAS_SHEET, rows=300, cols=3)
        ws.update(values=[["Guruh", "Taxallus (Kahoot'dagi)", "Talaba (jurnaldagi to'liq ism)"]], range_name="A1:C1")
        return {}
    out = {}
    for row in ws.get_all_values()[1:]:
        if len(row) >= 3 and row[1].strip() and row[2].strip() and row[0].strip() in ("", group):
            out[normalize(row[1])] = row[2].strip()
    return out


def write_scores(ws, col: int, items, overwrite: bool):
    """items: [(qator, ball)]. Bo'sh kataklarga yozadi; overwrite bo'lsa ustidan yozadi.

    Qaytaradi: yozilganlar [(qator, ball)], o'tkazib yuborilganlar [(qator, eski qiymat)]
    """
    if not items:
        return [], []
    rows = [r for r, _ in items]
    rng = f"{rowcol_to_a1(min(rows), col)}:{rowcol_to_a1(max(rows), col)}"
    current = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
    cur = {}
    for i, r in enumerate(range(min(rows), max(rows) + 1)):
        cur[r] = current[i][0] if i < len(current) and current[i] else ""
    written, skipped, updates = [], [], []
    for r, score in items:
        old = cur.get(r, "")
        if old not in ("", None) and not overwrite:
            skipped.append((r, old))
            continue
        updates.append({"range": rowcol_to_a1(r, col), "values": [[score]]})
        written.append((r, score))
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return written, skipped


def group_tabs(book):
    return [ws for ws in book.worksheets() if ws.title not in (ALIAS_SHEET, "Ko'rsatma")]


def student_stats(ws, dates, students, day, last_n=5):
    """Har talaba uchun: oxirgi last_n ta kunlik baho o'rtachasi (shu kundan oldingi) va shu kungi qiymat."""
    if not students:
        return {}
    last_row = max(students)
    grid = ws.get(f"A1:{rowcol_to_a1(last_row, max(dates.values()))}", value_render_option="UNFORMATTED_VALUE")
    before = sorted((d, c) for d, c in dates.items() if d < day)
    today_col = dates.get(day)
    out = {}
    for row in students:
        vals = grid[row - 1] if row - 1 < len(grid) else []
        cell = lambda c: vals[c - 1] if c - 1 < len(vals) else ""
        nums = [cell(c) for _, c in before if isinstance(cell(c), (int, float))]
        recent = nums[-last_n:]
        avg = sum(recent) / len(recent) if recent else None
        existing = cell(today_col) if today_col else ""
        out[row] = {"avg": avg, "existing": existing if existing != "" else None}
    return out


def write_cells(ws, col, items):
    """items: [(qator, qiymat)] — tasdiqlangan qiymatlarni ustidan yozadi."""
    if items:
        ws.batch_update([{"range": rowcol_to_a1(r, col), "values": [[v]]} for r, v in items],
                        value_input_option="USER_ENTERED")
