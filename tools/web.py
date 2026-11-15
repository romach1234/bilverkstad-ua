#!/usr/bin/env python3
"""Спільна основа скриптів під сайти: завантажити сторінку, перетворити в текст, заморозити в raw/.

Не запускається сам — його імпортують `mann.py`, `ersatzteile.py`, `elcats.py`, `workshop_manuals.py`.

Що робить замість кожного скрипта окремо:
- браузерний User-Agent, а на 403 — повтор з коротким `Mozilla/5.0` (workshop-manuals.com ріже довгий, _ai/lessons.md);
- повтор на 5xx і обрив (workshop-manuals відповідає 60–90 с і буває 522/524, elcats зрідка віддає порожню сторінку);
- `freeze()` — та сама сторінка в raw/ через `tools/freeze.py`, щоб значення в документі мало фікстуру.

Правило, з якого це виросло, — CLAUDE.md, «Сайт читається скриптом — пишемо під нього скрипт».
"""
import html as html_mod
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
REPO = Path(__file__).resolve().parent.parent


class FetchError(Exception):
    def __init__(self, msg: str, status: int = 0, url: str = ""):
        super().__init__(msg)
        self.url = url
        self.status = status  # 404 — сторінки немає (хибний артикул / URL), а не блок


def get(url: str, timeout: int = 40, tries: int = 3, expect: str = "", lang: str = "en") -> str:
    """Сторінка як текст HTML. `expect` — рядок, який має бути на сторінці: без нього повтор, потім помилка.

    Код 200 нічого не гарантує (car.info віддавав підставні дані з 200 — raw/README.md), тому скрипт, що знає,
    що шукає, передає `expect`.
    """
    last = ""
    for attempt in range(tries):
        for ua in (UA, "Mozilla/5.0"):
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": f"{lang},en;q=0.8"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    body = r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code == 403 and ua == UA:
                    continue  # спробувати короткий UA
                if e.code == 404:
                    raise FetchError(f"{last}: {url}", 404, url) from e
                break  # 5xx / інше — до наступної спроби
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = f"немає відповіді ({getattr(e, 'reason', e)})"
                break
            if expect and expect.lower() not in body.lower():
                last = f"сторінка без очікуваного «{expect}»"
                break
            return body
        if attempt + 1 < tries:
            time.sleep(3 * (attempt + 1))
    raise FetchError(f"{last}: {url}", 0, url)


def text(page: str) -> str:
    """Видимий текст HTML одним рядком на блок."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/div|/tr|/li|/h[1-6]|/td|/th)\s*/?>", "\n", t, flags=re.I)
    t = html_mod.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return "\n".join(ln.strip() for ln in re.sub(r"[ \t]+", " ", t).splitlines() if ln.strip())


def clean(fragment: str) -> str:
    """Шматок HTML → текст в один рядок."""
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def freeze(url: str, source: str, slug: str, timeout: int = 40) -> int:
    """Заморозити сторінку в raw/<source>/ через freeze.py (MHTML з малюнками + .txt + MANIFEST)."""
    cmd = [sys.executable, str(REPO / "tools" / "freeze.py"), url, "--source", source, "--slug", slug,
           "--timeout", str(timeout)]
    return subprocess.run(cmd, cwd=REPO).returncode


def fail(msg: str, url: str = "", status: int = 0) -> None:
    """Повідомлення про збій з наступним кроком — Chrome, потім MHTML (порядок доступу з CLAUDE.md)."""
    print(f"✗ {msg}", file=sys.stderr)
    if status == 404:
        print("  Сторінки немає — перевір написання номера; Chrome тут не допоможе.", file=sys.stderr)
    elif url:
        print(f"  Далі: відкрити через Claude in Chrome {url}\n"
              f"  або оператор зберігає сторінку як MHTML у downloads/ → freeze.py <файл> --url {url}",
              file=sys.stderr)
