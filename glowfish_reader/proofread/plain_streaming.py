"""Page-iterator plain text writers used by background document exports."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import proof_model as M


def _paragraphs(page, *, with_annotations, next_note):
    if not with_annotations:
        return M.assemble_paragraphs({"pages": [page]}, page_marks=False), [], next_note
    body, notes = M._page_annotated_segments(page)
    paragraphs = []
    for segments in body:
        shifted = []
        for value, superscript in segments:
            if superscript:
                local = int(str(value).strip("[]"))
                shifted.append(f"[{next_note + local - 1}]")
            else:
                shifted.append(value)
        paragraphs.append("".join(shifted))
    rendered_notes = [
        f"[{next_note + index}] {note['label']}\uff1a{note['note']}"
        for index, note in enumerate(notes)
    ]
    return paragraphs, rendered_notes, next_note + len(notes)


def write_plain_pages(output_path: Path, document_meta: dict, pages, *, fmt="txt",
                      page_marks=False, with_annotations=False, task=None, on_page=None) -> int:
    """Write TXT/MD/CSV a page at a time with a disk-backed annotation sidecar."""
    if fmt not in {"txt", "md", "csv"}:
        raise ValueError(f"unsupported plain export format: {fmt}")
    output_path = Path(output_path)
    temp = output_path.with_name(f".{output_path.name}.tmp")
    note_temp = output_path.with_name(f".{output_path.name}.notes.tmp")
    encoding = "utf-8-sig" if fmt == "csv" else "utf-8"
    paragraph_count, next_note, written = 0, 1, False
    try:
        with temp.open("w", encoding=encoding, newline="") as stream, \
                note_temp.open("w", encoding="utf-8", newline="") as note_stream:
            csv_writer = csv.writer(stream) if fmt == "csv" else None
            note_writer = csv.writer(note_stream) if fmt == "csv" else None
            if csv_writer:
                csv_writer.writerow(["\u5e8f", "\u5185\u5bb9"])
            elif fmt == "md":
                stream.write(f"# {document_meta.get('batch') or 'export'}\n\n")
            for ordinal, page in enumerate(pages, 1):
                if task:
                    task.check_cancelled()
                paragraphs, notes, next_note = _paragraphs(
                    page, with_annotations=with_annotations, next_note=next_note
                )
                values = []
                if page_marks:
                    values.append(M._page_label(page.get("page_id", ""), ordinal))
                values.extend(paragraphs)
                for value in values:
                    if csv_writer:
                        paragraph_count += 1
                        csv_writer.writerow([paragraph_count, value])
                    else:
                        if written:
                            stream.write("\n\n")
                        stream.write(("## " if fmt == "md" and value == values[0] and page_marks else "") + value)
                        written = True
                        if value in paragraphs:
                            paragraph_count += 1
                for note in notes:
                    if note_writer:
                        note_writer.writerow([note])
                    else:
                        note_stream.write(note + "\n")
                if on_page:
                    on_page(page, ordinal)
                if task:
                    task.progress(done=ordinal)
            document_notes = str(document_meta.get("notes") or "").strip()
            if with_annotations and document_notes:
                rendered = f"[{next_note}] \u7814\u7a76\u7b14\u8bb0\uff1a{document_notes}"
                if note_writer:
                    note_writer.writerow([rendered])
                else:
                    note_stream.write(rendered + "\n")
            note_stream.flush()
            os.fsync(note_stream.fileno())
            if with_annotations and note_temp.stat().st_size:
                if csv_writer:
                    note_stream.close()
                    with note_temp.open("r", encoding="utf-8", newline="") as source:
                        csv_writer.writerow(["", "\u6ce8\u91ca"])
                        for row in csv.reader(source):
                            if row:
                                csv_writer.writerow(["", row[0]])
                else:
                    note_stream.close()
                    stream.write("\n\n## \u6ce8\u91ca\n\n" if fmt == "md" else "\n\n\u6ce8\u91ca\n\n")
                    with note_temp.open("r", encoding="utf-8") as source:
                        stream.write("\n".join(line.rstrip("\n") for line in source))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, output_path)
        return paragraph_count
    finally:
        temp.unlink(missing_ok=True)
        note_temp.unlink(missing_ok=True)
