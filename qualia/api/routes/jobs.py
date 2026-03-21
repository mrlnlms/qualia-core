"""Endpoints para gerenciamento de jobs assíncronos."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from qualia.api.deps import get_job_manager
from qualia.core.jobs import JobStatus

router = APIRouter()


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(None),
    plugin_id: str | None = Query(None),
):
    manager = get_job_manager()
    status_filter = None
    if status:
        try:
            status_filter = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
    jobs = manager.list_jobs(status=status_filter, plugin_id=plugin_id)
    return [j.to_dict() for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    manager = get_job_manager()
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job.to_dict()


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    manager = get_job_manager()
    result = manager.cancel(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Job cannot be cancelled (already running or finished)")
    return {"status": "cancelled", "job_id": job_id}


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    manager = get_job_manager()
    queue = await manager.subscribe(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    event_type = event.pop("_event_type", "status")
                    yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                    if event.get("status") in ("completed", "failed", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            await manager.unsubscribe(job_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
