# -*- coding: utf-8 -*-
"""库管理 API（per-user）：设置、顶层笔记本注册表、删除/复制文档。

全部落在当前登录用户 _work/users/<uid>/ 内，各用户互不可见。
"""
import json
import shutil
from pathlib import Path

import anyio

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
    """Build a default notebook from completed or partially published documents."""
    docs, order = {}, 0
    for d in sorted([x for x in ctx.work.iterdir() if x.is_dir()],
                    key=lambda x: x.name.lower()):
        pf = d / "proof.json"
        meta_path = d / "document.json"
        if not pf.exists() and not meta_path.exists():
            continue
        try:
            p = repository_for_proof(pf).load_meta()
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
            "createdAt": int((meta_path if meta_path.exists() else pf).stat().st_mtime * 1000),
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


def _copy_page_repository(source_dir, destination_dir, destination_batch):
    """Copy and rebase one page at a time; remove an incomplete destination."""
    source_dir = Path(source_dir)
    destination_dir = Path(destination_dir)
    try:
        shutil.copytree(source_dir, destination_dir)
        repo = repository_for_proof(destination_dir / "proof.json")
        meta = repo.load_meta()
        source_root = str(source_dir.resolve())
        destination_root = str(destination_dir.resolve())
        raw_image_dir = str(meta.get("image_dir") or "")
        image_dir = raw_image_dir.replace(source_root, destination_root)
        if not image_dir and (destination_dir / "_src").is_dir():
            image_dir = str((destination_dir / "_src").resolve())

        def rebase(page, _index):
            raw_image = str(page.get("image") or "")
            rebased = raw_image.replace(source_root, destination_root)
            if rebased == raw_image:
                return False
            page["image"] = rebased
            return True

        return repo.transform_pages(
            rebase, meta_changes={"batch": destination_batch, "image_dir": image_dir}
        )
    except Exception:
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise

@router.post("/api/copy_batch")
async def copy_batch(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Copy a document using page repository reads and writes."""
    body = await req.json()
    src = safefs.safe_batch(body.get("batch", ""))
    sdir = ctx.work / src
    if not (sdir / "proof.json").exists():
        raise HTTPException(404, "Source document not found")
    base = safefs.coerce_batch(body.get("new_batch") or (src + "_copy"))
    dst, index = base, 2
    while (ctx.work / dst).exists():
        dst = safefs.coerce_batch(f"{base}{index}")
        index += 1
    ddir = ctx.work / dst
    try:
        meta = await anyio.to_thread.run_sync(_copy_page_repository, sdir, ddir, dst)
    except Exception as error:
        raise HTTPException(500, f"Document copy failed: {error}")
    return {"ok": True, "batch": dst, "document_meta": meta,
            "page_count": len(meta.get("pages", [])), "paged": True}

# ---- page-streaming library search ----
def _paged_library_search(ctx, body):
    """Search repositories one page at a time; never read a complete proof snapshot."""
    from document_repository import DocumentError, DocumentRepository

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
                for match_start, match_end in (M.search_in_texts(query, [text])[0] if text else []):
                    hits.append({
                        "batch": batch, "docId": batch, "docName": doc_name,
                        "pageId": page.get("page_id", ""), "pageIdx": page_idx,
                        "lineId": line_id, "start": match_start, "end": match_end, "text": text,
                    })
                    total_hits += 1
                    if len(hits) >= limit:
                        truncated = True
                        break
                if len(hits) >= limit:
                    break
    return {"hits": hits, "totalHits": total_hits, "skipped": skipped, "truncated": truncated}


@router.post("/api/library_search")
async def library_search(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Deprecated alias retained for one version; implementation is page streaming."""
    return _paged_library_search(ctx, await req.json())


@router.post("/api/document_search")
async def document_search(req: Request, ctx: Ctx = Depends(ctx_dep)):
    return _paged_library_search(ctx, await req.json())