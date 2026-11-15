#!/usr/bin/env python3
"""Пошук і відбір відео YouTube для гайдів.

Навіщо: механік працює в полі, не в гаражі, — відео до кроку там часто важливіше за текст. А WebSearch
YouTube не індексує, тож шукати треба на самому YouTube. Цей скрипт читає сторінки YouTube без API-ключа.

    uv run tools/youtube.py search "4D56 common rail timing belt" "L200 2013 cambio banda distribucion"
    uv run tools/youtube.py info <id> [<id> …]          # назва, канал, тривалість, дата, опис, розділи
    uv run tools/youtube.py frames <id> [<id> …] -o <аркуш.jpg>   # прев'ю + кадри на 25/50/75 %

    uv run tools/youtube.py transcript <id> [<id> …] [-o <тека>]   # текст ролика з таймкодами

`transcript` — щоб «переглянути» відео без перегляду: що кажуть і на якій хвилині, звірити з мануалом і поставити
таймкоди в кроки. Спершу субтитри самого YouTube (ручні або автоматичні мовою оригіналу) через `yt-dlp` — без ключів,
працює всюди. Субтитрів немає — сказати так у гайді й дивитись кадри (`frames`).

`frames` — щоб відсіяти чуже покоління мотора, не дивлячись відео: на кадрах видно, чи це той мотор, чи в машині
він, чи на стенді. Аркуш відкрити через Read. Потрібен pillow (`pyproject.toml`).

Розділи з `info` — готові таймкоди для посилань у кроках гайда: `[8:07 ремінь B](https://www.youtube.com/watch?v=<id>&t=487s)`.
Прев'ю для HTML заморожувати через `freeze.py` (див. скіл `gaid`). Саме відео не завантажувати.
"""
import argparse
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}


def get(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()


def walk(o, key):
    if isinstance(o, dict):
        if key in o:
            yield o[key]
        for x in o.values():
            yield from walk(x, key)
    elif isinstance(o, list):
        for x in o:
            yield from walk(x, key)


def search(queries: list[str], limit: int) -> None:
    for q in queries:
        print(f"== {q}")
        page = get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)).decode()
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", page)
        if not m:
            print("  (сторінка без ytInitialData — YouTube змінив розмітку або відрізав доступ)")
            continue
        for v in list(walk(json.loads(m.group(1)), "videoRenderer"))[:limit]:
            title = "".join(r["text"] for r in v["title"]["runs"])
            length = v.get("lengthText", {}).get("simpleText", "")
            channel = "".join(r["text"] for r in v.get("ownerText", {}).get("runs", []))
            views = v.get("viewCountText", {}).get("simpleText", "")
            print(f'{v["videoId"]} | {length} | {channel} | {views} | {title}')


def info(ids: list[str]) -> None:
    for vid in ids:
        page = get("https://www.youtube.com/watch?v=" + vid).decode()
        m = re.search(r"var ytInitialPlayerResponse = (\{.*?\});(?:var|</script>)", page)
        if not m:
            print(f"===== {vid} | (не прочиталось)")
            continue
        p = json.loads(m.group(1))
        d = p["videoDetails"]
        date = p.get("microformat", {}).get("playerMicroformatRenderer", {}).get("publishDate", "")[:10]
        print(f'===== {vid} | {d["title"]} | {d["author"]} | {int(d["lengthSeconds"]) // 60} хв | {date}')
        desc = d.get("shortDescription", "").strip()
        if desc:
            print(desc[:1500])
        for title, ms in re.findall(r'"chapterRenderer":\{"title":\{"simpleText":"(.*?)"\},"timeRangeStartMillis":(\d+)', page):
            s = int(ms) // 1000
            print(f"  [{s // 60}:{s % 60:02d}] t={s}s  {title}")


def frames(ids: list[str], out: str) -> None:
    from PIL import Image, ImageDraw

    w, h, cap = 320, 240, 18
    sheet = Image.new("RGB", (4 * w, len(ids) * (h + cap)), "white")
    draw = ImageDraw.Draw(sheet)
    for row, vid in enumerate(ids):
        y = row * (h + cap)
        draw.text((5, y + 2), vid, fill="black")
        for col, name in enumerate(("hqdefault", "hq1", "hq2", "hq3")):
            try:
                im = Image.open(io.BytesIO(get(f"https://img.youtube.com/vi/{vid}/{name}.jpg"))).convert("RGB")
                sheet.paste(im.resize((w, h)), (col * w, y + cap))
            except Exception as e:  # кадр може бути відсутній — решта аркуша все одно корисна
                draw.text((col * w + 5, y + cap + 5), f"{name}: {e}", fill="red")
    sheet.save(out, quality=80)
    print(out)


def mmss(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


TOOLS = Path(__file__).resolve().parent
YTDLP_LOCAL = TOOLS / ".bin" / "yt-dlp"  # .gitignore: бінарник не комітимо, скрипт качає його сам


def ytdlp_bin() -> str:
    """yt-dlp з PATH (uv run — з pyproject.toml), інакше — локальна копія в tools/.bin (качається при першому
    запуску). Нічого поза репо не ставимо."""
    found = shutil.which("yt-dlp")
    if found:
        return found
    if not YTDLP_LOCAL.exists():
        print("yt-dlp немає — качаю в tools/.bin/ …", file=sys.stderr)
        YTDLP_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        YTDLP_LOCAL.write_bytes(get("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"))
        YTDLP_LOCAL.chmod(0o755)
    return str(YTDLP_LOCAL)


def ytdlp(*args: str) -> str:
    r = subprocess.run([ytdlp_bin(), "--no-warnings", *args], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"yt-dlp код {r.returncode}")
    return r.stdout


def youtube_subs(meta: dict) -> tuple[str, list[dict]] | None:
    """Ручні субтитри мовою відео, інакше автоматичні мовою оригіналу (`<мова>-orig`). Одна мова — бо на кілька
    запитів поспіль YouTube відповідає 429."""
    lang = (meta.get("language") or "").split("-")[0]
    manual, auto = meta.get("subtitles") or {}, meta.get("automatic_captions") or {}
    pick = None
    for code in ([lang] if lang else []) + list(manual):
        if code in manual and code != "live_chat":
            pick = (code, manual[code]); break
    if not pick:
        orig = [c for c in auto if c.endswith("-orig")]
        code = orig[0] if orig else (lang if lang in auto else None)
        if code:
            pick = (code + " auto", auto[code])
    if not pick:
        return None
    fmt = next((f for f in pick[1] if f.get("ext") == "json3"), None)
    if not fmt:
        return None
    data = json.loads(get(fmt["url"]))
    segs = []
    for ev in data.get("events", []):
        text = "".join(s.get("utf8", "") for s in ev.get("segs") or []).replace("\n", " ").strip()
        if text:
            segs.append({"start": ev.get("tStartMs", 0) / 1000, "text": text})
    return pick[0], segs


def transcript(ids: list[str], out: str | None) -> None:
    for vid in ids:
        try:
            meta = json.loads(ytdlp("-J", "--skip-download", "--", vid))
            got = youtube_subs(meta)
        except Exception as e:  # один ролик не повинен зупиняти решту
            print(f"===== {vid} | помилка: {e}", file=sys.stderr)
            continue
        if not got:
            print(f"===== {vid} | субтитрів немає — лише кадри (frames)", file=sys.stderr)
            continue
        src, segs = got
        if not segs:
            print(f"===== {vid} | {src}: мови немає — лише музика чи шум", file=sys.stderr)
            continue
        lines, block, t0 = [], [], None
        for s in segs:  # блоки ~20 с: читабельно і таймкод досить точний для посилання &t=
            if t0 is None:
                t0 = s["start"]
            block.append(s["text"])
            if s["start"] - t0 >= 20:
                lines.append(f"[{mmss(t0)}] t={int(t0)}s  " + " ".join(block)); block, t0 = [], None
        if block:
            lines.append(f"[{mmss(t0)}] t={int(t0)}s  " + " ".join(block))
        head = (f"# {meta.get('title')} | {meta.get('channel')} | https://www.youtube.com/watch?v={vid}\n"
                f"# субтитри: {src}; {len(segs)} фрагментів. Автоматичні субтитри помиляються в числах "
                f"і термінах — моменти беремо з мануалу\n")
        text = head + "\n".join(lines) + "\n"
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            dest = Path(out) / f"{vid}.transcript.txt"
            dest.write_text(text, encoding="utf-8")
            print(f"{dest}  ({src}, {len(lines)} блоків)")
        else:
            print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("queries", nargs="+")
    s.add_argument("-n", type=int, default=12)
    i = sub.add_parser("info")
    i.add_argument("ids", nargs="+")
    f = sub.add_parser("frames")
    f.add_argument("ids", nargs="+")
    f.add_argument("-o", required=True)
    tr = sub.add_parser("transcript")
    tr.add_argument("ids", nargs="+")
    tr.add_argument("-o", help="тека для <id>.transcript.txt (без неї — у stdout)")
    a = ap.parse_args()
    if a.cmd == "search":
        search(a.queries, a.n)
    elif a.cmd == "info":
        info(a.ids)
    elif a.cmd == "transcript":
        transcript(a.ids, a.o)
    else:
        if len(a.ids) > 4:
            print("⚠ більше 4 відео на аркуш — дрібно; краще кілька аркушів", file=sys.stderr)
        frames(a.ids, a.o)


if __name__ == "__main__":
    main()
