#!/usr/bin/env python3
"""workshop-manuals.com — заводські мануали (Škoda, BMW, Nissan …): зміст, пошук розділу, текст сторінки з малюнками.

Використання:
    uv run tools/workshop_manuals.py models skoda
        → моделі марки з адресами змісту
    uv run tools/workshop_manuals.py index skoda/octavia-mk2 --grep "toothed belt" --grep "tdi cr"
        → сторінки змісту, де в назві чи шляху є ВСІ слова (шлях несе мотор: «2.0/81;_103;_125_kw_tdi_cr…»)
    uv run tools/workshop_manuals.py index skoda/octavia-mk2 --chapter 7
        → лише один розділ (номер — як «07 Power unit» на сайті); без --chapter — усі
    uv run tools/workshop_manuals.py read <URL або шлях сторінки>
        → текст сторінки (кроки, моменти) і список малюнків
    uv run tools/workshop_manuals.py read <URL> --freeze --slug skoda-ea189-grm-components
        → і заморозити: сторінку (MHTML) + кожен малюнок окремим файлом — їх вбудовує md2html.py

Мануал — 🟢, якщо він про **той самий мотор** (код, покоління, к-сть клапанів — CLAUDE.md). Сайт буває дуже
повільним (60–90 с, 522/524 — _ai/lessons.md): тайм-аут 120 с і повтори; не дочекались — список посилань оператору,
хай збереже MHTML.
"""
import argparse
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402

BASE = "https://workshop-manuals.com"
TIMEOUT = 120


def full(u: str) -> str:
    if u.startswith("http"):
        return u
    return BASE + "/" + u.strip("/") + "/"


def links(page: str, prefix: str) -> list[tuple[str, str]]:
    out, seen = [], set()
    for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.S):
        h = urllib.parse.unquote(h)
        if h.lower().startswith(prefix.lower()) and h not in seen:  # BMW: у змісті шлях малими літерами
            seen.add(h)
            out.append((h, web.clean(t)))
    return out


def chapters(model: str) -> list[tuple[int, str, str]]:
    """[(номер, назва, шлях змісту розділу)] — розділи йдуть як /fullindex/chapter-<id>/, id не = номер."""
    page = web.get(full(model) + "fullindex/", timeout=TIMEOUT, expect="fullindex")
    out = []
    for path in dict.fromkeys(re.findall(r'href="(/[^"]+/fullindex/chapter-\d+/)', page)):
        out.append((len(out) + 1, "", path))
    names = re.findall(r"(?m)^(\d\d) (.+?) \2: Sections$", web.text(page))  # «07 Power unit Power unit: Sections»
    for k, (n, title) in enumerate(names[:len(out)]):
        out[k] = (int(n), title.strip(), out[k][2])
    return out


def cmd_models(brand: str) -> None:
    url = full(brand)
    page = web.get(url, timeout=TIMEOUT, expect="fullindex")
    rows = [(h, t) for h, t in links(page, f"/{brand}/") if h.endswith("/fullindex/")]
    for h, t in rows:
        print(f"{h.removesuffix('fullindex/').strip('/')} | {t}")
    print(f"— {len(rows)} · {url}")


def cmd_index(model: str, chapter: int, grep: list[str]) -> None:
    model = model.strip("/")
    chs = [c for c in chapters(model) if not chapter or c[0] == chapter]
    if not chs:
        sys.exit(f"✗ розділу {chapter} немає — список: uv run tools/workshop_manuals.py index {model} --grep x")
    words = [g.lower() for g in grep]
    found = 0
    for n, title, path in chs:
        page = web.get(BASE + path, timeout=TIMEOUT, expect="fullindex")
        rows = [(h, t) for h, t in links(page, f"/{model}/")
                if h.count("/") > 4 and "/fullindex/" not in h]
        for h, t in rows:
            hay = (h + " " + t).lower().replace("_", " ")
            if all(w in hay for w in words):
                found += 1
                print(f"[{n:02d}] {t}\n     {BASE}{h}")
    print(f"— {found} сторінок · розділи: " + "; ".join(f"{n:02d} {t}" for n, t, _ in chs))


def cmd_read(target: str, freeze: bool, slug: str) -> None:
    url = full(target)
    page = web.get(url, timeout=TIMEOUT, expect="sheet")
    i = page.find('class="sheet"')
    j = page.find('class="pn pn--bottom"', i)
    j = page.rfind("<", i, j) if j > 0 else len(page)  # обрізати по початку тега, а не посеред «<div class=…»
    body = page[i:j]
    txt = web.text("<div " + body)
    txt = re.sub(r"(?m)^q$\n?", "• ", txt)  # маркери списків сайту — літера q окремим рядком
    title = re.search(r"<title>(.*?)</title>", page, flags=re.S)
    print(f"# {web.clean(title.group(1)) if title else url}\n{url}\n")
    print(txt)
    imgs = []
    for src in re.findall(r'<img[^>]+src="([^"]+)"', body):
        if "/images/" in src and not src.endswith(".gif") and src not in imgs:
            imgs.append(src)
    imgs = [urllib.parse.urljoin(url, s) for s in imgs]
    if imgs:
        print("\nМалюнки:")
        for s in imgs:
            print(f"  {s}")
    if freeze:
        slug = slug or web.slugify(url.rstrip("/").rsplit("/", 1)[-1])[:60]
        web.freeze(url, "workshop-manuals", slug, timeout=TIMEOUT)
        for s in imgs:
            web.freeze(s, "workshop-manuals", f"{slug}-img-{Path(urllib.parse.urlparse(s).path).stem}",
                       timeout=TIMEOUT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("models", "index", "read"))
    ap.add_argument("target", help="models: марка (skoda) · index: марка/модель (skoda/octavia-mk2) · read: URL / шлях")
    ap.add_argument("--chapter", type=int, default=0, help="index: номер розділу")
    ap.add_argument("--grep", action="append", default=[], help="index: слово в назві / шляху (можна кілька)")
    ap.add_argument("--freeze", action="store_true", help="read: заморозити сторінку й малюнки в raw/workshop-manuals/")
    ap.add_argument("--slug", default="", help="read --freeze: назва фікстури (<марка>-<мотор>-<розділ>)")
    a = ap.parse_args()
    try:
        if a.cmd == "models":
            cmd_models(a.target.strip("/"))
        elif a.cmd == "index":
            cmd_index(a.target, a.chapter, a.grep)
        else:
            cmd_read(a.target, a.freeze, a.slug)
    except web.FetchError as e:
        web.fail(str(e), e.url, e.status)
        sys.exit(2)


if __name__ == "__main__":
    main()
