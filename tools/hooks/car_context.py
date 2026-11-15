#!/usr/bin/env python3
"""Хук UserPromptSubmit: якщо в повідомленні оператора є номер машини (шаблон — tools/region.json), VIN або назва теки
машини (kia-niro) — підкласти стан машини.

Стан роботи кожної машини — у cars/<номер>/<авто>-stan.md, а _ai/HANDOFF.md — лише табло. Щоб сесія продовжила з того
місця, де кинули, а не почала з нуля, стан машини вкидається в контекст механічно, щойно оператор назвав машину.

- машина є в cars/ і має -stan.md → текст стану в контекст
- машина є, а -stan.md немає      → нагадування створити його на паркуванні
- номера немає ніде               → це нове авто, скіл nove-avto

Кожну машину вкидає один раз за сесію (позначка в теці tmp за session_id). Будь-яка помилка не має блокувати
повідомлення оператора — тому вихід 0 на всіх шляхах.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PLATE = r"[ABCEHIKMOPTXАВСЕНІКМОРТХ]{2}\d{4}[ABCEHIKMOPTXАВСЕНІКМОРТХ]{2}"
# Кирилиця й латиниця однакового вигляду — одна тека: «АА1234ВВ» і «AA1234BB» → aa1234bb
CYR2LAT = str.maketrans("АВСЕНІКМОРТХавсенікмортх", "ABCEHIKMOPTXabcehikmoptx")


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    prompt = data.get("prompt") or ""
    session = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id") or "nosession")
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
    root = Path(r.stdout.strip()) if r.returncode == 0 else Path.cwd()
    cars = root / "cars"

    try:
        plate = json.loads((root / "tools" / "region.json").read_text(encoding="utf-8"))["plate_regex"]
    except Exception:
        plate = DEFAULT_PLATE
    found, named = [], []
    # Межі слова з обох боків — щоб не ловити шматки артикулів
    for m in re.finditer(rf"(?<![\w])({plate})(?![\w])", prompt, flags=re.I):
        reg = m.group(1).translate(CYR2LAT).lower()
        if reg not in found:
            found.append(reg)
    # Теки не за номером (cars/kia-niro/, cars/toyota-hilux/) — ловити й назву: «Kia Niro», «kia-niro»
    for d in sorted(cars.iterdir()) if cars.is_dir() else []:
        if d.is_dir() and d.name not in found and not re.fullmatch(plate, d.name, flags=re.I):
            pat = r"[\s_-]+".join(map(re.escape, re.split(r"[-_]", d.name)))
            if re.search(rf"(?<![\w]){pat}(?![\w])", prompt, flags=re.I):
                found.append(d.name)
                named.append(d.name)
    if not found:
        return

    seen_file = Path(tempfile.gettempdir()) / f"bilverkstad-car-ctx-{session}"
    try:
        seen = set(seen_file.read_text(encoding="utf-8").split())
    except Exception:
        seen = set()

    parts = []
    for reg in found:
        if reg in seen:
            continue
        REG = reg.upper()
        folder = cars / reg
        if not folder.is_dir() and reg not in named:
            # Номер, якого немає, може бути й не машиною — тому підказка, а не наказ
            parts.append(f"## {REG} — машини немає в `cars/`\n\nЯкщо це номер авто — це нова машина: скіл `nove-avto`.")
        else:
            stan = sorted(folder.glob("*-stan.md"))
            if stan:
                parts.append(f"## {REG} — паркувальний файл машини `{stan[0].relative_to(root).as_posix()}`\n\n"
                             "Це стан незавершеної роботи по машині: продовжувати звідси, а не з нуля.\n\n---\n\n"
                             + stan[0].read_text(encoding="utf-8"))
            else:
                parts.append(f"## {REG} — є в `{folder.relative_to(root).as_posix()}/`, але паркувального файлу "
                             "`*-stan.md` немає\n\nСтан роботи — у файлах машини; на паркуванні створити `-stan.md` "
                             "за `templates/stan.md`.")
        seen.add(reg)
    if not parts:
        return
    try:
        seen_file.write_text(" ".join(sorted(seen)), encoding="utf-8")
    except Exception:
        pass
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "# Стан машин, названих у повідомленні\n\n" + "\n\n".join(parts),
    }}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
