#!/usr/bin/env python3
"""Проверяет согласованность спецификаций API, которую не ловят стандартные валидаторы.

- все локальные ссылки $ref указывают на существующие узлы;
- operationId в OpenAPI уникальны внутри сервиса;
- у каждого канала AsyncAPI есть и отправитель, и получатель;
- каждый канал AsyncAPI упомянут в справочнике docs/api/index.md.

Использование: python scripts/check_specs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "docs" / "api"


def walk_refs(node, path="#"):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield path, value
            else:
                yield from walk_refs(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_refs(value, f"{path}/{i}")


def ref_exists(doc: dict, ref: str) -> bool:
    if not ref.startswith("#/"):
        return False
    node = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def main() -> int:
    errors: list[str] = []
    specs = sorted(API_DIR.glob("openapi/*.yaml")) + sorted(API_DIR.glob("asyncapi/*.yaml"))
    for spec in specs:
        doc = yaml.safe_load(spec.read_text(encoding="utf-8"))
        name = spec.relative_to(ROOT).as_posix()
        for where, ref in walk_refs(doc):
            if not ref_exists(doc, ref):
                errors.append(f"{name}: битая ссылка {ref} в {where}")

        if "openapi" in doc:
            seen: dict[str, str] = {}
            for path, item in doc.get("paths", {}).items():
                for method, op in item.items():
                    if not isinstance(op, dict) or "operationId" not in op:
                        continue
                    op_id = op["operationId"]
                    if op_id in seen:
                        errors.append(f"{name}: operationId {op_id} повторяется ({seen[op_id]} и {method.upper()} {path})")
                    seen[op_id] = f"{method.upper()} {path}"

        if "asyncapi" in doc:
            actions: dict[str, set[str]] = {cid: set() for cid in doc.get("channels", {})}
            for op_name, op in doc.get("operations", {}).items():
                cid = op["channel"]["$ref"].rsplit("/", 1)[-1]
                actions.setdefault(cid, set()).add(op["action"])
            index = (API_DIR / "index.md").read_text(encoding="utf-8")
            for cid, acts in actions.items():
                address = doc["channels"].get(cid, {}).get("address", cid)
                for need in ("send", "receive"):
                    if need not in acts:
                        errors.append(f"{name}: у канала {address} нет операции {need}")
                if f"`{address}`" not in index:
                    errors.append(f"docs/api/index.md: канал {address} не описан в таблице сообщений")

    for e in errors:
        print(e)
    print(f"Проверено спецификаций: {len(specs)}, ошибок: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
