#!/usr/bin/env bash
# самопроверка скриптов Фатимы. только локально, во временной папке; Drive и rclone не трогает.
# запуск: bash selftest.sh   (из любой папки). код 0 — всё прошло.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
EX="$HERE/../examples/0151100007126000034/tender.json"
[ -f "$EX" ] || EX="$HERE/examples/0151100007126000034/tender.json"
PY="${PYTHON:-python3}"
T="$(mktemp -d /tmp/fatima_selftest.XXXXXX)"
trap 'rm -rf "$T"' EXIT
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
expect() { # expect <имя> <ожидаемый код> <команда...>
  local name="$1" want="$2"; shift 2
  "$@" >"$T/out" 2>&1; local got=$?
  if [ "$got" = "$want" ]; then ok "$name"; else bad "$name (код $got, ждали $want)"; sed 's/^/     /' "$T/out"; fi
}

# --- check_ready.py
mk() { # mk <папка> <state> <error-json> <status второго документа>
  mkdir -p "$T/$1"; echo x >"$T/$1/a.doc"; echo x >"$T/$1/b.pdf"
  cat >"$T/$1/docs_status.json" <<J
{"number":"$1","state":"$2","error":$3,"documents":[
 {"index":0,"name":"a","file":"a.doc","status":"ok","error":null},
 {"index":1,"name":"b","file":"b.pdf","status":"$4","error":null}]}
J
}
mk 1000000001 done null ok
mk 1000000002 pending null ok
mk 1000000003 done null error
mk 1000000004 done '"нет документов в tender.json"' ok
mk 1000000005 done null ok; rm "$T/1000000005/b.pdf"
mkdir -p "$T/1000000006"
expect "check_ready: готовая папка" 0 "$PY" "$HERE/check_ready.py" "$T/1000000001"
expect "check_ready: state pending" 1 "$PY" "$HERE/check_ready.py" "$T/1000000002"
expect "check_ready: документ с ошибкой" 1 "$PY" "$HERE/check_ready.py" "$T/1000000003"
expect "check_ready: error на папку" 1 "$PY" "$HERE/check_ready.py" "$T/1000000004"
expect "check_ready: файла нет" 1 "$PY" "$HERE/check_ready.py" "$T/1000000005"
expect "check_ready: нет docs_status.json" 1 "$PY" "$HERE/check_ready.py" "$T/1000000006"
expect "check_ready: stdin" 0 sh -c "\"$PY\" \"$HERE/check_ready.py\" --status-file - < \"$T/1000000001/docs_status.json\""

# --- extract_text.py
D="$T/extract"; mkdir -p "$D"
cat >"$D/извещение.html" <<'H'
<html><head><style>p{}</style><script>var x=1;</script></head><body>
<h1>Извещение о проведении электронного аукциона</h1><table><tr><td>Место поставки</td><td>г. Новосибирск, ул. Тестовая, д. 1</td></tr></table>
<p>Окончание подачи заявок 16.11.2026 08:00</p></body></html>
H
"$PY" - "$D/описание.docx" <<'P'
import sys, zipfile
x = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
     '<w:p><w:r><w:t>Описание объекта закупки: перчатки резиновые, размер М, 380 пар. Допускается эквивалент.</w:t></w:r></w:p>'
     '</w:body></w:document>')
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("word/document.xml", x)
P
echo '{}' >"$D/tender.json"
expect "extract_text: html и docx" 0 "$PY" "$HERE/extract_text.py" "$D"
grep -q "ул. Тестовая" "$D/txt/извещение.txt" && ! grep -q "var x" "$D/txt/извещение.txt" && ok "extract_text: html без скриптов" || bad "extract_text: html"
grep -q "380 пар" "$D/txt/описание.txt" && ok "extract_text: docx" || bad "extract_text: docx"
[ ! -e "$D/txt/tender.txt" ] && ok "extract_text: tender.json пропущен" || bad "extract_text: tender.json не пропущен"
if command -v soffice >/dev/null 2>&1; then
  D2="$T/extract_doc"; mkdir -p "$D2"
  echo "Описание объекта закупки: перчатки резиновые, 380 пар." >"$T/opis.txt"
  soffice -env:UserInstallation=file://$T/lo --headless --convert-to 'doc:MS Word 97' --outdir "$T" "$T/opis.txt" >/dev/null 2>&1
  mv "$T/opis.doc" "$D2/описание.doc" 2>/dev/null
  if [ -f "$D2/описание.doc" ]; then
    expect "extract_text: .doc через soffice" 0 "$PY" "$HERE/extract_text.py" "$D2"
    grep -q "380 пар" "$D2/txt/описание.txt" && ok "extract_text: текст .doc" || bad "extract_text: текст .doc"
  else bad "soffice не сделал .doc для проверки"; fi
else echo "skip extract_text .doc: нет soffice"; fi
echo "не документ" >"$D/странный.xyz"
expect "extract_text: неизвестный формат = код 1" 1 "$PY" "$HERE/extract_text.py" "$D"

# --- validate_tender.py и render_md.py
expect "validate: образец" 0 "$PY" "$HERE/validate_tender.py" "$EX" --folder-name 0151100007126000034
"$PY" - "$EX" "$T/broken.json" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
d["items"] = []; d["category"] = "Где-то"; d["лишнее"] = 1; del d["nmck"]
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
P
expect "validate: сломанный = код 1" 1 "$PY" "$HERE/validate_tender.py" "$T/broken.json"
"$PY" - "$EX" "$T/warn.json" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
d["conditions"]["licenses_permits"] = "лицензия МЧС"; d["items"][0]["total_price"] = 1.0
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
P
"$PY" "$HERE/validate_tender.py" "$T/warn.json" >"$T/out" 2>&1; c=$?
[ $c = 0 ] && grep -q "не «С ограничениями»" "$T/out" && grep -q "не равна НМЦК" "$T/out" && ok "validate: предупреждения" || { bad "validate: предупреждения"; cat "$T/out"; }
expect "render_md" 0 "$PY" "$HERE/render_md.py" "$EX" -o "$T/tender.md"
grep -q "## Объекты закупки" "$T/tender.md" && grep -q "40 785,40 ₽" "$T/tender.md" && ok "render_md: содержимое" || bad "render_md: содержимое"

# --- counter.py
C="$T/счётчик.json"
printf '%s\n' "В городе/" "В городе/0151100007126000034/" "В городе/0151100007126000034/txt/" \
  "Загород/" "С ограничениями/" "С ограничениями/Лицензии/" "С ограничениями/Лицензии/32616501202/" \
  "С ограничениями/Опыт/" "С ограничениями/0351200003326001418/" >"$T/lsf.txt"
expect "counter: inc без файла = ошибка" 1 "$PY" "$HERE/counter.py" inc "$C" "Загород"
expect "counter: init" 0 sh -c "\"$PY\" \"$HERE/counter.py\" init \"$C\" < \"$T/lsf.txt\""
expect "counter: init второй раз не затирает" 1 sh -c "\"$PY\" \"$HERE/counter.py\" init \"$C\" < \"$T/lsf.txt\""
expect "counter: inc" 0 "$PY" "$HERE/counter.py" inc "$C" "Загород" --tz Europe/Berlin
"$PY" - "$C" <<'P' && ok "counter: значения 1/1/2" || bad "counter: значения"
import json, re, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert (d["В городе"], d["Загород"], d["С ограничениями"]) == (1, 1, 2), d
assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", d["обновлено"]), d
P
expect "counter: неверная категория" 2 "$PY" "$HERE/counter.py" inc "$C" "Москва"

[ $fail = 0 ] && echo "selftest: всё прошло" || echo "selftest: есть ошибки"
exit $fail
