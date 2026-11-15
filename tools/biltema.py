#!/usr/bin/env python3
"""Витягує дані товару з biltema.se по артикулу: OE-номер, ціну, розміри.

Використання:
    uv run tools/biltema.py 2000038020
    uv run tools/biltema.py 2000038020 2000036268 2000043747   # кілька за раз
    uv run tools/biltema.py <повний URL товару>

Навіщо: Biltema не показує OE-номер у пошуку по регномеру, тільки в описі товару,
а розміри — в окремій вкладці. Скрипт збирає все в один рядок, щоб швидко звірити
з потрібним фільтром (напр. MANN WK 5002 x = 251 мм, Ø55).

Biltema віддає сторінки без захисту — на відміну від autodoc, trodo
і partsouq, які ріжуть і curl, і автоматичний fetch.
"""
import re
import sys
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SEARCH = "https://www.biltema.se/search?query={}"


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "sv-SE,sv;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse(page):
    out = {}

    price = re.findall(r'"fromPriceIncVAT":([\d.]+)', page)
    if price:
        out["pris"] = f"{float(price[0]):.2f} SEK"

    # OE-номери живуть у html-описі товару
    for desc in set(re.findall(r'"description":"((?:[^"\\]|\\.){0,400})"', page)):
        oe = re.findall(r'OE:\s*([0-9A-Za-z][0-9A-Za-z ,./-]{5,70})', desc)
        if oe:
            out["OE"] = ", ".join(x.strip() for x in oe)
            break

    name = re.findall(r'<title>\s*([^<|]+?)\s*(?:-\s*Biltema)', page)
    if name:
        out["namn"] = name[0].strip()

    props = []
    for n, v, u in re.findall(
            r'"name":"([^"]{2,30})","value":"([^"]{1,40})","unit":(null|"[^"]{0,10}")', page):
        u = "" if u == "null" else u.strip('"')
        item = (n, f"{v} {u}".strip())
        if item not in props:
            props.append(item)
    out["_props"] = props
    return out


def url_for(arg):
    if arg.startswith("http"):
        return arg
    # пошук по артикулу — Biltema сама редіректить на товар
    return SEARCH.format(arg)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)
    for arg in args:
        try:
            page = fetch(url_for(arg))
        except urllib.error.HTTPError as e:
            print(f"{arg}: HTTP {e.code}", file=sys.stderr)
            continue
        d = parse(page)
        if not d.get("pris"):
            print(f"{arg}: дані не знайдено (змінилась верстка або не той артикул?)",
                  file=sys.stderr)
            continue
        print(f"\n=== {arg} — {d.get('namn','?')}")
        print(f"  Ціна: {d['pris']}")
        print(f"  OE:   {d.get('OE','— не вказано')}")
        for n, v in d["_props"]:
            print(f"  · {n:22} {v}")


if __name__ == "__main__":
    main()
