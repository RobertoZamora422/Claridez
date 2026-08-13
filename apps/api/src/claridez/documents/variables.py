from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Final

from .errors import DocumentsError

LANGUAGE_VERSION: Final = "claridez-vars-v1"
PLACEHOLDER = re.compile(r"{{\s*([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)\s*}}")
ALLOWED_VARIABLES: Final = frozenset(
    {
        "organization.name",
        "organization.currency",
        "organization.timezone",
        "counterparty.full_name",
        "counterparty.phone",
        "counterparty.email",
        "quotation.number",
        "quotation.version",
        "quotation.currency",
        "quotation.subtotal",
        "quotation.discount_total",
        "quotation.total",
        "quotation.notes",
        "quotation.accepted_at",
        "quotation.lines_table",
        "reservation.root_id",
        "reservation.current_id",
        "reservation.venue_name",
        "reservation.space_name",
        "reservation.starts_at",
        "reservation.ends_at",
        "reservation.timezone",
        "reservation.status",
    }
)


class _RestrictedHTMLParser(HTMLParser):
    tags = frozenset(
        {
            "p",
            "h1",
            "h2",
            "h3",
            "strong",
            "em",
            "ul",
            "ol",
            "li",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "section",
            "div",
            "span",
            "br",
            "img",
        }
    )
    void_tags = frozenset({"br", "img"})
    class_value = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.tags:
            raise DocumentsError("unsafe_template", f"La etiqueta {tag!r} no está permitida.")
        safe_attrs: list[str] = []
        for name, value in attrs:
            value = value or ""
            if name == "class" and self.class_value.fullmatch(value):
                safe_attrs.append(f'class="{html.escape(value, quote=True)}"')
            elif name in {"colspan", "rowspan"} and value.isdigit() and 1 <= int(value) <= 20:
                safe_attrs.append(f'{name}="{value}"')
            elif tag == "img" and name == "src" and value == "claridez-asset:wordmark":
                safe_attrs.append('src="claridez-asset:wordmark"')
            elif tag == "img" and name == "alt" and len(value) <= 100:
                safe_attrs.append(f'alt="{html.escape(value, quote=True)}"')
            else:
                raise DocumentsError(
                    "unsafe_template", f"El atributo {name!r} no está permitido en {tag!r}."
                )
        suffix = f" {' '.join(safe_attrs)}" if safe_attrs else ""
        self.output.append(f"<{tag}{suffix}>")
        if tag not in self.void_tags:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.void_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.void_tags or not self.stack or self.stack[-1] != tag:
            raise DocumentsError("unsafe_template", "La estructura HTML no es válida.")
        self.stack.pop()
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def close(self) -> None:
        super().close()
        if self.stack:
            raise DocumentsError("unsafe_template", "La estructura HTML no está cerrada.")


def sanitize_template_html(value: str) -> str:
    if len(value.encode("utf-8")) > 200_000:
        raise DocumentsError("template_too_large", "La plantilla excede el límite permitido.")
    parser = _RestrictedHTMLParser()
    parser.feed(value)
    parser.close()
    sanitized = "".join(parser.output)
    if not sanitized.strip():
        raise DocumentsError("invalid_template", "La plantilla no puede estar vacía.")
    return sanitized


@dataclass(frozen=True, slots=True)
class VariableDeclaration:
    name: str
    required: bool
    fallback: str | None


def validate_variable_schema(
    schema: Mapping[str, Any], body_html: str
) -> tuple[VariableDeclaration, ...]:
    if schema.get("version") != LANGUAGE_VERSION or set(schema) != {"version", "variables"}:
        raise DocumentsError("invalid_variable_schema", "El esquema de variables no es válido.")
    raw_variables = schema.get("variables")
    if not isinstance(raw_variables, list):
        raise DocumentsError("invalid_variable_schema", "variables debe ser una lista.")
    declarations: list[VariableDeclaration] = []
    seen: set[str] = set()
    for item in raw_variables:
        if not isinstance(item, dict) or not set(item) <= {"name", "required", "fallback"}:
            raise DocumentsError("invalid_variable_schema", "Una declaración no es válida.")
        name = item.get("name")
        required = item.get("required")
        fallback = item.get("fallback")
        if name not in ALLOWED_VARIABLES or name in seen or not isinstance(required, bool):
            raise DocumentsError("invalid_variable_schema", "Variable desconocida o duplicada.")
        if required and fallback is not None:
            raise DocumentsError(
                "invalid_variable_schema", "Una variable obligatoria no usa fallback."
            )
        if fallback is not None and (not isinstance(fallback, str) or len(fallback) > 200):
            raise DocumentsError("invalid_variable_schema", "El fallback no es válido.")
        seen.add(name)
        declarations.append(VariableDeclaration(name, required, fallback))
    placeholders = set(PLACEHOLDER.findall(body_html))
    if "{{" in PLACEHOLDER.sub("", body_html) or "}}" in PLACEHOLDER.sub("", body_html):
        raise DocumentsError("invalid_variable", "La expresión de variable no es válida.")
    if placeholders != seen:
        raise DocumentsError(
            "invalid_variable_schema", "Las variables declaradas y usadas no coinciden."
        )
    return tuple(declarations)


def template_source_hash(
    *, body_html: str, schema: Mapping[str, Any], assets_manifest: Mapping[str, Any]
) -> tuple[str, str]:
    assets = json.dumps(assets_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    source = json.dumps(
        {
            "body_html": body_html,
            "schema": schema,
            "language": LANGUAGE_VERSION,
            "assets_sha256": hashlib.sha256(assets.encode()).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(source.encode()).hexdigest(), hashlib.sha256(assets.encode()).hexdigest()


def resolve_template(
    *, body_html: str, declarations: tuple[VariableDeclaration, ...], values: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    resolved: dict[str, Any] = {}
    by_name = {declaration.name: declaration for declaration in declarations}
    for name, declaration in by_name.items():
        value = values.get(name)
        if value in (None, ""):
            if declaration.required:
                raise DocumentsError("missing_required_variable", f"Falta la variable {name}.")
            value = declaration.fallback or ""
        resolved[name] = value

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        value = resolved[name]
        if name == "quotation.lines_table":
            return str(value)
        return html.escape(str(value), quote=False)

    return PLACEHOLDER.sub(substitute, body_html), resolved
