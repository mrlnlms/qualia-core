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
