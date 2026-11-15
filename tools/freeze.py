#!/usr/bin/env python3
"""Заморожує джерело в raw/ — щоб перевіряти твердження проти збереженої копії.

Навіщо: половина каталогів нам недоступна (PartSouq, exist.ua, autodoc — 403), а ті,
що доступні, завтра можуть змінити верстку або зникнути. Твердження «фільтр
11428507683», підкріплене живим посиланням, через місяць стає непідтвердженим.
Помилка в артикулі коштує двох тижнів простою машини — тож доказ має лежати в репо.

Два режими:

    # 1. Сторінка, до якої є доступ — завантажити й заморозити
    uv run tools/freeze.py https://www.mann-filter.com/.../c51001_mann-filter.html \\
        --source mann-filter --slug c51001

    # 2. Файл, який оператор зберіг руками (PartSouq, exist.ua — за Cloudflare)
    uv run tools/freeze.py ~/Downloads/partsouq.mhtml \\
        --source partsouq --slug oil-11428507683 --url https://partsouq.com/...

    # 3. Сторінка PDF-мануала як малюнок (моменти й мітки часто тільки на малюнку) — для HTML гайда
    uv run tools/freeze.py https://…/m_14_0044.pdf --page 4 \\
        --source workshop-manuals --slug toyota-rm-dr201e-img-grm-14-47

Сторінку за URL зберігає як **MHTML разом із картинками** (малюнки мануалів із моментами
відкриваються офлайн у браузері); `--no-assets` — голий HTML.

Кладе у `raw/<source>/<slug>_<дата>.<ext>` плюс `.txt` із видобутим текстом —
саме по .txt працює механічна звірка `tools/verify_values.py`.
Записує рядок у `raw/MANIFEST.tsv`: шлях, URL, дата, sha256, спосіб отримання.

Формати, з яких видобувається текст: HTML, MHTML (збережене «як веб-архів»),
PDF (якщо є `pdftotext`). З PNG/JPG текст не видобувається — скріншот лишається
візуальним доказом, механічно його не звірити. **Тому MHTML кращий за скріншот.**
"""
import argparse
import email
import hashlib
import html as html_mod
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

RAW = Path("raw")
MANIFEST = RAW / "MANIFEST.tsv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def html_to_text(raw: str) -> str:
    # Видимий текст сторінки
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/div|/tr|/li|/h[1-6])\s*>", "\n", t, flags=re.I)
    t = html_mod.unescape(re.sub(r"<[^>]+>", " ", t))
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    out = [ln.strip() for ln in t.splitlines() if ln.strip()]

    # Дані з <script> — без них губиться головне. Biltema тримає OE-номер,
    # ціну й розміри у вбудованому JSON, а не у видимій розмітці; так само
    # роблять інші магазини. Фікстура без цих значень марна для звірки.
    data = []
    for body in re.findall(r"<script[^>]*>(.*?)</script>", raw, flags=re.S | re.I):
        if '{"' in body and '":' in body:
            d = html_mod.unescape(body).replace("\xa0", " ")
            d = re.sub(r"\s+", " ", d)
            data.append(d)
    if data:
        out.append("")
        out.append("=== ДАНІ З <SCRIPT> (вбудований JSON сторінки) ===")
        out.extend(data)
    return "\n".join(out)


def mhtml_to_text(data: bytes) -> str:
    msg = email.message_from_bytes(data)
    parts = []
    for part in msg.walk():
        if part.get_content_type() in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, "replace")
            parts.append(html_to_text(text) if part.get_content_type() == "text/html"
                         else text)
    return "\n".join(parts)


def pdf_to_text(path: Path) -> str:
    # 1) pdftotext (poppler-utils), 2) PyMuPDF, якщо стоїть (pyproject.toml).
    # Скан без текстового шару дасть порожньо — тоді поруч кладеться ручна розшифровка
    # `<файл>.transcript.txt` (див. raw/README.md), і посилатися в документі на неї.
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                           capture_output=True, text=True)
        if r.stdout.strip():
            return r.stdout
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError:
        try:
            import fitz as pymupdf  # noqa: PLC0415  старіша назва
        except ImportError:
            return ""
    with pymupdf.open(str(path)) as doc:
        return "\n".join(page.get_text() for page in doc)


def fetch(url: str, timeout: int = 40):
    # workshop-manuals.com на повний Chrome-UA віддає 403, на короткий — 200 (_ai/lessons.md, 2026-10-24)
    for ua in (UA, "Mozilla/5.0"):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "en,sv;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get_content_type(), r.headers.get_content_charset()
        except urllib.error.HTTPError as e:
            if e.code != 403 or ua != UA:
                raise


IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def build_mhtml(url: str, body: bytes, charset: str | None, timeout: int = 30) -> tuple[bytes, int]:
    """Сторінка + її картинки одним файлом MHTML — щоб відкрити в браузері офлайн, з малюнками.

    Навіщо: у мануалах моменти й мітки часто тільки на малюнку, а текстова копія їх губить.
    MHTML відкривається в Chrome/Edge, `mhtml_to_text` видобуває з нього текст для звірки.
    Тягнемо лише картинки (не CSS/JS): вони й несуть зміст, а вага лишається помірною."""
    from email.mime.base import MIMEBase  # noqa: PLC0415
    from email.mime.multipart import MIMEMultipart  # noqa: PLC0415
    from email import encoders  # noqa: PLC0415

    if not charset:
        m = re.search(rb'charset=["\']?([\w-]+)', body[:4000], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    page = body.decode(charset, "replace")
    refs = re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', page, re.I)
    refs += re.findall(r"enlarge\(['\"]([^'\"]+)['\"]\)", page)  # mmc-manuals: збільшені малюнки
    urls = []
    for ref in refs:
        absu = urllib.parse.urljoin(url, html_mod.unescape(ref))
        if Path(urllib.parse.urlparse(absu).path).suffix.lower() in IMG_EXT and absu not in urls:
            urls.append(absu)

    root = MIMEMultipart("related", type="text/html")
    root["Subject"] = url
    main = MIMEBase("text", "html", charset=charset)
    main.set_payload(body)
    encoders.encode_quopri(main)
    main["Content-Location"] = url
    root.attach(main)
    total, n = len(body), 0
    for u in urls[:80]:
        try:
            data, ctype, _ = fetch(u, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — одна битa картинка не причина зупиняти заморожування
            print(f"  ⚠ картинка не завантажилась: {u} ({e})")
            continue
        if not ctype.startswith("image/") or len(data) > 5_000_000 or total + len(data) > 20_000_000:
            continue
        maintype, subtype = ctype.split("/", 1)
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        part["Content-Location"] = u
        root.attach(part)
        total += len(data)
        n += 1
    return root.as_bytes(), n


def heic_to_jpg(src: Path, dest: Path) -> bool:
    """Фото з iPhone (HEIC) → JPG ≤1800 px. Потрібні pillow + pillow-heif (pyproject.toml).

    JPG, бо HEIC не відкривається ні в браузері, ні в переглядачі на Linux — доказ, який
    ніхто не може відкрити, не доказ."""
    try:
        import pillow_heif  # noqa: PLC0415
        from PIL import Image, ImageOps  # noqa: PLC0415
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    im = ImageOps.exif_transpose(Image.open(src))
    im.thumbnail((1800, 1800))
    im.convert("RGB").save(dest, quality=90)
    return True


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        return html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    if suffix in (".mhtml", ".mht", ".eml"):
        return mhtml_to_text(path.read_bytes())
    if suffix == ".pdf":
        return pdf_to_text(path)
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def suspicious(text: str) -> str:
    """Причина, чому видобутий текст — не джерело, а заглушка. Порожній рядок — усе гаразд.

    Рядок «Checking your Browser» сам по собі нічого не означає: PartSouq вшиває віджет
    Cloudflare у кожну сторінку, і в нормальних схемах він теж є. Тому дивимось на зміст.
    """
    head = text[:300]
    if re.search(r"Just a moment|Attention Required|Verify you are human", head, re.I):
        return "сторінка-перевірка Cloudflare замість змісту — збережи ще раз, коли сторінка відкриється"
    if "Parts and callouts for this diagram" in text and "QTY:" not in text.upper():  # Mitsubishi — «QTY:», Toyota — «Qty:»
        return ("схема PartSouq без жодної позиції — або сторінка не довантажилась, "
                "або це лише ілюстрація без деталей. Артикулів тут нема, звіряти нема з чим")
    return ""


def register(path: Path, url: str, how: str):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        MANIFEST.write_text("шлях\tдата\tsha256\tспосіб\tURL\n", encoding="utf-8")
    rows = MANIFEST.read_text(encoding="utf-8").splitlines()
    rows = [r for r in rows if not r.startswith(str(path) + "\t")]
    rows.append(f"{path}\t{date.today().isoformat()}\t{digest}\t{how}\t{url}")
    MANIFEST.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return digest


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="URL або шлях до збереженого файлу")
    ap.add_argument("--source", required=True,
                    help="звідки: mann-filter, partsouq, elcats, workshop-manuals, baza-gai…")
    ap.add_argument("--slug", required=True, help="коротка назва: c51001, oil-11428507683")
    ap.add_argument("--url", default="", help="оригінальний URL (для режиму файлу)")
    ap.add_argument("--no-assets", action="store_true",
                    help="сторінку за URL зберегти голим HTML, без картинок (за замовчуванням — MHTML з картинками)")
    ap.add_argument("--page", type=int, default=0,
                    help="PDF: зберегти сторінку N (з 1) як PNG-малюнок; URL у MANIFEST — <url>#page=N. "
                         "Текст PDF — окремою фікстурою самого PDF")
    ap.add_argument("--force", action="store_true",
                    help="заморозити, навіть якщо сторінка схожа на заглушку")
    ap.add_argument("--how", default="",
                    help="як отримано файл (режим файлу), у MANIFEST: напр. «виписка Claude in Chrome», «кадр з відео». "
                         "За замовчуванням — «вручну оператором»")
    ap.add_argument("--timeout", type=int, default=40,
                    help="секунд на сторінку (workshop-manuals.com буває відповідає хвилину й довше)")
    args = ap.parse_args()

    out_dir = RAW / args.source
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    if args.target.startswith("http"):
        try:
            body, ctype, charset = fetch(args.target, timeout=args.timeout)
        except Exception as e:
            print(f"✗ не завантажилось: {e}", file=sys.stderr)
            print("  Якщо це 403 — відкрий у браузері, збережи як MHTML "
                  "і запусти цей скрипт на файлі з --url", file=sys.stderr)
            sys.exit(2)
        # Розширення — з URL, якщо це не сторінка: картинку чи PDF у .html не зберігати
        ext = Path(urllib.parse.urlparse(args.target).path).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".txt"):
            ext = ".html"
        if ext == ".html" and ctype == "text/html" and not args.no_assets:
            body, n_img = build_mhtml(args.target, body, charset, args.timeout)
            ext = ".mhtml"
            print(f"  MHTML: сторінка + {n_img} картинок")
        dest = out_dir / f"{args.slug}_{today}{ext}"
        dest.write_bytes(body)
        url, how = args.target, "curl"
    else:
        src = Path(args.target).expanduser()
        if not src.exists():
            print(f"✗ файлу немає: {src}", file=sys.stderr)
            sys.exit(2)
        dest = out_dir / f"{args.slug}_{today}{src.suffix.lower()}"
        if src.suffix.lower() in (".heic", ".heif"):
            dest = dest.with_suffix(".jpg")
            if not heic_to_jpg(src, dest):
                print("✗ HEIC не конвертувався: потрібні pillow і pillow-heif "
                      "(запускати через uv run — залежності з pyproject.toml)", file=sys.stderr)
                sys.exit(2)
            print(f"  HEIC → JPG: {src.name}")
        else:
            dest.write_bytes(src.read_bytes())
        url, how = args.url or "(не вказано)", args.how or "вручну оператором"

    if args.page:
        if dest.suffix != ".pdf":
            dest.unlink()
            sys.exit("✗ --page — лише для PDF")
        try:
            import pymupdf  # noqa: PLC0415
        except ImportError:
            try:
                import fitz as pymupdf  # noqa: PLC0415  старіша назва
            except ImportError:
                dest.unlink()
                sys.exit("✗ для --page потрібен pymupdf (запускати через uv run — залежності з pyproject.toml)")
        pdf = dest
        with pymupdf.open(str(pdf)) as doc:
            if not 1 <= args.page <= len(doc):
                pdf.unlink()
                sys.exit(f"✗ у PDF {len(doc)} стор., --page {args.page} поза межами")
            png = doc[args.page - 1].get_pixmap(dpi=110).tobytes("png")
        pdf.unlink()
        dest = dest.with_suffix(".png")
        dest.write_bytes(png)
        url = f"{url}#page={args.page}"
        how = f"{how}, стор. {args.page} PDF → PNG"
        digest = register(dest, url, how)
        print(f"✓ {dest}  ({dest.stat().st_size} b, sha256:{digest}, {how})")
        print("  Малюнок сторінки — для гайда й HTML. Текст для звірки — фікстура самого PDF (без --page).")
        return

    text = extract(dest)
    why = suspicious(text)
    if why and not args.force:
        dest.unlink()
        print(f"✗ не заморожено: {why}", file=sys.stderr)
        print("  Якщо впевнений, що це правильне джерело, — --force", file=sys.stderr)
        sys.exit(3)
    if why:
        print(f"⚠ заморожено з --force попри: {why}")
    txt_path = dest.with_suffix(".txt")
    if dest.suffix == ".txt":
        txt_path = dest  # уже текст — другий .txt поверх нього не пишемо
    elif text.strip():
        txt_path.write_text(text, encoding="utf-8")
    else:
        txt_path = None

    digest = register(dest, url, how)
    print(f"✓ {dest}  ({dest.stat().st_size} b, sha256:{digest}, {how})")
    if txt_path:
        print(f"✓ {txt_path}  ({len(text)} символів тексту)")
    else:
        print("⚠ текст не видобувся — механічна звірка по цьому файлу неможлива.")
        if dest.suffix in (".png", ".jpg", ".jpeg", ".gif"):
            print("  Для малюнка чи фото це нормально: лишається візуальним доказом.")
        else:
            print("  Перевір формат: для сторінки потрібен HTML/MHTML; для PDF — pdftotext або pymupdf.")
    downloads = Path("downloads").resolve()
    if not args.target.startswith("http") and downloads in src.resolve().parents:
        # downloads/ — проміжна тека, після заморозки оригінал прибирає оператор (CLAUDE.md)
        print(f"  Оригінал заморожено — прибрати з downloads/:\n  rm -v {shlex.quote(str(src.resolve()))}")


if __name__ == "__main__":
    main()
