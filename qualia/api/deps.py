"""Dependências compartilhadas entre módulos de rota."""

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException, UploadFile

from qualia.core import QualiaCore

_core: Optional[QualiaCore] = None
HAS_EXTENSIONS: bool = False

# Limite de upload do engine (500MB — plugins com limites menores tratam internamente)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024


def set_core(core: QualiaCore):
    global _core
    _core = core


def get_core() -> QualiaCore:
    assert _core is not None, "Core não inicializado — set_core() não foi chamado"
    return _core


_job_manager: "JobManager | None" = None


def set_job_manager(manager: "JobManager") -> None:
    global _job_manager
    _job_manager = manager


def get_job_manager() -> "JobManager":
    if _job_manager is None:
        raise RuntimeError("JobManager not initialized")
    return _job_manager


def set_extensions(available: bool):
    global HAS_EXTENSIONS
    HAS_EXTENSIONS = available


def validate_plugin_config(core: QualiaCore, plugin_id: str, config: Dict) -> None:
    """Valida config via registry. Levanta HTTPException 422 se inválida."""
    registry = core.get_config_registry()
    if registry is not None:
        valid, errors = registry.validate_config(plugin_id, config or {})
        if not valid:
            raise HTTPException(
                status_code=422,
                detail={"message": "Configuração inválida", "errors": errors},
            )


def require_plugin_type(core: QualiaCore, plugin_id: str, *expected_types: str) -> None:
    """Verifica se o plugin é do tipo esperado. Levanta HTTPException 422 se incompatível."""
    meta = core.registry.get(plugin_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' não encontrado")
    if meta.type.value not in expected_types:
        raise HTTPException(
            status_code=422,
            detail=f"Plugin '{plugin_id}' é do tipo '{meta.type.value}', "
                   f"esperado: {', '.join(expected_types)}",
        )


UPLOAD_CHUNK_SIZE = 64 * 1024  # 64KB por chunk


@dataclass
class UploadResult:
    """Resultado de upload streamed para tempfile."""
    tmp_path: str
    size: int
    content_hash: str  # md5 hex digest (8 chars)


async def check_upload_size(file: UploadFile, max_size: int = None, suffix: str = "") -> UploadResult:
    """Lê upload em streaming direto pra tempfile — sem acumular em RAM.

    Lê em chunks de 64KB, grava no disco e calcula hash incrementalmente.
    Aborta assim que ultrapassa max_size sem ler o resto.
    """
    if max_size is None:
        max_size = MAX_UPLOAD_SIZE

    hasher = hashlib.md5()
    total = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)

    try:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_size:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                size_mb = total / (1024 * 1024)
                limit_mb = max_size / (1024 * 1024)
                raise HTTPException(
                    status_code=413,
                    detail=f"Arquivo muito grande: >{size_mb:.0f}MB. Limite: {limit_mb:.0f}MB."
                )
            hasher.update(chunk)
            tmp.write(chunk)
        tmp.close()
    except HTTPException:
        raise
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise

    return UploadResult(
        tmp_path=tmp.name,
        size=total,
        content_hash=hasher.hexdigest()[:8],
    )


async def track(endpoint: str, plugin_id: str = None, error: str = None):
    """Wrapper de track_request — no-op quando extensions não estão disponíveis."""
    if HAS_EXTENSIONS:
        from qualia.api.monitor import track_request
        await track_request(endpoint, plugin_id, error)
