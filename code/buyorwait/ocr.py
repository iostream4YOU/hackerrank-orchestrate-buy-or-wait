"""Free, local reading of receipt/bill images: OCR + deterministic amount selection.

Backends (first available wins): Apple Vision (macOS, compiled from ocr_vision.swift on first use)
-> Tesseract CLI. The amount is chosen by rules keyed on the event the image belongs to
(outstanding balance -> balance due; bill -> amount due / total; payslip -> net pay; receipt ->
grand total / total paid), then cross-checked against any amount written in words and corrected for
the common OCR misread of a leading currency glyph (e.g. "₹79,679.26" read as "779,679.26").
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT_SRC = os.path.join(HERE, "ocr_vision.swift")


# --------------------------------------------------------------------------- OCR backends
def _vision_binary():
    if not (shutil.which("swiftc") and os.path.exists(SWIFT_SRC)):
        return None
    with open(SWIFT_SRC, "rb") as f:
        tag = hashlib.sha1(f.read()).hexdigest()[:10]
    binary = os.path.join(tempfile.gettempdir(), f"buyorwait_ocr_vision_{tag}")
    if not os.path.exists(binary):
        r = subprocess.run(["swiftc", "-O", SWIFT_SRC, "-o", binary], capture_output=True, text=True)
        if r.returncode != 0:
            return None
    return binary


def _rows_from_boxes(obs):
    """obs: [(y_center, x, height, text)] with y growing upwards -> text rows top to bottom."""
    obs.sort(key=lambda o: -o[0])
    rows = []
    for o in obs:
        if rows and abs(rows[-1][0][0] - o[0]) < max(0.012, 0.5 * o[2]):
            rows[-1].append(o)
        else:
            rows.append([o])
    return [" | ".join(t for _, _, _, t in sorted(r, key=lambda o: o[1])) for r in rows]


def _vision_rows(path):
    binary = _vision_binary()
    if not binary:
        return None
    r = subprocess.run([binary, path], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None
    obs = []
    for line in r.stdout.splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5:
            x, y, w, h, t = parts
            obs.append((float(y) + float(h) / 2, float(x), float(h), t))
    return _rows_from_boxes(obs)


def _tesseract_rows(path):
    if not shutil.which("tesseract"):
        return None
    r = subprocess.run(["tesseract", path, "stdout", "--psm", "6", "tsv"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None
    lines = {}
    for row in r.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) == 12 and c[11].strip():
            lines.setdefault((c[2], c[3], c[4]), []).append((int(c[6]), c[11]))
    return [" | ".join(t for _, t in sorted(ws)) for _, ws in sorted(lines.items(), key=lambda kv: tuple(map(int, kv[0])))]


def ocr_rows(path):
    for backend, fn in (("apple-vision", _vision_rows), ("tesseract", _tesseract_rows)):
        rows = fn(path)
        if rows:
            return backend, rows
    return None, []


# --------------------------------------------------------------------------- numbers
def parse_number(tok: str):
    """'1,00,000.00'->100000.0, '$33,50'->33.5, '41272,0'->41272.0, '3,543.54'->3543.54"""
    t = re.sub(r"[^\d,.]", "", tok)
    if not t or not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) and t.count(",") == 1 else t.replace(",", "")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def row_amounts(row: str):
    """Amounts in a text row, left to right. Joins handwritten 'rupees paise' groups like '4 543 00'."""
    out = []
    for cell in row.split("|"):
        cell = cell.strip()
        m = re.search(r"(\d{1,3}(?: \d{3})+) (\d{2})$", cell)
        if m:
            out.append(float(m.group(1).replace(" ", "") + "." + m.group(2)))
            continue
        for tok in re.findall(r"[\d][\d,.]*", cell):
            v = parse_number(tok)
            if v is not None:
                out.append(v)
    return out


# --------------------------------------------------------------------------- amount in words
_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "million": 1_000_000, "crore": 10_000_000}


def _words_to_int(words):
    total, cur, seen = 0, 0, False
    for w in words:
        if w in _UNITS:
            cur += _UNITS[w]; seen = True
        elif w in _TENS:
            cur += _TENS[w]; seen = True
        elif w == "hundred":
            cur = max(cur, 1) * 100; seen = True
        elif w in _SCALES:
            total += max(cur, 1) * _SCALES[w]; cur = 0; seen = True
    return total + cur if seen else None


def amount_in_words(rows):
    """Amount written in words ('... Seventy-Nine Thousand ... and Twenty-Six Paise Only')."""
    idx = [i for i, r in enumerate(rows) if re.search(r"rupee|paise|paisa|in words", r, re.I)]
    if not idx:
        return None
    known = set(_UNITS) | set(_TENS) | {"hundred", "and"} | set(_SCALES)
    keep = known | {"rupee", "rupees", "paise", "paisa"}
    text = " ".join(rows[i] for i in sorted(set(idx) | {i + 1 for i in idx if i + 1 < len(rows)}))
    toks = [t for t in re.findall(r"[a-z]+", text.lower().replace("-", " ")) if t in keep]
    while toks and toks[0] == "and":
        toks.pop(0)
    if not any(t in known - {"and"} for t in toks):
        return None
    if "paise" in toks or "paisa" in toks:
        p = toks.index("paise") if "paise" in toks else toks.index("paisa")
        head = toks[:p]
        k = len(head) - 1 - head[::-1].index("and") if "and" in head else None
        rupee_words, paise_words = (head[:k], head[k + 1:]) if k is not None else (head, [])
    else:
        rupee_words, paise_words = toks, []
    rupees = _words_to_int([w for w in rupee_words if w not in ("rupee", "rupees", "and")])
    if rupees is None:
        return None
    return rupees + (_words_to_int(paise_words) or 0) / 100.0


# --------------------------------------------------------------------------- selection
_LABELS = {
    "balance": [r"balance\s*due", r"amount\s*payab", r"outstanding", r"amount\s*due\s*(till|by|before)",
                r"amount\s*due", r"\bbalance\b", r"grand\s*total", r"\btotal\b"],
    "payslip": [r"net\s*pay", r"take\s*home", r"net\s*salary"],
    "receipt": [r"grand\s*total", r"total\s*paid", r"amount\s*paid", r"net\s*amount", r"total\s*amount\s*received",
                r"amount\s*received", r"order\s*total", r"bill\s*total", r"\btotal\b", r"item\s*bill", r"cash\s*paid"],
}
_EXCLUDE = re.compile(r"sub\s*-?\s*total|sebtotal|item\s*total|in\s*words|total\s*(earnings|deductions|savings|tax)|"
                      r"previous\s*balance|due\s*after", re.I)


def _kind(event):
    d = f"{event.description} {event.category}".lower()
    if event.direction == "credit" or "salary" in d or "payslip" in d:
        return "payslip"
    if re.search(r"outstanding|payable|balance|bill due|due\b", d) or event.status in ("pending", "scheduled"):
        return "balance"
    return "receipt"


def _fix_glyph(value, all_values, words_value):
    """Undo a currency glyph read as a leading digit when the evidence supports it."""
    s = f"{value:.2f}"
    if len(s) > 4:
        stripped = float(s[1:])
        if words_value is not None and abs(stripped - words_value) < 0.005:
            return stripped, "leading glyph removed (matches amount in words)"
        if any(abs(stripped - v) < 0.005 for v in all_values):
            return stripped, "leading glyph removed (matches another figure)"
    return value, None


_DATE = re.compile(r"\b\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4}\b")


def _cell_values(cell):
    return [v for v in row_amounts(_DATE.sub(" ", cell)) if v > 0]


def _is_label(cell):
    c = re.sub(r"\b(IDR|INR|ZAR|USD|EUR|Rs|RS|Rp)\b", " ", _DATE.sub(" ", cell))
    return len(re.findall(r"[A-Za-z]", c)) >= 3


def _value_for(rows, i, pattern):
    """Value belonging to the label matched in row i: same cell, then following numeric cells up to the next
    label, then the row directly below (values printed under their label)."""
    cells = [c.strip() for c in rows[i].split("|")]
    for j, cell in enumerate(cells):
        m = re.search(pattern, cell, re.I)
        if not m:
            continue
        inline = _cell_values(cell[m.end():])
        if inline:
            return inline[-1]
        vals = []
        for nxt in cells[j + 1:]:
            if _is_label(nxt):
                break
            vals += _cell_values(nxt)
        if vals:
            return vals[-1]
        if i + 1 < len(rows):
            below = [c.strip() for c in rows[i + 1].split("|")]
            vals = []
            for nxt in below:
                if _is_label(nxt) and vals:
                    break
                if not _is_label(nxt):
                    vals += _cell_values(nxt)
            if vals:
                return vals[-1]
    return None


def pick_amount(rows, event):
    """Returns (amount, label_row, note) or (None, None, reason)."""
    kind = _kind(event)
    words = amount_in_words(rows)
    if words is not None and words <= 0:
        words = None
    all_values = [v for r in rows for v in row_amounts(r)]
    if kind == "receipt" and words is not None and any(abs(words - v) < 0.005 for v in all_values):
        return words, None, "amount in words (matches a printed figure)"
    for pattern in _LABELS[kind]:
        for i, r in enumerate(rows):
            if not re.search(pattern, r, re.I):
                continue
            cell = next(c for c in r.split("|") if re.search(pattern, c, re.I))
            if _EXCLUDE.search(cell):
                continue
            value = _value_for(rows, i, pattern)
            if value is None:
                continue
            fixed, note = _fix_glyph(value, [v for v in all_values if abs(v - value) >= 0.005], words)
            if note is None and kind == "receipt" and words is not None and abs(value - words) >= 0.005 and \
                    any(abs(words - v) < 0.005 for v in all_values):
                return words, r, "amount in words overrides a conflicting label"
            return fixed, r, note
    if words is not None:
        return words, None, "amount in words"
    return None, None, "no labelled amount found"
