# создаёт config.json: ищет папки Сток и Бланки в Google Диске для компьютера
import json
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = HERE / "config.json"
EXAMPLE = HERE / "config.example.json"
ROOTS = ["Мой диск", "My Drive", r"Google Drive\Мой диск", r"Google Drive\My Drive"]


def ok(p: Path) -> bool:
    return (p / "Сток").is_dir() and (p / "Бланки").is_dir()


def find() -> Path | None:
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        for root in ROOTS:
            p = drive / root / "Госзакупки"
            try:
                if ok(p):
                    return p
            except OSError:
                pass
    home = Path.home()
    for root in ["Google Drive", "Мой диск", "My Drive"]:
        for sub in ["", "Мой диск", "My Drive"]:
            p = home / root / sub / "Госзакупки"
            if ok(p):
                return p
    return None


def main() -> int:
    if CFG.exists():
        cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
        print(f"настройки уже есть: Сток = {cfg.get('stock_dir')}")
        return 0
    base = find()
    if base is None:
        print("папку «Госзакупки» с «Сток» и «Бланки» не нашёл автоматически.")
        raw = input("вставьте путь к папке Госзакупки (например G:\\Мой диск\\Госзакупки): ").strip().strip('"')
        base = Path(raw)
        if not ok(base):
            print(f"в {base} нет папок «Сток» и «Бланки». проверьте путь и запустите снова.")
            return 1
    cfg = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
    cfg["stock_dir"] = str(base / "Сток")
    cfg["blanks_dir"] = str(base / "Бланки")
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"нашёл: {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
