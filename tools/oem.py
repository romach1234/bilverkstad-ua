#!/usr/bin/env python3
"""З OE-номера робить готовий блок для нотатки: лінки на пошук + перевірка Biltema.

Використання:
    uv run tools/oem.py 11428507683
    uv run tools/oem.py 11428507683 13717800151 64119272642
    uv run tools/oem.py 11428507683:2000038020        # OE:артикул_Biltema — перевірити збіг
    uv run tools/oem.py 11428507683 --md              # вивести Markdown-таблицею

Навіщо: оператор не може дати нам доступ до каталогів автоматично (Trodo, PartSouq,
autodoc — усі 403), зате може відкрити лінк і вставити результат. Скрипт готує ці лінки
і одразу перевіряє те, що перевірити можна — товар Biltema по артикулу.

Пошук Biltema по OE-номеру НЕ працює (їхній індекс не містить OE), тому артикул
Biltema доводиться давати руками через `OE:артикул`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from biltema import fetch as bt_fetch, parse as bt_parse  # noqa: E402

TRODO = "https://www.trodo.se/catalogsearch/oem/{}"
PARTSOUQ = "https://partsouq.com/en/search/all?q={}"
MANN = "https://www.mann-filter.com/en/catalog/search-results.html?q={}"
BILTEMA_PROD = "https://www.biltema.se/search?query={}"


def check_biltema(art, oe):
    """Повертає (вердикт, рядок деталей) по товару Biltema."""
    try:
        d = bt_parse(bt_fetch(BILTEMA_PROD.format(art)))
    except Exception as e:
        return "⚠️", f"не вдалося прочитати ({e})"
    if not d.get("pris"):
        return "⚠️", "товар не знайдено"
    found = (d.get("OE") or "").replace(" ", "")
    dims = ", ".join(f"{n} {v}" for n, v in d["_props"][:4])
    if oe and oe in found:
        return "✅", f"{d['pris']} · OE збігається · {dims}"
    if found:
        return "❌", f"{d['pris']} · OE у товарі: {d['OE']} · {dims}"
    return "⚠️", f"{d['pris']} · OE не вказано, звіряти по розмірах · {dims}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_md = "--md" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)

    rows = []
    for arg in args:
        oe, _, art = arg.partition(":")
        oe = oe.strip()
        verdict = details = ""
        if art:
            verdict, details = check_biltema(art.strip(), oe)
        rows.append((oe, art.strip(), verdict, details))

    if as_md:
        print("| OE | Trodo | PartSouq | MANN | Biltema |")
        print("|---|---|---|---|---|")
        for oe, art, v, d in rows:
            bt = f"{v} [{art}]({BILTEMA_PROD.format(art)}) — {d}" if art else "—"
            print(f"| `{oe}` | [пошук]({TRODO.format(oe)}) "
                  f"| [пошук]({PARTSOUQ.format(oe)}) "
                  f"| [пошук]({MANN.format(oe)}) | {bt} |")
        return

    for oe, art, v, d in rows:
        print(f"\n=== OE {oe}")
        print(f"  Trodo    {TRODO.format(oe)}")
        print(f"  PartSouq {PARTSOUQ.format(oe)}   (Cloudflare — відкривати вручну)")
        print(f"  MANN     {MANN.format(oe)}")
        if art:
            print(f"  Biltema  {v} {art} — {d}")
            print(f"           {BILTEMA_PROD.format(art)}")


if __name__ == "__main__":
    main()
