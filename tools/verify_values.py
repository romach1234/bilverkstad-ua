#!/usr/bin/env python3
"""Механічна звірка значень у документі з фікстурами в raw/.

Навіщо: нотатка може переконливо твердити «масляний фільтр 11428507683» — і бути
помилкою. Помилка в артикулі означає замовлену не ту деталь, два тижні простою
машини й повторне замовлення. Цей скрипт нічого не тлумачить: він лише відповідає
на питання, **чи стоїть це значення у збереженому джерелі**, на яке вказує документ.

Смислову перевірку (чи справді це джерело про нашу машину, чи момент від того вузла)
робить агент `perevirka` — і він цей скрипт перезапускає сам, не вірячи його виводу
на слово.

    uv run tools/verify_values.py guides/bmw-n47-to-filtry.md
    uv run tools/verify_values.py cars/*.md guides/*.md
    uv run tools/verify_values.py --all

## Як писати в документі, щоб скрипт міг перевірити

В одному логічному рядку — рядку таблиці, пункті списку (з рядками-продовженнями) чи абзаці — мусять бути разом:

- **значення в бектиках** — `11428507683`, `25 Нм`, `6PK1698`, `506 мм`
- **шлях до фікстури** — `raw/biltema/oljefilter-2000038020_2026-10-16.txt`

Приклад рядка таблиці:

    | Масляний фільтр | `11428507683` | `raw/biltema/oljefilter-...txt` | ✅ |

Кілька фікстур в одному логічному рядку — значення підтверджене, якщо воно є хоч в одній.

## Як порівнює

Два рівні, як у подібному скрипті в репо rag:

- `OK`  — значення знайдене дослівно
- `OK~` — знайдене після нормалізації: лишаються тільки літери й цифри.
  Потрібно, бо BMW друкує номери як `11 42 8 507 683`, а моменти як `25 Nm`
  проти нашого `25 Нм`. Не помилка, але варто глянути очима
- `НЕМА` — значення у фікстурі відсутнє. **Це або помилка в документі, або
  не та фікстура.** Розбиратися обов'язково

Одиниці (`Нм`, `мм`, `л`) при нормалізації відкидаються — порівнюється число.
Через це `25 Нм` зійдеться з рядком «25 Nm» у мануалі, але також і з будь-яким
іншим «25» на сторінці: скрипт підтверджує присутність числа, не його сенс.
Саме тому другий шар перевірки — агент, а не цей скрипт.
"""
import argparse
import re
import sys
from pathlib import Path

# Значення, які має сенс звіряти: є цифра, довжина 2+
# Спершу береться КОЖНА пара бектиків (навіть `2`), і лише потім відкидаються короткі значення.
# Інакше `2` daNm ламав розбір: regex «перескакував» і ловив текст МІЖ бектиками як значення.
VALUE_RE = re.compile(r"`([^`\n]{1,60})`")
MIN_LEN = 2
RAW_RE = re.compile(r"(raw/[A-Za-z0-9._/-]+?\.(?:txt|html|mhtml|pdf|png|jpg))")
UNITS = re.compile(r"\b(нм|nm|мм|mm|л|l|kw|к\.?с\.?|hp|sek|usd|грн|uah|eur|км|km|mil|год|h)\b",
                   re.I)


def norm(s: str) -> str:
    """Лишає тільки літери й цифри, у нижньому регістрі."""
    s = UNITS.sub(" ", s)
    return re.sub(r"[^0-9a-zа-яёіїєґ]+", "", s.lower())


def repo_root() -> Path:
    """Корінь репо. Шляхи до фікстур у документах пишуться від нього,
    а не від поточної теки — інакше посилання ламалися б при кожному
    переміщенні документа глибше по дереву."""
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists() or (d / "raw").is_dir():
            return d
    return p


def fixture_text(path: Path) -> str | None:
    """Текст фікстури. Для .html/.mhtml/.pdf шукає поруч .txt."""
    if not path.is_absolute():
        path = repo_root() / path
    if path.suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    txt = path.with_suffix(".txt")
    if txt.exists():
        return txt.read_text(encoding="utf-8", errors="replace")
    return None


LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def blocks(lines: list[str]):
    """Логічні рядки: [(номер_першого_рядка, [рядки])].

    Рядок таблиці — окремий блок. Пункт списку чи абзац разом із рядками-продовженнями —
    один блок: у кроці гайда значення часто на одному рядку, а шлях до фікстури — на
    наступному, і звірка їх мусить бачити разом."""
    cur: list = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        new_block = (not s or s.startswith("|") or s.startswith("#")
                     or LIST_ITEM.match(line) or not cur)
        if new_block:
            if cur:
                yield cur
            cur = [] if not s else [(n, line)]
            if s.startswith("|") or s.startswith("#"):
                yield cur
                cur = []
        else:
            cur.append((n, line))
    if cur:
        yield cur


def check_doc(doc: Path, verbose: bool = False) -> tuple[int, int, int, int]:
    lines = doc.read_text(encoding="utf-8").splitlines()
    ok = approx = missing = no_fixture = 0
    rows = []

    for block in blocks(lines):
        raws = [r for _, line in block for r in RAW_RE.findall(line)]
        if not raws:
            continue
        values = [(n, v) for n, line in block for v in VALUE_RE.findall(line)
                  if len(v.strip()) >= MIN_LEN and any(c.isdigit() for c in v)
                  and not v.startswith(("raw/", "books:"))]
        if not values:
            continue

        # Кілька фікстур в одному блоці (таблиця на дві машини, крок із двома джерелами):
        # значення підтверджене, якщо воно є хоч в одній із них
        texts = []
        for rp in dict.fromkeys(raws):
            text = fixture_text(Path(rp))
            if text is not None:
                texts.append((rp, text, norm(text), re.sub(r"\s+", " ", text)))
        if not texts:
            for n, v in values:
                rows.append((n, v, ", ".join(dict.fromkeys(raws)), "ФІКСТУРИ НЕМА"))
                no_fixture += 1
            continue

        for n, v in values:
            # Пробіли й переноси рядків — не відмінність: витягнутий з HTML текст рве «23 ± 3» на «23 ±⏎3»
            hit = next((rp for rp, text, _, wtext in texts
                        if v in text or re.sub(r"\s+", " ", v) in wtext), None)
            if hit:
                rows.append((n, v, hit, "OK"))
                ok += 1
                continue
            hit = next((rp for rp, _, ntext, _ in texts if norm(v) and norm(v) in ntext), None)
            if hit:
                rows.append((n, v, hit, "OK~"))
                approx += 1
            else:
                rows.append((n, v, ", ".join(rp for rp, *_ in texts), "НЕМА"))
                missing += 1

    if rows:
        print(f"\n=== {doc}")
        for n, v, rp, status in rows:
            mark = {"OK": "✅", "OK~": "🟡", "НЕМА": "❌", "ФІКСТУРИ НЕМА": "🔒"}[status]
            if verbose or status != "OK":
                print(f"  {mark} {status:14} рядок {n:4}  `{v}`")
                print(f"     {rp}")
        print(f"  — {ok} OK · {approx} OK~ · {missing} НЕМА · {no_fixture} без фікстури")
    return ok, approx, missing, no_fixture


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", nargs="*", help="файли для перевірки")
    ap.add_argument("--all", action="store_true", help="усі cars/, guides/, kb/")
    ap.add_argument("-v", "--verbose", action="store_true", help="показувати і OK")
    args = ap.parse_args()

    docs = [Path(d) for d in args.docs]
    if args.all or not docs:
        root = repo_root()
        docs = sorted(p for d in ("cars", "guides", "kb")
                      for p in (root / d).rglob("*.md"))

    t = [0, 0, 0, 0]
    for doc in docs:
        if not doc.exists():
            print(f"✗ немає: {doc}", file=sys.stderr)
            continue
        for i, v in enumerate(check_doc(doc, args.verbose)):
            t[i] += v

    print(f"\n{'='*52}")
    print(f"РАЗОМ: ✅ {t[0]} OK · 🟡 {t[1]} OK~ · ❌ {t[2]} НЕМА · 🔒 {t[3]} без фікстури")
    if t[2]:
        print("\n❌ НЕМА — значення немає у вказаному джерелі. Розібратися обов'язково:")
        print("   або помилка в документі, або вказана не та фікстура.")
    if t[0] + t[1] + t[2] + t[3] == 0:
        print("\n⚠ Нічого не перевірено: у документах немає пар «значення + фікстура».")
        print("  Формат — у docstring цього скрипта (--help).")
    sys.exit(1 if t[2] else 0)


if __name__ == "__main__":
    main()
