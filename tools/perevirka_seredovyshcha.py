#!/usr/bin/env python3
"""Перевірка середовища й джерел — після встановлення і будь-коли потім.

    uv run tools/perevirka_seredovyshcha.py            # середовище + сайти
    uv run tools/perevirka_seredovyshcha.py --env      # лише середовище
    uv run tools/perevirka_seredovyshcha.py --md       # сайти — рядками для kb/dzherela-artykuliv-ta-danych.md

Середовище: Python, git і віддалене репо, бібліотеки з pyproject.toml, pdftotext, deno, кодування консолі.

Сайти — стан **з вашої мережі** (з України може бути інакше, ніж там, де репо збирали):
  ✅ відкривається **і на сторінці є очікуваний текст** (код 200 сам нічого не гарантує) → скрипт
  ⚠️ 403 / Cloudflare / WAF / сторінка без очікуваного тексту → Claude in Chrome; у першій сесії пройти ці сайти
     через Chrome і дописати стан у довідник джерел
  ❌ немає відповіді (гео-блок, блок провайдера, сайт лежить) → лише людина: MHTML у downloads/

Нічого не пише в репо: результат дописати в kb/dzherela-artykuliv-ta-danych.md (колонка «Перевірено» — дата, «з
нашої мережі»).
"""
import argparse
import importlib
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# (назва, що це, URL глибокої сторінки, очікуваний текст, чим читати, якщо ✅)
SITES = [
    ("baza-gai.com.ua", "реєстр: номер / VIN", "https://baza-gai.com.ua/vin/W0LGT5GM2C1097615",
     "plate-model-card", "tools/ua-reiestr.py"),
    ("data.gov.ua", "відкриті дані МВС", "https://data.gov.ua/api/3/action/package_show?id="
     "06779371-308f-42d7-895e-5a39833375f0", "reestrTZ", "tools/ua-reiestr.py --opendata"),
    ("elcats.ru", "ETKA VAG", "https://www.elcats.ru/skoda/", "ToggleNode", "tools/elcats.py"),
    ("catcar.info", "оригінальні каталоги", "https://www.catcar.info/", "catcar", "curl"),
    ("partsouq.com", "каталоги по VIN", "https://partsouq.com/en/search/all?q=11428507683", "11428507683", "—"),
    ("7zap.com", "каталоги, VIN", "https://7zap.com/en/", "7zap", "—"),
    ("realoem.com", "BMW ETK", "https://www.realoem.com/bmw/enUS/partxref?q=11428507683", "11428507683", "curl"),
    ("mann-filter.com", "фільтри MANN, OE", "https://www.mann-filter.com/en/catalog/search-results/product.html/"
     "c27009_mann-filter.html", "OE Numbers", "tools/mann.py"),
    ("der-ersatzteile-profi.de", "TecDoc, пошук по OE", "https://www.der-ersatzteile-profi.de/search?w=11428507683",
     "artikel", "tools/ersatzteile.py"),
    ("exist.ua", "магазин", "https://exist.ua/uk/search/?q=W71275", "W 712", "—"),
    ("avto.pro", "агрегатор продавців", "https://avto.pro/part-w71275-mann-filter/", "712", "—"),
    ("zapchasti.ria.com", "продавці, розбірки", "https://zapchasti.ria.com/uk/", "zapchasti", "—"),
    ("dok.ua", "магазин", "https://dok.ua/result2/query?q=W71275", "712", "—"),
    ("ukrparts.com.ua", "магазин", "https://www.ukrparts.com.ua/search/?q=W71275", "712", "—"),
    ("intercars.com.ua", "магазин", "https://intercars.com.ua/", "intercars", "—"),
    ("elit.ua", "дистриб'ютор", "https://elit.ua/", "elit", "—"),
    ("vladislav.ua", "дистриб'ютор", "https://vladislav.ua/", "vladislav", "—"),
    ("workshop-manuals.com", "заводські мануали", "https://workshop-manuals.com/skoda/", "fullindex",
     "tools/workshop_manuals.py"),
    ("mmc-manuals.ru", "мануали Mitsubishi", "https://mmc-manuals.ru/", "mmc", "curl"),
    ("monolith-publisher.com", "керівництва «Монолит»", "https://monolith-publisher.com/", "monolith", "—"),
    ("drive2.ru", "бортжурнали", "https://www.drive2.ru/", "drive2", "—"),
    ("autoua.net", "форум", "https://autoua.net/", "autoua", "—"),
    ("youtube.com", "відео для гайдів", "https://www.youtube.com/results?search_query=4D56+timing+belt",
     "videoId", "tools/youtube.py"),
    ("biltema.se", "запасне: деталь, OE", "https://www.biltema.se/search?query=2000038020", "biltema",
     "tools/biltema.py"),
]


def probe(url: str, expect: str, timeout: int = 30) -> tuple[str, str]:
    last = ""
    for ua in (UA, "Mozilla/5.0"):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "uk,en;q=0.8"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (401, 403, 429, 503) and ua == UA:
                continue
            return ("⚠️" if e.code in (401, 403, 429, 503) else "❌"), last
        except Exception as e:  # тайм-аут, DNS, обрив — сайт недосяжний з цієї мережі
            return "❌", f"немає відповіді ({getattr(e, 'reason', e)})"
        low = body.lower()
        if "cf-chl" in low or "just a moment" in low or "attention required" in low:
            return "⚠️", "перевірка Cloudflare"
        if expect.lower() not in low:
            last = f"200, але без «{expect}»"
            continue
        return "✅", "200, очікуваний текст є"
    return "⚠️", last


def check_env() -> int:
    bad = 0

    def row(ok, what, note=""):
        nonlocal bad
        mark = {True: "✅", False: "❌", None: "⚪"}[ok]
        bad += ok is False
        print(f"  {mark} {what}{' — ' + note if note else ''}")

    print(f"Середовище ({platform.system()} {platform.release()}, Python {platform.python_version()})")
    row(sys.version_info >= (3, 11), "Python ≥ 3.11", sys.executable)
    git = shutil.which("git")
    row(bool(git), "git", git or "немає — Git for Windows / apt install git")
    if git:
        r = subprocess.run(["git", "-C", str(REPO), "remote", "-v"], capture_output=True, text=True)
        row(bool(r.stdout.strip()) or None, "віддалене репо (origin)",
            r.stdout.split("\n")[0] if r.stdout.strip() else "немає — пам'ять між комп'ютерами не синхронізується "
            "(створити репо на GitHub і `git remote add origin …`)")
    for mod, why in (("markdown", "HTML гайдів для телефона"), ("pymupdf", "текст із PDF"),
                     ("PIL", "фото, кадри відео (pillow)"), ("pillow_heif", "фото з iPhone"),
                     ("yt_dlp", "субтитри YouTube")):
        try:
            importlib.import_module(mod)
            row(True, mod, why)
        except ImportError:
            row(False, mod, f"{why} — запускати через `uv run`, не голим python")
    row(bool(shutil.which("pdftotext")) or None, "pdftotext",
        "є" if shutil.which("pdftotext") else "необов'язково: є pymupdf")
    row(bool(shutil.which("deno")) or None, "deno",
        "є" if shutil.which("deno") else "необов'язково: без нього YouTube може віддати лише автодубляж")
    enc = (sys.stdout.encoding or "").lower()
    row("utf" in enc, "кодування виводу", enc or "?")
    for d in ("cars", "downloads", "raw", "kb", "guides"):
        row((REPO / d).is_dir(), f"тека {d}/")
    return bad


def check_sites(md: bool) -> None:
    print(f"\nДжерела з цієї мережі, {date.today().isoformat()} (паралельно, до ~60 с)")
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda s: probe(s[2], s[3], timeout=60 if "workshop" in s[0] else 30), SITES))
    for (name, what, url, _, tool), (mark, note) in zip(SITES, res):
        if md:
            print(f"| {name} | {what} | {mark} {tool if mark == '✅' else ''} | {date.today().isoformat()}, з нашої "
                  f"мережі: {note} |")
        else:
            print(f"  {mark} {name:26} {what:24} {note}" + (f" → {tool}" if mark == "✅" and tool != "—" else ""))
    warn = [s[0] for s, r in zip(SITES, res) if r[0] == "⚠️"]
    if warn and not md:
        print("\n⚠️ — у першій сесії попросити Claude: «пройди сайти з ⚠️ через Claude in Chrome і допиши стан у "
              "довідник джерел»: " + ", ".join(warn))


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", action="store_true", help="лише середовище")
    ap.add_argument("--md", action="store_true", help="сайти — рядками Markdown для довідника джерел")
    a = ap.parse_args()
    bad = 0 if a.md else check_env()
    if not a.env:
        check_sites(a.md)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
