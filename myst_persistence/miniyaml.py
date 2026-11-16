"""miniyaml — a tiny safe YAML *subset* parser (stdlib only).

Used to read v1 ``invariants.yaml`` files (and other simple hand-written YAML)
when PyYAML is not installed. Not a general YAML parser: it supports the
subset hand-written config files actually use:

    - comments (``# ...`` — full-line and trailing, quote-aware)
    - plain scalars and quoted strings (single & double)
    - block mappings            key: value
    - block sequences           - item
    - nested structures by indentation
    - sequences of mappings     - key: value  (continuing lines)
    - inline lists              [a, b, c]
    - flat inline maps          {a: 1, b: 2}
    - literal scalars kept as strings; only int/float/bool/null are typed

Explicitly refuses anything it does not understand — malformed input raises
``DataFormatError`` instead of guessing. YAML tags (``!!python/...``) are
refused outright: this parser never evals anything.
"""

from __future__ import annotations

import re

from .errors import DataFormatError

__all__ = ["loads", "load", "dump"]


class _Line:
    __slots__ = ("content", "indent", "no")

    def __init__(self, content, indent, no):
        self.content = content
        self.indent = indent
        self.no = no


def _strip_comment(line: str) -> str:
    """Drop a trailing # comment, respecting simple quoting."""
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i].rstrip()
    return line.rstrip()


def _split_flow(text: str) -> list:
    """Split flow content on commas, respecting quotes and nesting."""
    parts, buf, depth, in_single, in_double = [], [], 0, False, False
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
        buf.append(ch)
    parts.append("".join(buf).strip())
    return [p for p in parts if p != ""]


def _parse_scalar(text: str):
    """Parse one scalar/flow value: quoted, number, bool, null, inline, plain."""
    t = text.strip()
    if t == "":
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        inner = t[1:-1]
        if t[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    if t.startswith("[") and t.endswith("]"):
        return [_parse_scalar(p) for p in _split_flow(t[1:-1])]
    if t.startswith("{") and t.endswith("}"):
        result = {}
        for part in _split_flow(t[1:-1]):
            if ":" not in part:
                raise DataFormatError("malformed inline map: %r" % text)
            k, v = part.split(":", 1)
            result[k.strip().strip("'\"")] = _parse_scalar(v)
        return result
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d*", t):
        return float(t)
    low = t.lower()
    if low in ("null", "~"):
        return None
    if low in ("true", "false"):
        return low == "true"
    return t


def _looks_like_key(text: str) -> bool:
    """True if ``text`` looks like ``key: value`` rather than a sentence."""
    head = text.split(":", 1)[0].strip()
    return bool(head) and " " not in head


def _parse_block(lines, i, indent):
    """Parse lines[i:] whose indent >= ``indent``; return (value, next_i)."""
    if i >= len(lines) or lines[i].indent < indent:
        return None, i

    item_indent = lines[i].indent

    # --- sequence block ---------------------------------------------------
    if lines[i].content == "-" or lines[i].content.startswith("- "):
        items = []
        while i < len(lines) and lines[i].indent == item_indent:
            content = lines[i].content
            if content == "-":
                node, i = _parse_block(lines, i + 1, item_indent + 1)
                if node is None:
                    raise DataFormatError(
                        "dangling '-' at line %d" % lines[i].no)
                items.append(node)
                continue
            rest = content[2:].lstrip()
            if _looks_like_key(rest):
                # "- key: value" — a mapping item; continuation lines are
                # those indented deeper than the dash.
                virtual = [_Line(rest, item_indent + 2, lines[i].no)]
                j = i + 1
                while j < len(lines) and lines[j].indent > item_indent:
                    virtual.append(lines[j])
                    j += 1
                node, _ = _parse_block(virtual, 0, item_indent + 2)
                items.append(node)
                i = j
            else:
                items.append(_parse_scalar(rest))
                i += 1
        return items, i

    # --- mapping block ------------------------------------------------------
    items = {}
    while i < len(lines) and lines[i].indent == item_indent:
        content = lines[i].content
        if content == "-" or content.startswith("- "):
            break
        if ":" not in content:
            raise DataFormatError(
                "expected 'key: value' at line %d: %r" % (lines[i].no, content))
        key_part, _, value_part = content.partition(":")
        key = key_part.strip().strip("'\"")
        if not key:
            raise DataFormatError(
                "empty key at line %d" % lines[i].no)
        value = value_part.strip()
        if value == "":
            # nested block (or a null value)
            j = i + 1
            if j < len(lines) and lines[j].indent > item_indent:
                node, i = _parse_block(lines, j, lines[j].indent)
                items[key] = node
            else:
                items[key] = None
                i += 1
        else:
            items[key] = _parse_scalar(value)
            i += 1
    return items, i


def _preprocess(text: str) -> list:
    lines = []
    for no, raw in enumerate(text.splitlines(), 1):
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append(_Line(stripped.strip(), indent, no))
    return lines


def loads(text):
    """Parse a YAML-subset document → dict / list / scalar / None."""
    if text is None:
        return None
    if "!!" in text:
        raise DataFormatError("YAML tags are not supported (safety)")
    lines = _preprocess(text)
    if not lines:
        return None
    value, _ = _parse_block(lines, 0, lines[0].indent)
    return value


def load(path) -> dict:
    """Read a YAML-subset file → object; {} when missing or empty."""
    from pathlib import Path as _P
    p = _P(path)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    result = loads(text)
    return {} if result is None else result


def dump(data) -> str:
    """Serialize simple data (dict/list/str/num/bool/None) to this subset."""
    out = []

    def scalar(v):
        if v is None:
            return "null"
        if v is True:
            return "true"
        if v is False:
            return "false"
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        if s == "" or any(c in s for c in ":#\n{}[],'\"") or s.strip() != s:
            return "'" + s.replace("'", "''") + "'"
        return s

    def inline_list(items):
        return "[" + ", ".join(
            scalar(i) if not isinstance(i, (dict, list)) else str(i)
            for i in items) + "]"

    def emit(node, indent):
        pad = "  " * indent
        if isinstance(node, dict):
            if not node:
                out.append(pad + "{}")
                return
            for k, v in node.items():
                key = scalar(k).strip("'")
                if isinstance(v, dict) and v:
                    out.append(pad + key + ":")
                    emit(v, indent + 1)
                elif isinstance(v, list) and v:
                    if all(not isinstance(x, (dict, list)) for x in v):
                        out.append(pad + key + ": " + inline_list(v))
                    else:
                        out.append(pad + key + ":")
                        emit(v, indent + 1)
                else:
                    out.append(pad + key + ": " + scalar(v))
        elif isinstance(node, list):
            if not node:
                out.append(pad + "[]")
                return
            for v in node:
                if isinstance(v, dict) and v:
                    first = True
                    for k, vv in v.items():
                        prefix = "- " if first else "  "
                        key = scalar(k).strip("'")
                        if isinstance(vv, (dict, list)) and vv:
                            out.append(pad + prefix + key + ":")
                            emit(vv, indent + 1)
                        else:
                            out.append(pad + prefix + key + ": " + scalar(vv))
                        first = False
                elif isinstance(v, list) and v:
                    out.append(pad + "-")
                    emit(v, indent + 1)
                else:
                    out.append(pad + "- " + scalar(v))
        else:
            out.append(pad + scalar(node))

    emit(data, 0)
    return "\n".join(out) + "\n"
