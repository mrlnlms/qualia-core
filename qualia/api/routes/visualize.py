"""Rota de visualização — plugin renderiza, BaseClass serializa."""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import JSONResponse

from qualia.api.deps import get_core, get_job_manager, track, validate_plugin_config, require_plugin_type
from qualia.api.routing import should_run_async
from qualia.api.schemas import VisualizeRequest

router = APIRouter()


@router.post("/visualize/{plugin_id}")
async def visualize(
    plugin_id: str,
    request: VisualizeRequest,
    sync: bool = Query(False, alias="sync"),
    async_mode: bool = Query(False, alias="async"),
):
    """Gera visualização usando plugin especificado.

    Retorna dict com "html" (string HTML) ou "data"+"encoding"+"format" (base64 imagem).
    """
    core = get_core()
    require_plugin_type(core, plugin_id, "visualizer")

    try:
        validate_plugin_config(core, plugin_id, request.config)
        config = {**request.config, "output_format": request.output_format or "html"}
        plugin = core.loader.get_plugin(plugin_id)

        meta = core.registry.get(plugin_id)
        if should_run_async(meta, sync_override=sync, async_override=async_mode, is_pipeline=False):
            manager = get_job_manager()
            from qualia.core.jobs import Job
            job = Job.create_single(plugin_id=plugin_id)
            manager.store(job)

            def executor(job_id):
                return plugin.render(request.data, config)

            asyncio.get_event_loop().create_task(manager.submit(job.id, executor))
            await track(f"/visualize/{plugin_id}", plugin_id, "async")
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": job.id,
                    "status": "pending",
                    "status_url": f"/jobs/{job.id}",
                    "stream_url": f"/jobs/{job.id}/stream",
                }
            )

        result = await asyncio.wait_for(
            asyncio.to_thread(plugin.render, request.data, config),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        await track(f"/visualize/{plugin_id}", plugin_id, "timeout")
        raise HTTPException(status_code=504, detail=f"Plugin '{plugin_id}' timed out (60s)")
    except HTTPException:
        raise
    except Exception as e:
        await track(f"/visualize/{plugin_id}", plugin_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))

    await track(f"/visualize/{plugin_id}", plugin_id)
    return {"status": "success", "plugin_id": plugin_id, **result}
