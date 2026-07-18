# -*- coding: utf-8 -*-
"""导出 API（浏览器版）：文件流直接下载，废原生「选目标文件夹」。

scope: page(本页) / all(本史料全部页) / notebook(全笔记本合并) / annotations(仅批注)。
单文件返回 Response(attachment, RFC5987 中文名)；勾「附带原图」→ 内存 zip（文档 + _原图/）。
"""
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import Response, FileResponse, JSONResponse

import proof_model as M
from document_task_manager import TASK_MANAGER
import safefs
from settings_store import load_settings
from userctx import Ctx, ctx_dep

router = APIRouter()

_EXT = {"docx": ".docx", "txt": ".txt", "md": ".md", "csv": ".csv", "zip": ".zip"}
_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8", "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8", "zip": "application/zip",
}


def _file_response(name, fmt, data, n):
    fname = name + _EXT.get(fmt, ".bin")
    disp = "attachment; filename*=UTF-8''" + quote(fname)    # RFC5987：中文名不乱码
    return Response(content=data, media_type=_MEDIA.get(fmt, "application/octet-stream"),
                    headers={"Content-Disposition": disp, "X-Doc-Paragraphs": str(n),
                             "Access-Control-Expose-Headers": "Content-Disposition, X-Doc-Paragraphs"})


def _packaged(name, fmt, data, n, target, with_image):
    """无原图→单文件；附带原图→内存 zip（文档 + <name>_原图/NNNN_*）。"""
    if not with_image or fmt == "docx":
        return _file_response(name, fmt, data, n)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name + _EXT.get(fmt, ".bin"), data)
        for i, p in enumerate(target.get("pages", []), 1):
            src = M.page_image_path(target, p)
            if src.exists() and safefs.within_work(src):     # 原图须在沙箱内
                try:
                    zf.write(src, f"{name}_原图/{i:04d}_{src.name}")
                except Exception:
                    pass
    return _file_response(name, "zip", buf.getvalue(), n)


def _proof_of(ctx: Ctx, batch):
    reg = ctx.reg(safefs.safe_batch(batch))
    if not reg:
        return None
    try:
        return json.loads(Path(reg["proof_path"]).read_text(encoding="utf-8"))
    except Exception:
        return None


def _annot_paras(proof):
    """从一份 proof 汇编批注段落（研究笔记 / 单页批注 / 段落批注）。"""
    paras = []
    notes = (proof.get("notes") or "").strip()
    if notes:
        paras.append("【研究笔记】" + notes)
    for pg in proof.get("pages", []):
        pa = (pg.get("page_annot") or "").strip()
        if pa:
            paras.append(f"〔{pg.get('page_id')}〕{pa}")
        for a in pg.get("annots", []) or []:      # v2 划批：quote+occ 锚定的划选批注
            q = (a.get("quote") or "").strip()
            note = (a.get("note") or "").strip()
            if not q and not note:
                continue
            paras.append(f"· 「{q}」▸ {note}" if note else f"· 「{q}」（划记）")
        lmap = {l["id"]: l for l in pg.get("lines", [])}
        for lid in pg.get("order", []):
            l = lmap.get(lid)
            if not l:
                continue
            a = (l.get("annot") or "").strip()
            if a:
                snippet = (l.get("text", "") or "")[:14]
                paras.append(f"· {snippet}… ▸ {a}")
    return paras


def _export_annotations(ctx, body, fmt):
    nm = safefs.coerce_batch(body.get("name") or "批注")
    paras = []
    if body.get("batches"):
        for b in body["batches"]:
            pr = _proof_of(ctx, b)
            if not pr:
                continue
            ap = _annot_paras(pr)
            if ap:
                paras.append("〖" + (pr.get("source") or b) + "〗")
                paras += ap
    else:
        paras = _annot_paras(body.get("proof") or {})
    data, n = M.paras_doc_bytes(paras, f"{nm}_批注", fmt)
    return _file_response(f"{nm}_批注", fmt, data, n)



def _filter_pages(proof, page_ids):
    wanted = {str(pid) for pid in (page_ids or []) if str(pid)}
    if not wanted:
        return []
    return [p for p in proof.get("pages", []) if str(p.get("page_id")) in wanted]


def _resolved_pages(proof, pages, proof_path=None):
    """Clone pages and pin each usable image to its source proof's safe absolute path."""
    resolved = []
    for page in pages:
        cloned = dict(page)
        src = M.resolve_original_page_image(proof, page, proof_path) if proof_path else M.page_image_path(proof, page)
        cloned["image"] = str(src.resolve()) if (src and src.exists() and safefs.within_work(src)) else ""
        resolved.append(cloned)
    return resolved


def _require_export_images(target, with_image):
    if not with_image:
        return
    missing = []
    for page in target.get("pages", []):
        img = page.get("image", "")
        if not img or not Path(img).exists():
            missing.append({"batch": page.get("batch", target.get("batch", "")),
                            "page_id": page.get("page_id", "")})
    if missing:
        raise HTTPException(422, {
            "code": "export_images_missing",
            "missing_count": len(missing),
            "pages": missing[:10],
        })


def _export_selected(ctx, body, fmt, with_image, page_marks=False, with_annot=False):
    nm = safefs.coerce_batch(body.get("name") or "\u9009\u4e2d\u9875\u9762")
    pages, script, batch_name = [], "s", None

    selected = body.get("selected")
    if not selected:
        raise HTTPException(409, "client_outdated: \u8bf7\u5347\u7ea7\u6216\u91cd\u542f\u5e94\u7528\u540e\u91cd\u65b0\u5bfc\u51fa")

    for item in selected:
        b = item.get("batch")
        if not b:
            continue
        reg = ctx.reg(safefs.safe_batch(b))
        if not reg:
            continue
        proof_path = reg.get("proof_path", "")
        pr = _proof_of(ctx, b)
        if not pr:
            continue
        selected_pages = _resolved_pages(pr, _filter_pages(pr, item.get("page_ids")), proof_path=proof_path)
        if selected_pages:
            pages.extend(selected_pages)
            script = pr.get("script", script)
            if not batch_name:
                batch_name = safefs.safe_batch(b or "")

    if not pages:
        raise HTTPException(400, "\u672a\u9009\u62e9\u9875\u9762")
    target = {"batch": nm, "script": script, "engine": "selected", "pages": pages}
    name = f"{batch_name or nm}_{len(pages)}\u9875_\u8f91\u5f55"
    _require_export_images(target, with_image)
    data, n = M.doc_bytes(target, fmt, t2s=False, page_marks=page_marks, with_annotations=with_annot, with_images=with_image)
    return _packaged(name, fmt, data, n, target, with_image)

def _export_notebook(ctx, body, fmt, with_image, page_marks=False, with_annot=False):
    nm = safefs.coerce_batch(body.get("name") or "笔记本")
    pages, script = [], "s"
    for b in (body.get("batches") or []):
        pr = _proof_of(ctx, b)
        if not pr:
            continue
        pages.extend(_resolved_pages(pr, pr.get("pages", [])))
        script = pr.get("script", script)
    target = {"batch": nm, "script": script, "engine": "merged", "pages": pages}
    name = f"{nm}_辑录"
    _require_export_images(target, with_image)
    data, n = M.doc_bytes(target, fmt, t2s=False, page_marks=page_marks, with_annotations=with_annot, with_images=with_image)
    return _packaged(name, fmt, data, n, target, with_image)


def _export_single(ctx, body, fmt, with_image, page_marks=False, with_annot=False):
    proof = body.get("proof")
    batch = safefs.safe_batch((proof or {}).get("batch", "") or body.get("batch", ""))
    if not proof:
        from document_repository import DocumentNotFoundError, repository_for_proof
        reg = ctx.reg(batch)
        if not reg:
            raise HTTPException(404, "Document not found")
        try:
            proof = repository_for_proof(reg["proof_path"]).load_full()
        except DocumentNotFoundError:
            raise HTTPException(404, "Document not found")
    reg = ctx.reg(batch)
    if reg and body.get("proof"):                 # 仅兼容旧客户端提交的完整 proof
        M.save_proof(proof, reg["proof_path"])
    target, name = proof, f"{batch}_辑录"
    if body.get("scope") == "selected_pages":
        pages = _filter_pages(proof, body.get("page_ids"))
        if not pages:
            raise HTTPException(400, "\u672a\u9009\u62e9\u9875\u9762")
        target = {**proof, "pages": pages}
        name = f"{batch}_{len(pages)}\u9875_\u8f91\u5f55"
    if body.get("scope") == "page" and body.get("page_id"):
        pid = body["page_id"]
        target = {**proof, "pages": [p for p in proof["pages"] if p["page_id"] == pid]}
        name = f"{batch}_{pid}_辑录"
    data, n = M.doc_bytes(target, fmt, t2s=False, page_marks=page_marks, with_annotations=with_annot, with_images=with_image)
    return _packaged(name, fmt, data, n, target, with_image)


def _docx_sources(ctx, body):
    """Resolve lightweight repositories/page selections without loading page bodies."""
    from document_repository import DocumentNotFoundError, repository_for_proof

    scope = body.get("scope", "all")
    if scope == "notebook":
        requests = [{"batch": batch, "page_ids": None} for batch in (body.get("batches") or [])]
    elif scope == "selected_pages":
        requests = body.get("selected") or []
        if not requests:
            raise HTTPException(409, "client_outdated: \u8bf7\u5347\u7ea7\u6216\u91cd\u542f\u5e94\u7528\u540e\u91cd\u65b0\u5bfc\u51fa")
    else:
        requests = [{
            "batch": body.get("batch", ""),
            "page_ids": [body.get("page_id")] if scope == "page" and body.get("page_id") else None,
        }]

    sources, batches, total = [], [], 0
    for request in requests:
        batch = safefs.safe_batch(request.get("batch", ""))
        if not batch:
            continue
        reg = ctx.reg(batch)
        if not reg:
            if scope in {"page", "all"}:
                raise HTTPException(404, "Document not found")
            continue
        try:
            repo = repository_for_proof(reg["proof_path"])
            meta = repo.load_meta()
        except DocumentNotFoundError:
            if scope in {"page", "all"}:
                raise HTTPException(404, "Document not found")
            continue
        requested = request.get("page_ids")
        wanted = {str(page_id) for page_id in requested if str(page_id)} if requested else None
        descriptors = meta.get("pages", [])
        selected_count = sum(1 for page in descriptors
                             if wanted is None or str(page.get("page_id")) in wanted)
        if selected_count:
            sources.append((batch, repo, wanted, meta, reg["proof_path"]))
            batches.append(batch)
            total += selected_count
    if not sources or not total:
        raise HTTPException(400, "No exportable pages selected")
    return sources, batches, total


def _docx_page_iterator(sources, *, with_images=False):
    """Yield cloned pages one at a time, pinning images to each source batch."""
    for batch, repo, wanted, meta, proof_path in sources:
        for page in repo.iter_pages():
            if wanted is not None and str(page.get("page_id")) not in wanted:
                continue
            cloned = dict(page)
            cloned["batch"] = batch
            if with_images:
                image = M.resolve_original_page_image(meta, page, proof_path)
                if not image or not image.exists() or not safefs.within_work(image):
                    raise FileNotFoundError(
                        f"export image missing: batch={batch}, page_id={page.get('page_id', '')}"
                    )
                cloned["image"] = str(image.resolve())
            yield cloned


def _queue_docx_export(ctx, body, *, page_marks=False, with_images=False,
                       with_annotations=False):
    from docx_streaming import write_docx_pages

    sources, batches, total = _docx_sources(ctx, body)
    scope = body.get("scope", "all")
    requested_name = safefs.coerce_batch(body.get("name") or batches[0] or "export")
    if scope == "page":
        page_id = str(body.get("page_id") or "page")
        result_stem = safefs.coerce_batch(f"{batches[0]}_{page_id}_\u8f91\u5f55")
    elif scope == "selected_pages":
        result_stem = safefs.coerce_batch(f"{requested_name}_{total}\u9875_\u8f91\u5f55")
    else:
        result_stem = safefs.coerce_batch(f"{requested_name}_\u8f91\u5f55")

    notes = []
    for batch, _repo, _wanted, meta, _proof_path in sources:
        note = str(meta.get("notes") or "").strip()
        if note:
            notes.append(f"\u3010{meta.get('source') or batch}\u3011{note}")
    document_meta = {"batch": requested_name, "notes": "\n\n".join(notes), "image_dir": ""}

    def runner(task):
        output = task.directory / f"{result_stem}.docx"
        write_docx_pages(
            output,
            document_meta,
            _docx_page_iterator(sources, with_images=with_images),
            page_marks=page_marks,
            with_annotations=with_annotations,
            with_images=with_images,
            task=task,
        )
        return output, output.name

    return TASK_MANAGER.submit(ctx.uid, ctx.work, "export_docx", batches, total, runner)

def _queue_annotation_export(ctx, body, fmt):
    from annotation_streaming import page_annotation_paragraphs, write_annotation_events

    batches = body.get("batches") or ([body.get("batch")] if body.get("batch") else [])
    source_body = {"scope": "notebook", "batches": batches}
    sources, resolved_batches, total = _docx_sources(ctx, source_body)
    export_format = fmt if fmt in {"docx", "txt", "md", "csv"} else "docx"
    name = safefs.coerce_batch(body.get("name") or "annotations")
    result_name = f"{name}_annotations{_EXT[export_format]}"

    def events():
        ordinal = 0
        for batch, repo, _wanted, meta, _proof_path in sources:
            label = str(meta.get("source") or batch)
            yield "heading", label, ordinal
            document_note = str(meta.get("notes") or "").strip()
            if document_note:
                yield "annotation", f"Research notes: {document_note}", ordinal
            for page in repo.iter_pages():
                for paragraph in page_annotation_paragraphs(page):
                    yield "annotation", paragraph, ordinal
                ordinal += 1
                yield "progress", "", ordinal

    def runner(task):
        output = task.directory / result_name
        write_annotation_events(output, events(), fmt=export_format, task=task)
        return output, output.name

    return TASK_MANAGER.submit(ctx.uid, ctx.work, "export_annotations",
                               resolved_batches, total, runner)

def _queue_plain_export(ctx, body, fmt, *, page_marks=False, with_images=False,
                        with_annotations=False):
    from plain_streaming import write_plain_pages

    sources, batches, total = _docx_sources(ctx, body)
    requested_name = safefs.coerce_batch(body.get("name") or batches[0] or "export")
    scope = body.get("scope", "all")
    if scope == "page":
        page_id = str(body.get("page_id") or "page")
        result_stem = safefs.coerce_batch(f"{batches[0]}_{page_id}_\u8f91\u5f55")
    elif scope == "selected_pages":
        result_stem = safefs.coerce_batch(f"{requested_name}_{total}\u9875_\u8f91\u5f55")
    else:
        result_stem = safefs.coerce_batch(f"{requested_name}_\u8f91\u5f55")
    notes = []
    for batch, _repo, _wanted, meta, _proof_path in sources:
        note = str(meta.get("notes") or "").strip()
        if note:
            notes.append(f"\u3010{meta.get('source') or batch}\u3011{note}")
    document_meta = {"batch": requested_name, "notes": "\n\n".join(notes)}

    def runner(task):
        document_path = task.directory / f"{result_stem}{_EXT[fmt]}"
        if not with_images:
            write_plain_pages(
                document_path, document_meta, _docx_page_iterator(sources), fmt=fmt,
                page_marks=page_marks, with_annotations=with_annotations, task=task,
            )
            return document_path, document_path.name

        zip_path = task.directory / f"{result_stem}.zip"
        zip_temp = zip_path.with_name(f".{zip_path.name}.tmp")
        try:
            with zipfile.ZipFile(zip_temp, "w", zipfile.ZIP_DEFLATED) as archive:
                def add_image(page, ordinal):
                    task.check_cancelled()
                    image = Path(page["image"])
                    archive.write(image, f"{result_stem}_originals/{ordinal:04d}_{image.name}")

                write_plain_pages(
                    document_path, document_meta,
                    _docx_page_iterator(sources, with_images=True), fmt=fmt,
                    page_marks=page_marks, with_annotations=with_annotations,
                    task=task, on_page=add_image,
                )
                task.check_cancelled()
                archive.write(document_path, document_path.name)
            zip_temp.replace(zip_path)
            return zip_path, zip_path.name
        finally:
            zip_temp.unlink(missing_ok=True)
            document_path.unlink(missing_ok=True)

    kind = "export_zip" if with_images else "export_plain"
    return TASK_MANAGER.submit(ctx.uid, ctx.work, kind, batches, total, runner)

@router.post("/api/export")
async def export(req: Request, ctx: Ctx = Depends(ctx_dep)):
    body = await req.json()
    scope = body.get("scope", "all")
    st = load_settings(ctx)
    fmt = body.get("fmt") or st.get("export_format", "docx")
    if fmt not in _EXT:
        fmt = "docx"
    with_image = body.get("with_image")
    if with_image is None:
        with_image = st.get("export_with_image", False)
    page_marks = body.get("page_marks")          # 每页正文前插「【第N页】」
    if page_marks is None:
        page_marks = st.get("export_page_marks", False)
    if scope == "annotations":
        if not body.get("proof") and (body.get("batches") or body.get("batch")):
            task = _queue_annotation_export(ctx, body, fmt)
            return JSONResponse({"job_id": task.task_id, "state": task.state,
                                 "kind": task.kind}, status_code=202)
        return _export_annotations(ctx, body, fmt)
    with_annot = bool(body.get("with_annot"))
    if fmt == "docx" and not body.get("proof"):
        task = _queue_docx_export(ctx, body, page_marks=page_marks,
                                  with_images=bool(with_image),
                                  with_annotations=with_annot)
        return JSONResponse({"job_id": task.task_id, "state": task.state,
                             "kind": task.kind}, status_code=202)
    if fmt in {"txt", "md", "csv"} and not body.get("proof") and (with_image or with_annot):
        task = _queue_plain_export(ctx, body, fmt, page_marks=page_marks,
                                   with_images=bool(with_image),
                                   with_annotations=with_annot)
        return JSONResponse({"job_id": task.task_id, "state": task.state,
                             "kind": task.kind}, status_code=202)
    streamed = _stream_multi_plain_export(ctx, body, fmt, page_marks, with_image, with_annot)
    if streamed is not None:
        return streamed
    if scope == "notebook":
        return _export_notebook(ctx, body, fmt, with_image, page_marks, with_annot)
    if scope == "selected_pages":
        return _export_selected(ctx, body, fmt, with_image, page_marks, with_annot)
    if not body.get("proof") and not body.get("batch"):
        raise HTTPException(400, "未打开史料")
    streamed = _stream_plain_export(ctx, body, fmt, page_marks)
    if streamed is not None:
        return streamed
    return _export_single(ctx, body, fmt, with_image, page_marks, with_annot)
def _stream_plain_export(ctx, body, fmt, page_marks):
    """Return a StreamingResponse for plain page-granular exports, or None."""
    if fmt not in {"txt", "md", "csv"} or body.get("with_image") or body.get("with_annot"):
        return None
    batch = safefs.safe_batch(body.get("batch", ""))
    if not batch:
        return None
    reg = ctx.reg(batch)
    if not reg:
        raise HTTPException(404, "Document not found")
    from document_repository import DocumentNotFoundError, repository_for_proof
    try:
        repo = repository_for_proof(reg["proof_path"])
        meta = repo.load_meta()
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found")
    wanted = {str(body.get("page_id"))} if body.get("scope") == "page" and body.get("page_id") else None

    def chunks():
        import csv
        import io
        if fmt == "csv":
            row = io.StringIO()
            writer = csv.writer(row)
            writer.writerow(["page_id", "line_id", "text"])
            yield row.getvalue().encode("utf-8-sig")
            for page in repo.iter_pages():
                if wanted and page.get("page_id") not in wanted:
                    continue
                line_map = {line.get("id"): line for line in page.get("lines", [])}
                for line_id in page.get("order", []):
                    line = line_map.get(line_id)
                    if not line or line.get("deleted"):
                        continue
                    row = io.StringIO()
                    csv.writer(row).writerow([page.get("page_id", ""), line_id, line.get("text", "")])
                    yield row.getvalue().encode("utf-8")
            return
        current = []
        for ordinal, page in enumerate(repo.iter_pages(), 1):
            if wanted and page.get("page_id") not in wanted:
                continue
            if page_marks:
                if current:
                    yield ("".join(current) + "\n\n").encode("utf-8")
                    current = []
                label = f"【第{ordinal}页】"
                yield ((f"## {label}\n\n" if fmt == "md" else label + "\n\n")).encode("utf-8")
            line_map = {line.get("id"): line for line in page.get("lines", [])}
            for line_id in page.get("order", []):
                line = line_map.get(line_id)
                if not line or line.get("deleted"):
                    continue
                current.append(line.get("text", ""))
                if line.get("para_break"):
                    yield ("".join(current) + "\n\n").encode("utf-8")
                    current = []
        if current:
            yield ("".join(current) + "\n").encode("utf-8")

    name = safefs.coerce_batch(body.get("name") or meta.get("source") or batch)
    filename = name + _EXT[fmt]
    disposition = "attachment; filename*=UTF-8''" + quote(filename)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(chunks(), media_type=_MEDIA[fmt],
                             headers={"Content-Disposition": disposition,
                                      "Access-Control-Expose-Headers": "Content-Disposition"})


def _stream_multi_plain_export(ctx, body, fmt, page_marks, with_image, with_annot):
    """Stream notebook and selected-page plain exports without document aggregation."""
    scope = body.get("scope")
    if scope not in {"notebook", "selected_pages"} or fmt not in {"txt", "md", "csv"}:
        return None
    if with_image or with_annot:
        return None
    from document_repository import DocumentNotFoundError, repository_for_proof
    if scope == "notebook":
        requests = [{"batch": batch, "page_ids": None} for batch in (body.get("batches") or [])]
    else:
        requests = body.get("selected") or []
    sources = []
    for request in requests:
        batch = safefs.safe_batch(request.get("batch", ""))
        reg = ctx.reg(batch)
        if not reg:
            continue
        try:
            repo = repository_for_proof(reg["proof_path"])
            meta = repo.load_meta()
        except DocumentNotFoundError:
            continue
        wanted = request.get("page_ids")
        wanted = {str(page_id) for page_id in wanted} if wanted else None
        sources.append((repo, wanted, meta))
    if not sources:
        raise HTTPException(400, "No exportable pages selected")

    def chunks():
        import csv
        import io
        if fmt == "csv":
            row = io.StringIO()
            csv.writer(row).writerow(["batch", "page_id", "line_id", "text"])
            yield row.getvalue().encode("utf-8-sig")
        ordinal = 0
        current = []
        for repo, wanted, meta in sources:
            for page in repo.iter_pages():
                if wanted and str(page.get("page_id")) not in wanted:
                    continue
                ordinal += 1
                if fmt == "csv":
                    line_map = {line.get("id"): line for line in page.get("lines", [])}
                    for line_id in page.get("order", []):
                        line = line_map.get(line_id)
                        if line and not line.get("deleted"):
                            row = io.StringIO()
                            csv.writer(row).writerow([meta.get("batch", ""), page.get("page_id", ""), line_id, line.get("text", "")])
                            yield row.getvalue().encode("utf-8")
                    continue
                if page_marks:
                    if current:
                        yield ("".join(current) + "\n\n").encode("utf-8")
                        current = []
                    label = f"Page {ordinal}"
                    yield ((f"## {label}\n\n" if fmt == "md" else label + "\n\n")).encode("utf-8")
                line_map = {line.get("id"): line for line in page.get("lines", [])}
                for line_id in page.get("order", []):
                    line = line_map.get(line_id)
                    if not line or line.get("deleted"):
                        continue
                    current.append(line.get("text", ""))
                    if line.get("para_break"):
                        yield ("".join(current) + "\n\n").encode("utf-8")
                        current = []
        if current:
            yield ("".join(current) + "\n").encode("utf-8")

    name = safefs.coerce_batch(body.get("name") or "export")
    disposition = "attachment; filename*=UTF-8''" + quote(name + _EXT[fmt])
    from fastapi.responses import StreamingResponse
    return StreamingResponse(chunks(), media_type=_MEDIA[fmt],
                             headers={"Content-Disposition": disposition,
                                      "Access-Control-Expose-Headers": "Content-Disposition"})
@router.get("/api/document_task/{task_id}")
def document_task_status(task_id: str, ctx: Ctx = Depends(ctx_dep)):
    task = TASK_MANAGER.get(ctx.uid, task_id)
    if task is None:
        raise HTTPException(404, "Document task not found")
    return task.status()


@router.post("/api/document_task/{task_id}/cancel")
def cancel_document_task(task_id: str, ctx: Ctx = Depends(ctx_dep)):
    task = TASK_MANAGER.cancel(ctx.uid, task_id)
    if task is None:
        raise HTTPException(404, "Document task not found")
    return task.status()


@router.get("/api/document_task/{task_id}/result")
def document_task_result(task_id: str, ctx: Ctx = Depends(ctx_dep)):
    task = TASK_MANAGER.get(ctx.uid, task_id)
    if task is None:
        raise HTTPException(404, "Document task not found")
    if task.state != "done" or task.result_path is None or not task.result_path.is_file():
        raise HTTPException(409, "Document task result is not ready")
    try:
        task.result_path.resolve().relative_to(task.directory.resolve())
    except ValueError:
        raise HTTPException(500, "Invalid document task result")
    filename = task.result_name or task.result_path.name
    return FileResponse(str(task.result_path), filename=filename,
                        media_type="application/octet-stream")