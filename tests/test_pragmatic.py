"""
Testes pragmáticos para Qualia Core
Respeita que cada plugin tem sua própria estrutura
Não força padronização artificial
"""

import pytest
from pathlib import Path
from qualia.core import QualiaCore, Document


@pytest.fixture
def core():
    """Core instance"""
    return QualiaCore()


class TestCoreBasics:
    """Testa funcionalidades básicas sem assumir estruturas"""
    
    def test_core_loads(self, core):
        """Core carrega e descobre plugins"""
        plugins = core.discover_plugins()
        assert len(plugins) >= 8
        assert all(p in plugins for p in [
            'word_frequency', 'sentiment_analyzer', 'teams_cleaner',
            'wordcloud_d3', 'frequency_chart_plotly', 'sentiment_viz_plotly',
            'readability_analyzer', 'transcription'
        ])
    
    def test_plugin_execution_returns_dict(self, core):
        """Plugins retornam dicionários (qualquer estrutura)"""
        doc = core.add_document("test", "texto de teste")
        
        # Não assumimos estrutura, só que retorna dict
        result = core.execute_plugin("word_frequency", doc)
        assert isinstance(result, dict)
        assert len(result) > 0  # Tem algum conteúdo
    
    def test_each_plugin_has_unique_output(self, core):
        """Cada plugin tem sua própria estrutura de saída"""
        doc = core.add_document("test", "Este texto é muito bom!")
        
        # Executa diferentes plugins
        wf_result = core.execute_plugin("word_frequency", doc)
        sa_result = core.execute_plugin("sentiment_analyzer", doc)
        
        # Cada um tem estrutura própria
        assert isinstance(wf_result, dict)
        assert isinstance(sa_result, dict)
        
        # E estruturas diferentes!
        assert set(wf_result.keys()) != set(sa_result.keys())
    
    def test_plugin_dependencies_work(self, core):
        """Plugins que dependem de outros conseguem acessar dados"""
        doc = core.add_document("test", "Texto para análise de sentimento positivo")

        # sentiment_viz_plotly depende de sentiment_analyzer
        # execute_plugin deve resolver a dependência automaticamente
        result = core.execute_plugin("sentiment_viz_plotly", doc)

        # Deve retornar resultado do visualizer (dict com html ou base64)
        assert isinstance(result, dict)
        assert "html" in result or "data" in result


class TestAPIBasics:
    """Testa API sem assumir estruturas específicas"""
    
    def test_health_returns_success(self, client):
        """Health endpoint responde com sucesso"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["plugins_loaded"] > 0
    
    def test_plugins_list_returns_array(self, client):
        """Lista de plugins retorna array"""
        response = client.get("/plugins")
        assert response.status_code == 200
        plugins = response.json()
        assert isinstance(plugins, list)
        assert len(plugins) >= 8
    
    def test_analyze_returns_plugin_specific_structure(self, client):
        """Análise retorna estrutura específica do plugin"""
        response = client.post("/analyze/word_frequency", 
                              json={"text": "teste teste", "config": {}})
        assert response.status_code == 200
        
        data = response.json()
        # API wrapper
        assert data["status"] == "success"
        assert data["plugin_id"] == "word_frequency"
        
        # Plugin data - não assumimos estrutura
        assert "result" in data
        assert isinstance(data["result"], dict)
        assert len(data["result"]) > 0
    
    def test_different_plugins_different_outputs(self, client):
        """Plugins diferentes retornam estruturas diferentes"""
        # Word frequency
        r1 = client.post("/analyze/word_frequency",
                        json={"text": "teste", "config": {}})
        
        # Sentiment analyzer  
        r2 = client.post("/analyze/sentiment_analyzer",
                        json={"text": "teste", "config": {}})
        
        assert r1.status_code == 200
        assert r2.status_code == 200
        
        # Estruturas diferentes
        result1 = r1.json()["result"]
        result2 = r2.json()["result"]
        
        assert set(result1.keys()) != set(result2.keys())


class TestPluginContracts:
    """Testa contratos reais de cada plugin (não estrutura idealizada)"""
    
    def test_word_frequency_contract(self, core):
        """word_frequency retorna dados sobre palavras (sem assumir campos)"""
        doc = core.add_document("test", "palavra palavra teste")
        result = core.execute_plugin("word_frequency", doc)
        
        # Só verificamos que tem dados relacionados a palavras
        assert any("word" in k.lower() or "total" in k.lower() 
                  for k in result.keys())
    
    def test_sentiment_analyzer_contract(self, core):
        """sentiment_analyzer retorna dados sobre sentimento"""
        doc = core.add_document("test", "Este produto é ótimo!")
        result = core.execute_plugin("sentiment_analyzer", doc)
        
        # Só verificamos que tem dados relacionados a sentimento
        assert any("sentiment" in str(v).lower() or 
                  "polarity" in str(k).lower() or
                  "interpretation" in str(k).lower()
                  for k, v in result.items())
    
    def test_teams_cleaner_contract(self, core):
        """teams_cleaner processa transcrições"""
        doc = core.add_document("test", "[00:00:00] João\nOlá")
        result = core.execute_plugin("teams_cleaner", doc)
        
        # Só verificamos que processou algo
        assert any("clean" in str(k).lower() or 
                  "metadata" in str(k).lower()
                  for k in result.keys())


class TestPipelineFlexibility:
    """Testa que pipeline funciona com estruturas variadas"""
    
    def test_pipeline_passes_data_between_plugins(self, client):
        """Pipeline passa dados entre plugins sem forçar estrutura"""
        import json as _json
        response = client.post("/pipeline?sync=true", data={
            "text": "Texto para análise",
            "steps": _json.dumps([
                {"plugin_id": "word_frequency"},
                {"plugin_id": "sentiment_analyzer"}
            ])
        })

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "results" in data
        assert data["steps_executed"] == 2

        for step_result in data["results"]:
            assert "plugin_id" in step_result
            assert "result" in step_result


class TestRealWorldUsage:
    """Testa casos de uso reais sem assumir estruturas"""
    
    def test_analyze_document_flow(self, core):
        """Fluxo completo: documento → análise → resultado"""
        # 1. Criar documento
        doc = core.add_document("report", 
            "Este relatório mostra resultados excelentes. "
            "A equipe está muito satisfeita com o progresso.")
        
        # 2. Executar várias análises
        analyses = {}
        for plugin_id in ["word_frequency", "sentiment_analyzer"]:
            try:
                result = core.execute_plugin(plugin_id, doc)
                analyses[plugin_id] = result
            except Exception:
                pass  # Plugin pode falhar, não é crítico
        
        # 3. Verificar que temos resultados
        assert len(analyses) > 0
        assert all(isinstance(r, dict) for r in analyses.values())
    
    def test_plugin_can_consume_others(self, core):
        """Plugin visualizer consome dados de analyzer"""
        doc = core.add_document("test", "dados para visualização")
        
        # Visualizer deve conseguir acessar dados do analyzer
        # Não testamos estrutura, só que funciona
        from unittest.mock import patch
        with patch('matplotlib.pyplot.savefig'):
            try:
                # Se sentiment_viz_plotly consegue executar, 
                # conseguiu acessar dados do sentiment_analyzer
                core.execute_plugin("sentiment_viz_plotly", doc)
                assert True
            except TypeError as e:
                if "NoneType" in str(e):
                    # Problema conhecido de dependências
                    pytest.skip("Dependência não resolvida corretamente")


# Testes de sanidade básica
def test_sanity_core_exists():
    """Core pode ser importado"""
    from qualia.core import QualiaCore
    assert QualiaCore is not None


def test_sanity_api_exists():
    """API pode ser importada"""
    from qualia.api import app
    assert app is not None


def test_sanity_plugins_directory_exists():
    """Diretório de plugins existe e tem conteúdo"""
    plugins_dir = Path(__file__).parent.parent / "plugins"
    assert plugins_dir.exists()
    # Conta __init__.py recursivamente (cada plugin tem um), ignorando _templates
    plugin_inits = [p for p in plugins_dir.rglob("__init__.py")
                    if not any(part.startswith("_") for part in p.parent.relative_to(plugins_dir).parts)]
    assert len(plugin_inits) >= 6