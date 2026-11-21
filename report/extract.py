#!/usr/bin/env python3
"""Собирает данные для итогового отчёта из репозитория в report/build/data.json.

Таблицы отчёта с записями ADR, операциями HTTP API и сообщениями строятся из этих данных,
поэтому отчёт не может разойтись с журналом решений и спецификациями.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "build" / "data.json"
METHODS = ("get", "post", "put", "patch", "delete")


def short(name: str) -> str:
    """Имя варианта без метки «А.»/«1.» и точки в конце, со строчной буквы."""
    name = re.sub(r"^([А-ЯA-Z]|\d+)\.\s+", "", name.strip())
    name = name.strip().rstrip(".").replace("`", "")
    # после двоеточия и точки с запятой — строчная буква; имена собственные и латиница (RabbitMQ, Ack) не трогаем
    if re.match(r"[А-ЯЁ]([а-яё]|\s)", name):
        name = name[0].lower() + name[1:]
    return name


def variants(text: str) -> str:
    """Рассмотренные варианты из разделов «## Варианты…» записи ADR."""
    groups = []
    for sec in re.finditer(r"^## Варианты(?::[ \t]*([^\n]+))?\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        topic, block = sec.group(1), sec.group(2)
        sub = re.split(r"^([А-ЯЁA-Z][^\n]*):\s*$", block, flags=re.M)
        parts = [(topic, sub[0])] + [(sub[i], sub[i + 1]) for i in range(1, len(sub) - 1, 2)]
        for label, body in parts:
            names = [short(m) for m in re.findall(r"^(?:\d+\.\s+)?\*\*(.+?)\*\*", body, re.M)]
            table = re.search(r"^\|\s*\|(.+)\|\s*$", body, re.M)
            if table:
                names += [short(c) for c in table.group(1).split("|") if c.strip()]
            if names:
                groups.append((f"{label.strip().rstrip(':')[:1].upper()}{label.strip().rstrip(':')[1:]}: " if label else "") + "; ".join(names))
    result = ". ".join(groups)
    return result[:1].upper() + result[1:]


def adrs() -> list[dict]:
    rows = []
    for f in sorted((ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")):
        text = f.read_text(encoding="utf-8")
        title = re.search(r"^# (ADR-\d{4})\. (.+)$", text, re.M)
        status = re.search(r"^- \*\*Статус:\*\* (.+)$", text, re.M)
        date = re.search(r"^- \*\*Дата:\*\* (.+)$", text, re.M)
        if not (title and status and date):
            raise SystemExit(f"{f.name}: нет заголовка, статуса или даты")
        rows.append({"id": title[1], "title": title[2].strip(), "status": status[1].strip(), "date": date[1].strip(),
                     "variants": variants(text)})
    return rows


def operations() -> list[dict]:
    rows = []
    for f in sorted((ROOT / "docs" / "api" / "openapi").glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        for path, item in doc["paths"].items():
            for method, op in item.items():
                if method in METHODS:
                    rows.append({"service": f.stem, "op": f"{method.upper()} {path}", "summary": op.get("summary", "")})
    return rows


def messages() -> list[dict]:
    doc = yaml.safe_load((ROOT / "docs" / "api" / "asyncapi" / "events.yaml").read_text(encoding="utf-8"))
    send: dict[str, list[str]] = {}
    recv: dict[str, list[str]] = {}
    for op in doc["operations"].values():
        cid = op["channel"]["$ref"].rsplit("/", 1)[-1]
        owners = [t["name"] for t in op.get("tags", [])]
        (send if op["action"] == "send" else recv).setdefault(cid, []).extend(owners)
    rows = []
    for cid, ch in doc["channels"].items():
        desc = ch.get("description", "")
        kind = "команда" if "**Команда**" in desc else "событие"
        to = ", ".join(recv.get(cid, []))
        queue = re.search(r"очередь `([^`]+)`", desc)
        if queue:
            to += f" (очередь {queue.group(1)})"
        rows.append({"key": ch["address"], "kind": kind, "from": ", ".join(send.get(cid, [])), "to": to})
    return rows


def versions() -> dict:
    v = {}
    for f in sorted((ROOT / "docs" / "api" / "openapi").glob("*.yaml")):
        v["openapi"] = yaml.safe_load(f.read_text(encoding="utf-8"))["openapi"]
    v["asyncapi"] = yaml.safe_load((ROOT / "docs" / "api" / "asyncapi" / "events.yaml").read_text(encoding="utf-8"))["asyncapi"]
    return v


def counts() -> dict:
    arc = sorted((ROOT / "docs" / "arc42").glob("*.md"))
    diagrams = sum(f.read_text(encoding="utf-8").count("```mermaid") for f in arc)
    return {"arc42_sections": len(arc), "diagrams": diagrams}




def _flatten_md(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[`*]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def services() -> list[dict]:
    """Extract table of services and stored data from arc42 5.3 instead of manual report duplicates."""
    text = (ROOT / "docs/arc42/05-building-blocks.md").read_text(encoding="utf-8")
    section = text.split("## 5.3. Сервисы", 1)[1].split("## 5.4.", 1)[0]
    rows = []
    for match in re.finditer(r"^### 5\.3\.\d+\. ([^\n]+)\n(.*?)(?=^### |\Z)", section, re.M | re.S):
        service = match.group(1).split(' — ')[0].strip()
        body = match.group(2)
        res = re.search(r"\*\*Ответственность\.\*\*\s*(.*?)(?=\n\n|\Z)", body, re.S)
        dat = re.search(r"\*\*Данные:\*\*\s*(.*?)(?=\n\n|\Z)", body, re.S)
        if not res or not dat: raise ValueError(f"Missing responsibility/data in {service}")
        rows.append({"service": service, "responsibility": _flatten_md(res.group(1)), "data": _flatten_md(dat.group(1))})
    if len(rows) != 4: raise ValueError(f"Expected four service descriptions; received {len(rows)}")
    return rows


def risks() -> list[dict]:
    """Extract every risk in arc42, including new privacy and payment risks."""
    text = (ROOT / "docs/arc42/11-risks.md").read_text(encoding="utf-8")
    section = text.split("## 11.1. Риски", 1)[1].split("## 11.2.", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(cells) == 4 and re.fullmatch(r"Р\d+", cells[0]):
            rows.append({"id":cells[0], "risk":_flatten_md(cells[1]), "impact":_flatten_md(cells[2]), "mitigation":_flatten_md(cells[3])})
    if not rows: raise ValueError('No risks extracted from arc42')
    return rows

def main() -> None:
    data = {"adrs": adrs(), "operations": operations(), "messages": messages(), "versions": versions(), "counts": counts(), "services": services(), "risks": risks()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: ADR {len(data['adrs'])}, операций {len(data['operations'])}, "
          f"сообщений {len(data['messages'])}, диаграмм {data['counts']['diagrams']}")


if __name__ == "__main__":
    main()
