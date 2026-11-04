#!/usr/bin/env python3
"""Загрузчик документов тендеров из папки «Сток» в «Бланки».

Требования: Python 3.10+, пакет requests. Опционально PyYAML для config.yaml / .yml.

Использование:
    python stock_docs_fetcher.py [--config PATH] [--once]

Без --once работает в цикле (интервал scan_interval_sec). Ctrl+C — чистый выход.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import mimetypes
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, IO
from urllib.parse import unquote, urlparse

import requests

try:
    # сертификаты zakupki.gov.ru выданы российским УЦ: берём доверенные корни из хранилища windows
    import truststore

    truststore.inject_into_ssl()
except Exception:
    truststore = None

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_NAME = "config.json"
STATUS_FILENAME = "docs_status.json"
TENDER_JSON = "tender.json"
TENDER_MD = "tender.md"
RESERVED_FILENAMES = {TENDER_JSON, TENDER_MD, STATUS_FILENAME}
WIN_RESERVED_STEMS = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
MULTI_SPACE = re.compile(r"\s+")
PLAUSIBLE_EXT = re.compile(r"(\.[A-Za-z0-9]{1,5})$")
KNOWN_EXTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".rtf",
    ".zip",
    ".rar",
    ".7z",
    ".sig",
    ".html",
    ".htm",
    ".odt",
    ".ods",
    ".txt",
    ".jpg",
    ".png",
    ".tif",
    ".xml",
}
HTML_EXTS = {".html", ".htm"}
HTML_MIME_TYPES = {"text/html", "application/xhtml+xml"}
GENERIC_PAGE_EXTS = {".html", ".htm", ".php", ".aspx", ".jsp", ".do"}
OCTET_STREAM_TYPES = {"application/octet-stream", "binary/octet-stream"}
ERROR_NOT_SAME_DEVICE = 17
EMPTY_STOCK_LOG_INTERVAL_SEC = 3600.0
NO_DOCUMENTS_ERROR = "нет документов в tender.json"
HTML_INSTEAD_OF_FILE = "получена html-страница вместо файла"
FILENAME_STAR = re.compile(
    r"filename\*\s*=\s*([^']+)'[^']*'([^;]+)",
    re.IGNORECASE,
)
FILENAME_QUOTED = re.compile(
    r'filename\s*=\s*"((?:\\.|[^"])*)"',
    re.IGNORECASE,
)
FILENAME_PLAIN = re.compile(
    r"filename\s*=\s*([^;]+)",
    re.IGNORECASE,
)
MAX_NAME_LEN = 150
MOVE_TRIES = 5
CHUNK_SIZE = 64 * 1024
ERROR_TEXT_LIMIT = 500

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.7390.122 Safari/537.36"
)

MIME_TO_EXT = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-rar-compressed": ".rar",
    "application/vnd.rar": ".rar",
    "application/x-7z-compressed": ".7z",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "text/plain": ".txt",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/octet-stream": "",
    "binary/octet-stream": "",
    "application/pkcs7-signature": ".sig",
    "application/x-pkcs7-signature": ".sig",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "application/xml": ".xml",
    "text/xml": ".xml",
}

LOGGER = logging.getLogger("stock_docs_fetcher")
CONSOLE = logging.getLogger("stock_docs_fetcher.console")


class ConfigError(Exception):
    """Некорректный или отсутствующий конфиг."""


class DownloadError(Exception):
    """Ошибка загрузки одного документа."""

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class SafeStreamHandler(logging.StreamHandler):
    """Консольный обработчик, который не падает на cp866/cp1251."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        return

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            return


@dataclass
class Config:
    stock_dir: Path
    blanks_dir: Path
    scan_interval_sec: float = 60.0
    download_pause_sec: float = 3.0
    request_timeout_sec: float = 60.0
    http_retries: int = 3
    retry_backoff_sec: float = 5.0
    max_file_size_mb: float = 200.0
    retry_delay_min: float = 30.0
    max_attempts: int = 5
    user_agent: str = DEFAULT_USER_AGENT
    log_file: Path = SCRIPT_DIR / "stock_docs_fetcher.log"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backups: int = 5
    lock_file: Path = SCRIPT_DIR / "stock_docs_fetcher.lock"
    verify_ssl: bool = True
    ssl_fallback_hosts: tuple[str, ...] = ("zakupki.gov.ru",)

    @property
    def max_file_bytes(self) -> int:
        return int(self.max_file_size_mb * 1024 * 1024)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


def now_local() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def now_iso() -> str:
    return now_local().isoformat()


def parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now_local().tzinfo)
    return dt


def truncate_error(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > ERROR_TEXT_LIMIT:
        return text[: ERROR_TEXT_LIMIT - 1] + "…"
    return text


def resolve_path(raw: str, base_dir: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _as_float(data: dict[str, Any], key: str, default: float) -> float:
    if key not in data or data[key] is None:
        return default
    try:
        return float(data[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Ключ {key!r} должен быть числом") from exc


def _as_int(data: dict[str, Any], key: str, default: int) -> int:
    return int(_as_float(data, key, float(default)))


def _as_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"Ключ {key!r} должен быть true/false")


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(
            f"Нет файла конфигурации: {path}. "
            f"Скопируйте config.example.json в {path.name} и заполните пути."
        )
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"Не удалось прочитать конфиг {path}: {exc}") from exc

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ConfigError(
                "Для YAML-конфига установите PyYAML: pip install pyyaml"
            ) from exc
        data = yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Некорректный JSON конфига {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Конфиг должен быть объектом (словарём ключей)")

    stock = data.get("stock_dir")
    blanks = data.get("blanks_dir")
    if not stock or not blanks:
        raise ConfigError("В конфиге обязательны ключи stock_dir и blanks_dir")

    cfg_dir = path.parent.resolve()
    log_file = data.get("log_file") or "stock_docs_fetcher.log"
    lock_file = data.get("lock_file") or "stock_docs_fetcher.lock"
    ua = data.get("user_agent") or DEFAULT_USER_AGENT

    return Config(
        stock_dir=resolve_path(str(stock), cfg_dir),
        blanks_dir=resolve_path(str(blanks), cfg_dir),
        scan_interval_sec=_as_float(data, "scan_interval_sec", 60.0),
        download_pause_sec=_as_float(data, "download_pause_sec", 3.0),
        request_timeout_sec=_as_float(data, "request_timeout_sec", 60.0),
        http_retries=_as_int(data, "http_retries", 3),
        retry_backoff_sec=_as_float(data, "retry_backoff_sec", 5.0),
        max_file_size_mb=_as_float(data, "max_file_size_mb", 200.0),
        retry_delay_min=_as_float(data, "retry_delay_min", 30.0),
        max_attempts=_as_int(data, "max_attempts", 5),
        user_agent=str(ua),
        log_file=resolve_path(str(log_file), SCRIPT_DIR),
        log_max_bytes=_as_int(data, "log_max_bytes", 5 * 1024 * 1024),
        log_backups=_as_int(data, "log_backups", 5),
        lock_file=resolve_path(str(lock_file), SCRIPT_DIR),
        verify_ssl=_as_bool(data, "verify_ssl", True),
        ssl_fallback_hosts=tuple(
            str(h).lower().strip() for h in (data.get("ssl_fallback_hosts") or ["zakupki.gov.ru"]) if str(h).strip()
        ),
    )


def setup_logging(cfg: Config) -> None:
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.handlers.clear()
    LOGGER.propagate = False

    file_handler = RotatingFileHandler(
        cfg.log_file,
        maxBytes=max(cfg.log_max_bytes, 1024),
        backupCount=max(cfg.log_backups, 0),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    LOGGER.addHandler(file_handler)

    CONSOLE.setLevel(logging.INFO)
    CONSOLE.handlers.clear()
    CONSOLE.propagate = False
    console_handler = SafeStreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    CONSOLE.addHandler(console_handler)

    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    if not cfg.verify_ssl:
        LOGGER.warning("verify_ssl=false: проверка сертификатов отключена")


def console_line(message: str) -> None:
    CONSOLE.info(message)
    LOGGER.info("%s", message)


def acquire_lock(lock_path: Path) -> IO[bytes] | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(lock_path, "a+b")
    except OSError as exc:
        print(f"Не удалось открыть lock-файл {lock_path}: {exc}", file=sys.stderr)
        return None
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n".encode("ascii", errors="replace"))
        handle.flush()
    except OSError:
        pass
    return handle


def sanitize_filename_value(name: str) -> str:
    cleaned = INVALID_NAME_CHARS.sub("", name)
    cleaned = MULTI_SPACE.sub(" ", cleaned).strip()
    cleaned = cleaned.rstrip(" .")
    stem_only, _ext = os.path.splitext(cleaned)
    check = stem_only if stem_only else cleaned
    if check.upper() in WIN_RESERVED_STEMS:
        cleaned = "_" + cleaned
    return cleaned


def sanitize_stem(name: str, fallback: str) -> str:
    cleaned = sanitize_filename_value(name)
    if not cleaned:
        cleaned = fallback
        cleaned = sanitize_filename_value(cleaned) or fallback
    return cleaned


def split_known_ext(name: str) -> tuple[str, str]:
    match = PLAUSIBLE_EXT.search(name)
    if not match:
        return name, ""
    ext = match.group(1).lower()
    if ext not in KNOWN_EXTS:
        return name, ""
    return name[: match.start()], ext


def limit_filename(stem: str, ext: str) -> str:
    if ext and not ext.startswith("."):
        ext = "." + ext
    ext = ext.lower() if ext else ""
    max_stem = MAX_NAME_LEN - len(ext)
    if max_stem < 1:
        max_stem = 1
    stem = stem[:max_stem].rstrip(" .")
    if not stem:
        stem = "document"
    if stem.upper() in WIN_RESERVED_STEMS:
        stem = "_" + stem
        stem = stem[:max_stem].rstrip(" .")
    return stem + ext


def make_unique(filename: str, used: set[str]) -> str:
    used_lower = {item.lower() for item in used}
    if filename.lower() not in used_lower:
        return filename
    stem, ext = os.path.splitext(filename)
    n = 2
    while True:
        candidate = f"{stem} ({n}){ext}"
        if candidate.lower() not in used_lower:
            return candidate
        n += 1


def _fix_mojibake(value: str) -> str:
    try:
        raw = value.encode("latin-1")
    except UnicodeEncodeError:
        return value
    for encoding in ("utf-8", "cp1251"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded != value:
            return decoded
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return value


def parse_content_disposition_filename(header: str | None) -> str | None:
    if not header:
        return None
    star = FILENAME_STAR.search(header)
    if star:
        charset = star.group(1).strip().strip('"') or "utf-8"
        raw_value = star.group(2).strip().strip('"')
        try:
            return unquote(raw_value, encoding=charset, errors="replace")
        except LookupError:
            return unquote(raw_value, encoding="utf-8", errors="replace")
    quoted = FILENAME_QUOTED.search(header)
    if quoted:
        return _fix_mojibake(quoted.group(1).replace('\\"', '"').replace("\\\\", "\\"))
    plain = FILENAME_PLAIN.search(header)
    if plain:
        return _fix_mojibake(plain.group(1).strip().strip('"'))
    return None


def extension_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    _stem, ext = split_known_ext(os.path.basename(path))
    if ext in GENERIC_PAGE_EXTS:
        return ""
    return ext


def extension_from_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in OCTET_STREAM_TYPES:
        return ""
    if mime in MIME_TO_EXT:
        return MIME_TO_EXT[mime]
    guessed = mimetypes.guess_extension(mime) or ""
    if guessed == ".htm":
        return ".html"
    if guessed == ".jpe":
        return ".jpg"
    return guessed


def cd_extension(content_disposition: str | None, fallback: str) -> str:
    cd_name = parse_content_disposition_filename(content_disposition)
    if not cd_name:
        return ""
    _stem, ext = split_known_ext(sanitize_stem(cd_name, fallback))
    return ext


def decide_filename(
    *,
    doc_name: str,
    index: int,
    url: str,
    response: requests.Response,
    used: set[str],
    stored: str | None,
) -> str:
    if stored:
        return stored
    fallback = f"document_{index + 1}"
    raw_name = (doc_name or "").strip() or fallback
    cleaned = sanitize_stem(raw_name, fallback)
    stem, ext = split_known_ext(cleaned)
    if not ext:
        ext = cd_extension(response.headers.get("Content-Disposition"), fallback)
        if not ext:
            ext = extension_from_content_type(response.headers.get("Content-Type"))
        if not ext:
            ext = extension_from_url(url)
        if not ext:
            ext = ".bin"
    filename = limit_filename(stem, ext)
    filename = make_unique(filename, used | RESERVED_FILENAMES)
    return filename


def html_should_be_rejected(
    doc_name: str,
    url: str,
    content_disposition: str | None,
) -> bool:
    fallback = "document"
    cleaned = sanitize_stem((doc_name or "").strip() or fallback, fallback)
    _stem, name_ext = split_known_ext(cleaned)
    if name_ext in HTML_EXTS:
        return False
    if name_ext:
        return True
    derived = cd_extension(content_disposition, fallback) or extension_from_url(url)
    if derived and derived not in HTML_EXTS:
        return True
    return False


def content_type_is_html(content_type: str | None) -> bool:
    if not content_type:
        return False
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime in HTML_MIME_TYPES


def body_looks_like_html(data: bytes) -> bool:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    data = data.lstrip(b" \t\r\n")
    head = data[:64].lower()
    return head.startswith(b"<html") or head.startswith(b"<!doctype")


def is_relative_inside(folder: Path, stored: str) -> bool:
    try:
        folder_r = folder.resolve()
        file_r = (folder / stored).resolve()
        file_r.relative_to(folder_r)
    except (OSError, ValueError):
        return False
    return file_r != folder_r


def safe_stored_filename(folder: Path, stored: Any) -> str | None:
    if not isinstance(stored, str) or not stored or stored in {".", ".."}:
        return None
    if "/" in stored or "\\" in stored:
        return None
    if os.sep in stored or (os.altsep and os.altsep in stored):
        return None
    if Path(stored).name != stored:
        return None
    if stored.lower() in {name.lower() for name in RESERVED_FILENAMES}:
        return None
    if sanitize_filename_value(stored) != stored:
        return None
    if not is_relative_inside(folder, stored):
        return None
    return stored


def take_stored_filename(folder: Path, stored: Any, *, warn: bool) -> str | None:
    if not stored:
        return None
    safe = safe_stored_filename(folder, stored)
    if safe is None and warn:
        LOGGER.warning(
            "%s: некорректное имя файла в статусе, игнорирую: %r",
            folder.name,
            stored,
        )
    return safe


def scrub_stored_files(folder: Path, documents: list[dict[str, Any]]) -> None:
    for rec in documents:
        stored = rec.get("file")
        if not stored:
            rec["file"] = None
            continue
        safe = take_stored_filename(folder, stored, warn=True)
        rec["file"] = safe
        if safe is None and rec.get("status") == "ok":
            rec["status"] = "error"
            rec["error"] = "некорректное имя файла в статусе"


def without_updated_at(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "updated_at"}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def load_status(folder: Path) -> dict[str, Any] | None:
    path = folder / STATUS_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("%s: не удалось прочитать %s (%s), начинаем заново", folder.name, STATUS_FILENAME, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def read_tender(folder: Path) -> tuple[str, dict[str, Any] | None]:
    path = folder / TENDER_JSON
    if not path.is_file():
        return "missing", None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "invalid", None
    if not isinstance(data, dict):
        return "invalid", None
    return "ok", data


def empty_status(number: str, max_attempts: int) -> dict[str, Any]:
    return {
        "number": number,
        "state": "pending",
        "attempts": 0,
        "max_attempts": max_attempts,
        "last_attempt_at": None,
        "next_attempt_after": None,
        "updated_at": now_iso(),
        "error": None,
        "documents": [],
    }


def merge_documents(
    tender_docs: list[Any],
    prev: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    prev_list = []
    if prev and isinstance(prev.get("documents"), list):
        prev_list = [d for d in prev["documents"] if isinstance(d, dict)]
    by_index = {d.get("index"): d for d in prev_list if isinstance(d.get("index"), int)}
    by_url: dict[str, dict[str, Any]] = {}
    for item in prev_list:
        url = item.get("url")
        if isinstance(url, str) and url and url not in by_url:
            by_url[url] = item

    merged: list[dict[str, Any]] = []
    for i, raw in enumerate(tender_docs):
        doc = raw if isinstance(raw, dict) else {}
        name = doc.get("name") if isinstance(doc.get("name"), str) else ""
        url = doc.get("url") if isinstance(doc.get("url"), str) else ""
        prev_doc = by_index.get(i)
        if not prev_doc or prev_doc.get("url") != url:
            prev_doc = by_url.get(url)
        merged.append(
            {
                "index": i,
                "name": name,
                "url": url,
                "file": prev_doc.get("file") if prev_doc else None,
                "size": prev_doc.get("size") if prev_doc else None,
                "status": prev_doc.get("status") if prev_doc else "error",
                "error": prev_doc.get("error") if prev_doc else None,
                "attempts": int(prev_doc.get("attempts") or 0) if prev_doc else 0,
                "http_status": prev_doc.get("http_status") if prev_doc else None,
            }
        )
    return merged


def file_is_ok(folder: Path, rec: dict[str, Any]) -> bool:
    if rec.get("status") != "ok":
        return False
    filename = safe_stored_filename(folder, rec.get("file"))
    if not filename:
        return False
    path = folder / filename
    if not path.is_file():
        return False
    size = rec.get("size")
    if size is None:
        return True
    try:
        return path.stat().st_size == int(size)
    except (TypeError, ValueError, OSError):
        return False


def remove_stale_parts(folder: Path) -> None:
    for part in folder.glob("*.part"):
        try:
            part.unlink()
            LOGGER.debug("%s: удалён незавершённый файл %s", folder.name, part.name)
        except OSError as exc:
            LOGGER.warning("%s: не удалось удалить %s: %s", folder.name, part.name, exc)


def is_busy_oserror(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if winerror in (5, 32):
            return True
        if exc.errno in {errno.EACCES, errno.EPERM, errno.EBUSY, errno.EAGAIN}:
            return True
    return False


def move_folder(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    last_exc: BaseException | None = None
    for attempt in range(MOVE_TRIES):
        if dst.exists():
            LOGGER.warning("Перенос %s: цель уже есть %s", src.name, dst)
            raise FileExistsError(dst)
        try:
            os.rename(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            if dst.exists():
                LOGGER.warning("Перенос %s: цель уже есть %s", src.name, dst)
                raise FileExistsError(dst) from exc
            winerror = getattr(exc, "winerror", None)
            if exc.errno == errno.EXDEV or winerror == ERROR_NOT_SAME_DEVICE:
                if dst.exists():
                    LOGGER.warning("Перенос %s: цель уже есть %s", src.name, dst)
                    raise FileExistsError(dst) from exc
                shutil.move(str(src), str(dst))
                return
            if not is_busy_oserror(exc) or attempt >= MOVE_TRIES - 1:
                raise
            delay = 2 * (2 ** attempt)
            LOGGER.warning(
                "Перенос %s заблокирован (%s), повтор через %s с",
                src.name,
                exc,
                delay,
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc


class Fetcher:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._warned_blanks: set[str] = set()
        self._invalid_tender_logged: set[str] = set()
        self._last_empty_stock_log: float | None = None
        self._need_download_pause = False
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "application/pdf,application/octet-stream,*/*;q=0.8"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Connection": "keep-alive",
            }
        )
        self.timeout = (cfg.request_timeout_sec, cfg.request_timeout_sec)
        self._ssl_fallback_warned: set[str] = set()
        # ручной проход --once не ждёт паузу между попытками
        self.ignore_retry_delay = False

    def close(self) -> None:
        self.session.close()

    def run_loop(self) -> None:
        LOGGER.info(
            "Запуск цикла: Сток=%s Бланки=%s интервал=%s с",
            self.cfg.stock_dir,
            self.cfg.blanks_dir,
            self.cfg.scan_interval_sec,
        )
        while True:
            try:
                self.scan_once(announce_idle=False)
            except KeyboardInterrupt:
                raise
            except Exception:
                # фоновый режим без окна: падать нельзя, следующий круг через интервал
                LOGGER.exception("сбой прохода по Стоку")
            time.sleep(self.cfg.scan_interval_sec)

    def scan_once(self, announce_idle: bool = True) -> int:
        stock = self.cfg.stock_dir
        if not stock.is_dir():
            LOGGER.warning("Папка Стока недоступна: %s", stock)
            if announce_idle:
                console_line("Нечего обрабатывать.")
            return 0

        try:
            entries = sorted(
                (p for p in stock.iterdir() if p.is_dir()),
                key=lambda p: p.name,
            )
        except OSError as exc:
            LOGGER.warning("Не удалось прочитать Сток %s: %s", stock, exc)
            if announce_idle:
                console_line("Нечего обрабатывать.")
            return 0

        if not entries:
            now = time.monotonic()
            last = self._last_empty_stock_log
            if last is None or now - last >= EMPTY_STOCK_LOG_INTERVAL_SEC:
                LOGGER.debug("Сток пуст, нечего делать")
                self._last_empty_stock_log = now
            if announce_idle:
                console_line("Нечего обрабатывать.")
            return 0

        if announce_idle:
            console_line(f"В Стоке папок: {len(entries)}")
        processed = 0
        for folder in entries:
            try:
                if self.process_folder(folder):
                    processed += 1
            except KeyboardInterrupt:
                raise
            except Exception:
                LOGGER.exception("%s: неожиданная ошибка обработки", folder.name)
                try:
                    self._record_unexpected_failure(folder)
                    processed += 1
                except Exception:
                    LOGGER.exception("%s: не удалось записать статус после сбоя", folder.name)
        if announce_idle and processed == 0:
            console_line("Нечего обрабатывать.")
        return processed

    def process_folder(self, folder: Path) -> bool:
        name = folder.name
        dest = self.cfg.blanks_dir / name
        prev = load_status(folder)

        if dest.exists():
            self._handle_exists_in_blanks(folder, prev)
            return True

        if prev and prev.get("state") == "failed":
            return False

        kind, tender = read_tender(folder)
        if kind != "ok" or tender is None:
            if name not in self._invalid_tender_logged:
                self._invalid_tender_logged.add(name)
                if kind == "missing":
                    LOGGER.info("%s: нет tender.json, пропуск", name)
                else:
                    LOGGER.info("%s: tender.json не читается, пропуск", name)
            return False
        self._invalid_tender_logged.discard(name)

        docs = tender.get("documents")
        if not isinstance(docs, list) or len(docs) == 0:
            return self._record_no_documents(folder, prev, tender)

        number = str(tender.get("number") or name)
        status = prev if prev else empty_status(number, self.cfg.max_attempts)
        status["number"] = number
        status["max_attempts"] = self.cfg.max_attempts
        status["error"] = None
        status["documents"] = merge_documents(docs, prev)
        scrub_stored_files(folder, status["documents"])

        all_ok = all(file_is_ok(folder, rec) for rec in status["documents"])
        if all_ok:
            return self._finish_and_move(folder, status)

        next_after = parse_iso(status.get("next_attempt_after"))
        if next_after and now_local() < next_after and not self.ignore_retry_delay:
            LOGGER.debug("%s: ещё рано, следующая попытка после %s", name, next_after.isoformat())
            return False

        return self._attempt_downloads(folder, status)

    def _handle_exists_in_blanks(self, folder: Path, prev: dict[str, Any] | None) -> None:
        name = folder.name
        status = dict(prev) if prev else empty_status(name, self.cfg.max_attempts)
        status["number"] = status.get("number") or name
        status["state"] = "skipped_exists_in_blanks"
        if "documents" not in status or not isinstance(status["documents"], list):
            status["documents"] = []
        prev_cmp = without_updated_at(prev) if prev else None
        new_cmp = without_updated_at(status)
        if prev_cmp != new_cmp:
            status["updated_at"] = now_iso()
            try:
                atomic_write_json(folder / STATUS_FILENAME, status)
            except OSError as exc:
                LOGGER.warning("%s: не удалось записать статус пропуска: %s", name, exc)
        if name not in self._warned_blanks:
            self._warned_blanks.add(name)
            stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
            console_line(f"[{stamp}] {name}: пропуск, уже есть в Бланках")
            LOGGER.warning("%s: папка уже есть в Бланках, не перезаписываю", name)

    def _write_status(self, folder: Path, status: dict[str, Any]) -> None:
        status["updated_at"] = now_iso()
        atomic_write_json(folder / STATUS_FILENAME, status)

    def _finish_and_move(self, folder: Path, status: dict[str, Any]) -> bool:
        status["state"] = "done"
        status["next_attempt_after"] = None
        self._write_status(folder, status)
        dest = self.cfg.blanks_dir / folder.name
        try:
            move_folder(folder, dest)
        except FileExistsError:
            self._handle_exists_in_blanks(folder, status)
            return True
        except OSError as exc:
            LOGGER.error("%s: не удалось перенести в Бланки: %s", folder.name, exc)
            stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
            ok = sum(1 for rec in status["documents"] if rec.get("status") == "ok")
            total = len(status["documents"])
            console_line(
                f"[{stamp}] {folder.name}: {ok}/{total} ok, ошибка переноса в Бланки"
            )
            return True
        stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
        total = len(status["documents"])
        console_line(f"[{stamp}] {folder.name}: {total}/{total} ok -> Бланки")
        LOGGER.info("%s: перенесён в %s", folder.name, dest)
        return True

    def _attempt_downloads(self, folder: Path, status: dict[str, Any]) -> bool:
        remove_stale_parts(folder)
        status["attempts"] = int(status.get("attempts") or 0) + 1
        status["last_attempt_at"] = now_iso()
        status["state"] = "pending"

        used_names: set[str] = set()
        for rec in status["documents"]:
            stored = take_stored_filename(folder, rec.get("file"), warn=False)
            rec["file"] = stored
            if stored:
                used_names.add(stored)

        total_docs = len(status["documents"])
        for idx, rec in enumerate(status["documents"], 1):
            if file_is_ok(folder, rec):
                stored = rec.get("file")
                if isinstance(stored, str) and stored:
                    used_names.add(stored)
                continue
            console_line(f"  {folder.name}: {idx}/{total_docs} качаю {rec.get('name') or rec.get('url')}")
            try:
                self._pause_before_download()
                filename, size, http_status = self._download_one(folder, rec, used_names)
                rec["file"] = filename
                rec["size"] = size
                rec["status"] = "ok"
                rec["error"] = None
                rec["http_status"] = http_status
                rec["attempts"] = int(rec.get("attempts") or 0) + 1
                used_names.add(filename)
                console_line(f"    ok, {size} байт")
                self._write_status(folder, status)
            except DownloadError as exc:
                rec["status"] = "error"
                rec["error"] = truncate_error(str(exc))
                rec["http_status"] = exc.http_status
                rec["attempts"] = int(rec.get("attempts") or 0) + 1
                console_line(f"    ошибка: {exc}")
                LOGGER.warning("%s: документ %s: %s", folder.name, rec.get("name"), exc)
                self._write_status(folder, status)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                rec["status"] = "error"
                rec["error"] = truncate_error(f"{type(exc).__name__}: {exc}")
                rec["attempts"] = int(rec.get("attempts") or 0) + 1
                console_line(f"    сбой: {type(exc).__name__}: {exc}")
                LOGGER.exception("%s: сбой документа %s", folder.name, rec.get("name"))
                self._write_status(folder, status)

        ok_count = sum(1 for rec in status["documents"] if file_is_ok(folder, rec))
        total = len(status["documents"])
        if ok_count == total:
            return self._finish_and_move(folder, status)

        attempts = int(status["attempts"])
        max_attempts = self.cfg.max_attempts
        stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
        if attempts >= max_attempts:
            status["state"] = "failed"
            status["next_attempt_after"] = None
            self._write_status(folder, status)
            console_line(
                f"[{stamp}] {folder.name}: {ok_count}/{total} ok, "
                f"ошибка (попытка {attempts}/{max_attempts}), провал"
            )
            LOGGER.error("%s: исчерпаны попытки (%s), папка больше не берётся", folder.name, attempts)
            return True

        nxt = now_local() + timedelta(minutes=self.cfg.retry_delay_min)
        status["state"] = "pending"
        status["next_attempt_after"] = nxt.isoformat()
        self._write_status(folder, status)
        console_line(
            f"[{stamp}] {folder.name}: {ok_count}/{total} ok, ошибка "
            f"(попытка {attempts}/{max_attempts}), следующая после {nxt.strftime('%H:%M')}"
        )
        return True

    def _record_no_documents(
        self,
        folder: Path,
        prev: dict[str, Any] | None,
        tender: dict[str, Any],
    ) -> bool:
        number = str(tender.get("number") or folder.name)
        status = prev if prev else empty_status(number, self.cfg.max_attempts)
        status["number"] = number
        status["max_attempts"] = self.cfg.max_attempts
        next_after = parse_iso(status.get("next_attempt_after"))
        if next_after and now_local() < next_after and not self.ignore_retry_delay:
            LOGGER.debug(
                "%s: ещё рано, следующая попытка после %s",
                folder.name,
                next_after.isoformat(),
            )
            return False
        status["error"] = NO_DOCUMENTS_ERROR
        status["documents"] = []
        status["attempts"] = int(status.get("attempts") or 0) + 1
        status["last_attempt_at"] = now_iso()
        attempts = int(status["attempts"])
        max_attempts = self.cfg.max_attempts
        stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
        LOGGER.warning("%s: %s", folder.name, NO_DOCUMENTS_ERROR)
        if attempts >= max_attempts:
            status["state"] = "failed"
            status["next_attempt_after"] = None
            self._write_status(folder, status)
            console_line(
                f"[{stamp}] {folder.name}: 0/0 ok, "
                f"ошибка (попытка {attempts}/{max_attempts}), провал"
            )
            LOGGER.error("%s: исчерпаны попытки (%s), папка больше не берётся", folder.name, attempts)
            return True
        nxt = now_local() + timedelta(minutes=self.cfg.retry_delay_min)
        status["state"] = "pending"
        status["next_attempt_after"] = nxt.isoformat()
        self._write_status(folder, status)
        console_line(
            f"[{stamp}] {folder.name}: 0/0 ok, ошибка "
            f"(попытка {attempts}/{max_attempts}), следующая после {nxt.strftime('%H:%M')}"
        )
        return True

    def _record_unexpected_failure(self, folder: Path) -> None:
        prev = load_status(folder)
        number = folder.name
        status = prev if prev else empty_status(number, self.cfg.max_attempts)
        if status.get("state") == "failed":
            stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
            console_line(
                f"[{stamp}] {folder.name}: неожиданная ошибка, папка уже в провале"
            )
            return
        status["attempts"] = int(status.get("attempts") or 0) + 1
        status["last_attempt_at"] = now_iso()
        status["max_attempts"] = self.cfg.max_attempts
        attempts = int(status["attempts"])
        if attempts >= self.cfg.max_attempts:
            status["state"] = "failed"
            status["next_attempt_after"] = None
        else:
            status["state"] = "pending"
            nxt = now_local() + timedelta(minutes=self.cfg.retry_delay_min)
            status["next_attempt_after"] = nxt.isoformat()
        self._write_status(folder, status)
        stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
        ok = sum(
            1
            for rec in status.get("documents") or []
            if isinstance(rec, dict) and rec.get("status") == "ok"
        )
        total = len(status.get("documents") or [])
        if status["state"] == "failed":
            console_line(
                f"[{stamp}] {folder.name}: {ok}/{total} ok, "
                f"ошибка (попытка {attempts}/{self.cfg.max_attempts}), провал"
            )
        else:
            nxt_s = parse_iso(status.get("next_attempt_after"))
            hhmm = nxt_s.strftime("%H:%M") if nxt_s else "?"
            console_line(
                f"[{stamp}] {folder.name}: {ok}/{total} ok, ошибка "
                f"(попытка {attempts}/{self.cfg.max_attempts}), следующая после {hhmm}"
            )

    def _pause_before_download(self) -> None:
        if self._need_download_pause and self.cfg.download_pause_sec > 0:
            time.sleep(self.cfg.download_pause_sec)
        self._need_download_pause = True

    def _download_one(
        self,
        folder: Path,
        rec: dict[str, Any],
        used_names: set[str],
    ) -> tuple[str, int, int | None]:
        url = rec.get("url")
        if not url:
            raise DownloadError("нет url")
        response = self._get_with_retry(url)
        try:
            status_code = response.status_code
            if status_code in {403, 404}:
                raise DownloadError(f"HTTP {status_code}", http_status=status_code)
            if status_code == 429 or status_code >= 500:
                raise DownloadError(f"HTTP {status_code}", http_status=status_code)
            if status_code >= 400:
                raise DownloadError(f"HTTP {status_code}", http_status=status_code)

            stored = take_stored_filename(folder, rec.get("file"), warn=False)
            filename = decide_filename(
                doc_name=str(rec.get("name") or ""),
                index=int(rec.get("index") or 0),
                url=url,
                response=response,
                used=used_names,
                stored=stored,
            )
            reject_html = html_should_be_rejected(
                str(rec.get("name") or ""),
                url,
                response.headers.get("Content-Disposition"),
            )
            if reject_html and content_type_is_html(response.headers.get("Content-Type")):
                raise DownloadError(HTML_INSTEAD_OF_FILE, http_status=status_code)

            content_length = _identity_content_length(response)
            if content_length is not None and content_length > self.cfg.max_file_bytes:
                raise DownloadError(
                    f"файл больше лимита {self.cfg.max_file_size_mb:g} МБ "
                    f"(Content-Length {content_length})",
                    http_status=status_code,
                )

            part_path = folder / f"{filename}.part"
            final_path = folder / filename
            written = 0
            try:
                chunks = response.iter_content(chunk_size=CHUNK_SIZE)
                first = b""
                for chunk in chunks:
                    if chunk:
                        first = chunk
                        break
                if reject_html and first and body_looks_like_html(first):
                    raise DownloadError(HTML_INSTEAD_OF_FILE, http_status=status_code)
                with part_path.open("wb") as fh:
                    if first:
                        written += len(first)
                        if written > self.cfg.max_file_bytes:
                            raise DownloadError(
                                f"файл больше лимита {self.cfg.max_file_size_mb:g} МБ",
                                http_status=status_code,
                            )
                        fh.write(first)
                    for chunk in chunks:
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > self.cfg.max_file_bytes:
                            raise DownloadError(
                                f"файл больше лимита {self.cfg.max_file_size_mb:g} МБ",
                                http_status=status_code,
                            )
                        fh.write(chunk)
                if content_length is not None and written != content_length:
                    raise DownloadError(
                        f"размер {written} не совпал с Content-Length {content_length}",
                        http_status=status_code,
                    )
                os.replace(part_path, final_path)
            except Exception:
                try:
                    if part_path.exists():
                        part_path.unlink()
                except OSError:
                    pass
                raise
            return filename, written, status_code
        finally:
            response.close()

    def _get_with_retry(self, url: str) -> requests.Response:
        retries = max(self.cfg.http_retries, 0)
        last_exc: BaseException | None = None
        last_response: requests.Response | None = None
        host = (urlparse(url).hostname or "").lower()
        verify = self.cfg.verify_ssl
        for attempt in range(retries + 1):
            try:
                try:
                    response = self.session.get(
                        url,
                        stream=True,
                        timeout=self.timeout,
                        verify=verify,
                        allow_redirects=True,
                    )
                except requests.exceptions.SSLError:
                    fallback = any(host == h or host.endswith("." + h) for h in self.cfg.ssl_fallback_hosts)
                    if not verify or not fallback:
                        raise
                    if host not in self._ssl_fallback_warned:
                        self._ssl_fallback_warned.add(host)
                        LOGGER.warning("%s: сертификат не проверяется (российский УЦ), качаю без проверки", host)
                    verify = False
                    response = self.session.get(
                        url,
                        stream=True,
                        timeout=self.timeout,
                        verify=False,
                        allow_redirects=True,
                    )
                code = response.status_code
                if code in {403, 404}:
                    return response
                if code == 429 or code >= 500:
                    last_response = response
                    if attempt < retries:
                        response.close()
                        delay = self.cfg.retry_backoff_sec * (2 ** attempt)
                        LOGGER.info(
                            "HTTP %s для %s, повтор через %s с (%s/%s)",
                            code,
                            url,
                            delay,
                            attempt + 1,
                            retries,
                        )
                        time.sleep(delay)
                        continue
                    return response
                return response
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < retries:
                    delay = self.cfg.retry_backoff_sec * (2 ** attempt)
                    LOGGER.info(
                        "сеть/таймаут для %s: %s, повтор через %s с (%s/%s)",
                        url,
                        exc,
                        delay,
                        attempt + 1,
                        retries,
                    )
                    time.sleep(delay)
                    continue
                raise DownloadError(truncate_error(str(exc))) from exc
        if last_response is not None:
            return last_response
        raise DownloadError(truncate_error(str(last_exc or "ошибка запроса")))


def _identity_content_length(response: requests.Response) -> int | None:
    encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
    if encoding and encoding not in {"identity"}:
        return None
    raw = response.headers.get("Content-Length")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Загрузка документов тендеров из папки Сток в Бланки."
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=f"Путь к конфигу (по умолчанию {SCRIPT_DIR / DEFAULT_CONFIG_NAME})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Обработать текущие подходящие папки и выйти",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    config_path = Path(args.config) if args.config else SCRIPT_DIR / DEFAULT_CONFIG_NAME
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    lock_handle = acquire_lock(cfg.lock_file)
    if lock_handle is None:
        print(
            f"Уже запущен другой экземпляр (lock: {cfg.lock_file}). Выход.",
            file=sys.stderr,
        )
        return 2

    fetcher: Fetcher | None = None
    try:
        setup_logging(cfg)
        LOGGER.info("Конфиг: %s", config_path)
        fetcher = Fetcher(cfg)
        if args.once:
            fetcher.ignore_retry_delay = True
            fetcher.scan_once(announce_idle=True)
        else:
            fetcher.run_loop()
        return 0
    except KeyboardInterrupt:
        LOGGER.info("Остановка по Ctrl+C")
        return 0
    finally:
        if fetcher is not None:
            fetcher.close()
        try:
            lock_handle.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
