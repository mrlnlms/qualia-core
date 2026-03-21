# Async Job Queue — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add async job queue to Qualia so heavy plugins (ML, transcription) can run without timeout, with progress tracking via SSE/polling/webhook.

**Architecture:** New data models in `qualia/core/jobs.py`, `JobManager` orchestrator in `qualia/api/jobs.py`, new `/jobs` routes, and modifications to existing endpoints for sync/async routing. Engine stays synchronous — all async logic lives in the API layer.

**Tech Stack:** Python 3.13, FastAPI (lifespan, Query, StreamingResponse), asyncio, threading.Lock, httpx (webhook dispatch), pytest + httpx.AsyncClient (async tests)

---

## Chunk 1: Job Data Models + PluginMetadata

### Task 1: Job data models (`qualia/core/jobs.py`)

**Files:**
- Create: `qualia/core/jobs.py`
- Create: `tests/test_job_models.py`

- [ ] **Step 1: Write failing tests for Job data models**

```python
# tests/test_job_models.py
"""Testes para os data models do Job."""
import time
from datetime import datetime, timezone

from qualia.core.jobs import Job, JobStatus, JobStep, JobType


class TestJobStatus:
    def test_enum_values(self):
        assert JobStatus.pending == "pending"
        assert JobStatus.running == "running"
        assert JobStatus.completed == "completed"
        assert JobStatus.failed == "failed"
        assert JobStatus.cancelled == "cancelled"

    def test_is_terminal(self):
        assert not JobStatus.pending.is_terminal
        assert not JobStatus.running.is_terminal
        assert JobStatus.completed.is_terminal
        assert JobStatus.failed.is_terminal
        assert JobStatus.cancelled.is_terminal


class TestJobType:
    def test_enum_values(self):
        assert JobType.single == "single"
        assert JobType.pipeline == "pipeline"


class TestJobStep:
    def test_create_pending(self):
        step = JobStep(plugin_id="sentiment")
        assert step.status == JobStatus.pending
        assert step.progress is None
        assert step.result is None
        assert step.error is None

    def test_mark_running(self):
        step = JobStep(plugin_id="sentiment")
        step.status = JobStatus.running
        assert step.status == JobStatus.running

    def test_mark_completed_with_result(self):
        step = JobStep(plugin_id="sentiment")
        step.status = JobStatus.completed
        step.result = {"sentiment_score": 0.85}
        assert step.result == {"sentiment_score": 0.85}

    def test_mark_failed_with_error(self):
        step = JobStep(plugin_id="sentiment")
        step.status = JobStatus.failed
        step.error = "Plugin crashed"
        assert step.error == "Plugin crashed"


class TestJob:
    def test_create_single_job(self):
        job = Job.create_single(plugin_id="sentiment")
        assert job.type == JobType.single
        assert job.status == JobStatus.pending
        assert job.plugin_id == "sentiment"
        assert job.progress == 0.0
        assert job.current_step == 0
        assert job.total_steps == 1
        assert job.steps == []
        assert job.result is None
        assert job.error is None
        assert job.callback_url is None
        assert job.temp_files == []
        assert job.ttl == 3600
        assert len(job.id) == 36  # UUID format

    def test_create_single_with_options(self):
        job = Job.create_single(
            plugin_id="transcription_local",
            callback_url="http://localhost:9000/hook",
            temp_files=["/tmp/audio.wav"],
            ttl=7200,
        )
        assert job.callback_url == "http://localhost:9000/hook"
        assert job.temp_files == ["/tmp/audio.wav"]
        assert job.ttl == 7200

    def test_create_pipeline_job(self):
        plugin_ids = ["transcription_local", "sentiment", "wordcloud"]
        job = Job.create_pipeline(plugin_ids=plugin_ids)
        assert job.type == JobType.pipeline
        assert job.status == JobStatus.pending
        assert job.plugin_id == "transcription_local"
        assert job.total_steps == 3
        assert len(job.steps) == 3
        assert all(s.status == JobStatus.pending for s in job.steps)
        assert [s.plugin_id for s in job.steps] == plugin_ids

    def test_is_expired_false_when_fresh(self):
        job = Job.create_single(plugin_id="sentiment")
        assert not job.is_expired

    def test_is_expired_true_when_old(self):
        job = Job.create_single(plugin_id="sentiment", ttl=0)
        time.sleep(0.01)
        assert job.is_expired

    def test_to_dict_single(self):
        job = Job.create_single(plugin_id="sentiment")
        d = job.to_dict()
        assert d["type"] == "single"
        assert d["status"] == "pending"
        assert d["plugin_id"] == "sentiment"
        assert "id" in d
        assert "created_at" in d
        assert "steps" not in d  # single jobs omit steps

    def test_to_dict_pipeline_includes_steps(self):
        job = Job.create_pipeline(plugin_ids=["a", "b"])
        d = job.to_dict()
        assert "steps" in d
        assert len(d["steps"]) == 2
        assert d["steps"][0]["plugin_id"] == "a"

    def test_calculate_progress_single(self):
        job = Job.create_single(plugin_id="sentiment")
        assert job.progress == 0.0
        job.status = JobStatus.completed
        job.progress = 1.0
        assert job.progress == 1.0

    def test_calculate_progress_pipeline(self):
        job = Job.create_pipeline(plugin_ids=["a", "b", "c", "d", "e"])
        # 2 of 5 completed
        job.steps[0].status = JobStatus.completed
        job.steps[1].status = JobStatus.completed
        job.steps[2].status = JobStatus.running
        job.update_progress()
        assert job.progress == 0.4  # 2/5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qualia.core.jobs'`

- [ ] **Step 3: Implement Job data models**

```python
# qualia/core/jobs.py
"""Data models para o sistema de jobs assíncronos."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """Status do ciclo de vida de um job."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled)


class JobType(str, Enum):
    """Tipo de job: execução de um plugin ou pipeline."""
    single = "single"
    pipeline = "pipeline"


@dataclass
class JobStep:
    """Etapa de um pipeline job."""
    plugin_id: str
    status: JobStatus = JobStatus.pending
    progress: float | None = None  # reservado para v2
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "status": self.status.value,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class Job:
    """Representa uma execução assíncrona de plugin ou pipeline."""
    id: str
    type: JobType
    status: JobStatus
    plugin_id: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    current_step: int = 0
    total_steps: int = 1
    steps: list[JobStep] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    callback_url: str | None = None
    temp_files: list[str] = field(default_factory=list)
    ttl: int = 3600

    @classmethod
    def create_single(
        cls,
        plugin_id: str,
        callback_url: str | None = None,
        temp_files: list[str] | None = None,
        ttl: int = 3600,
    ) -> "Job":
        return cls(
            id=str(uuid.uuid4()),
            type=JobType.single,
            status=JobStatus.pending,
            plugin_id=plugin_id,
            created_at=datetime.now(timezone.utc),
            total_steps=1,
            callback_url=callback_url,
            temp_files=temp_files or [],
            ttl=ttl,
        )

    @classmethod
    def create_pipeline(
        cls,
        plugin_ids: list[str],
        callback_url: str | None = None,
        temp_files: list[str] | None = None,
        ttl: int = 3600,
    ) -> "Job":
        steps = [JobStep(plugin_id=pid) for pid in plugin_ids]
        return cls(
            id=str(uuid.uuid4()),
            type=JobType.pipeline,
            status=JobStatus.pending,
            plugin_id=plugin_ids[0],
            created_at=datetime.now(timezone.utc),
            total_steps=len(plugin_ids),
            steps=steps,
            callback_url=callback_url,
            temp_files=temp_files or [],
            ttl=ttl,
        )

    @property
    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return elapsed > self.ttl

    def update_progress(self) -> None:
        if self.type == JobType.single:
            return
        completed = sum(1 for s in self.steps if s.status == JobStatus.completed)
        self.progress = completed / self.total_steps

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "plugin_id": self.plugin_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "result": self.result,
            "error": self.error,
        }
        if self.type == JobType.pipeline:
            d["steps"] = [s.to_dict() for s in self.steps]
        return d
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qualia/core/jobs.py tests/test_job_models.py
~/.claude/scripts/commit.sh "feat: job data models — Job, JobStep, JobStatus, JobType"
```

---

### Task 2: Add `heavy` field to PluginMetadata + PluginInfo

**Files:**
- Modify: `qualia/core/interfaces.py:19-35`
- Modify: `qualia/api/schemas.py:31-39`
- Modify: `qualia/api/schemas.py:42-59` (plugin_to_info)
- Create: `tests/test_plugin_heavy_field.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plugin_heavy_field.py
"""Testes para o campo heavy em PluginMetadata e PluginInfo."""
from qualia.core.interfaces import PluginMetadata, PluginType


class TestPluginMetadataHeavy:
    def test_default_heavy_is_false(self):
        meta = PluginMetadata(
            id="test",
            type=PluginType.ANALYZER,
            name="Test",
            description="test",
            version="1.0",
        )
        assert meta.heavy is False

    def test_heavy_can_be_set_true(self):
        meta = PluginMetadata(
            id="test",
            type=PluginType.DOCUMENT,
            name="Test",
            description="test",
            version="1.0",
            heavy=True,
        )
        assert meta.heavy is True


class TestPluginInfoHeavy:
    def test_plugin_info_includes_heavy(self, client):
        resp = client.get("/plugins")
        assert resp.status_code == 200
        plugins = resp.json()
        # Todos os plugins existentes devem ter heavy: false
        for plugin in plugins:
            assert "heavy" in plugin
            assert plugin["heavy"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_plugin_heavy_field.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'heavy'` and `KeyError: 'heavy'`

- [ ] **Step 3: Add `heavy` field to PluginMetadata**

In `qualia/core/interfaces.py`, add `heavy: bool = False` after `parameters`:

```python
# After line 31 (parameters field), add:
    heavy: bool = False
```

- [ ] **Step 4: Add `heavy` field to PluginInfo schema**

In `qualia/api/schemas.py`, add `heavy: bool` to `PluginInfo` class (after `parameters` field, line 39), and update `plugin_to_info()` to include it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_plugin_heavy_field.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite for regression**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS — existing tests unaffected

- [ ] **Step 7: Commit**

```bash
git add qualia/core/interfaces.py qualia/api/schemas.py tests/test_plugin_heavy_field.py
~/.claude/scripts/commit.sh "feat: campo heavy em PluginMetadata e PluginInfo"
```

---

## Chunk 2: JobManager — Core Orchestration

### Task 3: JobManager — store, create, get, list, cancel, cleanup

**Files:**
- Create: `qualia/api/jobs.py`
- Create: `tests/test_job_manager.py`

- [ ] **Step 1: Write failing tests for JobManager store operations**

```python
# tests/test_job_manager.py
"""Testes para o JobManager."""
import asyncio
import os
import tempfile
import time

import pytest

from qualia.api.jobs import JobManager
from qualia.core.jobs import Job, JobStatus, JobType


@pytest.fixture
def manager():
    return JobManager(max_concurrent=1)


class TestJobManagerStore:
    def test_create_and_get_job(self, manager):
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        retrieved = manager.get(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get("nonexistent") is None

    def test_list_all_jobs(self, manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        manager.store(j1)
        manager.store(j2)
        jobs = manager.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_filter_by_status(self, manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        j2.status = JobStatus.running
        manager.store(j1)
        manager.store(j2)
        pending = manager.list_jobs(status=JobStatus.pending)
        assert len(pending) == 1
        assert pending[0].plugin_id == "a"

    def test_list_jobs_filter_by_plugin(self, manager):
        j1 = Job.create_single(plugin_id="sentiment")
        j2 = Job.create_single(plugin_id="wordcloud")
        manager.store(j1)
        manager.store(j2)
        result = manager.list_jobs(plugin_id="sentiment")
        assert len(result) == 1

    def test_cancel_pending_job(self, manager):
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        success = manager.cancel(job.id)
        assert success is True
        assert manager.get(job.id).status == JobStatus.cancelled

    def test_cancel_running_job_fails(self, manager):
        job = Job.create_single(plugin_id="sentiment")
        job.status = JobStatus.running
        manager.store(job)
        success = manager.cancel(job.id)
        assert success is False

    def test_cancel_nonexistent_returns_none(self, manager):
        result = manager.cancel("nonexistent")
        assert result is None

    def test_cleanup_expired_jobs(self, manager):
        job = Job.create_single(plugin_id="sentiment", ttl=0)
        manager.store(job)
        time.sleep(0.01)
        removed = manager.cleanup_expired()
        assert removed == 1
        assert manager.get(job.id) is None

    def test_cleanup_removes_temp_files(self, manager):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        assert os.path.exists(tmp.name)

        job = Job.create_single(plugin_id="sentiment", ttl=0, temp_files=[tmp.name])
        manager.store(job)
        time.sleep(0.01)
        manager.cleanup_expired()
        assert not os.path.exists(tmp.name)

    def test_cleanup_ignores_missing_temp_files(self, manager):
        job = Job.create_single(plugin_id="sentiment", ttl=0, temp_files=["/tmp/nonexistent_abc123"])
        manager.store(job)
        time.sleep(0.01)
        # Não deve levantar exceção
        manager.cleanup_expired()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qualia.api.jobs'`

- [ ] **Step 3: Implement JobManager store operations**

```python
# qualia/api/jobs.py
"""JobManager — orquestração de jobs assíncronos."""
import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from qualia.core.jobs import Job, JobStatus, JobType

logger = logging.getLogger(__name__)


class JobManager:
    """Gerencia ciclo de vida de jobs assíncronos."""

    def __init__(self, max_concurrent: int = 1):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent
        self._pending_queue: list[tuple[str, callable]] = []  # (job_id, executor)
        self._streams: dict[str, set[asyncio.Queue]] = {}
        self._streams_lock = asyncio.Lock()

    # --- Stub para notify (implementado no Task 5) ---

    async def _notify_job(self, job_id: str) -> None:
        """Envia estado do job para subscribers SSE. Stub até Task 5."""
        pass

    def store(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.is_expired:
                return None
            return job

    def list_jobs(
        self,
        status: JobStatus | None = None,
        plugin_id: str | None = None,
    ) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if not j.is_expired]
        if status:
            jobs = [j for j in jobs if j.status == status]
        if plugin_id:
            jobs = [j for j in jobs if j.plugin_id == plugin_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool | None:
        """Cancela job. Retorna True se cancelou, False se não pode, None se não existe."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status != JobStatus.pending:
                return False
            job.status = JobStatus.cancelled
            job.completed_at = datetime.now(timezone.utc)
            self._cleanup_temp_files(job)
            return True

    def cleanup_expired(self) -> int:
        with self._lock:
            expired_ids = [jid for jid, j in self._jobs.items() if j.is_expired]
            for jid in expired_ids:
                job = self._jobs.pop(jid)
                self._cleanup_temp_files(job)
            return len(expired_ids)

    def _cleanup_temp_files(self, job: Job) -> None:
        for path in job.temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qualia/api/jobs.py tests/test_job_manager.py
~/.claude/scripts/commit.sh "feat: JobManager — store, get, list, cancel, cleanup"
```

---

### Task 4: JobManager — async execution (single + pipeline)

**Files:**
- Modify: `qualia/api/jobs.py`
- Modify: `tests/test_job_manager.py`

- [ ] **Step 1: Write failing tests for async execution**

```python
# Append to tests/test_job_manager.py

class TestJobManagerExecution:
    @pytest.mark.asyncio
    async def test_submit_single_job_completes(self, manager):
        """Plugin simples roda e job fica completed."""
        def fake_executor(job_id):
            return {"sentiment_score": 0.85}

        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        await manager.submit(job.id, fake_executor)

        # Aguarda execução
        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.completed
        assert result_job.result == {"sentiment_score": 0.85}
        assert result_job.started_at is not None
        assert result_job.completed_at is not None
        assert result_job.progress == 1.0

    @pytest.mark.asyncio
    async def test_submit_single_job_failure(self, manager):
        """Plugin que levanta exceção → job failed."""
        def failing_executor(job_id):
            raise RuntimeError("Plugin crashed")

        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        await manager.submit(job.id, failing_executor)

        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.failed
        assert "Plugin crashed" in result_job.error

    @pytest.mark.asyncio
    async def test_submit_pipeline_job_completes(self, manager):
        """Pipeline com 3 steps roda sequencialmente."""
        call_order = []

        def make_executor(step_idx):
            def executor(job_id):
                call_order.append(step_idx)
                return {f"result_{step_idx}": True}
            return executor

        job = Job.create_pipeline(plugin_ids=["a", "b", "c"])
        manager.store(job)

        executors = [make_executor(i) for i in range(3)]
        await manager.submit_pipeline(job.id, executors)

        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.completed
        assert call_order == [0, 1, 2]
        assert all(s.status == JobStatus.completed for s in result_job.steps)

    @pytest.mark.asyncio
    async def test_pipeline_fail_fast(self, manager):
        """Pipeline para no primeiro step que falha."""
        def ok_executor(job_id):
            return {"ok": True}

        def fail_executor(job_id):
            raise RuntimeError("Step 2 failed")

        job = Job.create_pipeline(plugin_ids=["a", "b", "c"])
        manager.store(job)

        executors = [ok_executor, fail_executor, ok_executor]
        await manager.submit_pipeline(job.id, executors)

        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.failed
        assert result_job.steps[0].status == JobStatus.completed
        assert result_job.steps[1].status == JobStatus.failed
        assert result_job.steps[2].status == JobStatus.pending  # never ran

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, manager):
        """Segundo job fica pending até o primeiro terminar."""
        started = []
        gate = asyncio.Event()

        def slow_executor(job_id):
            started.append(job_id)
            # Bloqueia até o gate abrir (simula trabalho pesado)
            import time
            for _ in range(100):
                if gate.is_set():
                    break
                time.sleep(0.01)
            return {"done": True}

        j1 = Job.create_single(plugin_id="heavy_a")
        j2 = Job.create_single(plugin_id="heavy_b")
        manager.store(j1)
        manager.store(j2)

        await manager.submit(j1.id, slow_executor)
        await asyncio.sleep(0.05)  # Dá tempo do j1 iniciar
        await manager.submit(j2.id, slow_executor)
        await asyncio.sleep(0.05)

        # j1 rodando, j2 deve estar pending
        assert manager.get(j1.id).status == JobStatus.running
        assert manager.get(j2.id).status == JobStatus.pending

        # Libera j1
        gate.set()
        for _ in range(100):
            if manager.get(j2.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        assert manager.get(j1.id).status == JobStatus.completed
        assert manager.get(j2.id).status == JobStatus.completed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_manager.py::TestJobManagerExecution -v`
Expected: FAIL — `AttributeError: 'JobManager' object has no attribute 'submit'`

- [ ] **Step 3: Implement async execution in JobManager**

Add to `qualia/api/jobs.py`:

```python
    # --- Execution ---

    async def submit(self, job_id: str, executor: callable) -> None:
        """Submete um job single para execução."""
        if not self._try_acquire_slot(job_id, ("single", executor)):
            return  # fica pending na fila, será iniciado quando slot liberar
        asyncio.create_task(self._run_single(job_id, executor))

    async def submit_pipeline(self, job_id: str, executors: list[callable]) -> None:
        """Submete um pipeline job para execução."""
        if not self._try_acquire_slot(job_id, ("pipeline", executors)):
            return
        asyncio.create_task(self._run_pipeline(job_id, executors))

    def _try_acquire_slot(self, job_id: str, entry: tuple) -> bool:
        """Tenta adquirir um slot de execução. Retorna False se cheio (job fica na fila)."""
        with self._lock:
            running_count = sum(
                1 for j in self._jobs.values() if j.status == JobStatus.running
            )
            if running_count >= self._max_concurrent:
                self._pending_queue.append((job_id, entry))
                return False
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.running
                job.started_at = datetime.now(timezone.utc)
            return True

    async def _run_single(self, job_id: str, executor: callable) -> None:
        """Executa um job single em background thread."""
        try:
            result = await asyncio.to_thread(executor, job_id)
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.status = JobStatus.completed
                    job.result = result
                    job.progress = 1.0
                    job.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.status = JobStatus.failed
                    job.error = str(e)
                    job.completed_at = datetime.now(timezone.utc)
        finally:
            await self._notify_job(job_id)
            await self._process_pending_queue()
            self._cleanup_temp_files_if_terminal(job_id)

    async def _run_pipeline(self, job_id: str, executors: list[callable]) -> None:
        """Executa pipeline steps sequencialmente."""
        try:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return

            for i, executor in enumerate(executors):
                with self._lock:
                    job = self._jobs[job_id]
                    job.current_step = i
                    job.steps[i].status = JobStatus.running
                await self._notify_job(job_id)

                try:
                    result = await asyncio.to_thread(executor, job_id)
                    with self._lock:
                        job.steps[i].status = JobStatus.completed
                        job.steps[i].result = result
                        job.update_progress()
                except Exception as e:
                    with self._lock:
                        job.steps[i].status = JobStatus.failed
                        job.steps[i].error = str(e)
                        job.status = JobStatus.failed
                        job.error = f"Step {i} ({job.steps[i].plugin_id}): {e}"
                        job.completed_at = datetime.now(timezone.utc)
                    await self._notify_job(job_id)
                    return

            with self._lock:
                job.status = JobStatus.completed
                job.progress = 1.0
                job.result = {
                    "steps_executed": len(executors),
                    "results": [
                        {"plugin_id": s.plugin_id, "result": s.result}
                        for s in job.steps
                    ],
                }
                job.completed_at = datetime.now(timezone.utc)
        finally:
            await self._notify_job(job_id)
            await self._process_pending_queue()
            self._cleanup_temp_files_if_terminal(job_id)

    async def _process_pending_queue(self) -> None:
        """Inicia o próximo job pendente se há slot disponível."""
        with self._lock:
            running_count = sum(
                1 for j in self._jobs.values() if j.status == JobStatus.running
            )
            if running_count >= self._max_concurrent or not self._pending_queue:
                return
            job_id, entry = self._pending_queue.pop(0)
            job = self._jobs.get(job_id)
            if not job or job.status != JobStatus.pending:
                return
            job.status = JobStatus.running
            job.started_at = datetime.now(timezone.utc)

        kind, executor_or_executors = entry
        if kind == "pipeline":
            asyncio.create_task(self._run_pipeline(job_id, executor_or_executors))
        else:
            asyncio.create_task(self._run_single(job_id, executor_or_executors))

    def _cleanup_temp_files_if_terminal(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status.is_terminal:
                self._cleanup_temp_files(job)
```

Note: `_pending_queue` and `_notify_job` stub are already in the `__init__` from Task 3.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qualia/api/jobs.py tests/test_job_manager.py
~/.claude/scripts/commit.sh "feat: JobManager — execução async single e pipeline com limite de concorrência"
```

---

### Task 5: JobManager — SSE pub/sub

**Files:**
- Modify: `qualia/api/jobs.py`
- Modify: `tests/test_job_manager.py`

- [ ] **Step 1: Write failing tests for SSE streaming**

```python
# Append to tests/test_job_manager.py

class TestJobManagerSSE:
    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self, manager):
        """Subscriber recebe eventos do job."""
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)

        queue = await manager.subscribe(job.id)
        assert queue is not None

        # Simula notificação
        await manager._notify_job(job.id)

        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event is not None
        assert "status" in event

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self, manager):
        """Unsubscribe remove a queue do job."""
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)

        queue = await manager.subscribe(job.id)
        await manager.unsubscribe(job.id, queue)

        async with manager._streams_lock:
            assert job.id not in manager._streams or queue not in manager._streams[job.id]

    @pytest.mark.asyncio
    async def test_two_subscribers_same_job(self, manager):
        """Dois subscribers recebem o mesmo evento."""
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)

        q1 = await manager.subscribe(job.id)
        q2 = await manager.subscribe(job.id)

        await manager._notify_job(job.id)

        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert e1 == e2

    @pytest.mark.asyncio
    async def test_subscriber_only_gets_own_job_events(self, manager):
        """Subscriber do job A não recebe eventos do job B."""
        ja = Job.create_single(plugin_id="a")
        jb = Job.create_single(plugin_id="b")
        manager.store(ja)
        manager.store(jb)

        qa = await manager.subscribe(ja.id)

        await manager._notify_job(jb.id)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(qa.get(), timeout=0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_manager.py::TestJobManagerSSE -v`
Expected: FAIL — `AttributeError: 'JobManager' object has no attribute 'subscribe'`

- [ ] **Step 3: Implement SSE pub/sub in JobManager**

Add to `qualia/api/jobs.py`:

```python
    # --- SSE Pub/Sub ---

    async def subscribe(self, job_id: str) -> asyncio.Queue | None:
        """Cria uma queue para receber eventos de um job."""
        job = self.get(job_id)
        if not job:
            return None
        queue: asyncio.Queue = asyncio.Queue()
        async with self._streams_lock:
            if job_id not in self._streams:
                self._streams[job_id] = set()
            self._streams[job_id].add(queue)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        """Remove uma queue de subscriber."""
        async with self._streams_lock:
            if job_id in self._streams:
                self._streams[job_id].discard(queue)
                if not self._streams[job_id]:
                    del self._streams[job_id]

    async def _notify_job(self, job_id: str) -> None:
        """Envia estado atual do job para todos os subscribers. Substitui o stub do Task 3."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            # Build event with type matching spec: status, step, completed
            event = job.to_dict()
            if job.status in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled):
                event["_event_type"] = "completed"
            elif job.type == JobType.pipeline and any(s.status == JobStatus.running for s in job.steps):
                event["_event_type"] = "step"
            else:
                event["_event_type"] = "status"
        async with self._streams_lock:
            queues = self._streams.get(job_id, set()).copy()
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop event se queue cheia
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qualia/api/jobs.py tests/test_job_manager.py
~/.claude/scripts/commit.sh "feat: JobManager — SSE pub/sub per-job"
```

---

### Task 6: JobManager — webhook dispatch

**Files:**
- Modify: `qualia/api/jobs.py`
- Modify: `tests/test_job_manager.py`

- [ ] **Step 1: Write failing tests for webhook dispatch**

```python
# Append to tests/test_job_manager.py
from unittest.mock import AsyncMock, patch


class TestJobManagerWebhook:
    @pytest.mark.asyncio
    async def test_webhook_called_on_completion(self, manager):
        """Webhook é chamado quando job completa."""
        job = Job.create_single(
            plugin_id="sentiment",
            callback_url="http://localhost:9000/hook",
        )
        manager.store(job)

        with patch("qualia.api.jobs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock()
            mock_client_cls.return_value = mock_client

            def executor(job_id):
                return {"score": 0.85}

            await manager.submit(job.id, executor)

            for _ in range(50):
                if manager.get(job.id).status.is_terminal:
                    break
                await asyncio.sleep(0.05)

            # Dá tempo pro webhook ser disparado
            await asyncio.sleep(0.1)
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "http://localhost:9000/hook"

    @pytest.mark.asyncio
    async def test_no_webhook_without_callback_url(self, manager):
        """Sem callback_url, webhook não é chamado."""
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)

        with patch("qualia.api.jobs.httpx.AsyncClient") as mock_client_cls:
            def executor(job_id):
                return {"score": 0.85}

            await manager.submit(job.id, executor)

            for _ in range(50):
                if manager.get(job.id).status.is_terminal:
                    break
                await asyncio.sleep(0.05)

            mock_client_cls.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_job_manager.py::TestJobManagerWebhook -v`
Expected: FAIL

- [ ] **Step 3: Implement webhook dispatch**

Add to `qualia/api/jobs.py` (add `import httpx` at top):

```python
    # --- Webhook ---

    async def _dispatch_webhook(self, job_id: str) -> None:
        """Envia webhook callback se configurado."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not job.callback_url or not job.status.is_terminal:
                return
            payload = self._build_webhook_payload(job)
            url = job.callback_url

        delays = [0, 1, 5]  # tentativa imediata + 2 retries
        for attempt, delay in enumerate(delays):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code < 400:
                        logger.info(f"Webhook delivered for job {job_id}")
                        return
                    logger.warning(f"Webhook attempt {attempt+1} failed: HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"Webhook attempt {attempt+1} failed: {e}")

        logger.error(f"Webhook delivery failed after 3 attempts for job {job_id}")

    def _build_webhook_payload(self, job: Job) -> dict:
        payload = {
            "job_id": job.id,
            "type": job.type.value,
            "status": job.status.value,
            "plugin_id": job.plugin_id,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        if job.type == JobType.single:
            payload["result"] = job.result
        else:
            payload["steps_executed"] = job.total_steps
            payload["results"] = [
                {"plugin_id": s.plugin_id, "result": s.result}
                for s in job.steps
            ]
        if job.status == JobStatus.failed:
            payload["error"] = job.error
        return payload
```

Update `_run_single` and `_run_pipeline` finally blocks to call `await self._dispatch_webhook(job_id)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_job_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qualia/api/jobs.py tests/test_job_manager.py
~/.claude/scripts/commit.sh "feat: JobManager — webhook dispatch com retry"
```

---

## Chunk 3: API Routes — Job Endpoints

### Task 7: Job API routes (`/jobs`)

**Files:**
- Create: `qualia/api/routes/jobs.py`
- Create: `tests/test_job_routes.py`
- Modify: `qualia/api/__init__.py` (register router + lifespan)
- Modify: `qualia/api/deps.py` (add job_manager singleton)

- [ ] **Step 1: Add `job_manager` singleton to deps.py**

Add to `qualia/api/deps.py` (after the `_core` singleton pattern):

```python
_job_manager: "JobManager | None" = None

def set_job_manager(manager: "JobManager") -> None:
    global _job_manager
    _job_manager = manager

def get_job_manager() -> "JobManager":
    if _job_manager is None:
        raise RuntimeError("JobManager not initialized")
    return _job_manager
```

- [ ] **Step 2: Write failing tests for /jobs routes**

```python
# tests/test_job_routes.py
"""Testes para os endpoints /jobs."""
import asyncio
import json

import pytest
import pytest_asyncio
import httpx

from qualia.api import app
from qualia.api.deps import get_job_manager, set_job_manager
from qualia.api.jobs import JobManager
from qualia.core.jobs import Job, JobStatus


@pytest.fixture(autouse=True)
def fresh_manager():
    """JobManager limpo para cada teste."""
    manager = JobManager(max_concurrent=1)
    set_job_manager(manager)
    yield manager


@pytest.fixture
def client():
    from starlette.testclient import TestClient
    return TestClient(app)


class TestGetJob:
    def test_get_existing_job(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment")
        fresh_manager.store(job)
        resp = client.get(f"/jobs/{job.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job.id
        assert data["status"] == "pending"

    def test_get_nonexistent_job_returns_404(self, client):
        resp = client.get("/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_get_expired_job_returns_404(self, client, fresh_manager):
        import time
        job = Job.create_single(plugin_id="sentiment", ttl=0)
        fresh_manager.store(job)
        time.sleep(0.01)
        resp = client.get(f"/jobs/{job.id}")
        assert resp.status_code == 404


class TestListJobs:
    def test_list_empty(self, client):
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_all_jobs(self, client, fresh_manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        fresh_manager.store(j1)
        fresh_manager.store(j2)
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_filter_by_status(self, client, fresh_manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        j2.status = JobStatus.running
        fresh_manager.store(j1)
        fresh_manager.store(j2)
        resp = client.get("/jobs?status=pending")
        assert len(resp.json()) == 1

    def test_list_filter_by_plugin(self, client, fresh_manager):
        j1 = Job.create_single(plugin_id="sentiment")
        j2 = Job.create_single(plugin_id="wordcloud")
        fresh_manager.store(j1)
        fresh_manager.store(j2)
        resp = client.get("/jobs?plugin_id=sentiment")
        assert len(resp.json()) == 1


class TestCancelJob:
    def test_cancel_pending_job(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment")
        fresh_manager.store(job)
        resp = client.delete(f"/jobs/{job.id}")
        assert resp.status_code == 200
        assert fresh_manager.get(job.id).status == JobStatus.cancelled

    def test_cancel_running_job_returns_409(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment")
        job.status = JobStatus.running
        fresh_manager.store(job)
        resp = client.delete(f"/jobs/{job.id}")
        assert resp.status_code == 409

    def test_cancel_nonexistent_returns_404(self, client):
        resp = client.delete("/jobs/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_job_routes.py -v`
Expected: FAIL

- [ ] **Step 4: Implement /jobs routes**

```python
# qualia/api/routes/jobs.py
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
```

- [ ] **Step 5: Register router and lifespan in `__init__.py`**

In `qualia/api/__init__.py`:

1. Add lifespan context manager (before `app = FastAPI()`):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # Startup: init JobManager
    from qualia.api.jobs import JobManager
    from qualia.api.deps import set_job_manager
    import os
    max_concurrent = int(os.environ.get("QUALIA_MAX_CONCURRENT_HEAVY_JOBS", "1"))
    manager = JobManager(max_concurrent=max_concurrent)
    set_job_manager(manager)

    yield

    # Shutdown: cleanup
    manager.cleanup_expired()
```

2. Pass lifespan to FastAPI: `app = FastAPI(..., lifespan=lifespan)`

3. Import and include jobs router (before SPA catch-all):

```python
from qualia.api.routes.jobs import router as jobs_router
app.include_router(jobs_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_job_routes.py -v`
Expected: ALL PASS

- [ ] **Step 7: Run full test suite for regression**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add qualia/api/routes/jobs.py qualia/api/__init__.py qualia/api/deps.py tests/test_job_routes.py
~/.claude/scripts/commit.sh "feat: endpoints /jobs — GET, DELETE, SSE stream + lifespan"
```

---

## Chunk 4: Async Routing in Existing Endpoints

### Task 8: Routing helper + analyze.py async support

**Files:**
- Create: `qualia/api/routing.py` — shared routing logic
- Modify: `qualia/api/routes/analyze.py`
- Create: `tests/test_async_routing.py`

- [ ] **Step 1: Write failing tests for routing logic**

```python
# tests/test_async_routing.py
"""Testes para roteamento sync/async dos endpoints existentes."""
import pytest
from unittest.mock import MagicMock

from qualia.api.routing import should_run_async


class TestShouldRunAsync:
    def test_light_plugin_default_is_sync(self):
        meta = MagicMock(heavy=False)
        assert should_run_async(meta, sync_override=False, async_override=False, is_pipeline=False) is False

    def test_heavy_plugin_default_is_async(self):
        meta = MagicMock(heavy=True)
        assert should_run_async(meta, sync_override=False, async_override=False, is_pipeline=False) is True

    def test_heavy_plugin_sync_override(self):
        meta = MagicMock(heavy=True)
        assert should_run_async(meta, sync_override=True, async_override=False, is_pipeline=False) is False

    def test_light_plugin_async_override(self):
        meta = MagicMock(heavy=False)
        assert should_run_async(meta, sync_override=False, async_override=True, is_pipeline=False) is True

    def test_pipeline_default_is_async(self):
        assert should_run_async(None, sync_override=False, async_override=False, is_pipeline=True) is True

    def test_pipeline_sync_override(self):
        assert should_run_async(None, sync_override=True, async_override=False, is_pipeline=True) is False

    def test_sync_and_async_both_true_sync_wins(self):
        meta = MagicMock(heavy=True)
        assert should_run_async(meta, sync_override=True, async_override=True, is_pipeline=False) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_async_routing.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement routing helper**

```python
# qualia/api/routing.py
"""Lógica de roteamento sync/async para endpoints."""
from qualia.core.interfaces import PluginMetadata


def should_run_async(
    meta: PluginMetadata | None,
    sync_override: bool,
    async_override: bool,
    is_pipeline: bool,
) -> bool:
    """Decide se a execução deve ser async (job) ou sync (direto)."""
    if sync_override:
        return False
    if async_override:
        return True
    if is_pipeline:
        return True
    if meta and meta.heavy:
        return True
    return False
```

- [ ] **Step 4: Run routing tests**

Run: `pytest tests/test_async_routing.py -v`
Expected: ALL PASS

- [ ] **Step 5: Write failing tests for analyze endpoint async mode**

```python
# Append to tests/test_async_routing.py

from starlette.testclient import TestClient
from qualia.api import app
from qualia.api.deps import set_job_manager
from qualia.api.jobs import JobManager


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_manager():
    manager = JobManager(max_concurrent=1)
    set_job_manager(manager)
    yield manager


class TestAnalyzeAsyncRouting:
    def test_light_plugin_returns_200_sync(self, client):
        """Plugin leve sem override → sync como hoje."""
        resp = client.post("/analyze/sentiment", json={
            "text": "I love this product",
            "config": {},
        })
        # Plugin existe e retorna 200 (resultado direto)
        assert resp.status_code == 200

    def test_light_plugin_async_override_returns_202(self, client):
        """Plugin leve com ?async=true → 202 + job_id."""
        resp = client.post("/analyze/sentiment?async=true", json={
            "text": "I love this product",
            "config": {},
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert "status_url" in data
        assert "stream_url" in data
```

- [ ] **Step 6: Run analyze async tests to verify they fail**

Run: `pytest tests/test_async_routing.py::TestAnalyzeAsyncRouting -v`
Expected: FAIL — endpoint doesn't return 202

- [ ] **Step 7: Modify analyze.py for async routing**

In `qualia/api/routes/analyze.py`, modify the `POST /{plugin_id}` endpoint to add query params and routing logic:

1. Add imports: `from fastapi import Query` and `from qualia.api.routing import should_run_async` and `from qualia.api.deps import get_job_manager`
2. Add `sync` and `async_mode` query params to function signature
3. After validation, before execution: check `should_run_async()`. If True, create job, submit, return 202. If False, run as today.

The async path creates a Job, stores it, builds an executor closure that calls `core.execute_plugin(...)`, submits via `manager.submit()`, and returns `JSONResponse(status_code=202, content={...})`.

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_async_routing.py -v`
Expected: ALL PASS

- [ ] **Step 9: Run full test suite for regression**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS — existing analyze tests unchanged (they don't pass `?async=true`)

- [ ] **Step 10: Commit**

```bash
git add qualia/api/routing.py qualia/api/routes/analyze.py tests/test_async_routing.py
~/.claude/scripts/commit.sh "feat: roteamento async em /analyze — helper + query params"
```

---

### Task 9: Async routing in remaining endpoints

**Files:**
- Modify: `qualia/api/routes/process.py`
- Modify: `qualia/api/routes/visualize.py`
- Modify: `qualia/api/routes/transcribe.py`
- Modify: `qualia/api/routes/pipeline.py`
- Modify: `tests/test_async_routing.py`

Apply the same pattern from Task 8 to each endpoint. The key differences:

**process.py:**
- Same pattern as analyze. Executor calls `core.execute_plugin(plugin_id, doc, config, context)`.

**visualize.py:**
- Executor calls `plugin.render(data, config)` (not `core.execute_plugin`).

**transcribe.py:**
- Has file upload → `temp_files` must be passed to Job when async.
- Route handler does NOT cleanup temp file when async — JobManager handles it.

**pipeline.py:**
- Always async by default (unless `?sync=true`).
- Creates pipeline job with `Job.create_pipeline()`.
- Builds a list of executor closures (one per step).
- Submits via `manager.submit_pipeline()`.
- Must handle file uploads + accumulated_data pattern.

- [ ] **Step 1: Write failing tests for each endpoint**

Append to `tests/test_async_routing.py`:

```python
class TestProcessAsyncRouting:
    def test_process_sync_default(self, client):
        resp = client.post("/process/readability", json={
            "text": "Some document text to process.",
            "config": {},
        })
        assert resp.status_code == 200

    def test_process_async_override(self, client):
        resp = client.post("/process/readability?async=true", json={
            "text": "Some document text to process.",
            "config": {},
        })
        assert resp.status_code == 202
        assert "job_id" in resp.json()


class TestPipelineAsyncRouting:
    def test_pipeline_async_by_default(self, client):
        """Pipeline sem parâmetros → 202 (async por default)."""
        resp = client.post("/pipeline", data={
            "steps": '[{"plugin_id": "sentiment"}]',
            "text": "I love this!",
        })
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    def test_pipeline_sync_override(self, client):
        """Pipeline com ?sync=true → 200 (sync, como antes)."""
        resp = client.post("/pipeline?sync=true", data={
            "steps": '[{"plugin_id": "sentiment"}]',
            "text": "I love this!",
        })
        assert resp.status_code == 200


class TestHeavyPluginSyncOverride:
    """Testa que plugin pesado + ?sync=true roda sync."""
    # Nota: requer um plugin com heavy=True registrado.
    # Na v1 nenhum plugin existente é heavy, então este teste
    # usa mock ou será implementado junto com o primeiro plugin heavy.
    # O routing helper já cobre essa lógica em TestShouldRunAsync.
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_async_routing.py -v`

- [ ] **Step 3: Modify process.py**

Same pattern as analyze.py: add query params, routing check, async path.

- [ ] **Step 4: Modify visualize.py**

Same pattern. Executor wraps `plugin.render()`.

- [ ] **Step 5: Modify transcribe.py**

Same pattern, plus: when async, pass `temp_files=[upload.tmp_path]` to Job and do NOT unlink in route handler.

- [ ] **Step 6: Modify pipeline.py**

Largest change. Wrap the entire pipeline execution logic into executor closures. Build `Job.create_pipeline(plugin_ids)`, build executors list, submit via `manager.submit_pipeline()`.

- [ ] **Step 7: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add qualia/api/routes/process.py qualia/api/routes/visualize.py qualia/api/routes/transcribe.py qualia/api/routes/pipeline.py tests/test_async_routing.py
~/.claude/scripts/commit.sh "feat: roteamento async em /process, /visualize, /transcribe, /pipeline"
```

---

## Chunk 5: Lifespan Cleanup + Integration Tests

### Task 10: Periodic cleanup background task

**Files:**
- Modify: `qualia/api/__init__.py`
- Create: `tests/test_job_cleanup.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_job_cleanup.py
"""Testes para cleanup periódico de jobs."""
import time

import pytest

from qualia.api.deps import get_job_manager, set_job_manager
from qualia.api.jobs import JobManager
from qualia.core.jobs import Job


@pytest.fixture
def manager():
    m = JobManager(max_concurrent=1)
    set_job_manager(m)
    return m


class TestPeriodicCleanup:
    def test_expired_jobs_are_cleaned(self, manager):
        j1 = Job.create_single(plugin_id="a", ttl=0)
        j2 = Job.create_single(plugin_id="b", ttl=3600)
        manager.store(j1)
        manager.store(j2)
        time.sleep(0.01)
        removed = manager.cleanup_expired()
        assert removed == 1
        assert manager.get(j1.id) is None
        assert manager.get(j2.id) is not None
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_job_cleanup.py -v`
Expected: PASS (cleanup_expired already implemented in Task 3)

- [ ] **Step 3: Add periodic cleanup to lifespan**

In the `lifespan` context manager in `__init__.py`, add a background task that runs `manager.cleanup_expired()` every 5 minutes:

```python
@asynccontextmanager
async def lifespan(app):
    # Startup
    from qualia.api.jobs import JobManager
    from qualia.api.deps import set_job_manager
    import os
    max_concurrent = int(os.environ.get("QUALIA_MAX_CONCURRENT_HEAVY_JOBS", "1"))
    manager = JobManager(max_concurrent=max_concurrent)
    set_job_manager(manager)

    # Background cleanup task
    async def periodic_cleanup():
        while True:
            await asyncio.sleep(300)  # 5 min
            try:
                removed = manager.cleanup_expired()
                if removed:
                    logger.info(f"Cleaned up {removed} expired jobs")
            except Exception as e:
                logger.error(f"Job cleanup error: {e}")

    cleanup_task = asyncio.create_task(periodic_cleanup())

    yield

    # Shutdown
    cleanup_task.cancel()
    manager.cleanup_expired()
```

- [ ] **Step 4: Commit**

```bash
git add qualia/api/__init__.py tests/test_job_cleanup.py
~/.claude/scripts/commit.sh "feat: cleanup periódico de jobs expirados via lifespan"
```

---

### Task 11: Integration tests — full async flow

**Files:**
- Create: `tests/test_job_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_job_integration.py
"""Testes de integração — fluxo async completo."""
import asyncio
import json
import time

import pytest
import pytest_asyncio
import httpx

from qualia.api import app
from qualia.api.deps import set_job_manager
from qualia.api.jobs import JobManager


@pytest.fixture(autouse=True)
def fresh_manager():
    manager = JobManager(max_concurrent=1)
    set_job_manager(manager)
    yield manager


@pytest_asyncio.fixture
async def ac():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestAsyncFlowIntegration:
    @pytest.mark.asyncio
    async def test_analyze_async_then_poll(self, ac):
        """Analyze com ?async=true → poll até completed."""
        # Submete async
        resp = await ac.post("/analyze/sentiment?async=true", json={
            "text": "This is a great product!",
            "config": {},
        })
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # Poll até completar
        for _ in range(50):
            resp = await ac.get(f"/jobs/{job_id}")
            assert resp.status_code == 200
            if resp.json()["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"] is not None

    @pytest.mark.asyncio
    async def test_analyze_sync_unchanged(self, ac):
        """Analyze sem parâmetros → sync como sempre."""
        resp = await ac.post("/analyze/sentiment", json={
            "text": "This is a great product!",
            "config": {},
        })
        assert resp.status_code == 200
        assert "sentiment_score" in resp.json() or "result" in resp.json()

    @pytest.mark.asyncio
    async def test_cancel_pending_job_via_api(self, ac, fresh_manager):
        """Cancela job pending via DELETE."""
        from qualia.core.jobs import Job
        job = Job.create_single(plugin_id="sentiment")
        fresh_manager.store(job)

        resp = await ac.delete(f"/jobs/{job.id}")
        assert resp.status_code == 200

        resp = await ac.get(f"/jobs/{job.id}")
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_list_jobs_returns_active(self, ac, fresh_manager):
        """GET /jobs retorna jobs ativos."""
        from qualia.core.jobs import Job
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        fresh_manager.store(j1)
        fresh_manager.store(j2)

        resp = await ac.get("/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestRegressionExistingEndpoints:
    @pytest.mark.asyncio
    async def test_analyze_sync_no_regression(self, ac):
        resp = await ac.post("/analyze/sentiment", json={
            "text": "Test text",
            "config": {},
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_visualize_sync_no_regression(self, ac):
        resp = await ac.post("/visualize/wordcloud", json={
            "data": {"word_frequencies": {"hello": 5, "world": 3}},
            "config": {},
        })
        assert resp.status_code in (200, 422)  # 422 if plugin needs different data
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_job_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS (950+ existing tests + new tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_job_integration.py
~/.claude/scripts/commit.sh "test: integração async job queue — fluxo completo + regressão"
```

---

## Chunk 6: Frontend Support

### Task 12: Frontend API helper for async jobs

**Files:**
- Modify: `qualia/frontend/src/lib/api.js`

- [ ] **Step 1: Add `executeWithJobSupport` wrapper**

Add to `qualia/frontend/src/lib/api.js`:

```javascript
/**
 * Wrapper que lida com respostas sync (200) e async (202) transparentemente.
 * Para 202, faz polling via SSE e retorna quando o job completar.
 * Chama onProgress callback com updates de progresso.
 *
 * IMPORTANTE: usa fetch() direto em vez de request() porque request()
 * já faz res.json() e perde o status code HTTP. Precisamos distinguir
 * 200 (sync) de 202 (async).
 */
export async function executeWithJobSupport(url, options = {}, { onProgress } = {}) {
  const res = await fetch(url, {
    method: options.method || 'POST',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const data = await res.json();

  if (!res.ok) {
    throw new Error(data.detail || `Request failed: ${res.status}`);
  }

  // Sync — retorna direto
  if (res.status === 200) {
    return data;
  }

  // Async — abre SSE e espera conclusão
  if (res.status === 202) {
    const { job_id, stream_url } = data;
    return new Promise((resolve, reject) => {
      const eventSource = new EventSource(stream_url);
      let fallbackTimer = null;

      const startPollingFallback = () => {
        eventSource.close();
        fallbackTimer = setInterval(async () => {
          try {
            const resp = await request(`/jobs/${job_id}`);
            if (onProgress) onProgress(resp);
            if (resp.status === 'completed') {
              clearInterval(fallbackTimer);
              resolve(resp.result);
            } else if (resp.status === 'failed') {
              clearInterval(fallbackTimer);
              reject(new Error(resp.error || 'Job failed'));
            }
          } catch (e) {
            clearInterval(fallbackTimer);
            reject(e);
          }
        }, 3000);
      };

      eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        if (onProgress) onProgress(data);
      });

      eventSource.addEventListener('completed', (e) => {
        const data = JSON.parse(e.data);
        eventSource.close();
        resolve(data.result);
      });

      eventSource.addEventListener('failed', (e) => {
        const data = JSON.parse(e.data);
        eventSource.close();
        reject(new Error(data.error || 'Job failed'));
      });

      eventSource.onerror = () => {
        startPollingFallback();
      };
    });
  }

  return data;
}
```

- [ ] **Step 2: Wrap existing API functions**

Update `analyze`, `analyzeFile`, `transcribe`, `executePipeline` to optionally use the new wrapper when the caller passes `{ async: true, onProgress }`.

Keep backward-compatible: without options, they behave exactly as today.

- [ ] **Step 3: Commit**

```bash
git add qualia/frontend/src/lib/api.js
~/.claude/scripts/commit.sh "feat: frontend — executeWithJobSupport wrapper para async jobs"
```

---

### Task 13: Final regression + coverage check

**Files:** No new files

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Check coverage**

Run: `pytest tests/ --cov=qualia --cov-report=term-missing`
Expected: >95% coverage, new files well covered

- [ ] **Step 3: Manual smoke test**

```bash
# Terminal 1: start API
source .venv/bin/activate
python -m uvicorn qualia.api:app --port 8000

# Terminal 2: test async flow
curl -X POST "http://localhost:8000/analyze/sentiment?async=true" \
  -H "Content-Type: application/json" \
  -d '{"text": "This is great!", "config": {}}' | python -m json.tool

# Should return 202 with job_id. Then:
# curl http://localhost:8000/jobs/{job_id} | python -m json.tool
```

- [ ] **Step 4: Commit any fixes from smoke test**

```bash
~/.claude/scripts/commit.sh "fix: ajustes do smoke test async job queue"
```
