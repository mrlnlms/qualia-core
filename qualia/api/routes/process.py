"""Endpoint de processamento de documentos."""

import hashlib
import asyncio

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import JSONResponse

from qualia.core import Document
from qualia.api.deps import get_core, get_job_manager, track, validate_plugin_config, require_plugin_type
from qualia.api.routing import should_run_async
from qualia.api.schemas import ProcessRequest

router = APIRouter()


@router.post("/process/{plugin_id}")
async def process(
    plugin_id: str,
    request: ProcessRequest,
    sync: bool = Query(False, alias="sync"),
    async_mode: bool = Query(False, alias="async"),
):
    """Execute a document processor plugin"""
    core = get_core()
    require_plugin_type(core, plugin_id, "document")

    # Bloquear plugins de transcrição — precisam de file upload via /transcribe
    meta = core.registry.get(plugin_id)
    if meta and "transcription" in (meta.provides or []):
        raise HTTPException(
            status_code=422,
            detail=f"Plugin '{plugin_id}' é de transcrição — use POST /transcribe/{plugin_id} com upload de arquivo.",
        )

    try:
        validate_plugin_config(core, plugin_id, request.config)

        doc = core.add_document(f"api_process_{plugin_id}_{hashlib.md5(request.text.encode()).hexdigest()[:8]}", request.text)

        if should_run_async(meta, sync_override=sync, async_override=async_mode, is_pipeline=False):
            manager = get_job_manager()
            from qualia.core.jobs import Job
            job = Job.create_single(plugin_id=plugin_id)
            manager.store(job)

            def executor(job_id):
                result = core.execute_plugin(plugin_id, doc, request.config, request.context)
                if isinstance(result, Document):
                    result = result.content
                return result

            asyncio.get_event_loop().create_task(manager.submit(job.id, executor))
            await track(f"/process/{plugin_id}", plugin_id, "async")
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": job.id,
                    "status": "pending",
                    "status_url": f"/jobs/{job.id}",
                    "stream_url": f"/jobs/{job.id}/stream",
                }
            )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(core.execute_plugin, plugin_id, doc, request.config, request.context),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            await track(f"/process/{plugin_id}", plugin_id, "timeout")
            raise HTTPException(status_code=504, detail="Plugin execution timed out (60s)")

        if isinstance(result, Document):
            result = result.content

        await track(f"/process/{plugin_id}", plugin_id)

        return {
            "status": "success",
            "plugin_id": plugin_id,
            "processed_text": result
        }
    except HTTPException:
        raise
    except Exception as e:
        await track(f"/process/{plugin_id}", plugin_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))
