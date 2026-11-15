#!/usr/bin/env python3
"""der-ersatzteile-profi.de: пошук по OE-номеру → товари всіх брендів; картка → бренд, OE-кроси, авто з кодами моторів.

Використання:
    uv run tools/ersatzteile.py 9818531680                     # що продається під цей OE (назва, ціна, наявність)
    uv run tools/ersatzteile.py 9818531680 --details           # + картка кожного: бренд, номер, OE-кроси, авто
    uv run tools/ersatzteile.py 9818531680 --details --engine BHY   # авто лише з цим кодом мотора
    uv run tools/ersatzteile.py https://www.der-ersatzteile-profi.de/artikel/harnstoff-tank-a11011271
    uv run tools/ersatzteile.py 9818531680 --freeze            # і заморозити сторінку пошуку (з --details — і картки)

Навіщо: магазин на TecDoc, і пошук по OE знаходить навіть те, чого немає в категоріях типу авто (бак AdBlue
PSA). Рівень 🟡 (TecDoc магазину): застосування звіряти з OE-каталогом авто (`pidbir-detalei`). Ціни — в євро
з німецьким ПДВ, для орієнтиру.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402

BASE = "https://www.der-ersatzteile-profi.de"
SEARCH = BASE + "/search?w={}"  # не /suche?q= — то 404 (kb/dzherela-artykuliv-ta-danych.md)


def parse_search(page: str) -> list[dict]:
    items = []
    for b in page.split('class="artikel-list col-xs-12"')[1:]:
        title = re.search(r'list_artitle[^>]*>(.*?)</a>', b, flags=re.S)
        link = re.search(r'href="(' + re.escape(BASE) + r'/artikel/[^"]+)"', b)
        art = re.search(r"Art\.-Nummer: </strong>([^<]+)", b)
        price = re.search(r"productSpecialPrice'?\"?>([^<]+)<", b)
        refs = re.findall(r"<span>([^<]+?):?\s*</span>\s*<span class=\"rf_rechts\">([^<]+)</span>", b)
        stock = re.search(r'class="lagerware"[^>]*>(.*?)</div>', b, flags=re.S)
        items.append({
            "title": web.clean(title.group(1)) if title else "?",
            "url": link.group(1) if link else "",
            "art": art.group(1).strip() if art else "",
            "price": web.clean(price.group(1)) if price else "",
            "via": ", ".join(f"{m.strip(': ')} {n}" for m, n in refs),
            "stock": web.clean(stock.group(1)) if stock else "",
        })
    return items


def parse_product(page: str) -> dict:
    out = {"brand": "", "mpn": "", "name": "", "oe": [], "cars": []}
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, flags=re.S):
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "Product":
                b = d.get("brand")
                out["brand"] = (b.get("name", "") if isinstance(b, dict) else str(b or "")).strip()
                out["mpn"] = str(d.get("mpn", "")).strip()
                out["name"] = re.sub(r"\s+online kaufen$", "", str(d.get("name", ""))).strip()
    i = page.find("OE-Referenznummern")
    if i > 0:
        block = page[i:page.find("</ul>", i)]
        out["oe"] = [(web.clean(m), web.clean(n)) for m, n in
                     re.findall(r'rf_links"><strong>(.*?)</strong>.*?rf_rechts\'>(.*?)</span>', block, flags=re.S)]
    i = page.find('class="prodinfocars')
    if i > 0:
        block = page[i:page.find("</table>", i)]
        for row in re.findall(r'<tr class="prg[^"]*"[^>]*>(.*?)</tr>', block, flags=re.S):
            cells = [web.clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
            if len(cells) >= 7:
                out["cars"].append(cells[:7])  # марка, модель, тип, PS/kW, об'єм, код мотора, роки
    return out


def show_product(url: str, engine: str, freeze: bool) -> None:
    try:
        # не "Passende Fahrzeuge": таблиці авто буває немає (шланги, насоси)
        d = parse_product(web.get(url, expect="application/ld+json"))
    except web.FetchError as e:
        web.fail(str(e), url, e.status)
        return
    print(f"    бренд: {d['brand'] or '?'} · номер: {d['mpn'] or '?'}")
    if d["oe"]:
        print("    OE: " + ", ".join(f"{m} {n}" for m, n in d["oe"]))
    cars = [c for c in d["cars"] if not engine or engine.upper() in c[5].upper()]
    print(f"    авто: {len(cars)} з {len(d['cars'])}")
    for mk, model, typ, power, ccm, eng, years in cars:
        print(f"      {mk} {model} {typ} | {eng} | {power}, {ccm} ccm | {years}")
    if freeze:
        web.freeze(url, "der-ersatzteile-profi", "artikel-" + url.rsplit("-a", 1)[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="+", help="OE-номер (без пробілів) або URL картки /artikel/…")
    ap.add_argument("--details", action="store_true", help="відкрити картку кожного товару")
    ap.add_argument("--engine", default="", help="авто лише з цим кодом мотора (з --details)")
    ap.add_argument("--freeze", action="store_true", help="заморозити сторінки в raw/der-ersatzteile-profi/")
    a = ap.parse_args()

    rc = 0
    for q in a.query:
        if q.startswith("http"):
            print(f"## {q}")
            show_product(q, a.engine, a.freeze)
            continue
        oe = re.sub(r"[\s.\-]", "", q)
        url = SEARCH.format(oe)
        try:
            items = parse_search(web.get(url, timeout=60))
        except web.FetchError as e:
            web.fail(str(e), url, e.status)
            rc = 2
            continue
        print(f"## OE {oe} — {len(items)} товарів\n{url}")
        if not items:
            print("  нічого: спробувати OE з пробілами як у каталозі виробника або інший OE з кросів")
        for n, it in enumerate(items, 1):
            via = f" · знайдено через {it['via']}" if it["via"] else ""
            print(f"{n}. {it['title']} | {it['price']} | {it['stock']} | {it['art']}{via}\n   {it['url']}")
            if a.details and it["url"]:
                show_product(it["url"], a.engine, a.freeze)
        if a.freeze:
            web.freeze(url, "der-ersatzteile-profi", f"search-{oe.lower()}", timeout=60)
        print()
    sys.exit(rc)


if __name__ == "__main__":
    main()
