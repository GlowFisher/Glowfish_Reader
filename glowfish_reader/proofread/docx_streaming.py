"""Page-iterator DOCX writer used by document background exports."""

from __future__ import annotations

from pathlib import Path

import proof_model as M


def write_docx_pages(output_path: Path, document_meta: dict, pages, *, page_marks=False,
                     with_annotations=False, with_images=False, task=None) -> int:
    """Write one page at a time; never materialize a document-wide pages list."""
    doc, sec, font, size_pt, indent, qn = M._docx_base()
    max_width = sec.page_width - sec.left_margin - sec.right_margin
    page_count, note_number = 0, 1
    for ordinal, page in enumerate(pages, 1):
        if task:
            task.check_cancelled()
        page_body, page_notes = M._page_annotated_segments(page)
        if not page_body:
            continue
        if page_count:
            doc.add_paragraph()
        if with_images:
            M._add_page_image(doc, document_meta, page, max_width)
        if page_marks:
            M._add_docx_segments(doc, [(M._page_label(page.get("page_id", ""), ordinal), False)], font, size_pt, qn, indent)
        if with_annotations:
            for segments in page_body:
                M._add_docx_segments(doc, segments, font, size_pt, qn, indent)
            if page_notes:
                head = doc.add_paragraph()
                run = head.add_run("注释")
                run.bold = True
                run.font.name = font
                run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
                for note in page_notes:
                    text = f"[{note_number}] {note['label']}：{note['note']}"
                    M._add_docx_segments(doc, [(text, False)], font, size_pt, qn, None, small=True)
                    note_number += 1
        else:
            for paragraph in M.assemble_paragraphs({**document_meta, "pages": [page]}, page_marks=False):
                M._add_docx_segments(doc, [(paragraph, False)], font, size_pt, qn, indent)
        page_count += 1
        if task:
            task.progress(done=page_count)
    doc_notes = (document_meta.get("notes") or "").strip()
    if with_annotations and doc_notes:
        doc.add_paragraph()
        M._add_docx_segments(doc, [("注释", False)], font, size_pt, qn, None)
        M._add_docx_segments(doc, [(doc_notes, False)], font, size_pt, qn, None, small=True)
    temp = Path(output_path).with_suffix(".tmp")
    doc.save(temp)
    temp.replace(output_path)
    return page_count
