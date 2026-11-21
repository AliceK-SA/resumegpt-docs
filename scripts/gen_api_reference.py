#!/usr/bin/env python3
"""Генерирует справочник API в Markdown из спецификаций OpenAPI и AsyncAPI.

Использование:
    python scripts/gen_api_reference.py          # перезаписать docs/api/*.md
    python scripts/gen_api_reference.py --check  # только проверить, что файлы актуальны (для CI)

Сгенерированные страницы не правятся вручную: правится спецификация, затем запускается скрипт.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "docs" / "api"
OPENAPI = [
    ("analysis-service", API_DIR / "openapi" / "analysis-service.yaml"),
    ("billing-service", API_DIR / "openapi" / "billing-service.yaml"),
    ("payment-service", API_DIR / "openapi" / "payment-service.yaml"),
]
ASYNCAPI = API_DIR / "asyncapi" / "events.yaml"
HEADER = "<!-- Файл сгенерирован scripts/gen_api_reference.py из {src}. Не редактируйте вручную. -->\n\n"
METHODS = ("get", "post", "put", "patch", "delete")


LIST_RE = re.compile(r"^([-*+]|\d+[.)])\s")


def md_block(text: str | None) -> str:
    """Нормализует Markdown из описаний спецификации: пустые строки вокруг списков и блоков кода."""
    if not text:
        return ""
    src = text.strip().split("\n")
    out: list[str] = []
    in_code = False
    for line in src:
        stripped = line.strip()
        fence = stripped.startswith("```")
        prev = out[-1] if out else ""
        if fence and not in_code:
            if prev.strip():
                out.append("")
            out.append(line)
            in_code = True
            continue
        if fence and in_code:
            out.append(line)
            out.append("")
            in_code = False
            continue
        if in_code:
            out.append(line)
            continue
        is_item = bool(LIST_RE.match(line))
        prev_item = bool(LIST_RE.match(prev)) or (prev.startswith(" ") and prev.strip() != "")
        if is_item and prev.strip() and not prev_item:
            out.append("")
        elif stripped and not is_item and not line.startswith(" ") and prev_item:
            out.append("")
        if not stripped and prev == "":
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


# ---------------------------------------------------------------- общие функции

def resolve(doc: dict, node: dict) -> tuple[dict, str | None]:
    """Разворачивает локальную ссылку $ref. Возвращает (схема, имя компонента или None)."""
    name = None
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"Внешние ссылки не поддерживаются: {ref}")
        target = doc
        for part in ref[2:].split("/"):
            target = target[part]
        name = ref.rsplit("/", 1)[-1]
        node = target
    return node, name


def one_line(text: str | None) -> str:
    """Текст для ячейки таблицы: одна строка, без вертикальных черт."""
    if not text:
        return ""
    return " ".join(str(text).split()).replace("|", "\\|")


def anchor(prefix: str, name: str) -> str:
    return f"{prefix}-{name.lower()}"


def type_label(doc: dict, schema: dict, prefix: str) -> str:
    """Краткое описание типа для таблицы."""
    if "$ref" in schema:
        target, name = resolve(doc, schema)
        if target.get("type") == "object" or "allOf" in target or "enum" in target:
            return f"[{name}](#{anchor(prefix, name)})"
        return type_label(doc, target, prefix)
    if "allOf" in schema:
        return " + ".join(type_label(doc, s, prefix) for s in schema["allOf"])
    t = schema.get("type", "object")
    if t == "array":
        return f"массив из {type_label(doc, schema.get('items', {}), prefix)}"
    label = f"{t}"
    if "format" in schema:
        label += f" ({schema['format']})"
    if "enum" in schema:
        label += ": " + ", ".join(f"`{v}`" for v in schema["enum"])
    limits = []
    if "minimum" in schema:
        limits.append(f"≥ {schema['minimum']}")
    if "maximum" in schema:
        limits.append(f"≤ {schema['maximum']}")
    if limits:
        label += ", " + ", ".join(limits)
    return label


def merge_allof(doc: dict, schema: dict) -> dict:
    """Объединяет allOf в одну объектную схему (свойства и required)."""
    schema, _ = resolve(doc, schema)
    if "allOf" not in schema:
        return schema
    merged = {"type": "object", "properties": {}, "required": []}
    for part in schema["allOf"]:
        part = merge_allof(doc, part)
        merged["properties"].update(part.get("properties", {}))
        merged["required"] += part.get("required", [])
    return merged


def field_rows(doc: dict, schema: dict, prefix: str, path: str = "", depth: int = 0) -> list[str]:
    """Строки таблицы полей объекта. Вложенные безымянные объекты разворачиваются."""
    schema = merge_allof(doc, schema)
    rows = []
    required = set(schema.get("required", []))
    for name, prop in schema.get("properties", {}).items():
        full = f"{path}.{name}" if path else name
        target, ref_name = resolve(doc, prop)
        desc = prop.get("description") or (target.get("description") if not ref_name else "")
        rows.append(
            f"| `{full}` | {type_label(doc, prop, prefix)} | {'да' if name in required else 'нет'} | {one_line(desc)} |"
        )
        if ref_name or depth >= 3:
            continue
        inner = target
        if inner.get("type") == "array":
            inner, inner_ref = resolve(doc, inner.get("items", {}))
            if inner_ref:
                continue
            if inner.get("type") == "object" or "properties" in inner:
                rows += field_rows(doc, inner, prefix, full + "[]", depth + 1)
        elif "properties" in inner or "allOf" in inner:
            rows += field_rows(doc, inner, prefix, full, depth + 1)
    return rows


def fields_table(doc: dict, schema: dict, prefix: str) -> str:
    rows = field_rows(doc, schema, prefix)
    if not rows:
        return f"Тип: {type_label(doc, schema, prefix)}\n"
    return "| Поле | Тип | Обязательное | Описание |\n|---|---|---|---|\n" + "\n".join(rows) + "\n"


def schemas_section(doc: dict, schemas: dict, prefix: str) -> list[str]:
    out = ["## Схемы данных", ""]
    for name, schema in schemas.items():
        out += [f"### {name} {{#{anchor(prefix, name)}}}", ""]
        if schema.get("description"):
            out += [md_block(schema["description"]), ""]
        if "enum" in schema:
            out += ["Значения: " + ", ".join(f"`{v}`" for v in schema["enum"]) + ".", ""]
        elif "properties" in schema or "allOf" in schema:
            out += [fields_table(doc, schema, prefix)]
        else:
            out += [f"Тип: {type_label(doc, schema, prefix)}", ""]
    return out


# ---------------------------------------------------------------- OpenAPI

def render_openapi(service: str, path: Path) -> str:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    prefix = "schema"
    info = doc["info"]
    rel = path.relative_to(ROOT).as_posix()
    out = [HEADER.format(src=rel).rstrip("\n"), "", f"# {service}", ""]
    out += [f"Спецификация: [`{path.name}`](openapi/{path.name}) · OpenAPI {doc['openapi']} · версия API {info['version']}", ""]
    if info.get("description"):
        out += [md_block(info["description"]), ""]

    out += ["## Адреса", "", "| Адрес | Назначение |", "|---|---|"]
    out += [f"| `{s['url']}` | {one_line(s.get('description'))} |" for s in doc.get("servers", [])]
    out.append("")

    out += ["## Операции", "", "| Метод и путь | Назначение | Ответы |", "|---|---|---|"]
    ops = [(p, m, o) for p, item in doc["paths"].items() for m, o in item.items() if m in METHODS]
    for p, m, o in ops:
        out.append(f"| `{m.upper()} {p}` | {one_line(o.get('summary'))} | {', '.join(o.get('responses', {}))} |")
    out.append("")

    for p, m, o in ops:
        out += [f"### {m.upper()} {p}", "", f"**{o.get('summary', '')}**", ""]
        if o.get("description"):
            out += [md_block(o["description"]), ""]
        out += [f"`operationId`: `{o.get('operationId', '—')}` · тег: {', '.join(o.get('tags', []))}", ""]

        params = [resolve(doc, prm)[0] for prm in o.get("parameters", [])]
        if params:
            out += ["**Параметры**", "", "| Имя | Где | Тип | Обязательный | Описание |", "|---|---|---|---|---|"]
            for prm in params:
                out.append(
                    f"| `{prm['name']}` | {prm['in']} | {type_label(doc, prm.get('schema', {}), prefix)} | "
                    f"{'да' if prm.get('required') else 'нет'} | {one_line(prm.get('description'))} |"
                )
            out.append("")

        body = o.get("requestBody")
        if body:
            body, _ = resolve(doc, body)
            for ctype, content in body.get("content", {}).items():
                out += [f"**Тело запроса** (`{ctype}`)", "", fields_table(doc, content.get("schema", {}), prefix)]

        out += ["**Ответы**", "", "| Код | Описание | Тело |", "|---|---|---|"]
        for code, resp in o.get("responses", {}).items():
            resp, _ = resolve(doc, resp)
            bodies = [
                f"`{ct}`: {type_label(doc, c.get('schema', {}), prefix)}" for ct, c in resp.get("content", {}).items()
            ]
            out.append(f"| `{code}` | {one_line(resp.get('description'))} | {'; '.join(bodies) or '—'} |")
        out.append("")

    out += schemas_section(doc, doc.get("components", {}).get("schemas", {}), prefix)
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- AsyncAPI

def render_asyncapi(path: Path) -> str:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    prefix = "schema"
    info = doc["info"]
    rel = path.relative_to(ROOT).as_posix()
    out = [HEADER.format(src=rel).rstrip("\n"), "", "# События и команды (AsyncAPI)", ""]
    out += [f"Спецификация: [`{path.name}`](asyncapi/{path.name}) · AsyncAPI {doc['asyncapi']} · версия {info['version']}", ""]
    if info.get("description"):
        out += [md_block(info["description"]), ""]

    senders: dict[str, list[str]] = {}
    receivers: dict[str, list[str]] = {}
    for op in doc.get("operations", {}).values():
        channel = op["channel"]["$ref"].rsplit("/", 1)[-1]
        owners = [t["name"] for t in op.get("tags", [])]
        (senders if op["action"] == "send" else receivers).setdefault(channel, []).extend(owners)

    out += ["## Каналы", "", "| Routing key | Публикует | Слушает | Назначение |", "|---|---|---|---|"]
    for cid, ch in doc["channels"].items():
        out.append(
            f"| `{ch['address']}` | {', '.join(senders.get(cid, [])) or '—'} | "
            f"{', '.join(receivers.get(cid, [])) or '—'} | {one_line(ch.get('description'))} |"
        )
    out.append("")

    out += ["## Сообщения", ""]
    for name, msg in doc["components"]["messages"].items():
        out += [f"### {msg.get('name', name)}", "", f"**{msg.get('title', '')}**", ""]
        if msg.get("description"):
            out += [md_block(msg["description"]), ""]
        out += [fields_table(doc, msg["payload"], prefix)]
        for ex in msg.get("examples", []):
            out += [f"Пример ({ex.get('name', '')}):", "", "```json",
                    json.dumps(ex["payload"], ensure_ascii=False, indent=2), "```", ""]

    out += schemas_section(doc, doc["components"].get("schemas", {}), prefix)
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- запуск

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="проверить актуальность, ничего не записывая")
    args = parser.parse_args()

    pages = {API_DIR / f"{svc}.md": render_openapi(svc, src) for svc, src in OPENAPI}
    pages[API_DIR / "asyncapi.md"] = render_asyncapi(ASYNCAPI)

    stale = []
    for target, text in pages.items():
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != text:
            stale.append(target.relative_to(ROOT).as_posix())
            if not args.check:
                target.write_text(text, encoding="utf-8")

    if args.check and stale:
        print("Справочник API устарел, запустите scripts/gen_api_reference.py:", *stale, sep="\n  ")
        return 1
    print("Справочник API актуален." if not stale else "Обновлено: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
