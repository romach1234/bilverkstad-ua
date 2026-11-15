#!/usr/bin/env python3
"""Витягує зі збереженої сторінки груп PartSouq (MHTML) прямі посилання на схеми.

PartSouq за Cloudflare — схеми відкриває тільки оператор у браузері. Щоб не шукати
кожну схему руками, скрипт дає список «назва схеми → посилання», який можна
віддати оператору на збереження.

Використання:
    uv run tools/partsouq_links.py raw/partsouq/<сторінка-груп>.mhtml
    uv run tools/partsouq_links.py <файл.mhtml> --grep "water pump|belt"   # фільтр за назвою (regex, без регістру)
"""
import argparse
import email
import html
import re
import sys


def page_html(path):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8", "replace")
    sys.exit(f"{path}: у MHTML немає text/html")


def text_of(fragment):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragment, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [l.strip() for l in t.splitlines() if l.strip()]


def diagrams(page):
    """[(назва, опис, url)] — по одному на кожне унікальне посилання /partcatalog/diagram/."""
    out, seen = [], set()
    # кожне посилання на схему — <a href=".../diagram/...">…</a>; назва й опис стоять
    # у тексті між цим посиланням і наступним
    links = list(re.finditer(r'<a[^>]+href="([^"]*/partcatalog/diagram/[^"]*)"', page))
    for i, m in enumerate(links):
        url = html.unescape(m.group(1))
        if url in seen:
            continue
        seen.add(url)
        end = links[i + 1].start() if i + 1 < len(links) else m.end() + 3000
        lines = text_of(page[m.start():end])
        title = lines[0] if lines else "?"
        desc = next((l for l in reversed(lines) if l.isupper() or "ALL" in l), "")
        out.append((title, desc, url))
    if out:
        return out
    # Toyota: плитки <a class="diagram-tile" href=".../catalog/toyota/diagram/...">, номер і назва — у
    # diagram-id / diagram-name. URL без токена сесії, тож інші категорії (Chassis…) теж за посиланням нижче
    for m in re.finditer(r'<a[^>]+class="diagram-tile"[^>]+href="([^"]+)"(.*?)</a>', page, re.S):
        url = html.unescape(m.group(1))
        if url in seen:
            continue
        seen.add(url)
        did = re.search(r'diagram-id">([^<]*)<', m.group(2))
        name = re.search(r'diagram-name">([^<]*)<', m.group(2))
        out.append((did.group(1).strip() if did else "?", html.unescape(name.group(1).strip()) if name else "", url))
    return out


def categories(page):
    """Посилання на основні групи каталогу — щоб за схемами з іншої групи не ходити по сайту.
    Toyota: категорії Engine / Chassis / Body / Electrical. Mitsubishi та інші `partcatalog`: групи `groupId=…`
    (Engine, Brake system, Electrical…) — у посиланні лише параметри VIN, без токена сесії."""
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]*/catalog/toyota/vehicle/[^"]*/category/\d+/[^"]*)"[^>]*>(.*?)</a>', page, re.S):
        url = html.unescape(m.group(1))
        if "/en/" in url and "#" not in url:
            out.setdefault(url, " ".join(text_of(m.group(2))))
    for m in re.finditer(r'<a[^>]+href="([^"]*/partcatalog/groups/[^"]*groupId=[^"]*)"[^>]*>(.*?)</a>', page, re.S):
        url = html.unescape(m.group(1))
        name = " ".join(text_of(m.group(2)))
        if "#" in url or not name or name in ("Previous", "Next", "Login", "Register") or re.search(r"[?&]page=", url):
            continue
        out.setdefault(url, name)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mhtml")
    ap.add_argument("--grep", help="regex по назві й опису схеми")
    a = ap.parse_args()
    found = diagrams(page_html(a.mhtml))
    if a.grep:
        rx = re.compile(a.grep, re.I)
        found = [d for d in found if rx.search(d[0] + " " + d[1])]
    if not found:
        sys.exit("Посилань на схеми не знайдено (це сторінка груп? верстка змінилась?)")
    for title, desc, url in found:
        print(f"- {title} — {desc}\n  {url}")
    cats = categories(page_html(a.mhtml))
    if cats:
        print("\nОсновні групи каталогу (кожна — окрема сторінка схем):")
        for url, name in cats.items():
            print(f"- {name}\n  {url}")
    # сторінки груп пагіновані: наступна сторінка — окремий файл
    nxt = re.search(r'<a[^>]+href="([^"]*/partcatalog/groups/[^"]*page=\d+[^"]*)"[^>]*>\s*Next', page_html(a.mhtml))
    if nxt:
        print(f"\nЄ наступна сторінка груп — теж зберегти:\n  {html.unescape(nxt.group(1))}")


if __name__ == "__main__":
    main()
