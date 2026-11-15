#!/usr/bin/env python3
"""ETKA на elcats.ru (VAG: Škoda, VW, Audi, Seat) — модель → рік → підгрупа → позиції OE з кодами моторів.

Використання (три кроки, як у каталозі):
    uv run tools/elcats.py models skoda --model Superb --year 2013
        → рядки «модель · рік · Mdl=<id>»
    uv run tools/elcats.py groups skoda --mdl 4745d1ab-9605-4217-86ca-3a54340a0e5a --group 1 --engine CFFB
        → підгрупи групи 1 (мотор), де є CFFB: номер малюнка, назва, об'єм, мотори, SubId
    uv run tools/elcats.py parts skoda --mdl 4745d1ab-… --sub 59B0010D --engine CFFB
        → позиції: №, OE, назва, примітка, к-сть, дані моделі (рядки без мотора теж — вони спільні)
    … --freeze   (лише parts) — заморозити сторінку позицій у raw/elcats/

Групи ETKA: 1 мотор і зчеплення · 2 паливо, вихлоп, опалення · 3 КПП · 4 передня вісь, кермо · 5 задня вісь ·
6 колеса, гальма · 7 педалі · 8 кузов · 9 електрика · 0 аксесуари.

Навіщо: VIN європейського VAG elcats (і PartSouq) часто не знаходить — іти по моделі й брати позиції за **кодом мотора** й датами
(«D >> …»), а гальма й пружини — за PR-кодами з наклейки (`pidbir-detalei`). Рівень 🟢 — каталог виробника.
Інші марки на elcats мають іншу структуру — цей скрипт лише для VAG.
"""
import argparse
import html as html_mod
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402

BASE = "https://www.elcats.ru/{brand}/"
BRANDS = ("skoda", "vw", "audi", "seat")
GROUPS = BASE + "Groups.aspx?Mdl={mdl}"
SUBGROUP = BASE + "SubGroup.aspx?GroupId={group}&Model={mdl}"
PARTS = BASE + "Parts.aspx?Mdl={mdl}&SubId={sub}"


def cells(row: str) -> list[str]:
    return [web.clean(re.sub(r"<br\s*/?>", " ", c)) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]


def models(page: str) -> list[tuple[str, str, str]]:
    """[(модель, рік / підпис, mdl)] у порядку сторінки."""
    out, name = [], ""
    for m in re.finditer(r"javascript:ToggleNode\('\d+'\)\">([^<]+)</a>|"
                         r"javascript:submit\('([0-9a-f-]{36})','\d+'\);\">(.*?)</a>", page):
        if m.group(1):
            name = web.clean(m.group(1))
        else:
            out.append((name, web.clean(html_mod.unescape(m.group(3))), m.group(2)))
    return out


def subgroups(page: str) -> list[list[str]]:
    """[[SubId, гол.група, підгрупа, № малюнка, назва, об'єм, мотори]]."""
    rows = []
    for sid, row in re.findall(r'<tr id="([0-9A-F]{8})">(.*?)</tr>', page, flags=re.S):
        c = cells(row)
        if len(c) >= 6:
            rows.append([sid] + c[:6])
    return rows


def parts(page: str) -> list[list[str]]:
    """[[поз., OE, назва, примітка, к-сть, дані моделі]] і рядки-заголовки варіантів як ['', '', '== …']."""
    i = page.find("tblParts")
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page[i:page.find("</table>", i)], flags=re.S):
        c = cells(row)
        if len(c) < 6 or c[0] in ("Поз.",):
            continue
        if not c[1] and c[2]:  # заголовок варіанта: назва, об'єм, мотори
            rows.append(["", "", f"== {c[2]} · {c[3]} · {c[5]}", "", "", ""])
        elif c[1]:
            rows.append(c[:6])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("models", "groups", "parts"))
    ap.add_argument("brand", choices=BRANDS)
    ap.add_argument("--model", default="", help="models: частина назви моделі (Superb, Octavia, Caddy)")
    ap.add_argument("--year", default="", help="models: модельний рік")
    ap.add_argument("--mdl", default="", help="groups / parts: ідентифікатор моделі з models")
    ap.add_argument("--group", default="1", help="groups: номер групи 0–9 (за замовчуванням 1 — мотор)")
    ap.add_argument("--sub", default="", help="parts: SubId з groups")
    ap.add_argument("--engine", default="", help="groups / parts: код мотора (CFFB)")
    ap.add_argument("--grep", default="", help="groups: частина назви підгрупи (ремень, насос)")
    ap.add_argument("--freeze", action="store_true", help="parts: заморозити сторінку в raw/elcats/")
    a = ap.parse_args()
    b = a.brand

    try:
        if a.cmd == "models":
            url = BASE.format(brand=b)
            rows = models(web.get(url, expect="ToggleNode"))
            rows = [r for r in rows if a.model.lower() in r[0].lower() and a.year in r[1]]
            for name, year, mdl in rows:
                print(f"{name} · {year} · {mdl}")
            print(f"— {len(rows)} рядків · {url}")
            if not rows:
                print("  нічого: перевір назву моделі (як на сайті: Octavia, Superb, Caddy) і рік")
        elif a.cmd == "groups":
            if not a.mdl:
                sys.exit("✗ потрібен --mdl (з команди models)")
            url = SUBGROUP.format(brand=b, group=a.group, mdl=a.mdl)
            rows = subgroups(web.get(url, expect="<tr id="))
            eng, grep = a.engine.upper(), a.grep.lower()
            # Підгрупа без кодів моторів — спільна для всіх, її лишаємо
            rows = [r for r in rows if (not eng or eng in r[6].upper() or not re.search(r"[A-Z]{3,4}", r[6]))
                    and (not grep or grep in r[4].lower())]
            for sid, _g, _s, pic, name, vol, eng_s in rows:
                print(f"{pic} | {name} | {vol} | {eng_s} | SubId {sid}")
            print(f"— {len(rows)} підгруп · {url}")
        else:
            if not (a.mdl and a.sub):
                sys.exit("✗ потрібні --mdl і --sub (з команд models і groups)")
            url = PARTS.format(brand=b, mdl=a.mdl, sub=a.sub)
            rows = parts(web.get(url, expect="tblParts"))
            eng = a.engine.upper()
            shown = 0
            for pos, oe, name, note, qty, data in rows:
                if not oe and name.startswith("=="):
                    print(name)
                    continue
                if eng and data and re.search(r"[A-Z]{4}", data) and eng not in data.upper():
                    continue  # позиція під інший мотор
                shown += 1
                print(f"{pos:>4} | {oe:<16} | {name} | {note} | {qty} | {data}")
            print(f"— {shown} позицій · {url}")
            if a.freeze:
                web.freeze(url, "elcats", f"{b}-{a.mdl[:8]}-{a.sub.lower()}")
    except web.FetchError as e:
        web.fail(str(e), e.url, e.status)
        sys.exit(2)


if __name__ == "__main__":
    main()
