"""Modelos Pydantic para request/response da API."""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Literal
from fastapi import HTTPException


class AnalyzeRequest(BaseModel):
    text: str = Field(..., description="Text content to analyze")
    config: Dict[str, Any] = Field(default_factory=dict, description="Plugin configuration parameters")
    context: Dict[str, Any] = Field(default_factory=dict, description="Execution context")


class ProcessRequest(BaseModel):
    text: str = Field(..., description="Text content to process")
    config: Dict[str, Any] = Field(default_factory=dict, description="Plugin configuration parameters")
    context: Dict[str, Any] = Field(default_factory=dict, description="Execution context")


class VisualizeRequest(BaseModel):
    data: Dict[str, Any] = Field(..., description="Data to visualize (usually from analyzer output)")
    config: Dict[str, Any] = Field(default_factory=dict, description="Visualization configuration")
    output_format: Literal["html", "png", "svg"] = Field("html", description="Output format: png, svg, html")


class ConfigResolveRequest(BaseModel):
    plugin_id: str = Field(..., description="Plugin ID to resolve config for")
    text_size: str = Field("medium", description="Text size category: short_text, medium, long_text")


class PluginInfo(BaseModel):
    id: str
    name: str
    type: str
    description: str
    version: str
    provides: List[str]
    requires: List[str]
    parameters: Dict[str, Any]
    heavy: bool


def plugin_to_info(plugin_id: str) -> PluginInfo:
    """Convert plugin metadata to API response model"""
    from qualia.api.deps import get_core
    core = get_core()
    meta = core.registry.get(plugin_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    return PluginInfo(
        id=meta.id,
        name=meta.name,
        type=meta.type.value,
        description=meta.description,
        version=meta.version,
        provides=meta.provides,
        requires=meta.requires,
        parameters=meta.parameters,
        heavy=meta.heavy
    )
