# qualia/core/interfaces.py
"""
Contratos do Qualia Core — interfaces que todo plugin deve implementar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class PluginType(Enum):
    """Tipos de plugins que o Core pode orquestrar"""
    ANALYZER = "analyzer"
    VISUALIZER = "visualizer"
    DOCUMENT = "document"


@dataclass
class PluginMetadata:
    """Metadados que todo plugin deve fornecer"""
    id: str
    type: PluginType
    name: str
    description: str
    version: str
    provides: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    can_use: List[str] = field(default_factory=list)
    accepts: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    heavy: bool = False

    def get_dependencies(self) -> Set[str]:
        """Retorna todas as dependências (obrigatórias e opcionais)"""
        return set(self.requires + self.can_use)


class IPlugin(ABC):
    """Interface base que todo plugin deve implementar"""

    @abstractmethod
    def meta(self) -> PluginMetadata:
        """Plugin se descreve completamente"""
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Valida configuração contra schema do plugin"""
        pass


class IAnalyzerPlugin(IPlugin):
    """Cria dados novos a partir de documentos"""

    @abstractmethod
    def analyze(self, document: Any, config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analisa documento com configuração e contexto de dependências
        context contém resultados de plugins que este depende
        """
        pass


class IVisualizerPlugin(IPlugin):
    """Renderiza dados em visualizações"""

    @abstractmethod
    def render(self, data: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """Renderiza visualização e retorna dict serializado.

        Retorno: {"html": str} ou {"data": str, "encoding": "base64", "format": str}
        """
        pass


class IDocumentPlugin(IPlugin):
    """Processa e prepara documentos"""

    @abstractmethod
    def process(self, document: Any, config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Processa documento com configuração e contexto"""
        pass


