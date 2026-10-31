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
grep -q "## Особые пометки" "$T/tender.md" && grep -q "7 этаж" "$T/tender.md" && ok "render_md: особые пометки" || bad "render_md: особые пометки"
"$PY" - "$EX" "$T/nonotes.json" "$T/nofield.json" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
d["special_notes"] = []; d["delivery"]["notes"] = "Доставка силами Поставщика"; d["delivery"]["address_notice"] = "г. Новосибирск"
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
del d["special_notes"]
json.dump(d, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False)
P
expect "validate: нет special_notes = код 1" 1 "$PY" "$HERE/validate_tender.py" "$T/nofield.json"
expect "validate: пустые особые пометки допустимы" 0 "$PY" "$HERE/validate_tender.py" "$T/nonotes.json"
"$PY" "$HERE/render_md.py" "$T/nonotes.json" -o "$T/nonotes.md" >/dev/null
grep -A2 "## Особые пометки" "$T/nonotes.md" | grep -qx "нет" && ok "render_md: пустые пометки = «нет»" || bad "render_md: пустые пометки"
"$PY" - "$EX" "$T/lost.json" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
d["special_notes"] = []
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
P
"$PY" "$HERE/validate_tender.py" "$T/lost.json" >"$T/out" 2>&1; c=$?
[ $c = 0 ] && grep -q "special_notes пусто" "$T/out" && ok "validate: подъём в условиях, а пометок нет" || { bad "validate: пропавшие пометки"; cat "$T/out"; }

# --- нацрежим: conditions.national_regime — объект, «Обязателен: ДА/НЕТ/нет данных»
grep -qx -- "- \*\*Нацрежим:\*\* Обязателен: ДА — ограничение; основание: ст. 14 44-ФЗ, ПП РФ от 23.12.2024 № 1875; подтверждение: .*" "$T/tender.md" \
  && ok "render_md: нацрежим — Обязателен: ДА" || bad "render_md: нацрежим ДА"
"$PY" - "$EX" "$T" <<'P2'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8")); t = sys.argv[2]
def put(name, nr):
    x = json.loads(json.dumps(d)); x["conditions"]["national_regime"] = nr
    json.dump(x, open(f"{t}/nr_{name}.json", "w", encoding="utf-8"), ensure_ascii=False)
na = {"basis": "не применимо", "confirmation": "не применимо", "note": "нет"}
put("no", dict(na, mandatory=False, measure="не установлен"))
put("pref", {"mandatory": False, "measure": "преимущество", "basis": "ст. 14 44-ФЗ, ПП РФ от 23.12.2024 № 1875 (приложение 3)",
             "confirmation": "страна происхождения товара", "note": "скидка 15% при оценке заявок"})
put("null", {"mandatory": None, "measure": "нет данных", "basis": "нет данных", "confirmation": "нет данных",
             "note": "в извещении нет раздела о нацрежиме, файл извещения не открылся"})
put("str", "Ограничение (ст. 14 44-ФЗ)")
put("mismatch", dict(na, mandatory=True, measure="не установлен"))
put("pref_true", dict(na, mandatory=True, measure="преимущество"))
put("nullnote", dict(na, mandatory=None, measure="нет данных"))
put("badmeasure", dict(na, mandatory=False, measure="нету"))
put("empty", dict(na, mandatory=False, measure="не установлен", basis=" "))
put("nomand", {k: v for k, v in dict(na, measure="не установлен").items()})
put("extra", dict(na, mandatory=False, measure="не установлен", lishnee="x"))
put("strbool", dict(na, mandatory="да", measure="ограничение"))
P2
for f in no pref null; do expect "validate: нацрежим $f" 0 "$PY" "$HERE/validate_tender.py" "$T/nr_$f.json"; done
for f in str mismatch pref_true nullnote badmeasure empty nomand extra strbool; do
  expect "validate: нацрежим $f = код 1" 1 "$PY" "$HERE/validate_tender.py" "$T/nr_$f.json"; done
for f in no pref null; do "$PY" "$HERE/render_md.py" "$T/nr_$f.json" -o "$T/nr_$f.md" >/dev/null; done
grep -qx -- "- \*\*Нацрежим:\*\* Обязателен: НЕТ — не установлен; основание: не применимо; подтверждение: не применимо" "$T/nr_no.md" \
  && ok "render_md: нацрежим — Обязателен: НЕТ" || bad "render_md: нацрежим НЕТ"
grep -q -- "^- \*\*Нацрежим:\*\* Обязателен: НЕТ — преимущество; .*скидка 15%" "$T/nr_pref.md" \
  && ok "render_md: нацрежим — преимущество = НЕТ" || bad "render_md: нацрежим преимущество"
grep -q -- "^- \*\*Нацрежим:\*\* Обязателен: нет данных — нет данных; .*примечание: в извещении нет раздела" "$T/nr_null.md" \
  && ok "render_md: нацрежим — нет данных с причиной" || bad "render_md: нацрежим нет данных"
[ "$(grep -c "Нацрежим" "$T/nr_no.md")" = 1 ] && ok "render_md: строка «Нацрежим» одна" || bad "render_md: строк «Нацрежим» не одна"

# --- dgis_link.py (офлайн: фейковый HTML поиска 2ГИС, в сеть не ходит)
G="$T/dgis"; mkdir -p "$G"
"$PY" - "$G" <<'P'
import json, sys
g = sys.argv[1]
def page(blds, path):
    prof = {b["id"]: {"data": b} for b in blds}
    state = json.dumps({"data": {"entity": {"profile": prof}}}, ensure_ascii=False)
    state = state.replace('\\"', '\\\\"')                 # как в странице 2ГИС: JSON внутри JS-строки
    open(f"{g}/{path}", "w", encoding="utf-8").write(
        f"<html><script>var initialState = JSON.parse('{state}');</script></html>")
b104 = {"id": "141373143524501", "type": "building", "name": "улица Богдана Хмельницкого, 104",
        "address_name": "улица Богдана Хмельницкого, 104", "purpose_name": "Административное \"здание\""}
page([b104], "one.html")
page([b104, dict(b104, id="141373143500000")], "two.html")
page([dict(b104, type="branch")], "firm.html")
open(f"{g}/none.html", "w", encoding="utf-8").write("<html>museum</html>")
P
DG="$HERE/dgis_link.py"; A='630027, г. Новосибирск, ул. Богдана Хмельницкого, д.104, этаж 7'
SRCH='https://2gis.ru/novosibirsk/search/%D0%B3.%20%D0%9D%D0%BE%D0%B2%D0%BE%D1%81%D0%B8%D0%B1%D0%B8%D1%80%D1%81%D0%BA%2C%20%D1%83%D0%BB.%20%D0%91%D0%BE%D0%B3%D0%B4%D0%B0%D0%BD%D0%B0%20%D0%A5%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D0%BA%D0%BE%D0%B3%D0%BE%2C%20%D0%B4.104'
dg() { "$PY" "$DG" "$@" 2>/dev/null; }
[ "$(dg --address "$A" --city Новосибирск --short)" = "г. Новосибирск, ул. Богдана Хмельницкого, д.104" ] \
  && ok "dgis: сокращение адреса (индекс, этаж)" || bad "dgis: сокращение адреса"
[ "$(dg --address 'ООО «Ромашка», 630099, Новосибирск, ул. Ленина, 1, офис 5, 2 этаж, тел. +7 383 000-00-00' --city Новосибирск --short)" = "г. Новосибирск, ул. Ленина, 1" ] \
  && ok "dgis: сокращение адреса (название, офис, телефон)" || bad "dgis: сокращение адреса с названием"
[ "$(dg --address 'Российская Федерация, обл. Новосибирская, г.о. город Новосибирск, г. Новосибирск, ул. Богдана Хмельницкого, зд. 104, с подъемом на 7 этаж' --city Новосибирск --short)" = "г. Новосибирск, ул. Богдана Хмельницкого, зд. 104" ] \
  && ok "dgis: сокращение адреса из извещения" || bad "dgis: сокращение адреса из извещения"
[ "$(dg --address "$A" --city Новосибирск --html "$G/one.html")" = "https://2gis.ru/novosibirsk/geo/141373143524501" ] \
  && ok "dgis: initialState → geo/<id>" || bad "dgis: разбор initialState"
[ "$(dg --address 'г. Новосибирск, ул. Богдана Хмельницкого, 105' --city Новосибирск --html "$G/one.html")" != "https://2gis.ru/novosibirsk/geo/141373143524501" ] \
  && ok "dgis: дом не совпал — не geo" || bad "dgis: дом не совпал"
for f in two firm none; do
  [ "$(dg --address "$A" --city Новосибирск --html "$G/$f.html")" = "$SRCH" ] && ok "dgis: $f.html → запасная ссылка" || bad "dgis: $f.html"
done
[ "$(dg --address "$A" --city Новосибирск --offline)" = "$SRCH" ] && ok "dgis: --offline → запасная ссылка" || bad "dgis: --offline"
"$PY" - "$EX" "$G/t.json" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8")); del d["delivery"]["map_url"]
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
P
expect "validate: нет delivery.map_url = код 1" 1 "$PY" "$HERE/validate_tender.py" "$G/t.json"
expect "dgis: --tender заполняет map_url" 0 "$PY" "$DG" --tender "$G/t.json" --html "$G/one.html"
"$PY" -c 'import json,sys; assert json.load(open(sys.argv[1]))["delivery"]["map_url"] == "https://2gis.ru/novosibirsk/geo/141373143524501"' "$G/t.json" \
  && ok "dgis: delivery.map_url = geo" || bad "dgis: delivery.map_url"
expect "validate: map_url после dgis_link" 0 "$PY" "$HERE/validate_tender.py" "$G/t.json" --folder-name 0151100007126000034
"$PY" "$HERE/render_md.py" "$G/t.json" -o "$G/t.md" >/dev/null
grep -qx -- "- 2ГИС: https://2gis.ru/novosibirsk/geo/141373143524501" "$G/t.md" && ok "render_md: строка 2ГИС" || bad "render_md: строка 2ГИС"
cp "$G/t.json" "$G/s.json"
expect "dgis: --tender --offline" 0 "$PY" "$DG" --tender "$G/s.json" --offline
"$PY" "$HERE/validate_tender.py" "$G/s.json" >"$T/out" 2>&1; c=$?
[ $c = 0 ] && grep -q "запасная ссылка" "$T/out" && ok "validate: запасная ссылка = предупреждение" || { bad "validate: запасная ссылка"; cat "$T/out"; }
"$PY" - "$G/t.json" "$G" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for name, url in (("stat", "https://2gis.ru/novosibirsk/geo/141373143524501?stat=abc"),
                  ("city", "https://2gis.ru/moscow/geo/141373143524501"),
                  ("dgis", "dgis://2gis.ru/routeSearch"), ("http", "http://2gis.ru/novosibirsk/geo/1")):
    d["delivery"]["map_url"] = url
    json.dump(d, open(f"{sys.argv[2]}/bad_{name}.json", "w", encoding="utf-8"), ensure_ascii=False)
P
for f in stat city dgis http; do expect "validate: map_url $f = код 1" 1 "$PY" "$HERE/validate_tender.py" "$G/bad_$f.json"; done

# --- counter.py
C="$T/счётчик.json"
printf '%s\n' "В городе/" "В городе/0151100007126000034/" "В городе/0151100007126000034/txt/" \
  "Загород/" "С ограничениями/" "С ограничениями/32616501202/" \
  "С ограничениями/0351200003326001418/" "С ограничениями/0351200003326001418/txt/" >"$T/lsf.txt"
expect "counter: inc без файла = ошибка" 1 "$PY" "$HERE/counter.py" inc "$C" "Загород"
expect "counter: init" 0 sh -c "\"$PY\" \"$HERE/counter.py\" init \"$C\" < \"$T/lsf.txt\""
expect "counter: init второй раз не затирает" 1 sh -c "\"$PY\" \"$HERE/counter.py\" init \"$C\" < \"$T/lsf.txt\""
expect "counter: inc (TZ бокса — Нью-Йорк)" 0 env TZ=America/New_York "$PY" "$HERE/counter.py" inc "$C" "Загород"
"$PY" - "$C" <<'P' && ok "counter: значения 1/1/2, время по Новосибирску" || bad "counter: значения или время"
import json, re, sys
from datetime import datetime, timedelta, timezone
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert (d["В городе"], d["Загород"], d["С ограничениями"]) == (1, 1, 2), d
assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", d["обновлено"]), d
t = datetime.strptime(d["обновлено"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=7)))
assert abs((datetime.now(timezone.utc) - t).total_seconds()) < 180, (d["обновлено"], "не UTC+7")
P
expect "counter: --tz больше нет" 2 "$PY" "$HERE/counter.py" inc "$C" "Загород" --tz Europe/Berlin
expect "counter: неверная категория" 2 "$PY" "$HERE/counter.py" inc "$C" "Москва"

[ $fail = 0 ] && echo "selftest: всё прошло" || echo "selftest: есть ошибки"
exit $fail
