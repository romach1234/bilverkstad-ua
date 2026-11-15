#!/usr/bin/env python3
"""Хук SessionStart: підтягує свіжий стан із GitHub і вкидає табло _ai/HANDOFF.md у контекст сесії.

Навіщо: пам'ять Claude між сесіями й комп'ютерами — у git. Без цього нова сесія стартує з того, що лежить у локальній
копії, а вона може бути на кілька комітів позаду.

Python, а не bash: на Windows Claude Code запускає хуки через Git Bash, де немає `python3` і ламаються шляхи, — тому
хук запускається як `uv run --no-project python …` однаково на Windows і Linux. Будь-яка помилка не має ламати старт
сесії, тому всюди фолбеки й вихід 0.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def git(*args, timeout=25):
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})  # щоб git не завис на паролі
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    try:
        code, root = git("rev-parse", "--show-toplevel", timeout=10)
        if code:
            return
        root = Path(root)
        os.chdir(root)
        _, dirty = git("status", "--porcelain", timeout=10)
        _, remote = git("remote", timeout=10)
        if dirty:
            pull = "pull НЕ робив: у робочій копії є незакомічені зміни. Розібратися вручну."
        elif not remote:
            pull = "віддаленого репо (origin) немає — синхронізації між комп'ютерами немає, працюємо локально."
        else:
            # fetch + merge з origin/<гілка>, а не pull: pull зливає з FETCH_HEAD і ловить гонку з автофетчем редактора
            _, branch = git("rev-parse", "--abbrev-ref", "HEAD", timeout=10)
            code, out = git("fetch", "origin", branch)
            if not code:
                code, out = git("merge", "--ff-only", f"origin/{branch}")
            pull = "\n".join(out.splitlines()[-3:]) or "(git fetch / merge без виводу)"
    except Exception as e:  # git немає, тайм-аут — старт сесії все одно має пройти
        pull = f"синхронізація не вдалась: {e}"
        root = Path.cwd()

    try:
        handoff = (root / "_ai" / "HANDOFF.md").read_text(encoding="utf-8")
    except Exception:
        handoff = "(файл _ai/HANDOFF.md не знайдено)"

    ctx = f"""# Стан майстерні на старті сесії

Синхронізація з GitHub (контекст між комп'ютерами передається через git):

```
{pull}
```

Нижче — табло майстерні: машини в роботі одним рядком і справи системи. Повний стан машини —
у її `cars/<номер>/<авто>-stan.md`; хук сам вкине його, щойно оператор назве номер.
Обґрунтування рішень — у `_ai/decisions.md`, вже відомі граблі — у `_ai/lessons.md`.
У кінці сесії паркуватися скілом `parkovka`.

---

{handoff}"""
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
