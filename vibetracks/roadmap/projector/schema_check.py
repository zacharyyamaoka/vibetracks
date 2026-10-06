"""A stdlib subset of JSON Schema Draft 2020-12: exactly the keywords bam-roadmap/1 uses.

WHY not the ``jsonschema`` package: the runtime stays dependency-free. WHY it refuses any
keyword it does not implement: a validator that silently skips ``unevaluatedProperties`` would
pass documents the schema rejects. The tests hold this validator against ``jsonschema`` itself,
on the real projections and on mutants, so the two cannot drift apart unnoticed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "bam-roadmap-1.schema.json"

ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples", "$defs"}
CHECKED = {"type", "enum", "const", "required", "properties", "additionalProperties", "items", "minItems", "maxItems",
           "minLength", "pattern", "minimum", "$ref", "allOf", "anyOf", "oneOf", "if", "then", "else"}


class SchemaError(ValueError):
    """The schema uses something this validator does not implement."""


def _walk(schema: Any, where: str = "#") -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, Mapping):
        raise SchemaError(f"{where}: a schema must be an object or a boolean")
    unknown = set(schema) - ANNOTATIONS - CHECKED
    if unknown:
        raise SchemaError(f"{where}: unsupported keyword(s) {sorted(unknown)}")
    for name, child in (schema.get("properties") or {}).items():
        _walk(child, f"{where}/properties/{name}")
    for name, child in (schema.get("$defs") or {}).items():
        _walk(child, f"{where}/$defs/{name}")
    for keyword in ("items", "additionalProperties", "if", "then", "else"):
        if keyword in schema and not isinstance(schema[keyword], bool):
            _walk(schema[keyword], f"{where}/{keyword}")
    for keyword in ("allOf", "anyOf", "oneOf"):
        for index, child in enumerate(schema.get(keyword) or []):
            _walk(child, f"{where}/{keyword}/{index}")


@lru_cache(maxsize=4)
def load(path: str = str(SCHEMA_PATH)) -> dict:
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    _walk(schema)
    return schema


def _resolve(root: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("#"):
        raise SchemaError(f"only local references are supported, not {reference!r}")
    node: Any = root
    for token in [part for part in reference[1:].split("/") if part]:
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def _type_ok(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise SchemaError(f"unknown type {name!r}")


def _equal(left: Any, right: Any) -> bool:
    """JSON equality: 1 == 1.0, but True is not 1."""

    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


def iter_errors(instance: Any, schema: Any = None, root: Any = None, where: str = "") -> Iterator[str]:
    """Every way ``instance`` breaks ``schema``, as ``"<json path>: <message>"``."""

    if schema is None:
        schema = load()
    if root is None:
        root = schema
    if schema is True:
        return
    if schema is False:
        yield f"{where or '/'}: nothing is allowed here"
        return
    path = where or "/"
    if "$ref" in schema:
        yield from iter_errors(instance, _resolve(root, schema["$ref"]), root, where)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(instance, name) for name in names):
            yield f"{path}: {type(instance).__name__} is not {' or '.join(names)}"
            return
    if "enum" in schema and not any(_equal(instance, option) for option in schema["enum"]):
        yield f"{path}: {instance!r} is not one of {schema['enum']}"
    if "const" in schema and not _equal(instance, schema["const"]):
        yield f"{path}: {instance!r} is not {schema['const']!r}"
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            yield f"{path}: shorter than {schema['minLength']}"
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            yield f"{path}: {instance!r} does not match {schema['pattern']}"
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            yield f"{path}: {instance} < {schema['minimum']}"
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            yield f"{path}: fewer than {schema['minItems']} items"
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            yield f"{path}: more than {schema['maxItems']} items"
        if "items" in schema:
            for index, item in enumerate(instance):
                yield from iter_errors(item, schema["items"], root, f"{where}/{index}")
    if isinstance(instance, dict):
        for name in schema.get("required") or []:
            if name not in instance:
                yield f"{path}: missing required {name!r}"
        properties = schema.get("properties") or {}
        for name, value in instance.items():
            if name in properties:
                yield from iter_errors(value, properties[name], root, f"{where}/{name}")
            elif "additionalProperties" in schema:
                yield from iter_errors(value, schema["additionalProperties"], root, f"{where}/{name}")
    for child in schema.get("allOf") or []:
        yield from iter_errors(instance, child, root, where)
    if "anyOf" in schema and not any(not list(iter_errors(instance, child, root, where)) for child in schema["anyOf"]):
        yield f"{path}: matches none of anyOf"
    if "oneOf" in schema:
        matches = sum(1 for child in schema["oneOf"] if not list(iter_errors(instance, child, root, where)))
        if matches != 1:
            yield f"{path}: matches {matches} of oneOf, not exactly 1"
    if "if" in schema:
        branch = "then" if not list(iter_errors(instance, schema["if"], root, where)) else "else"
        if branch in schema:
            yield from iter_errors(instance, schema[branch], root, where)


def errors(instance: Any, schema_path: Path = SCHEMA_PATH) -> list[str]:
    return list(iter_errors(instance, load(str(schema_path))))
