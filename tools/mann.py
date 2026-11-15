#!/usr/bin/env python3
"""Товар MANN-FILTER по артикулу MANN: розміри, OE-номери, застосування з кодами моторів.

Використання:
    uv run tools/mann.py "C 27 009"
    uv run tools/mann.py C27009 WK5002 "HU 716/2 x"
    uv run tools/mann.py C27009 --engine CFFB          # лише рядки застосувань з цим кодом мотора
    uv run tools/mann.py C27009 --make SKODA           # лише одна марка
    uv run tools/mann.py C27009 --freeze               # і заморозити сторінку в raw/mann-filter/

Вхід — **артикул MANN**, не OE: пошук по OE на сайті малюється JavaScript-ом, скрипту не видно. OE → артикул MANN
дають кроси (`tools/ersatzteile.py <OE>`), Trodo, Biltema.

Застосування — каталог виробника фільтра (TecDoc-рівень, 🟢 для «MANN каже, що підходить», але не для OE авто):
зводити з OE-каталогом авто, як велить `pidbir-detalei`.
"""
import argparse
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402

URL = "https://www.mann-filter.com/en/catalog/search-results/product.html/{}_mann-filter.html"


def code(art: str) -> str:
    """'HU 716/2 x' → 'hu716/2x' (як у URL сайту)."""
    return re.sub(r"\s+", "", art).lower()


def parse(page: str) -> dict:
    out = {}
    m = re.search(r"<title>\s*([^<]+?)\s*</title>", page)
    out["name"] = web.clean(m.group(1)) if m else ""
    # Розміри — рядок опису «Length (A) = 269 mm; Width (B) = …» (у різних фільтрів різні назви)
    dims = [web.clean(d) for d in re.findall(r"<li>\s*([^<]*=\s*[\d.,]+\s*mm[^<]*)</li>", page)]
    out["dims"] = dims[0] if dims else ""
    # OE-номери: акордеон «OE Numbers» → підрозділ по виробнику → <li>
    oe = {}
    i = page.rfind("OE Numbers")
    j = page.find('id="downloads"', i)
    if i > 0:
        block = page[i:j if j > 0 else i + 20000]
        for mk, ul in re.findall(r'cmp-accordion__title">([^<]+)</span>.*?<ul>(.*?)</ul>', block, flags=re.S):
            oe[web.clean(mk)] = [web.clean(x) for x in re.findall(r"<li>(.*?)</li>", ul, flags=re.S)]
    out["oe"] = oe
    # Застосування: кожне посилання в таблиці несе структуровані параметри
    apps, seen = [], set()
    for params in re.findall(r'data-g-binding-params="([^"]+)"', page):
        q = urllib.parse.parse_qs(urllib.parse.unquote(params).lstrip("?"))
        g = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        if not g("vehicleMake"):
            continue
        row = (g("vehicleMake"), g("vehicleModel"), g("vehicleName"), g("engineCode"), g("ccm"), g("kw"),
               g("vehicleManufacturedFrom")[:7], g("vehicleManufacturedTo")[:7].replace("9999-12", ""))
        if row not in seen:
            seen.add(row)
            apps.append(row)
    out["apps"] = apps
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("art", nargs="+", help="артикул MANN: 'C 27 009', C27009, 'HU 716/2 x'")
    ap.add_argument("--engine", help="фільтр застосувань за кодом мотора (частина рядка)")
    ap.add_argument("--make", help="фільтр застосувань за маркою")
    ap.add_argument("--freeze", action="store_true", help="заморозити сторінку в raw/mann-filter/")
    a = ap.parse_args()

    rc = 0
    for art in a.art:
        url = URL.format(code(art))
        try:
            page = web.get(url, expect="OE Numbers")
        except web.FetchError as e:
            web.fail(f"{art}: {e}", url, e.status)
            rc = 2
            continue
        d = parse(page)
        print(f"## {d['name'] or art}\n{url}")
        if d["dims"]:
            print(f"Розміри: {d['dims']}")
        for mk, nums in d["oe"].items():
            print(f"OE {mk}: {', '.join(nums)}")
        if not d["oe"]:
            print("OE: на сторінці немає")
        apps = [r for r in d["apps"]
                if (not a.engine or a.engine.upper() in r[3].upper())
                and (not a.make or a.make.upper() in r[0].upper())]
        print(f"Застосування: {len(apps)} з {len(d['apps'])}")
        for mk, model, name, eng, ccm, kw, f, t in apps:
            print(f"  {mk} {model} {name} | {eng or '—'} | {ccm} ccm {kw} kW | {f} → {t or '…'}")
        if a.freeze:
            web.freeze(url, "mann-filter", web.slugify(code(art)).replace("-", ""))
        print()
    sys.exit(rc)


if __name__ == "__main__":
    main()
