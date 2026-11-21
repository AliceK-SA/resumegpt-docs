#!/usr/bin/env python3
"""Рендерит все диаграммы Mermaid из docs/arc42/*.md в PNG (docs/assets/diagrams/).

Имя файла: <имя раздела>-<номер диаграммы в разделе>.png, например 06-runtime-2.png.
Нужен Mermaid CLI: команда `mmdc` или Node.js (тогда используется npx @mermaid-js/mermaid-cli).
Скрипт также служит проверкой синтаксиса: при ошибке в диаграмме он завершается с кодом 1.

Использование: python scripts/render_diagrams.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "arc42"
OUT = ROOT / "docs" / "assets" / "diagrams"
PUPPETEER_CI = ROOT / "scripts" / "puppeteer-ci.json"  # в CI Chrome запускается без песочницы
BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)


def mmdc_command() -> list[str]:
    if shutil.which("mmdc"):
        return ["mmdc"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@mermaid-js/mermaid-cli@11"]
    sys.exit("Не найден Mermaid CLI: установите Node.js или @mermaid-js/mermaid-cli")


def main() -> int:
    cmd = mmdc_command()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for page in sorted(SRC.glob("*.md")):
            for n, code in enumerate(BLOCK.findall(page.read_text(encoding="utf-8")), 1):
                src = Path(tmp) / f"{page.stem}-{n}.mmd"
                src.write_text(code, encoding="utf-8")
                dst = OUT / f"{page.stem}-{n}.png"
                extra = ["-p", str(PUPPETEER_CI)] if os.environ.get("CI") else []
                res = subprocess.run(
                    cmd + ["-i", str(src), "-o", str(dst), "-b", "white", "-s", "2", "-w", "1400"] + extra,
                    capture_output=True, text=True,
                )
                if res.returncode != 0 or not dst.exists():
                    failed += 1
                    print(f"ОШИБКА {page.name}, диаграмма {n}:\n{res.stderr.strip()}")
                else:
                    print(f"{dst.relative_to(ROOT).as_posix()}")
    print(f"Ошибок: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
