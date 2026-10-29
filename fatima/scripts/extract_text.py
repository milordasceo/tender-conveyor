#!/usr/bin/env python3
"""Достать текст из всех документов папки тендера, чтобы прочитать их целиком.

Форматы: .docx/.docm (zip+xml, без зависимостей), .doc/.rtf/.odt (LibreOffice soffice),
.pdf (pdftotext из poppler-utils), .html/.htm (стандартный html.parser),
.xlsx/.xls/.ods (soffice → csv), .txt/.csv/.xml/.json (как есть).
Файлы tender.md, tender.json, docs_status.json пропускаются.

Запуск:
  python3 extract_text.py <папка тендера> [--out <папка для .txt>]
По умолчанию --out = <папка тендера>/txt. Папку txt на Drive не заливать.

Вывод: строка на файл «ok|empty|error<TAB>символов<TAB>файл[<TAB>ошибка]», в конце «итого: ...».
Код выхода: 0 — всё извлечено, 1 — есть ошибки или пустые тексты (их читать вручную или
сообщить в сводке), 2 — ошибка запуска.
"""
import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path

SKIP = {"tender.md", "tender.json", "docs_status.json"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def from_docx(p):
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(p) as z:
        names = ["word/document.xml"] + sorted(n for n in z.namelist()
                                               if re.match(r"word/(header|footer|footnotes|endnotes)\d*\.xml$", n))
        out = []
        for n in names:
            if n not in z.namelist():
                continue
            root = ET.fromstring(z.read(n))
            for el in root.iter():
                if el.tag == W + "p":
                    out.append("\n")
                elif el.tag == W + "tab":
                    out.append("\t")
                elif el.tag in (W + "br", W + "cr"):
                    out.append("\n")
                elif el.tag == W + "t" and el.text:
                    out.append(el.text)
                elif el.tag == W + "tc":
                    out.append(" | ")
    return "".join(out)


class _H(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def read_text_any(p):
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def from_html(p):
    h = _H()
    h.feed(read_text_any(p))
    return html.unescape("".join(h.out))


def soffice(p, fmt, ext):
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError("нет soffice (поставить libreoffice)")
    with tempfile.TemporaryDirectory() as td:
        # отдельный профиль: не мешать другим запускам LibreOffice на общем боксе
        prof = Path(td) / "profile"
        src = Path(td) / ("in" + p.suffix.lower())  # латинское имя: soffice капризен к путям
        shutil.copyfile(p, src)
        r = subprocess.run([exe, f"-env:UserInstallation=file://{prof}", "--headless",
                            "--convert-to", fmt, "--outdir", td, str(src)],
                           capture_output=True, text=True, timeout=180)
        outs = list(Path(td).glob("in." + ext))
        if not outs:
            raise RuntimeError(f"soffice не сконвертировал: {r.stderr.strip()[:200]}")
        return read_text_any(outs[0])


def from_pdf(p):
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("нет pdftotext (поставить poppler-utils)")
    r = subprocess.run([exe, "-layout", str(p), "-"], capture_output=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"pdftotext: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout.decode("utf-8", "replace")


def extract(p):
    ext = p.suffix.lower()
    if ext in (".docx", ".docm"):
        try:
            return from_docx(p)
        except (zipfile.BadZipFile, KeyError):
            return soffice(p, "txt:Text (encoded):UTF8", "txt")
    if ext in (".doc", ".rtf", ".odt"):
        return soffice(p, "txt:Text (encoded):UTF8", "txt")
    if ext == ".pdf":
        return from_pdf(p)
    if ext in (".html", ".htm"):
        return from_html(p)
    if ext in (".xlsx", ".xls", ".ods"):
        return soffice(p, "csv:Text - txt - csv (StarCalc):44,34,76", "csv")
    if ext in (".txt", ".csv", ".xml", ".json"):
        return read_text_any(p)
    raise RuntimeError(f"формат {ext or 'без расширения'} не поддержан — открыть вручную")


def tidy(t):
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip() + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if not a.folder.is_dir():
        print(f"нет папки {a.folder}", file=sys.stderr)
        return 2
    out = a.out or a.folder / "txt"
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(f for f in a.folder.iterdir() if f.is_file() and f.name not in SKIP)
    bad = 0
    for f in files:
        try:
            t = tidy(extract(f))
            (out / (f.stem + ".txt")).write_text(t, encoding="utf-8")
            n = len(t.strip())
            if n < 50:
                bad += 1
                print(f"empty\t{n}\t{f.name}\tтекста почти нет (скан?) — открыть вручную")
            else:
                print(f"ok\t{n}\t{f.name}")
        except Exception as e:  # один плохой файл не останавливает остальные
            bad += 1
            print(f"error\t0\t{f.name}\t{e}")
    print(f"итого: файлов {len(files)}, с проблемами {bad}, тексты в {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
