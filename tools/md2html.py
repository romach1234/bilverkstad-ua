#!/usr/bin/env python3
"""Markdown → один HTML-файл для читання з телефона.

Навіщо: гайд у `.md` писаний для git і верифікатора — з шляхами `raw/...`, посиланнями
на малюнки замість самих малюнків. Механік біля машини читає з телефона, часто без
інтернету. Цей скрипт робить із `.md` один самодостатній `.html`: малюнки вбудовані,
службові шляхи сховані, таблиці гортаються, тема — за налаштуваннями телефону.

`.md` лишається оригіналом. HTML — похідний, руками не правиться.

    uv run tools/md2html.py guides/mitsubishi-4d56-remin-grm-pompa.md            # → поруч .html
    uv run tools/md2html.py <файл.md> -o <файл.html>
    uv run tools/md2html.py cars/<номер>/export/x.en.md --lang en   # переклад для клієнта: підписи англійською

`--lang` — мова документа (uk за замовчуванням; en, sv, de, pl, ru, …): атрибут `lang`, службові підписи
й розпізнавання розділу джерел («Джерела» / «Sources» / «Källor» / «Quellen» …). Невідома мова — підписи англійською.

Що робить понад звичайне перетворення:
- **Якорі.** Кожен h2–h4 має id як на GitHub (`#доступ-hilux`), тож внутрішні посилання `[…](#…)` працюють і тут;
  згорнутий розділ із ціллю розгортається сам
- **Малюнки.** Посилання на картинку (`[малюнок AC502914](https://…png)` або на `raw/…png`)
  стає самим малюнком у тексті, дотик — на весь екран. Картинка береться із замороженої
  копії в `raw/` (URL → файл через `raw/MANIFEST.tsv`), інтернет не потрібен
- **Шляхи `raw/…`** у тексті прибираються — людині вони не потрібні. У розділі «Джерела» лишаються
- **YouTube** — картка з прев'ю, якщо прев'ю заморожене в `raw/` (`https://img.youtube.com/vi/<id>/hqdefault.jpg`).
  Посилання з таймкодом (`&t=487s`) — це відео прямо в кроці: компактна кнопка «▶ …» без картки
- Зверху — швидкі переходи по розділах; «Джерела» згорнуті

Потрібен пакет `markdown` (є в `pyproject.toml`, запускати через `uv run`).
"""
import argparse
import base64
import html
import mimetypes
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:  # guides_to_cars.py перевіряє це сам і пропускає HTML
    markdown = None


def repo_root(start: Path) -> Path:
    for d in (start.resolve(), *start.resolve().parents):
        if (d / "raw").is_dir() and (d / "tools").is_dir():
            return d
    return Path.cwd()


def manifest_map(root: Path) -> dict[str, Path]:
    """URL → заморожений файл."""
    out = {}
    mf = root / "raw" / "MANIFEST.tsv"
    if mf.exists():
        for line in mf.read_text(encoding="utf-8").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 5 and cols[4].startswith("http"):
                out[cols[4]] = root / cols[0]
    return out


IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
RAW_SPAN = r"`raw/[^`\n]+`"
SOURCES_WORDS = r"(?:Джерела|Sources|Källor|Quellen|Источники|Źródła|Kilder|Lähteet)"
SOURCES_RE = re.compile(r"^#{1,6}\s*" + SOURCES_WORDS, re.M)

# Службові підписи HTML; невідома мова — англійські
LABELS = {
    "uk": {"not_frozen": "(малюнок не заморожений — лише онлайн)",
           "footer": "Згенеровано з <code>{rel}</code> — правити .md, не цей файл."},
    "en": {"not_frozen": "(image available online only)",
           "footer": "Translated from Ukrainian workshop notes ({rel})."},
    "sv": {"not_frozen": "(bilden finns bara online)",
           "footer": "Översatt från verkstadens anteckningar på ukrainska ({rel})."},
    "de": {"not_frozen": "(Bild nur online verfügbar)",
           "footer": "Übersetzt aus ukrainischen Werkstattnotizen ({rel})."},
}


def labels(lang: str) -> dict:
    return LABELS.get(lang, LABELS["en"])


def strip_raw_paths(md: str) -> str:
    """Прибрати `raw/…` з тексту, лишивши розділ «Джерела» як є."""
    m = SOURCES_RE.search(md)
    body, tail = (md[:m.start()], md[m.start():]) if m else (md, "")
    body = re.sub(r"\(\s*" + RAW_SPAN + r"\s*\)", "", body)              # «(`raw/…`)»
    body = re.sub(r"\s*[—–-]\s*" + RAW_SPAN + r"(?=\s*[);,.\n])", "", body)  # «— `raw/…`»
    body = re.sub(RAW_SPAN + r"\s*[;,]\s*", "", body)                    # «`raw/…`; далі»
    body = re.sub(r"[;,]\s*" + RAW_SPAN, "", body)                       # «…; `raw/…`»
    body = re.sub(RAW_SPAN, "", body)
    # Рядки таблиць, де колонка «Джерело» спорожніла, лишаються з порожньою клітинкою — це нормально.
    body = re.sub(r"\(\s*[,;]?\s*\)", "", body)
    body = re.sub(r"[ \t]+([,;.)])", r"\1", body)
    return body + tail


def escape_angles(md: str) -> str:
    """`<<A>>`, `>>B<<` з мануалів markdown прийняв би за HTML-тег `<A>` — і показав би `<>`.
    У наших .md сирого HTML немає, тож `<` екрануємо скрізь, крім коду й автопосилань `<https://…>`."""
    parts = re.split(r"(`[^`\n]*`)", md)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"<(?!https?:)", "&lt;", parts[i])
        parts[i] = re.sub(r"(?<=\w)>>|>>(?=\w)", "&gt;&gt;", parts[i])
    return "".join(parts)


def data_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([\w-]{11})", url)
    return m.group(1) if m else None


def embed_media(body: str, md_path: Path, root: Path, frozen: dict[str, Path], lang: str = "uk") -> str:
    def local(href: str) -> Path | None:
        href = html.unescape(href)
        if href.startswith("http"):
            return frozen.get(href)
        p = (md_path.parent / href).resolve()
        if p.exists():
            return p
        p = root / href  # шляхи `raw/…` пишуться від кореня репо
        return p if p.exists() else None

    def repl(m: re.Match) -> str:
        href, text = m.group(1), m.group(2)
        vid = youtube_id(html.unescape(href))
        if vid and re.search(r"[?&]t=\d", html.unescape(href)):
            # відео з таймкодом — посилання прямо в кроці: компактно, без картки, щоб не роздувати порядок робіт
            return f'<a class="vt" href="{href}">▶ {text}</a>'
        if vid:
            thumb = frozen.get(f"https://img.youtube.com/vi/{vid}/hqdefault.jpg")
            uri = data_uri(thumb) if thumb else None
            img = f'<img src="{uri}" alt="">' if uri else '<span class="play">▶</span>'
            return f'<a class="video" href="{href}">{img}<span>{text}</span></a>'
        if not html.unescape(href).lower().split("?")[0].endswith(IMG_EXT):
            return m.group(0)
        p = local(href)
        uri = data_uri(p) if p else None
        if not uri:
            return m.group(0) + f" <small>{labels(lang)['not_frozen']}</small>"
        return (f'<figure><img class="zoom" src="{uri}" alt="{html.escape(text)}">'
                f'<figcaption><a href="{href}">{text}</a></figcaption></figure>')

    return re.sub(r'<a href="([^"]+)">(.*?)</a>', repl, body)


def github_slug(text: str) -> str:
    """Якір заголовка, як у GitHub / VS Code: нижній регістр, лише літери, цифри, «-» і «_», пробіли → «-».
    Тоді посилання `[розділ](#доступ-hilux)` у .md однаково працює і на GitHub, і в HTML для телефона."""
    t = html.unescape(re.sub(r"<[^>]+>", "", text)).strip().lower()
    t = re.sub(r"[^\w\- ]", "", t)
    return t.replace(" ", "-")


def heading_ids(body: str) -> str:
    """id на кожен h2–h4 (дублі — з суфіксом -1, -2, як у GitHub)."""
    seen: dict[str, int] = {}

    def repl(m: re.Match) -> str:
        slug = github_slug(m.group(2))
        if slug in seen:
            seen[slug] += 1
            slug = f"{slug}-{seen[slug]}"
        else:
            seen[slug] = 0
        return f'<h{m.group(1)} id="{slug}">{m.group(2)}</h{m.group(1)}>'

    return re.sub(r"<h([234])>(.*?)</h\1>", repl, body, flags=re.S)


def sectionize(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Кожен h2 — згортуваний розділ з якорем; «Джерела» згорнуті за замовчуванням."""
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", body, flags=re.S)
    out, toc, n = [parts[0]], [], 0
    for i in range(1, len(parts), 2):
        title_html = re.sub(r"^<h2[^>]*>|</h2>$", "", parts[i])
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        n += 1
        anchor = f"s{n}"
        toc.append((anchor, re.sub(r"^[^\wА-Яа-яІіЇїЄєҐґ]+", "", title)))
        is_open = "" if re.match(SOURCES_WORDS, title) else " open"
        attrs = re.match(r"<h2([^>]*)>", parts[i]).group(1)
        out.append(f'<details id="{anchor}"{is_open}><summary><h2{attrs}>{title_html}</h2></summary>'
                   f'{parts[i + 1]}</details>')
    return "".join(out), toc


CSS = """
:root{--bg:#fff;--fg:#1b1b1b;--mut:#666;--line:#ddd;--head:#f3f3f3;--acc:#0b63c5;--note:#fff8e1}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#e8e8e8;--mut:#9a9a9a;--line:#333;--head:#1e1e1e;--acc:#6ab0ff;--note:#2a2410}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  -webkit-text-size-adjust:100%}
main{max-width:860px;margin:0 auto;padding:12px 14px 60px}
h1{font-size:1.35em;line-height:1.25;margin:.4em 0 .6em}
h2{font-size:1.15em;margin:0;display:inline}
h3{font-size:1.05em;margin:1.2em 0 .4em}
a{color:var(--acc)}
code{font-size:.9em;background:var(--head);padding:0 .25em;border-radius:3px;word-break:break-word}
nav{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
  display:flex;gap:6px;overflow-x:auto;padding:8px 14px;white-space:nowrap}
nav a{flex:none;text-decoration:none;border:1px solid var(--line);border-radius:16px;padding:4px 10px;font-size:.85em;color:var(--fg)}
details{border-top:1px solid var(--line);padding:10px 0}
summary{cursor:pointer;list-style:none;padding:4px 0}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";color:var(--mut)}
details[open]>summary::before{content:"▾ "}
.tw{overflow-x:auto;margin:.6em 0;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:.92em}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--head);position:sticky;top:0}
blockquote{margin:.8em 0;padding:.5em .8em;background:var(--note);border-left:4px solid #e0b000;border-radius:4px}
li{margin:.25em 0}
ol ol,ul ul,ol ul,ul ol{padding-left:1.3em}
figure{margin:.6em 0}
figure img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:zoom-in}
figcaption{font-size:.8em;color:var(--mut)}
.video{display:flex;gap:10px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px;text-decoration:none;margin:.4em 0}
.video img{width:120px;border-radius:4px}.vt{white-space:nowrap;text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:0 5px}.play{font-size:2em;width:60px;text-align:center}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;z-index:10;overflow:auto}
#lb img{width:100%;min-height:100%;object-fit:contain;background:#fff}
hr{border:0;border-top:1px solid var(--line)}
footer{color:var(--mut);font-size:.8em;margin-top:2em}
"""

JS = """
document.querySelectorAll('img.zoom').forEach(function(i){i.onclick=function(){
  var lb=document.getElementById('lb');lb.firstChild.src=i.src;lb.style.display='block';}});
document.getElementById('lb').onclick=function(){this.style.display='none';};
function openTo(id){var t=document.getElementById(id);for(var e=t;e;e=e.parentElement)if(e.tagName==='DETAILS')e.open=true;return t;}
document.querySelectorAll('a[href^="#"]').forEach(function(a){a.onclick=function(){
  var t=openTo(decodeURIComponent(a.getAttribute('href').slice(1)));if(t){t.scrollIntoView();return false;}}});
if(location.hash){var t=openTo(decodeURIComponent(location.hash.slice(1)));if(t)t.scrollIntoView();}
"""


def convert(md_path: Path, lang: str = "uk") -> str:
    if markdown is None:
        raise RuntimeError("немає пакета markdown: запускати через uv run tools/…")
    root = repo_root(md_path.parent)
    src = md_path.read_text(encoding="utf-8")
    src = re.sub(r"\A(> .*\n)+\n?", "", src) if src.startswith("> **КОПІЯ**") else src
    src = escape_angles(strip_raw_paths(src))
    md = markdown.Markdown(extensions=["tables", "sane_lists"], lazy_ol=False, tab_length=4)  # type: ignore[call-arg]  # lazy_ol: рахувати кроки з «13.», а не з 1
    body = md.convert(src)
    m = re.search(r"<h1>(.*?)</h1>", body, re.S)
    title = re.sub(r"<[^>]+>", "", m.group(1)) if m else md_path.stem
    body = embed_media(body, md_path, root, manifest_map(root), lang)
    body = re.sub(r"(<table>.*?</table>)", r'<div class="tw">\1</div>', body, flags=re.S)
    body = heading_ids(body)
    body, toc = sectionize(body)
    nav = "".join(f'<a href="#{a}">{html.escape(t)}</a>' for a, t in toc)
    rel = md_path.resolve().relative_to(root).as_posix() if md_path.resolve().is_relative_to(root) else md_path.name
    return ("<!doctype html>\n<html lang=\"" + html.escape(lang) + "\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
            f"<nav>{nav}</nav><main>{body}"
            f"<footer>{labels(lang)['footer'].format(rel=html.escape(rel))}</footer>"
            f"</main><div id=\"lb\"><img alt=\"\"></div><script>{JS}</script></body></html>\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--lang", default="uk", help="мова документа: uk (за замовчуванням), en, sv, de, …")
    a = ap.parse_args()
    try:
        out = convert(a.md, a.lang)
    except RuntimeError as e:
        sys.exit(f"✗ {e}")
    dest = a.out or a.md.with_suffix(".html")
    dest.write_text(out, encoding="utf-8")
    print(f"✓ {dest}  ({len(out.encode()) // 1024} КБ)")


if __name__ == "__main__":
    main()
