#!/usr/bin/env python3
"""Дублює гайди в папки машин, які на них посилаються.

Навіщо: усе по машині має лежати в її папці — відкрив `cars/<номер>/` і маєш і закупку,
і процедуру. Але гайд один на мотор і живе в `guides/`: правки (як після перевірки)
вносяться **тільки там**. Копія в машині — похідна, її перегенеровує цей скрипт.

    uv run tools/guides_to_cars.py           # оновити копії
    uv run tools/guides_to_cars.py --check   # лише перевірити; код 1, якщо копія застаріла

Яку машину стосується гайд — видно з файлів машини: будь-яке посилання на
`guides/<файл>.md` у `cars/<номер>/*.md` (не в `guides/` і не в `export/`).

Поруч із копією — `<файл>.html` для телефона (`tools/md2html.py`): малюнки вбудовані, шляхи `raw/` сховані.
Потрібен `markdown` (`pyproject.toml`, запуск через `uv run`); без нього HTML пропускається з попередженням.

Копія лягає в `cars/<номер>/guides/<файл>.md`, з шапкою «КОПІЯ, не правити» і з
переписаними відносними посиланнями, щоб вони працювали з нового місця.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md2html  # noqa: E402


def repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists() or (d / "guides").is_dir():
            return d
    return p


ROOT = repo_root()
GUIDES = ROOT / "guides"
LINK = re.compile(r"(\]\()(?!https?:|#|mailto:)([^)\s]+)(\))")


def referenced_guides(car: Path) -> set[str]:
    names = set()
    for md in car.glob("*.md"):
        for m in re.finditer(r"guides/([\w.-]+\.md)", md.read_text(encoding="utf-8")):
            # README.md — індекс гайдів, не гайд: посилання на нього з файлу машини не означає копію
            if m.group(1) != "README.md" and (GUIDES / m.group(1)).exists():
                names.add(m.group(1))
    return names


def render(guide: Path, dest: Path) -> str:
    text = guide.read_text(encoding="utf-8")

    def fix(m):
        target = (guide.parent / m.group(2)).resolve()
        try:
            rel = Path(*[".."] * len(dest.parent.relative_to(ROOT).parts)) / target.relative_to(ROOT)
        except ValueError:
            return m.group(0)
        return f"{m.group(1)}{rel.as_posix()}{m.group(3)}"

    src = guide.relative_to(ROOT).as_posix()
    header = (f"> **КОПІЯ** `{src}` — не правити тут. Правки вносити в оригінал, потім\n"
              f"> `uv run tools/guides_to_cars.py`.\n\n")
    return header + LINK.sub(fix, text)


def sync(dest: Path, want: str, check: bool) -> int:
    """Записати або перевірити один похідний файл. Повертає 1, якщо застарілий у режимі --check."""
    have = dest.read_text(encoding="utf-8") if dest.exists() else None
    rel = dest.relative_to(ROOT)
    if have == want:
        print(f"✅ {rel}")
        return 0
    if check:
        print(f"❌ застаріла: {rel}")
        return 1
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(want, encoding="utf-8")
    print(f"✍️  {rel}")
    return 0


def main():
    check = "--check" in sys.argv
    stale = 0
    if md2html.markdown is None:
        print("⚠ немає markdown — HTML для телефона не генерується (запускати через uv run)")
        if check:  # інакше --check каже «актуально» про HTML, якого не перевіряв
            stale += 1
    for car in sorted(p for p in (ROOT / "cars").iterdir() if p.is_dir()):
        for name in sorted(referenced_guides(car)):
            dest = car / "guides" / name
            stale += sync(dest, render(GUIDES / name, dest), check)
            if md2html.markdown is not None:
                html_dest = dest.with_suffix(".html")
                if dest.exists():
                    stale += sync(html_dest, md2html.convert(dest), check)
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
