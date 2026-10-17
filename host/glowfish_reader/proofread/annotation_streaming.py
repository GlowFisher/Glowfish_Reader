"""Page-iterator annotation-only export writers."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import proof_model as M


def page_annotation_paragraphs(page):
    paragraphs = []
    page_id = str(page.get("page_id") or "")
    page_note = str(page.get("page_annot") or "").strip()
    if page_note:
        paragraphs.append(f"[{page_id}] {page_note}")
    for annotation in page.get("annots", []) or []:
        quote = str(annotation.get("quote") or "").strip()
        note = str(annotation.get("note") or "").strip()
        if quote or note:
            paragraphs.append(f'"{quote}" -> {note}' if note else f'"{quote}"')
    line_map = {line.get("id"): line for line in page.get("lines", [])}
    for line_id in page.get("order", []):
        line = line_map.get(line_id)
        if not line:
            continue
        note = str(line.get("annot") or "").strip()
        if note:
            snippet = str(line.get("text") or "")[:24]
            paragraphs.append(f"{snippet} -> {note}")
    return paragraphs


def write_annotation_events(output_path: Path, events, *, fmt="txt", task=None) -> int:
    """Write annotation events while holding at most one page body."""
    if fmt not in {"docx", "txt", "md", "csv"}:
        raise ValueError(f"unsupported annotation format: {fmt}")
    output_path = Path(output_path)
    temp = output_path.with_name(f".{output_path.name}.tmp")
    count = 0
    try:
        if fmt == "docx":
            document, _section, font, size_pt, indent, qn = M._docx_base()
            for event in events:
                if task:
                    task.check_cancelled()
                kind, value, ordinal = event
                if kind == "progress":
                    if task:
                        task.progress(done=ordinal)
                    continue
                M._add_docx_segments(document, [(value, False)], font, size_pt, qn,
                                     None if kind == "heading" else indent)
                count += 1
            document.save(temp)
        else:
            encoding = "utf-8-sig" if fmt == "csv" else "utf-8"
            with temp.open("w", encoding=encoding, newline="") as stream:
                writer = csv.writer(stream) if fmt == "csv" else None
                if writer:
                    writer.writerow(["index", "annotation"])
                written = False
                for event in events:
                    if task:
                        task.check_cancelled()
                    kind, value, ordinal = event
                    if kind == "progress":
                        if task:
                            task.progress(done=ordinal)
                        continue
                    count += 1
                    if writer:
                        writer.writerow([count, value])
                    else:
                        if written:
                            stream.write("\n\n")
                        prefix = "## " if fmt == "md" and kind == "heading" else ""
                        stream.write(prefix + value)
                        written = True
                stream.flush()
                os.fsync(stream.fileno())
        with temp.open("r+b") as completed:
            os.fsync(completed.fileno())
        if task:
            task.check_cancelled()
        os.replace(temp, output_path)
        return count
    finally:
        temp.unlink(missing_ok=True)
