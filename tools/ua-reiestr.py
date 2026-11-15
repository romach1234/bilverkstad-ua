#!/usr/bin/env python3
"""Авто за номером або VIN з українського реєстру: baza-gai.com.ua, підстраховка — відкриті дані МВС (data.gov.ua).

Використання:
    uv run tools/ua-reiestr.py AA1234BB                 # номер (кирилиця чи латиниця, з пробілами чи без)
    uv run tools/ua-reiestr.py W0LGT5GM2C1097615        # VIN
    uv run tools/ua-reiestr.py AA1234BB --freeze        # і заморозити сторінку в raw/baza-gai/
    uv run tools/ua-reiestr.py AA1234BB --write         # створити cars/<номер>/<марка>-<модель>-<номер>.md
    uv run tools/ua-reiestr.py <VIN> --opendata 2024 2025   # + кВт і дати операцій з відкритих даних МВС за роки

Що дає baza-gai: марку, модель, рік, повний VIN, колір, паливо, кузов, об'єм і історію реєстраційних операцій
(дата, номер, ТСЦ, населений пункт) — без імен власників. **Коду мотора й потужності тут немає** — код мотора з VIN і
таблички (скіл `nove-avto`), потужність — `--opendata` (колонка POWER_KWT). Пробігу реєстр не знає — з одометра.

`--opendata <рік …>` качає річні архіви реєстраційних операцій МВС (50–110 МБ кожен) у кеш поза репо
(`~/.cache/bilverkstad-ua/`, на Windows — `%LOCALAPPDATA%\\bilverkstad-ua\\`) і шукає в них VIN. Роки брати з дат
операцій, які показав baza-gai. Держномерів у відкритих даних з 07.2026 немає — тому пошук лише за VIN.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402

BASE = "https://baza-gai.com.ua"
OPENDATA_API = "https://data.gov.ua/api/3/action/package_show?id=06779371-308f-42d7-895e-5a39833375f0"
CYR2LAT = str.maketrans("АВСЕНІКМОРТХ", "ABCEHIKMOPTX")
VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")


def normalize(q: str) -> tuple[str, str]:
    """('vin' | 'nomer', значення латиницею великими без пробілів)."""
    q = re.sub(r"[\s-]", "", q.upper()).translate(CYR2LAT)
    return ("vin" if VIN_RE.fullmatch(q) else "nomer"), q


def parse(page: str) -> dict:
    car = {}
    m = re.search(r'plate-model-card__content-date-model">\s*(\d{4})', page)
    car["рік"] = m.group(1) if m else ""
    m = re.search(r'plate-model-card__content-title">(.*?)</h4>', page, flags=re.S)
    car["авто"] = " ".join(web.clean(m.group(1)).split()) if m else ""
    m = re.search(r'data-full="([A-Z0-9]{17})"', page)
    car["vin"] = m.group(1) if m else ""
    txt = web.text(page)
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    ops = []
    for i, ln in enumerate(lines):
        if ln in ("Приметы", "Прикмети") and i + 1 < len(lines):
            # перед «Приметы»: «UA», номер, дата (з «Регистрация» між ними на сторінці номера)
            back = lines[max(0, i - 6):i]
            date = next((b for b in reversed(back) if re.fullmatch(r"\d\d\.\d\d\.\d{4}", b)), "")
            plate = next((b for b in reversed(back) if re.fullmatch(r"[A-ZА-Я]{2} ?\d{4} ?[A-ZА-Я]{2}", b)), "")
            j = next((x for x in range(i, min(i + 5, len(lines))) if lines[x] in ("Операция", "Операція")), i + 2)
            op = lines[j + 1] if j + 1 < len(lines) else ""
            if j + 2 < len(lines) and lines[j + 2].startswith("("):  # «( Опер. 308 ,» «ТСЦ 3541 )»
                tail = []
                for x in lines[j + 2:j + 6]:
                    tail.append(x)
                    if x.endswith(")"):
                        break
                op += " " + " ".join(" ".join(tail).split())
            k = next((x for x in range(i, min(i + 20, len(lines))) if lines[x] in ("Адрес", "Адреса")), None)
            addr = lines[k + 1] if k is not None and k + 1 < len(lines) else ""
            ops.append({"дата": date, "номер": plate, "прикмети": lines[i + 1], "операція": op,
                        "адреса": "" if addr in ("-", "UA") else addr})
    car["операції"] = ops
    m = re.search(r"(Не викрадений за станом на|Не числится в угоне на)\s*(\d\d\.\d\d\.\d{4})", txt)
    car["розшук"] = f"не викрадений за станом на {m.group(2)}" if m else ""
    return car


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".cache")
    d = Path(base) / "bilverkstad-ua"
    d.mkdir(parents=True, exist_ok=True)
    return d


def opendata(vin: str, years: list[str]) -> list[dict]:
    meta = json.loads(web.get(OPENDATA_API, timeout=60, expect="resources"))["result"]["resources"]
    out = []
    for y in years:
        res = [r for r in meta if r.get("name", "").lower() == f"reestrtz{y}"]
        if not res:
            print(f"  ⚠ відкриті дані: року {y} немає ({', '.join(sorted(r['name'] for r in meta))})", file=sys.stderr)
            continue
        for r in res:  # 2022 — кілька частин
            dest = cache_dir() / (r["id"] + ".zip")
            if not dest.exists() or dest.stat().st_size < 1000:
                print(f"  качаю {r['name']} ({int(r.get('size') or 0) // 1_000_000} МБ) → {dest}", file=sys.stderr)
                req = urllib.request.Request(r["url"], headers={"User-Agent": web.UA})
                with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
                    while chunk := resp.read(1 << 20):
                        f.write(chunk)
            with zipfile.ZipFile(dest) as z:
                for name in z.namelist():
                    if not name.lower().endswith(".csv"):
                        continue
                    with z.open(name) as raw:
                        head = raw.readline()
                        enc = "utf-8-sig" if head[:3] == b"\xef\xbb\xbf" or _utf8(head) else "cp1251"
                        cols = next(csv.reader([head.decode(enc)], delimiter=";"))
                        cols = [c.strip().strip('"').upper() for c in cols]
                        needle = vin.encode()
                        for line in raw:
                            if needle in line:
                                row = next(csv.reader([line.decode(enc, "replace")], delimiter=";"))
                                out.append({"рік файлу": y, **dict(zip(cols, (v.strip() for v in row)))})
    return out


def _utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def write_car(car: dict, key: str, url: str, frozen: str, od: list[dict]) -> Path:
    brand_model = car["авто"].split()
    slug = web.slugify(" ".join(brand_model[:2])) or "avto"
    folder_name = key.lower() if key and not VIN_RE.fullmatch(key) else slug
    folder = web.REPO / "cars" / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}-{folder_name}.md" if folder_name != slug else folder / f"{slug}.md"
    if path.exists():
        print(f"✗ {path.relative_to(web.REPO)} уже є — не перезаписую", file=sys.stderr)
        return path
    last = car["операції"][0] if car["операції"] else {}
    kw = next((r.get("POWER_KWT") for r in od if r.get("POWER_KWT")), "")
    src = f"[baza-gai]({url})" + (f", `{frozen}`" if frozen else "")
    title_num = key if folder_name != slug else f"VIN …{car['vin'][-6:]}"
    text = f"""# {car['авто'].title()}, {car['рік']} — {title_num}

- **VIN:** `{car['vin']}` — {src}. ПІДТВЕРДИТИ зі скла / техпаспорта
- **Двигун:** {', '.join(last.get('прикмети', '').split(', ')[1::2])}{f', {kw} кВт (відкриті дані МВС)' if kw else ''} — **код мотора невідомий**: з VIN і таблички
- **КПП:**
- **Пробіг:** ПІДТВЕРДИТИ по одометру (реєстр пробігу не знає)
- **Власник / контакт:**
- **Рік випуску:** {car['рік']} — {src}
- **Розшук:** {car['розшук'] or 'не перевірено'}

## Реєстраційні операції

| Дата | Номер | Операція | Населений пункт |
|---|---|---|---|
""" + "".join(f"| {o['дата']} | {o['номер']} | {o['операція']} | {o['адреса']} |\n" for o in car["операції"]) + f"""
## 🔁 Перевірено на машині — наступного разу купувати те саме

| Що | Артикул | Магазин / ID | К-ть | Ціна, дата | Фікстура |
|---|---|---|---|---|---|

## Особливості / відомі болячки

-

## Історія обслуговування

<!-- Нові записи додавати зверху, формат: templates/service-entry.md -->

## Джерела

| Джерело | Що з нього взято | Рівень |
|---|---|---|
| {src} | марка, модель, рік, VIN, паливо, об'єм, операції | 🟡 агрегатор відкритих даних МВС |
""" + ("| відкриті дані МВС, data.gov.ua | потужність, кВт | 🟢 реєстр |\n" if kw else "")
    path.write_text(text, encoding="utf-8")
    print(f"✓ {path.relative_to(web.REPO).as_posix()}")
    return path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", help="номер (AA1234BB, АА 1234 ВВ) або VIN")
    ap.add_argument("--freeze", action="store_true", help="заморозити сторінку baza-gai в raw/baza-gai/")
    ap.add_argument("--write", action="store_true", help="створити файл авто в cars/")
    ap.add_argument("--opendata", nargs="+", metavar="РІК", default=[],
                    help="шукати VIN у відкритих даних МВС за ці роки (кВт, дати операцій)")
    a = ap.parse_args()
    kind, key = normalize(a.query)
    url = f"{BASE}/{kind}/{key}"
    try:
        page = web.get(url, expect="baza-gai", lang="uk")
    except web.FetchError as e:
        web.fail(str(e), e.url, e.status)
        sys.exit(2)
    if "plate-model-card" not in page:  # невідомий номер / VIN — сайт віддає 200 зі сторінкою пошуку
        sys.exit(f"✗ {key}: baza-gai нічого не знайшов — перевір номер / VIN; машина могла не реєструватись в "
                 "Україні (тоді — гілка «номера немає» в nove-avto)")
    car = parse(page)
    if kind == "nomer":
        for o in car["операції"]:
            o["номер"] = o["номер"] or key  # сторінка номера показує номер раз, у шапці
    print(f"# {car['авто']} {car['рік']}\n{url}\n")
    print(f"VIN: {car['vin'] or '— (не знайдено на сторінці)'}")
    if car["розшук"]:
        print(f"Розшук: {car['розшук']}")
    for o in car["операції"]:
        print(f"  {o['дата']:10}  {o['номер']:11}  {o['прикмети']}  · {o['операція']}  · {o['адреса']}")
    frozen = ""
    if a.freeze:
        slug = f"{kind}-{key.lower()}"
        web.freeze(url, "baza-gai", slug)
        frozen = f"raw/baza-gai/{slug}"
    od = []
    if a.opendata:
        vin = car["vin"] or (key if kind == "vin" else "")
        if not vin:
            print("⚠ --opendata: VIN невідомий — пошук у відкритих даних лише за VIN", file=sys.stderr)
        else:
            od = opendata(vin, a.opendata)
            print(f"\nВідкриті дані МВС ({len(od)} записів):")
            for r in od:
                print("  " + " · ".join(f"{k}={v}" for k, v in r.items() if v and k not in ("PERSON",)))
    if a.write:
        write_car(car, key if kind == "nomer" else "", url, frozen, od)


if __name__ == "__main__":
    main()
