"""Convert between editor lines and the stored structured document."""

from __future__ import annotations

import json
import re


LIST_PREFIX = re.compile(r"^(?:● |• |\d+\. |☐ |✓ )")
NUMBER_PREFIX = re.compile(r"^(\d+)\. ")


def strip_prefix(text: str) -> str:
    return LIST_PREFIX.sub("", text, count=1)


def _text(node: dict) -> str:
    return "".join(child.get("text", "") if child.get("type") == "text" else _text(child)
                   for child in node.get("content", []))


def _node(kind: str, value: str, **attrs) -> dict:
    node = {"type": kind}
    if attrs:
        node["attrs"] = attrs
    if value:
        node["content"] = [{"type": "text", "text": value}]
    return node


def table_data(node: dict) -> tuple[list[list[str]], list[int]]:
    """Read the simple header-and-cells table used by the editor."""
    rows = [[_text(cell) for cell in row.get("content", [])]
            for row in node.get("content", []) if row.get("type") == "tableRow"]
    count = max((len(row) for row in rows), default=0)
    count = max(1, count)
    rows = [(row + [""] * count)[:count] for row in rows] or [[""] * count]
    widths = node.get("attrs", {}).get("columnWidths", [])
    widths = [max(80, min(800, int(width))) if isinstance(width, (int, float)) else 160
              for width in (widths + [160] * count)[:count]] if isinstance(widths, list) else [160] * count
    return rows, widths


def make_table(rows: list[list[str]], widths: list[int]) -> dict:
    return {
        "type": "table",
        "attrs": {"columnWidths": widths},
        "content": [
            {"type": "tableRow", "content": [
                {"type": "tableHeader" if row_index == 0 else "tableCell",
                 "content": [_node("paragraph", value)]}
                for value in row]}
            for row_index, row in enumerate(rows)
        ],
    }


def image_data(node: dict) -> tuple[str, int]:
    attrs = node.get("attrs", {})
    attachment_id = attrs.get("attachmentId", "")
    width = attrs.get("width", 320)
    if not isinstance(attachment_id, str):
        attachment_id = ""
    if not isinstance(width, (int, float)):
        width = 320
    return attachment_id, max(80, min(1600, int(width)))


def make_image(attachment_id: str, width: int) -> dict:
    return {"type": "image", "attrs": {"attachmentId": attachment_id, "width": width}}


def document_to_lines(content_json: str, fallback_body: str = "") -> list[tuple[str, str]]:
    try:
        document = json.loads(content_json)
        if document.get("type") != "doc" or not isinstance(document.get("content"), list):
            raise ValueError("Invalid document")
    except (TypeError, ValueError, AttributeError):
        return [("paragraph", line) for line in fallback_body.split("\n")]

    lines = []
    for node in document["content"]:
        kind = node.get("type")
        if kind == "heading":
            level = node.get("attrs", {}).get("level", 1)
            lines.append((f"heading{level}" if level in (1, 2, 3) else "paragraph", _text(node)))
        elif kind in ("bulletList", "orderedList", "taskList"):
            for index, item in enumerate(node.get("content", []), 1):
                value = _text(item)
                if kind == "bulletList":
                    lines.append(("bullet", "• " + value))
                elif kind == "orderedList":
                    lines.append(("number", f"{index}. {value}"))
                else:
                    checked = bool(item.get("attrs", {}).get("checked", False))
                    lines.append(("todo", ("✓ " if checked else "☐ ") + value))
        elif kind == "table":
            lines.append(("table", node))
        elif kind == "image":
            lines.append(("image", node))
        else:
            lines.append(("paragraph", _text(node)))
    return lines or [("paragraph", "")]


def lines_to_document(lines: list[tuple[str, str]]) -> tuple[str, str]:
    content = []
    body = []
    for kind, display in lines:
        if kind == "table":
            rows, widths = table_data(display)
            content.append(make_table(rows, widths))
            body.append("\n".join("\t".join(row) for row in rows))
            continue
        if kind == "image":
            attachment_id, width = image_data(display)
            content.append(make_image(attachment_id, width))
            body.append("")
            continue
        value = strip_prefix(display) if kind in ("bullet", "number", "todo") else display
        body.append(value)
        if kind in ("bullet", "number", "todo"):
            list_kind = {"bullet": "bulletList", "number": "orderedList", "todo": "taskList"}[kind]
            if not content or content[-1]["type"] != list_kind:
                content.append({"type": list_kind, "content": []})
            item_kind = "taskItem" if kind == "todo" else "listItem"
            item = {"type": item_kind}
            if kind == "todo":
                item["attrs"] = {"checked": display.startswith("✓ ")}
            item["content"] = [_node("paragraph", value)]
            content[-1]["content"].append(item)
        elif kind.startswith("heading"):
            content.append(_node("heading", value, level=int(kind[-1])))
        else:
            content.append(_node("paragraph", value))
    return "\n".join(body), json.dumps({"type": "doc", "content": content}, ensure_ascii=False)


def repair_excess_blank_lines(content_json: str, *, threshold: int = 128) -> tuple[str, str] | None:
    """Collapse the pathological blank runs produced by the old line reader.

    Only runs with at least ``threshold`` newline-bearing empty paragraphs are
    changed, leaving ordinary blank lines intact.
    """
    document = json.loads(content_json)
    nodes = document.get("content", [])
    if any(node.get("type") != "paragraph" for node in nodes):
        return None
    repaired = []
    changed = False
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.get("type") != "paragraph" or _text(node) not in ("", "\n"):
            repaired.append(node)
            index += 1
            continue
        end = index
        newline_count = 0
        while end < len(nodes) and nodes[end].get("type") == "paragraph" and _text(nodes[end]) in ("", "\n"):
            newline_count += _text(nodes[end]) == "\n"
            end += 1
        if newline_count >= threshold:
            repaired.append({"type": "paragraph"})
            changed = True
        else:
            repaired.extend(nodes[index:end])
        index = end
    if not changed:
        return None
    document["content"] = repaired
    body = "\n".join(_text(node) for node in repaired)
    return body, json.dumps(document, ensure_ascii=False)
