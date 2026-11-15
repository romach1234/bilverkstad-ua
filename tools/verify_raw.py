#!/usr/bin/env python3
"""Перевіряє цілісність фікстур: чи збігається sha256 з raw/MANIFEST.tsv.

Навіщо: фікстура — це доказ. Якщо файл змінився після того, як на нього
посилалися, твердження перестає бути підтвердженим. Git з перетворенням кінців
рядків уже був близький до того, щоб тихо зіпсувати всі фікстури — тому
`.gitattributes` тримає `raw/**` як бінарні, а цей скрипт це контролює.

    uv run tools/verify_raw.py
"""
import hashlib
import sys
from pathlib import Path

def repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists() or (d / "raw").is_dir():
            return d
    return p


MANIFEST = repo_root() / "raw/MANIFEST.tsv"


def main():
    if not MANIFEST.exists():
        print(f"✗ немає {MANIFEST}", file=sys.stderr)
        sys.exit(2)

    ok = bad = missing = 0
    for line in MANIFEST.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path, _, digest = parts[0], parts[1], parts[2]
        p = repo_root() / path
        if not p.exists():
            print(f"🔒 немає файлу: {p}")
            missing += 1
            continue
        have = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if have == digest:
            ok += 1
        else:
            print(f"❌ ЗМІНИВСЯ: {p}\n   манифест {digest}   факт {have}")
            bad += 1

    print(f"\n✅ {ok} цілих · ❌ {bad} змінених · 🔒 {missing} відсутніх")
    if bad:
        print("\nФікстура змінилася після реєстрації. Твердження, що на неї")
        print("посилаються, більше не підтверджені — перезаморозити й перевірити заново.")
    sys.exit(1 if bad or missing else 0)


if __name__ == "__main__":
    main()
