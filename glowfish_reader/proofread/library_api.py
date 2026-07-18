# -*- coding: utf-8 -*-
"""库管理 API（per-user）：设置、顶层笔记本注册表、删除/复制文档。

全部落在当前登录用户 _work/users/<uid>/ 内，各用户互不可见。
"""
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends

import proof_model as M
from document_repository import repository_for_proof
import safefs
from settings_store import DEFAULT_SETTINGS, load_settings, save_settings
from userctx import Ctx, ctx_dep

router = APIRouter()

# ---- 全库搜索限制 ----
MAX_QUERY_LEN = 200
MAX_HITS = 200
MAX_BATCHES = 500


@router.get("/api/settings")
def get_settings(ctx: Ctx = Depends(ctx_dep)):
    return load_settings(ctx)


@router.post("/api/settings")
async def set_settings(req: Request, ctx: Ctx = Depends(ctx_dep)):
    body = await req.json()
    if body.get("reset"):
        s = dict(DEFAULT_SETTINGS)
    else:
        s = load_settings(ctx)
        for k in DEFAULT_SETTINGS:               # 仅接受已知键
            if k in body:
                s[k] = body[k]
    save_settings(ctx, s)
    return {"ok": True, "settings": s}


@router.post("/api/proof_search")
async def proof_search(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """点校区关键词搜索：简繁互通 + 忽略标点。无状态纯计算（登录后可用）。
    body {query, items:[{text}, ...]} → {hits:[ [[s,e],...], ... ]}（与 items 等长，原文坐标）。"""
    body = await req.json()
    query = body.get("query") or ""
    texts = [(it or {}).get("text", "") for it in (body.get("items") or [])]
    return {"hits": M.search_in_texts(query, texts)}


# ---- 顶层笔记本注册表（磁盘持久备份；IndexedDB 清缓存后据此重建索引）----
def _bootstrap_notebooks(ctx):
    """notebooks.json 不存在时：扫本用户各 <batch>/proof.json 自举默认笔记本。"""
    docs, order = {}, 0
    for d in sorted([x for x in ctx.work.iterdir() if x.is_dir()],
                    key=lambda x: x.name.lower()):
        pf = d / "proof.json"
        if not pf.exists():
            continue
        try:
            p = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            continue
        batch = p.get("batch", d.name)
        pages = p.get("pages", [])
        docs[batch] = {
            "notebookId": "nb_default",
            "displayName": p.get("source") or batch,
            "order": order,
            "pageCount": len(pages),
            "firstPage": pages[0].get("page_id") if pages else None,
            "createdAt": int(pf.stat().st_mtime * 1000),
        }
        order += 1
    nb = {"id": "nb_default", "name": "我的史料", "tags": [], "archived": False,
          "created": 0, "updated": 0, "order": 0, "documentIds": list(docs.keys())}
    return {"notebooks": [nb] if docs else [], "documents": docs}


def _load_notebooks(ctx):
    if ctx.notebooks_path.exists():
        try:
            return json.loads(ctx.notebooks_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    nb = _bootstrap_notebooks(ctx)
    ctx.notebooks_path.write_text(
        json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
    return nb


@router.get("/api/notebooks")
def get_notebooks(ctx: Ctx = Depends(ctx_dep)):
    return _load_notebooks(ctx)


@router.post("/api/notebooks")
async def set_notebooks(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """前端整树提交（笔记本/文档增删改、归属、排序），后端整体覆写落盘。"""
    body = await req.json()
    nb = {"notebooks": body.get("notebooks", []), "documents": body.get("documents", {})}
    ctx.notebooks_path.write_text(
        json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@router.post("/api/delete_batch")
async def delete_batch(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """彻底销毁某文档：删 _work/users/<uid>/<batch>/。safe_batch 限定在本用户目录内。"""
    body = await req.json()
    batch = safefs.safe_batch(body.get("batch", ""))
    bdir = ctx.work / batch
    if bdir.exists():
        shutil.rmtree(bdir, ignore_errors=True)
    return {"ok": True}


@router.post("/api/copy_batch")
async def copy_batch(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """复制一个文档为新批次。返回新 batch id 与 proof。"""
    body = await req.json()
    src = safefs.safe_batch(body.get("batch", ""))
    sdir = ctx.work / src
    if not (sdir / "proof.json").exists():
        raise HTTPException(404, "源文档不存在")
    base = safefs.coerce_batch(body.get("new_batch") or (src + "_副本"))
    dst, i = base, 2
    while (ctx.work / dst).exists():
        dst = safefs.coerce_batch(f"{base}{i}"); i += 1
    ddir = ctx.work / dst
    shutil.copytree(sdir, ddir)
    proof_path = ddir / "proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["batch"] = dst
    old_img, new_img = str(sdir), str(ddir)       # 旧目录→新目录，重写归一图绝对路径
    for p in proof.get("pages", []):
        if p.get("image"):
            p["image"] = p["image"].replace(old_img, new_img)
    if proof.get("image_dir"):
        proof["image_dir"] = proof["image_dir"].replace(old_img, new_img)
    M.save_proof(proof, proof_path)
    # The copied batch is immediately available through the page repository. Do
    # not return all OCR lines to the browser merely to register it in the tree.
    meta = repository_for_proof(proof_path).load_meta()
    return {"ok": True, "batch": dst, "document_meta": meta,
            "page_count": len(meta.get("pages", [])), "paged": True}


# ---- 全库只读搜索 ----
@router.post("/api/library_search")
async def library_search(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Read-only full-library keyword search.

    Reads only notebook.json + proof.json files. No OCR, no file writes, no engine
    imports. Each damaged document is skipped individually and reported in `skipped`.

    Request: {query, limit?}
    Response: {hits: [{batch, docName, pageId, pageIdx, lineId, start, end, text}],
               totalHits, skipped: [{batch, reason}], truncated: bool}
    """
    body = await req.json()
    query = (body.get("query") or "").strip()
    if not query:
        return {"hits": [], "totalHits": 0, "skipped": [], "truncated": False}
    if len(query) > MAX_QUERY_LEN:
        raise HTTPException(400, f"Query too long (max {MAX_QUERY_LEN} chars)")
    limit = min(int(body.get("limit") or MAX_HITS), MAX_HITS)

    # 1. Load notebook registry without creating/updating any file. Search must
    # remain read-only even for a legacy/cold-start data directory.
    if ctx.notebooks_path.exists():
        try:
            nb_data = json.loads(ctx.notebooks_path.read_text(encoding="utf-8"))
        except Exception:
            nb_data = _bootstrap_notebooks(ctx)
    else:
        nb_data = _bootstrap_notebooks(ctx)
    docs = nb_data.get("documents") or {}

    hits = []
    skipped = []
    total_hits = 0
    truncated = False

    # 2. Iterate batches in deterministic order
    batch_ids = list(docs.keys())
    if len(batch_ids) > MAX_BATCHES:
        batch_ids = batch_ids[:MAX_BATCHES]
        truncated = True

    for batch in batch_ids:
        if len(hits) >= limit:
            truncated = True
            break

        doc_meta = docs.get(batch) or {}
        doc_name = doc_meta.get("displayName") or batch
        proof_path = ctx.work / safefs.safe_batch(batch) / "proof.json"
        if not proof_path.exists():
            skipped.append({"batch": batch, "reason": "proof.json not found"})
            continue

        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
        except Exception:
            skipped.append({"batch": batch, "reason": "proof.json corrupted"})
            continue

        # 3. Walk pages in order, skip deleted lines
        for page_idx, pg in enumerate(proof.get("pages", []) or []):
            if len(hits) >= limit:
                truncated = True
                break
            page_id = pg.get("page_id", "")
            lmap = {l["id"]: l for l in pg.get("lines", [])}
            for lid in pg.get("order", []) or []:
                if len(hits) >= limit:
                    truncated = True
                    break
                l = lmap.get(lid)
                if not l or l.get("deleted"):
                    continue
                line_text = l.get("text") or ""
                if not line_text:
                    continue

                # 4. Search in this line using existing normalization (简繁互通 + 忽略标点)
                rngs = M.search_in_texts(query, [line_text])
                for rng in (rngs[0] if rngs else []):
                    if len(hits) >= limit:
                        truncated = True
                        break
                    s, e = rng
                    hits.append({
                        "batch": batch,
                        "docId": batch,
                        "docName": doc_name,
                        "pageId": page_id,
                        "pageIdx": page_idx,
                        "lineId": lid,
                        "start": s,
                        "end": e,
                        "text": line_text,
                    })
                    total_hits += 1

    # 5. Strip absolute paths from skipped (safety)
    return {
        "hits": hits,
        "totalHits": total_hits,
        "skipped": skipped,
        "truncated": truncated,
    }
@router.post("/api/document_search")
async def document_search(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Page-streaming full-library search for versioned documents."""
    from document_repository import DocumentError, DocumentRepository

    body = await req.json()
    query = (body.get("query") or "").strip()
    if not query:
        return {"hits": [], "totalHits": 0, "skipped": [], "truncated": False}
    if len(query) > MAX_QUERY_LEN:
        raise HTTPException(400, f"Query too long (max {MAX_QUERY_LEN} chars)")
    limit = min(int(body.get("limit") or MAX_HITS), MAX_HITS)
    try:
        notebooks = json.loads(ctx.notebooks_path.read_text(encoding="utf-8")) if ctx.notebooks_path.exists() else _bootstrap_notebooks(ctx)
    except Exception:
        notebooks = _bootstrap_notebooks(ctx)
    docs = notebooks.get("documents") or {}
    hits, skipped, total_hits = [], [], 0
    truncated = len(docs) > MAX_BATCHES
    for batch in list(docs)[:MAX_BATCHES]:
        if len(hits) >= limit:
            truncated = True
            break
        batch_dir = ctx.work / safefs.safe_batch(batch)
        try:
            repo = DocumentRepository(batch_dir)
            repo.load_meta()
        except (DocumentError, OSError, ValueError):
            skipped.append({"batch": batch, "reason": "document storage unavailable"})
            continue
        doc_name = (docs.get(batch) or {}).get("displayName") or batch
        for page_idx, page in enumerate(repo.iter_pages()):
            if len(hits) >= limit:
                truncated = True
                break
            line_map = {line.get("id"): line for line in page.get("lines", [])}
            for line_id in page.get("order", []):
                line = line_map.get(line_id)
                if not line or line.get("deleted"):
                    continue
                text = line.get("text") or ""
                for start, end in (M.search_in_texts(query, [text])[0] if text else []):
                    hits.append({
                        "batch": batch, "docId": batch, "docName": doc_name,
                        "pageId": page.get("page_id", ""), "pageIdx": page_idx,
                        "lineId": line_id, "start": start, "end": end, "text": text,
                    })
                    total_hits += 1
                    if len(hits) >= limit:
                        truncated = True
                        break
                if len(hits) >= limit:
                    break
    return {"hits": hits, "totalHits": total_hits, "skipped": skipped, "truncated": truncated}

