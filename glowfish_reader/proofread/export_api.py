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
from fastapi.responses import Response

import proof_model as M
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
            src = Path(p.get("image", ""))
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


def _export_selected(ctx, body, fmt, with_image, page_marks=False, with_annot=False):
    nm = safefs.coerce_batch(body.get("name") or "\u9009\u4e2d\u9875\u9762")
    pages, script, batch_name = [], "s", None

    if body.get("selected"):
        for item in body.get("selected") or []:
            b = item.get("batch")
            pr = _proof_of(ctx, b)
            if not pr:
                continue
            selected_pages = _filter_pages(pr, item.get("page_ids"))
            if selected_pages:
                pages.extend(selected_pages)
                script = pr.get("script", script)
                if not batch_name:
                    batch_name = safefs.safe_batch(b or "")
    else:
        proof = body.get("proof") or {}
        batch_name = safefs.safe_batch(proof.get("batch", ""))
        pages = _filter_pages(proof, body.get("page_ids"))
        script = proof.get("script", script)
        nm = batch_name or nm

    if not pages:
        raise HTTPException(400, "\u672a\u9009\u62e9\u9875\u9762")
    target = {"batch": nm, "script": script, "engine": "selected", "pages": pages}
    name = f"{batch_name or nm}_{len(pages)}\u9875_\u8f91\u5f55"
    data, n = M.doc_bytes(target, fmt, t2s=False, page_marks=page_marks, with_annotations=with_annot, with_images=with_image)
    return _packaged(name, fmt, data, n, target, with_image)

def _export_notebook(ctx, body, fmt, with_image, page_marks=False, with_annot=False):
    nm = safefs.coerce_batch(body.get("name") or "笔记本")
    pages, script = [], "s"
    for b in (body.get("batches") or []):
        pr = _proof_of(ctx, b)
        if not pr:
            continue
        pages.extend(pr.get("pages", []))
        script = pr.get("script", script)
    target = {"batch": nm, "script": script, "engine": "merged", "pages": pages}
    name = f"{nm}_辑录"
    data, n = M.doc_bytes(target, fmt, t2s=False, page_marks=page_marks, with_annotations=with_annot, with_images=with_image)
    return _packaged(name, fmt, data, n, target, with_image)


def _export_single(ctx, body, fmt, with_image, page_marks=False, with_annot=False):
    proof = body["proof"]
    batch = safefs.safe_batch(proof.get("batch", ""))
    reg = ctx.reg(batch)
    if reg:                                       # 导出前落盘当前 proof
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
        return _export_annotations(ctx, body, fmt)
    with_annot = bool(body.get("with_annot"))
    if scope == "notebook":
        return _export_notebook(ctx, body, fmt, with_image, page_marks, with_annot)
    if scope == "selected_pages":
        return _export_selected(ctx, body, fmt, with_image, page_marks, with_annot)
    if not body.get("proof"):
        raise HTTPException(400, "未打开史料")
    return _export_single(ctx, body, fmt, with_image, page_marks, with_annot)
