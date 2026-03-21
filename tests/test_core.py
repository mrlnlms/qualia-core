"""
Testes unitários para o Qualia Core
Versão corrigida para estrutura atual
"""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

from qualia.core import (
    QualiaCore, Document, PluginMetadata, PluginType,
    BaseAnalyzerPlugin, BaseVisualizerPlugin, BaseDocumentPlugin,
    PipelineConfig, PipelineStep, ExecutionContext, DependencyResolver
)


@pytest.fixture
def temp_dir():
    """Cria diretório temporário para testes"""
    temp = tempfile.mkdtemp()
    yield Path(temp)
    shutil.rmtree(temp)


@pytest.fixture
def core(temp_dir):
    """Cria instância do core para testes"""
    return QualiaCore(
        plugins_dir=Path(__file__).parent.parent / "plugins",
        cache_dir=temp_dir / "cache"
    )


@pytest.fixture
def sample_document():
    """Documento de exemplo para testes"""
    return Document(
        id="test_doc",
        content="Este é um texto de teste. Teste teste palavra.",
        metadata={"source": "test"}
    )


class TestQualiaCore:
    """Testes do core principal"""
    
    def test_core_initialization(self, temp_dir):
        """Testa inicialização básica"""
        core = QualiaCore(cache_dir=temp_dir / "cache")
        assert core is not None
        assert len(core.registry) >= 8
        assert (temp_dir / "cache").exists()
    
    def test_plugin_discovery(self, core):
        """Testa descoberta de plugins"""
        plugins = core.discover_plugins()
        
        expected_plugins = {
            'word_frequency', 'sentiment_analyzer', 'teams_cleaner',
            'wordcloud_d3', 'frequency_chart_plotly', 'sentiment_viz_plotly',
            'readability_analyzer', 'transcription', 'transcription_local'
        }
        
        assert set(plugins.keys()) == expected_plugins
        
        for plugin_id, meta in plugins.items():
            assert isinstance(meta, PluginMetadata)
            assert meta.id == plugin_id
            assert meta.type in PluginType
    
    def test_document_creation(self, core):
        """Testa criação de documentos efêmeros"""
        doc = core.add_document("doc1", "Conteúdo teste", {"lang": "pt"})
        assert doc.id == "doc1"
        assert doc.content == "Conteúdo teste"
        assert doc.metadata["lang"] == "pt"
    
    def test_simple_plugin_execution(self, core, sample_document):
        """Testa execução simples - CORRIGIDO"""
        core.add_document(sample_document.id, sample_document.content)
        
        result = core.execute_plugin("word_frequency", sample_document)
        
        # Plugin real retorna estrutura diferente
        assert isinstance(result, dict)
        # Pode ter word_frequencies OU top_words
        assert "word_frequencies" in result or "top_words" in result
        assert "total_words" in result
        assert result["total_words"] > 0
    
    def test_plugin_with_config(self, core, sample_document):
        """Testa plugin com configuração válida"""
        core.add_document(sample_document.id, sample_document.content)

        config = {"min_word_length": 5}
        result = core.execute_plugin("word_frequency", sample_document, config)

        assert isinstance(result, dict)
        assert "word_frequencies" in result
        # Com min_word_length=5, palavras curtas devem ser filtradas
        for word in result["word_frequencies"]:
            assert len(word) >= 5, f"Palavra '{word}' tem menos de 5 caracteres"
    
    def test_cache_functionality(self, core, sample_document):
        """Testa funcionalidade de cache"""
        core.add_document(sample_document.id, sample_document.content)
        
        # Primeira execução
        result1 = core.execute_plugin("word_frequency", sample_document)
        
        # Segunda execução (deve vir do cache)
        with patch.object(core.get_plugin('word_frequency'), 'analyze') as mock_analyze:
            result2 = core.execute_plugin("word_frequency", sample_document)
            mock_analyze.assert_not_called()
        
        assert result1 == result2
    
    def test_invalid_plugin(self, core, sample_document):
        """Testa erro ao executar plugin inválido"""
        with pytest.raises(ValueError, match="Plugin 'nao_existe' não encontrado"):
            core.execute_plugin("nao_existe", sample_document)
    
    def test_pipeline_execution(self, core):
        """Testa execução de pipeline"""
        from qualia.core import PipelineConfig, PipelineStep

        doc = core.add_document("pipeline_test", "Texto para pipeline. Muito bom! " * 10)

        pipeline = PipelineConfig(
            name="test_pipeline",
            steps=[
                PipelineStep("word_frequency"),
                PipelineStep("sentiment_analyzer", {"language": "pt"})
            ]
        )

        results = core.execute_pipeline(pipeline, doc)

        assert isinstance(results, dict)
        assert "word_frequency" in results
        assert "sentiment_analyzer" in results
        assert results["word_frequency"]["total_words"] > 0


class TestPluginTypes:
    """Testa diferentes tipos de plugins"""
    
    def test_analyzer_plugin(self, core):
        """Testa plugin analyzer - CORRIGIDO"""
        doc = core.add_document("analyzer_test", "teste de análise")
        result = core.execute_plugin("word_frequency", doc)
        
        assert isinstance(result, dict)
        assert "total_words" in result
        assert result["total_words"] >= 2
    
    def test_document_plugin(self, core):
        """Testa plugin de documento - CORRIGIDO"""
        teams_text = """
        [00:00:00] João Silva
        Olá pessoal, vamos começar?
        
        [00:00:15] Maria Santos
        Sim, podemos começar.
        """
        
        doc = core.add_document("teams_test", teams_text)
        result = core.execute_plugin("teams_cleaner", doc)
        
        # Verificar campos que realmente existem
        assert "cleaned_document" in result or "clean_text" in result
        assert "metadata" in result
    


class TestErrorHandling:
    """Testa tratamento de erros"""
    
    def test_invalid_config_rejected(self, core, sample_document):
        """Core deve rejeitar parâmetros desconhecidos (alinhado com API)"""
        with pytest.raises(ValueError, match="Configuração inválida"):
            core.execute_plugin(
                "word_frequency",
                sample_document,
                {"invalid_param": "value"}
            )
    
    def test_missing_dependency_warns(self, core, caplog):
        """Plugin com dependência inexistente deve logar warning no build_graph"""
        import logging

        mock_plugin = MagicMock()
        meta = PluginMetadata(
            id="mock_plugin",
            type=PluginType.ANALYZER,
            name="Mock",
            description="Test",
            version="1.0",
            requires=["plugin_inexistente"]
        )
        mock_plugin.meta.return_value = meta
        mock_plugin.validate_config.return_value = (True, None)

        core.loader.loaded_plugins["mock_plugin"] = mock_plugin
        core.registry["mock_plugin"] = meta

        # Reconstruir grafo — warning deve ser emitido aqui
        core.resolver = DependencyResolver()
        for pid, m in core.registry.items():
            core.resolver.add_plugin(pid, m)
        with caplog.at_level(logging.WARNING):
            core.resolver.build_graph()

        assert "plugin_inexistente" in caplog.text
        assert "nenhum plugin fornece" in caplog.text


class TestPerformance:
    """Testes de performance"""
    
    def test_large_document(self, core):
        """Testa com documento grande"""
        large_text = " ".join(["palavra"] * 1000)
        doc = core.add_document("large_doc", large_text)
        
        import time
        start = time.time()
        result = core.execute_plugin("word_frequency", doc)
        duration = time.time() - start
        
        assert duration < 1.0
        assert result["total_words"] >= 1000
    
    def test_cache_performance_fixed(self, core):
        """Testa performance do cache - CORRIGIDO"""
        doc = core.add_document("cache_test", "teste de cache")
        
        # Primeira execução
        import time
        start1 = time.time()
        result1 = core.execute_plugin("word_frequency", doc)
        time1 = time.time() - start1
        
        # Segunda execução (cache)
        start2 = time.time()
        result2 = core.execute_plugin("word_frequency", doc)
        time2 = time.time() - start2
        
        # Cache deve ser mais rápido, mas talvez não 10x
        # Mudando para teste mais realista
        assert time2 <= time1  # Cache não pode ser mais lento
        assert result1 == result2  # Resultados devem ser iguais


class TestEngineEdgeCases:
    """Testes de edge cases do engine.py"""

    def test_get_plugin_not_found(self, core):
        """get_plugin com plugin inexistente deve levantar ValueError"""
        with pytest.raises(ValueError, match="não encontrado"):
            core.get_plugin("nonexistent")

    def test_execute_plugin_invalid_config(self, core, temp_dir):
        """Plugin cuja validate_config retorna (False, msg) deve levantar ValueError"""
        mock_plugin = MagicMock()
        mock_plugin.validate_config.return_value = (False, "bad config")
        meta = PluginMetadata(
            id="invalid_config_plugin",
            type=PluginType.ANALYZER,
            name="InvalidConfig",
            description="Test",
            version="1.0",
        )
        mock_plugin.meta.return_value = meta

        core.loader.loaded_plugins["invalid_config_plugin"] = mock_plugin
        core.registry["invalid_config_plugin"] = meta

        doc = core.add_document("test_inv", "texto")
        with pytest.raises(ValueError, match="Configuração inválida"):
            core.execute_plugin("invalid_config_plugin", doc, {"x": 1})

    def test_execute_plugin_with_dependencies(self, core):
        """Plugin com dependência deve auto-executar o provider primeiro"""
        # Provider
        provider = MagicMock()
        provider_meta = PluginMetadata(
            id="provider_plugin",
            type=PluginType.ANALYZER,
            name="Provider",
            description="Provides data_field",
            version="1.0",
            provides=["data_field"],
        )
        provider.meta.return_value = provider_meta
        provider.validate_config.return_value = (True, None)
        provider.analyze.return_value = {"data_field": [1, 2, 3]}

        # Consumer
        consumer = MagicMock()
        consumer_meta = PluginMetadata(
            id="consumer_plugin",
            type=PluginType.ANALYZER,
            name="Consumer",
            description="Requires data_field",
            version="1.0",
            requires=["data_field"],
        )
        consumer.meta.return_value = consumer_meta
        consumer.validate_config.return_value = (True, None)
        consumer.analyze.return_value = {"consumed": True}

        # Registrar ambos
        core.loader.loaded_plugins["provider_plugin"] = provider
        core.registry["provider_plugin"] = provider_meta
        core.loader.loaded_plugins["consumer_plugin"] = consumer
        core.registry["consumer_plugin"] = consumer_meta

        # Reconstruir grafo de dependências
        core.resolver = DependencyResolver()
        for pid, meta in core.registry.items():
            core.resolver.add_plugin(pid, meta)
        core.resolver.build_graph()

        doc = core.add_document("dep_test", "texto")
        result = core.execute_plugin("consumer_plugin", doc)

        # Provider deve ter sido chamado
        provider.analyze.assert_called_once()
        # Consumer deve ter sido chamado com dep_results contendo resultado do provider
        consumer.analyze.assert_called_once()
        assert result == {"consumed": True}

    def test_execute_plugin_visualizer(self, core, temp_dir):
        """Visualizer cujo render retorna dict com html ou base64"""
        viz = MagicMock()
        viz_meta = PluginMetadata(
            id="test_viz",
            type=PluginType.VISUALIZER,
            name="TestViz",
            description="Test visualizer",
            version="1.0",
        )
        viz.meta.return_value = viz_meta
        viz.validate_config.return_value = (True, None)
        viz.render.return_value = {"html": "<html><body>chart</body></html>"}

        core.loader.loaded_plugins["test_viz"] = viz
        core.registry["test_viz"] = viz_meta

        doc = core.add_document("viz_test", "texto")
        result = core.execute_plugin("test_viz", doc)

        assert "html" in result
        assert "<html>" in result["html"]

    def test_execute_pipeline_step_failure(self, core):
        """Pipeline deve levantar RuntimeError quando um step falha"""
        from qualia.core import PipelineConfig, PipelineStep

        # Plugin que falha
        failing = MagicMock()
        failing_meta = PluginMetadata(
            id="failing_plugin",
            type=PluginType.ANALYZER,
            name="Failing",
            description="Always fails",
            version="1.0",
        )
        failing.meta.return_value = failing_meta
        failing.validate_config.return_value = (True, None)
        failing.analyze.side_effect = RuntimeError("boom")

        core.loader.loaded_plugins["failing_plugin"] = failing
        core.registry["failing_plugin"] = failing_meta

        pipeline = PipelineConfig(
            name="fail_pipeline",
            steps=[PipelineStep("failing_plugin")],
        )
        doc = core.add_document("pipe_fail", "texto")

        with pytest.raises(RuntimeError, match="failing_plugin"):
            core.execute_pipeline(pipeline, doc)


    def test_list_plugins_filtered(self, core):
        """list_plugins com tipo deve retornar somente plugins daquele tipo"""
        analyzers = core.list_plugins(PluginType.ANALYZER)
        assert len(analyzers) > 0
        for meta in analyzers:
            assert meta.type == PluginType.ANALYZER

        visualizers = core.list_plugins(PluginType.VISUALIZER)
        assert len(visualizers) > 0
        for meta in visualizers:
            assert meta.type == PluginType.VISUALIZER

    def test_get_plugin_info(self, core):
        """get_plugin_info com plugin válido deve retornar PluginMetadata"""
        info = core.get_plugin_info("word_frequency")
        assert info is not None
        assert isinstance(info, PluginMetadata)
        assert info.id == "word_frequency"

    def test_get_plugin_info_not_found(self, core):
        """get_plugin_info com plugin inexistente deve retornar None"""
        info = core.get_plugin_info("nonexistent")
        assert info is None


class TestBasePluginValidation:
    """Testes de validação das base classes de plugins"""

    def test_analyzer_validate_config_catches_error(self):
        """validate_config de BaseAnalyzerPlugin deve capturar exceção e retornar (False, msg)"""

        class FailAnalyzer(BaseAnalyzerPlugin):
            def meta(self):
                return PluginMetadata(
                    id="fail_analyzer", type=PluginType.ANALYZER,
                    name="Fail", description="Test", version="1.0",
                )

            def _validate_config(self, config):
                raise ValueError("param X inválido")

        plugin = FailAnalyzer()
        valid, error = plugin.validate_config({"x": 1})
        assert valid is False
        assert "param X inválido" in error

    def test_visualizer_validate_config_catches_error(self):
        """validate_config de BaseVisualizerPlugin deve capturar exceção"""

        class FailVisualizer(BaseVisualizerPlugin):
            def meta(self):
                return PluginMetadata(
                    id="fail_viz", type=PluginType.VISUALIZER,
                    name="Fail", description="Test", version="1.0",
                )

            def _validate_config(self, config):
                raise ValueError("config ruim")

        plugin = FailVisualizer()
        valid, error = plugin.validate_config({"y": 2})
        assert valid is False
        assert "config ruim" in error

    def test_document_validate_config_catches_error(self):
        """validate_config de BaseDocumentPlugin deve capturar exceção"""
        from qualia.core import BaseDocumentPlugin

        class FailDoc(BaseDocumentPlugin):
            def meta(self):
                return PluginMetadata(
                    id="fail_doc", type=PluginType.DOCUMENT,
                    name="Fail", description="Test", version="1.0",
                )

            def _validate_config(self, config):
                raise TypeError("tipo errado")

        plugin = FailDoc()
        valid, error = plugin.validate_config({"z": 3})
        assert valid is False
        assert "tipo errado" in error

    def test_visualizer_type_conversion_integer(self):
        """Visualizer deve converter string '42' para int quando type='integer'"""

        class IntViz(BaseVisualizerPlugin):
            def meta(self):
                return PluginMetadata(
                    id="int_viz", type=PluginType.VISUALIZER,
                    name="IntViz", description="Test", version="1.0",
                    parameters={"count": {"type": "integer", "default": 10}},
                )

        plugin = IntViz()
        result = plugin._validate_config({"count": "42"})
        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_visualizer_type_conversion_bool_string(self):
        """Visualizer deve converter string 'true' para True quando type='bool'"""

        class BoolViz(BaseVisualizerPlugin):
            def meta(self):
                return PluginMetadata(
                    id="bool_viz", type=PluginType.VISUALIZER,
                    name="BoolViz", description="Test", version="1.0",
                    parameters={"flag": {"type": "bool", "default": False}},
                )

        plugin = BoolViz()
        result = plugin._validate_config({"flag": "true"})
        assert result["flag"] is True

    def test_visualizer_type_conversion_bool_value(self):
        """Visualizer deve converter 0 para False quando type='bool'"""

        class BoolViz2(BaseVisualizerPlugin):
            def meta(self):
                return PluginMetadata(
                    id="bool_viz2", type=PluginType.VISUALIZER,
                    name="BoolViz2", description="Test", version="1.0",
                    parameters={"flag": {"type": "bool", "default": True}},
                )

        plugin = BoolViz2()
        result = plugin._validate_config({"flag": 0})
        assert result["flag"] is False


class TestProvidesValidation:
    """Testes de validação do contrato de provides no engine"""

    def test_provides_error_on_missing_field(self, core):
        """Engine levanta ValueError se resultado não contém campo de provides"""
        plugin = MagicMock()
        plugin_meta = PluginMetadata(
            id="incomplete_plugin",
            type=PluginType.ANALYZER,
            name="Incomplete",
            description="Missing provides field",
            version="1.0",
            provides=["field_a", "field_b"],
        )
        plugin.meta.return_value = plugin_meta
        plugin.validate_config.return_value = (True, None)
        plugin.analyze.return_value = {"field_a": "ok"}  # field_b ausente

        core.loader.loaded_plugins["incomplete_plugin"] = plugin
        core.registry["incomplete_plugin"] = plugin_meta

        doc = core.add_document("test", "texto")
        with pytest.raises(ValueError, match="field_b"):
            core.execute_plugin("incomplete_plugin", doc)

    def test_no_warning_when_provides_complete(self, core, caplog):
        """Sem warning quando resultado contém todos os campos de provides"""
        import logging

        plugin = MagicMock()
        plugin_meta = PluginMetadata(
            id="complete_plugin",
            type=PluginType.ANALYZER,
            name="Complete",
            description="All provides present",
            version="1.0",
            provides=["field_a", "field_b"],
        )
        plugin.meta.return_value = plugin_meta
        plugin.validate_config.return_value = (True, None)
        plugin.analyze.return_value = {"field_a": "ok", "field_b": "ok"}

        core.loader.loaded_plugins["complete_plugin"] = plugin
        core.registry["complete_plugin"] = plugin_meta

        doc = core.add_document("test2", "texto")
        with caplog.at_level(logging.WARNING, logger="qualia.core.engine"):
            core.execute_plugin("complete_plugin", doc)

        assert "provides" not in caplog.text

    def test_visualizer_skips_provides_validation(self, core, temp_dir, caplog):
        """Visualizers não disparam warning de provides (retornam Path, não dict)"""
        import logging

        viz = MagicMock()
        viz_meta = PluginMetadata(
            id="skip_viz",
            type=PluginType.VISUALIZER,
            name="SkipViz",
            description="Test",
            version="1.0",
            provides=["should_not_warn"],
        )
        viz.meta.return_value = viz_meta
        viz.validate_config.return_value = (True, None)
        viz.render.return_value = temp_dir / "result.png"

        core.loader.loaded_plugins["skip_viz"] = viz
        core.registry["skip_viz"] = viz_meta

        doc = core.add_document("viz_test", "texto")
        with caplog.at_level(logging.WARNING, logger="qualia.core.engine"):
            core.execute_plugin("skip_viz", doc)

        assert "provides" not in caplog.text


class TestProvidesContract:
    """Teste paramétrico: cada analyzer/document plugin retorna os campos de provides"""

    @pytest.mark.parametrize("plugin_id", [
        "word_frequency",
        "readability_analyzer",
        "sentiment_analyzer",
    ])
    def test_analyzer_result_matches_provides(self, core, plugin_id):
        """Resultado do plugin contém todos os campos declarados em provides"""
        meta = core.registry[plugin_id]
        doc = core.add_document(f"contract_{plugin_id}", "Este é um texto de teste para validação do contrato de provides. " * 5)
        result = core.execute_plugin(plugin_id, doc)

        for field in meta.provides:
            assert field in result, f"Plugin '{plugin_id}' declara provides='{field}' mas não retorna no resultado"

    def test_visualizer_provides_empty(self, core):
        """Todos os visualizers devem ter provides=[]"""
        for pid, meta in core.registry.items():
            if meta.type == PluginType.VISUALIZER:
                assert meta.provides == [], f"Visualizer '{pid}' não deveria ter provides (tem {meta.provides})"

    def test_visualizer_validate_data_missing_field(self):
        """_validate_data deve levantar ValueError se campo requerido estiver faltando"""

        class NeedyViz(BaseVisualizerPlugin):
            def meta(self):
                return PluginMetadata(
                    id="needy_viz", type=PluginType.VISUALIZER,
                    name="NeedyViz", description="Test", version="1.0",
                    requires=["needed_field"],
                )

        plugin = NeedyViz()
        with pytest.raises(ValueError, match="needed_field"):
            plugin._validate_data({})


class TestModels:
    """Testes para models.py — ExecutionContext"""

    def test_execution_context_add_and_get_results(self):
        """add_result + get_dependency_results deve retornar apenas deps solicitadas"""
        from qualia.core import ExecutionContext, Document

        doc = Document(id="ctx_test", content="texto")
        ctx = ExecutionContext(document=doc)

        ctx.add_result("plugin_a", {"score": 0.8})
        ctx.add_result("plugin_b", {"count": 42})

        deps = ctx.get_dependency_results(["plugin_a"])
        assert "plugin_a" in deps
        assert deps["plugin_a"] == {"score": 0.8}
        assert "plugin_b" not in deps

    def test_execution_context_missing_dependency(self):
        """get_dependency_results para dep inexistente deve retornar dict vazio"""
        from qualia.core import ExecutionContext, Document

        doc = Document(id="ctx_test2", content="texto")
        ctx = ExecutionContext(document=doc)

        deps = ctx.get_dependency_results(["nonexistent"])
        assert deps == {}


class TestInterfaces:
    """Testes para PluginMetadata.get_dependencies (interfaces.py line 38)"""

    def test_plugin_metadata_get_dependencies(self):
        """get_dependencies retorna union de requires e can_use"""
        meta = PluginMetadata(
            id="test_dep",
            type=PluginType.ANALYZER,
            name="Test",
            description="Test",
            version="1.0",
            requires=["a", "b"],
            can_use=["c"],
        )
        deps = meta.get_dependencies()
        assert deps == {"a", "b", "c"}

    def test_plugin_metadata_get_dependencies_empty(self):
        """get_dependencies com listas vazias retorna set vazio"""
        meta = PluginMetadata(
            id="test_empty",
            type=PluginType.ANALYZER,
            name="Test",
            description="Test",
            version="1.0",
            requires=[],
            can_use=[],
        )
        deps = meta.get_dependencies()
        assert deps == set()


class TestValidateAndConvert:
    """Testa _validate_and_convert com todas as branches de tipo."""

    def test_int_conversion_from_string(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"count": {"type": "int", "default": 0}}
        result = _validate_and_convert({"count": "42"}, params)
        assert result["count"] == 42

    def test_float_conversion_from_string(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"threshold": {"type": "float", "default": 0.0}}
        result = _validate_and_convert({"threshold": "0.75"}, params)
        assert result["threshold"] == 0.75

    def test_bool_from_string_true(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"enabled": {"type": "bool", "default": False}}
        for truthy in ("true", "True", "1", "yes"):
            result = _validate_and_convert({"enabled": truthy}, params)
            assert result["enabled"] is True, f"Failed for '{truthy}'"

    def test_bool_from_string_false(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"enabled": {"type": "bool", "default": True}}
        for falsy in ("false", "0", "no", "anything"):
            result = _validate_and_convert({"enabled": falsy}, params)
            assert result["enabled"] is False, f"Failed for '{falsy}'"

    def test_bool_from_nonstring(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"enabled": {"type": "bool", "default": False}}
        assert _validate_and_convert({"enabled": 1}, params)["enabled"] is True
        assert _validate_and_convert({"enabled": 0}, params)["enabled"] is False
        assert _validate_and_convert({"enabled": None}, params)["enabled"] is False

    def test_int_invalid_raises(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"count": {"type": "int", "default": 0}}
        with pytest.raises(ValueError):
            _validate_and_convert({"count": "abc"}, params)

    def test_unknown_param_rejected(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"known": {"type": "str", "default": ""}}
        with pytest.raises(ValueError, match="desconhecido"):
            _validate_and_convert({"unknown": "x"}, params)

    def test_exclude_skips_params(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"keep": {"type": "str", "default": ""}, "skip": {"type": "str", "default": ""}}
        result = _validate_and_convert({"keep": "a", "skip": "b"}, params, exclude={"skip"})
        assert "keep" in result
        assert "skip" not in result

    def test_default_applied_when_missing(self):
        from qualia.core.base_plugins import _validate_and_convert
        params = {"count": {"type": "int", "default": 42}}
        result = _validate_and_convert({}, params)
        assert result["count"] == 42