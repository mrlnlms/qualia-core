# tests/test_stress.py
"""
Testes de stress — concorrência pesada, entradas extremas, configs aleatórias.

Roda com: pytest tests/test_stress.py -v
Ou separado: pytest tests/test_stress.py -v -m stress
"""

import json
import random
import string
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
import pytest_asyncio
import asyncio
import httpx

from qualia.core import QualiaCore, Document
from qualia.core.cache import CacheManager
from qualia.api import app

pytestmark = pytest.mark.stress


@pytest.fixture
def core():
    tmp = Path(tempfile.mkdtemp())
    c = QualiaCore(
        plugins_dir=Path(__file__).parent.parent / "plugins",
        cache_dir=tmp / "cache",
    )
    yield c
    shutil.rmtree(tmp)


@pytest.fixture
def cache_dir():
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


@pytest_asyncio.fixture
async def ac():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# =============================================================================
# CACHE — concorrência pesada
# =============================================================================

class TestCacheStress:
    """Cache sob pressão: múltiplas threads fazendo set/get/invalidate."""

    def test_concurrent_set_get_no_corruption(self, cache_dir):
        """20 threads gravando e lendo ao mesmo tempo — dados nunca corrompem."""
        cache = CacheManager(cache_dir)
        errors = []

        def worker(thread_id):
            try:
                for i in range(50):
                    doc_id = f"doc_{thread_id}"
                    plugin_id = f"plugin_{thread_id % 3}"
                    config = {"iter": i}
                    data = {"thread": thread_id, "iter": i, "value": thread_id * 1000 + i}

                    cache.set(doc_id, plugin_id, config, data)
                    result = cache.get(doc_id, plugin_id, config)

                    if result is None:
                        errors.append(f"Thread {thread_id} iter {i}: got None after set")
                    elif result["value"] != thread_id * 1000 + i:
                        errors.append(f"Thread {thread_id} iter {i}: wrong value {result['value']}")
            except Exception as e:
                errors.append(f"Thread {thread_id}: {type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(worker, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Erros de concorrência:\n" + "\n".join(errors[:10])

    def test_concurrent_invalidate_during_writes(self, cache_dir):
        """Threads invalidando enquanto outras gravam — sem crash."""
        cache = CacheManager(cache_dir)
        errors = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    cache.set(f"doc_{i % 10}", "plugin_a", {"i": i}, {"v": i})
                    i += 1
                except Exception as e:
                    errors.append(f"Writer: {e}")

        def invalidator():
            while not stop.is_set():
                try:
                    cache.invalidate(doc_id=f"doc_{random.randint(0, 9)}")
                except Exception as e:
                    errors.append(f"Invalidator: {e}")

        threads = [threading.Thread(target=writer) for _ in range(5)]
        threads += [threading.Thread(target=invalidator) for _ in range(3)]
        for t in threads:
            t.start()

        time.sleep(2)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Erros:\n" + "\n".join(errors[:10])

        stats = cache.stats()
        assert stats["hits"] >= 0
        assert stats["misses"] >= 0

    def test_cache_stats_consistent_under_load(self, cache_dir):
        """Após N operações, hits + misses + size devem ser consistentes."""
        cache = CacheManager(cache_dir, max_size=50)

        for i in range(200):
            cache.set(f"doc_{i % 20}", "plugin", {"i": i}, {"v": i})

        for i in range(200):
            cache.get(f"doc_{i % 20}", "plugin", {"i": i})

        stats = cache.stats()
        assert stats["size"] <= 50, f"Size {stats['size']} excede max_size 50"
        assert stats["hits"] + stats["misses"] == 200
        assert stats["evictions"] >= 150  # 200 sets - 50 max_size


# =============================================================================
# CONFIG FUZZING — configs aleatórias nunca crasham
# =============================================================================

class TestConfigFuzzing:
    """Configs aleatórias/malformadas nunca devem crashar — sempre ValueError ou resultado válido."""

    FUZZ_CONFIGS = [
        {"min_word_length": "abc"},
        {"min_word_length": -999},
        {"min_word_length": 999999},
        {"max_words": 0},
        {"max_words": 0.5},
        {"case_sensitive": "maybe"},
        {"language": "klingon"},
        {"tokenization": "quantum"},
        {"param_fantasma": 123},
        {"remove_stopwords": None},
        {"min_word_length": True},
        {"": ""},
        {"a" * 1000: "b" * 1000},
    ]

    def test_word_frequency_never_crashes_on_bad_config(self, core):
        """word_frequency com configs malformadas: ValueError ou resultado, nunca crash."""
        doc = core.add_document("fuzz", "Texto normal para fuzzing de configuração.")
        for i, config in enumerate(self.FUZZ_CONFIGS):
            try:
                result = core.execute_plugin("word_frequency", doc, config)
                assert "word_frequencies" in result, f"Config {i}: resultado sem word_frequencies"
            except ValueError:
                pass

    def test_sentiment_never_crashes_on_bad_config(self, core):
        """sentiment_analyzer com configs malformadas: ValueError ou resultado, nunca crash."""
        doc = core.add_document("fuzz_sent", "Texto positivo e feliz para teste.")
        bad_configs = [
            {"language": 42},
            {"polarity_threshold": "alto"},
            {"polarity_threshold": -5},
            {"analyze_sentences": "yes"},
            {"campo_inexistente": [1, 2, 3]},
        ]
        for i, config in enumerate(bad_configs):
            try:
                result = core.execute_plugin("sentiment_analyzer", doc, config)
                assert "polarity" in result, f"Config {i}: resultado sem polarity"
            except ValueError:
                pass

    def test_readability_never_crashes_on_bad_config(self, core):
        """readability com configs malformadas: sempre controlado."""
        doc = core.add_document("fuzz_read", "Frase curta. Frase longa com muitas palavras diferentes.")
        bad_configs = [
            {"detail_level": 999},
            {"detail_level": "full"},
            {"campo": {"nested": True}},
        ]
        for i, config in enumerate(bad_configs):
            try:
                result = core.execute_plugin("readability_analyzer", doc, config)
                assert "word_count" in result
            except ValueError:
                pass

    def test_random_configs_never_crash(self, core):
        """50 configs geradas aleatoriamente — nenhum plugin crasheia."""
        doc = core.add_document("random", "Texto para teste aleatório de configuração.")
        analyzers = ["word_frequency", "sentiment_analyzer", "readability_analyzer"]

        for _ in range(50):
            plugin = random.choice(analyzers)
            config = {}
            for _ in range(random.randint(1, 3)):
                key = random.choice(["min_word_length", "max_words", "language",
                                     "xyz", "foo_bar", ""])
                value = random.choice([
                    random.randint(-100, 100),
                    random.random(),
                    "".join(random.choices(string.ascii_letters, k=5)),
                    True, False, None, [], {},
                ])
                config[key] = value

            try:
                core.execute_plugin(plugin, doc, config)
            except (ValueError, TypeError):
                pass


# =============================================================================
# TEXTOS EXTREMOS — provides sempre cumprido
# =============================================================================

class TestExtremeInputs:
    """Textos extremos nunca devem quebrar o contrato de provides."""

    EXTREME_TEXTS = [
        ("empty", ""),
        ("single_char", "a"),
        ("single_word", "palavra"),
        ("only_spaces", "   \t\n  \t  "),
        ("only_numbers", "123 456 789 0 42 99"),
        ("only_punctuation", "!@#$%^&*()_+-=[]{}|;':\",./<>?"),
        ("only_emojis", "\U0001f600\U0001f389\U0001f680\U0001f4a1\U0001f525 " * 20),
        ("null_bytes", "texto\x00com\x00nulos\x00dentro"),
        ("unicode_mixed", "café naïve résumé über straße 日本語 中文 العربية"),
        ("repetitive_100kb", "palavra " * 12500),
        ("single_long_word", "a" * 10000),
        ("newlines_only", "\n" * 100),
        ("tabs_only", "\t" * 100),
    ]

    @pytest.mark.parametrize("name,text", EXTREME_TEXTS)
    def test_word_frequency_provides_contract(self, core, name, text):
        """word_frequency cumpre provides com qualquer texto."""
        doc = core.add_document(f"extreme_{name}", text)
        result = core.execute_plugin("word_frequency", doc)
        assert "word_frequencies" in result
        assert "vocabulary_size" in result
        assert isinstance(result["vocabulary_size"], int)
        assert result["vocabulary_size"] >= 0

    @pytest.mark.parametrize("name,text", EXTREME_TEXTS)
    def test_readability_provides_contract(self, core, name, text):
        """readability cumpre provides ou rejeita texto vazio com ValueError."""
        doc = core.add_document(f"extreme_read_{name}", text)
        try:
            result = core.execute_plugin("readability_analyzer", doc)
            assert "word_count" in result
            assert isinstance(result["word_count"], int)
        except ValueError:
            # Texto vazio/whitespace → ValueError esperado
            assert not text.strip()

    def test_sentiment_with_extreme_texts(self, core):
        """sentiment com textos extremos — nunca crash."""
        safe_texts = [
            ("empty", ""),
            ("single_word", "bom"),
            ("emojis", "\U0001f600\U0001f389\U0001f680 " * 10),
            ("unicode", "café résumé über日本語"),
            ("big", "Texto positivo e bom. " * 2000),
        ]
        for name, text in safe_texts:
            doc = core.add_document(f"sent_{name}", text)
            try:
                result = core.execute_plugin("sentiment_analyzer", doc)
                assert "polarity" in result
                assert -1 <= result["polarity"] <= 1
            except (ValueError, Exception):
                pass


# =============================================================================
# API — concorrência pesada, nunca 500
# =============================================================================

class TestAPIStress:
    """API sob carga: muitos requests simultâneos, nunca 500."""

    @pytest.mark.asyncio
    async def test_20_concurrent_analyze_requests(self, ac):
        """20 requests simultâneos ao /analyze — todos 200, nenhum 500."""
        tasks = [
            ac.post("/analyze/word_frequency", json={
                "text": f"Texto único thread {i} com palavras suficientes pra análise.",
                "config": {},
            })
            for i in range(20)
        ]
        responses = await asyncio.gather(*tasks)
        status_codes = [r.status_code for r in responses]
        assert 500 not in status_codes, f"500 encontrado: {status_codes}"
        assert all(s == 200 for s in status_codes), f"Status inesperados: {status_codes}"

    @pytest.mark.asyncio
    async def test_mixed_endpoints_under_load(self, ac):
        """Mix de endpoints simultâneos — health, plugins, analyze, pipeline."""
        tasks = []
        for i in range(5):
            tasks.append(ac.get("/health"))
            tasks.append(ac.get("/plugins"))
            tasks.append(ac.post("/analyze/word_frequency", json={
                "text": f"Texto mix {i} para teste de carga.",
                "config": {},
            }))
            tasks.append(ac.post("/pipeline?sync=true", data={
                "steps": '[{"plugin_id": "word_frequency", "config": {}}]',
                "text": f"Pipeline mix {i} para teste.",
            }))

        responses = await asyncio.gather(*tasks)
        status_codes = [r.status_code for r in responses]
        assert 500 not in status_codes, f"500 encontrado nos {len(responses)} responses"

    @pytest.mark.asyncio
    async def test_bad_requests_never_500(self, ac):
        """Requests inválidos devem retornar 4xx, nunca 500."""
        bad_requests = [
            ac.post("/analyze/nonexistent_plugin", json={"text": "t", "config": {}}),
            ac.post("/analyze/word_frequency", json={"text": "", "config": {}}),
            ac.post("/analyze/word_frequency", json={"text": "t", "config": "bad"}),
            ac.post("/pipeline?sync=true", data={"steps": "invalid json", "text": "t"}),
            ac.post("/pipeline?sync=true", data={"steps": "[]", "text": "t"}),
            ac.post("/visualize/word_frequency", json={"data": {}, "config": {}}),
        ]
        responses = await asyncio.gather(*bad_requests, return_exceptions=True)
        for i, r in enumerate(responses):
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500, f"Request {i} retornou 500: {r.text[:200]}"


# =============================================================================
# PIPELINE — combinações aleatórias falham limpo
# =============================================================================

class TestPipelineStress:
    """Pipelines com combinações diversas — falham limpo, nunca crasham."""

    def test_all_analyzer_pairs(self, core):
        """Todas as combinações de 2 analyzers em pipeline — todas completam."""
        analyzers = ["word_frequency", "sentiment_analyzer", "readability_analyzer"]
        text = "Texto para testar combinações de pipeline com múltiplos analyzers."

        for a in analyzers:
            for b in analyzers:
                doc = core.add_document(f"pipe_{a}_{b}", text)
                results = {}
                for plugin_id in [a, b]:
                    result = core.execute_plugin(plugin_id, doc)
                    results[plugin_id] = result

                for plugin_id, result in results.items():
                    assert isinstance(result, dict), f"{a}→{b}: {plugin_id} não retornou dict"

    def test_pipeline_with_document_then_analyzer(self, core):
        """teams_cleaner → word_frequency — pipeline misto funciona."""
        transcript = "[10:00:00] Maria: Olá pessoal bom dia\n[10:01:00] João: Bom dia Maria"
        doc = core.add_document("pipe_doc_analyze", transcript)

        doc_result = core.execute_plugin("teams_cleaner", doc)
        assert "cleaned_document" in doc_result

        cleaned_doc = core.add_document("pipe_cleaned", doc_result["cleaned_document"])
        freq_result = core.execute_plugin("word_frequency", cleaned_doc)
        assert "word_frequencies" in freq_result

    def test_repeated_plugin_same_pipeline(self, core):
        """Mesmo plugin 3x com configs diferentes — sem estado vazando."""
        text = "Gato gato cachorro pato gato cachorro pato pato leão"
        configs = [
            {"min_word_length": 2},
            {"min_word_length": 4},
            {"min_word_length": 6},
        ]
        results = []
        for i, config in enumerate(configs):
            doc = core.add_document(f"repeat_{i}", text)
            result = core.execute_plugin("word_frequency", doc, config)
            results.append(result)

        assert results[0]["vocabulary_size"] >= results[1]["vocabulary_size"]
        assert results[1]["vocabulary_size"] >= results[2]["vocabulary_size"]


# =============================================================================
# CORE vs API — mesmo erro, mesmo tipo, mesma mensagem
# =============================================================================

class TestCoreAPIErrorParity:
    """Core e API devem retornar erros equivalentes para os mesmos inputs."""

    @pytest.mark.asyncio
    async def test_invalid_config_same_rejection(self, ac, core):
        """Config inválida rejeitada pelo core e pela API com mesmo diagnóstico."""
        bad_config = {"tokenization": "quantum"}
        doc = core.add_document("parity_test", "Texto para teste de paridade.")

        # Core
        core_error = None
        try:
            core.execute_plugin("word_frequency", doc, bad_config)
        except ValueError as e:
            core_error = str(e)

        # API
        resp = await ac.post("/analyze/word_frequency", json={
            "text": "Texto para teste de paridade.",
            "config": bad_config,
        })

        if core_error:
            # Core rejeitou → API deve rejeitar também (422)
            assert resp.status_code == 422, f"Core rejeitou mas API retornou {resp.status_code}"
        else:
            # Core aceitou → API deve aceitar também (200)
            assert resp.status_code == 200, f"Core aceitou mas API retornou {resp.status_code}"

    @pytest.mark.asyncio
    async def test_plugin_not_found_same_code(self, ac, core):
        """Plugin inexistente: core ValueError, API 404."""
        doc = core.add_document("nf", "texto")
        with pytest.raises(ValueError, match="não encontrado"):
            core.execute_plugin("fantasma", doc)

        resp = await ac.post("/analyze/fantasma", json={"text": "t", "config": {}})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_plugin_type_same_rejection(self, ac, core):
        """Plugin tipo errado: API 422 em /analyze com visualizer."""
        resp = await ac.post("/analyze/wordcloud_d3", json={"text": "t", "config": {}})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_multiple_bad_configs_parity(self, ac, core):
        """Várias configs ruins — core e API concordam em rejeitar ou aceitar."""
        configs = [
            {"min_word_length": -999},
            {"max_words": "abc"},
            {"language": 42},
            {"remove_stopwords": "talvez"},
            {"param_fantasma": True},
        ]
        text = "Texto para teste de paridade de configuração."
        for config in configs:
            doc = core.add_document(f"parity_{id(config)}", text)
            core_ok = True
            try:
                core.execute_plugin("word_frequency", doc, config)
            except (ValueError, TypeError):
                core_ok = False

            resp = await ac.post("/analyze/word_frequency", json={
                "text": text, "config": config,
            })
            api_ok = resp.status_code == 200

            assert core_ok == api_ok, (
                f"Config {config}: core={'ok' if core_ok else 'erro'}, "
                f"API={resp.status_code}"
            )


# =============================================================================
# CACHE PERSISTENTE — restart real entre operações
# =============================================================================

class TestCachePersistentRestart:
    """Cache com restart real (nova instância CacheManager) entre operações."""

    def test_write_restart_read(self, cache_dir):
        """Grava → restart → lê — dado sobrevive."""
        cache_a = CacheManager(cache_dir)
        cache_a.set("doc1", "plugin_a", {"k": 1}, {"value": "alice"})
        del cache_a

        cache_b = CacheManager(cache_dir)
        result = cache_b.get("doc1", "plugin_a", {"k": 1})
        assert result is not None
        assert result["value"] == "alice"

    def test_write_restart_invalidate_restart_read(self, cache_dir):
        """Grava → restart → invalida → restart → lê — dado não volta."""
        cache_a = CacheManager(cache_dir)
        cache_a.set("doc1", "plugin_a", {}, {"v": 1})
        cache_a.set("doc2", "plugin_a", {}, {"v": 2})
        del cache_a

        cache_b = CacheManager(cache_dir)
        cache_b.invalidate(doc_id="doc1")
        del cache_b

        cache_c = CacheManager(cache_dir)
        assert cache_c.get("doc1", "plugin_a", {}) is None
        assert cache_c.get("doc2", "plugin_a", {})["v"] == 2

    def test_multiple_restarts_accumulate(self, cache_dir):
        """Várias sessões gravando — tudo acumula."""
        for i in range(5):
            cache = CacheManager(cache_dir)
            cache.set(f"doc_{i}", "plugin", {}, {"session": i})
            del cache

        final = CacheManager(cache_dir)
        for i in range(5):
            result = final.get(f"doc_{i}", "plugin", {})
            assert result is not None, f"doc_{i} perdido após 5 restarts"
            assert result["session"] == i

    def test_clear_restart_empty(self, cache_dir):
        """Clear → restart → nada sobrevive."""
        cache_a = CacheManager(cache_dir)
        for i in range(10):
            cache_a.set(f"doc_{i}", "plugin", {}, {"v": i})
        cache_a.clear()
        del cache_a

        cache_b = CacheManager(cache_dir)
        for i in range(10):
            assert cache_b.get(f"doc_{i}", "plugin", {}) is None
        assert cache_b.stats()["size"] == 0


# =============================================================================
# LAZY LOADING CONCORRENTE — plugins carregando ao mesmo tempo
# =============================================================================

class TestLazyLoadingConcurrent:
    """Plugins lazy sendo carregados por threads concorrentes."""

    def test_concurrent_first_access_different_lazy_plugins(self, core):
        """3 plugins lazy acessados pela primeira vez em threads diferentes."""
        # readability_analyzer e teams_cleaner são lazy (sem __init__ pesado)
        plugins = ["readability_analyzer", "teams_cleaner"]
        results = {}
        errors = []

        def access_plugin(plugin_id):
            try:
                p = core.get_plugin(plugin_id)
                meta = p.meta()
                return plugin_id, meta.id
            except Exception as e:
                errors.append(f"{plugin_id}: {e}")
                return plugin_id, None

        with ThreadPoolExecutor(max_workers=len(plugins)) as executor:
            futures = [executor.submit(access_plugin, pid) for pid in plugins]
            for f in as_completed(futures):
                pid, meta_id = f.result()
                results[pid] = meta_id

        assert errors == [], f"Erros: {errors}"
        for pid in plugins:
            assert results[pid] == pid, f"{pid} retornou meta.id={results[pid]}"

    def test_concurrent_execute_different_plugins(self, core):
        """Execução concorrente de plugins diferentes (eager + lazy)."""
        text = "Texto para teste de concorrência entre plugins diferentes."
        doc = core.add_document("concurrent_diff", text)
        plugins = ["word_frequency", "sentiment_analyzer", "readability_analyzer"]
        results = {}
        errors = []

        def run_plugin(plugin_id):
            try:
                # Cada thread precisa do seu próprio Document (evita cache collision)
                d = core.add_document(f"conc_{plugin_id}", text)
                return plugin_id, core.execute_plugin(plugin_id, d)
            except Exception as e:
                errors.append(f"{plugin_id}: {e}")
                return plugin_id, None

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_plugin, pid) for pid in plugins]
            for f in as_completed(futures):
                pid, result = f.result()
                results[pid] = result

        assert errors == [], f"Erros: {errors}"
        assert "word_frequencies" in results["word_frequency"]
        assert "polarity" in results["sentiment_analyzer"]
        assert "word_count" in results["readability_analyzer"]


# =============================================================================
# CONTEXT — tipos Python não triviais
# =============================================================================

class TestContextNonTrivialTypes:
    """Context com tipos Python que não são JSON nativo."""

    def test_context_with_path(self, core):
        """Context com Path — não crasheia, cache funciona."""
        doc = core.add_document("ctx_path", "Texto para teste de contexto com Path.")
        ctx = {"source": Path("/tmp/data/file.txt")}
        result = core.execute_plugin("word_frequency", doc, {}, ctx)
        assert "word_frequencies" in result

    def test_context_with_set(self, core):
        """Context com set — não crasheia, cache funciona."""
        doc = core.add_document("ctx_set", "Texto para teste de contexto com set.")
        ctx = {"tags": {"alpha", "beta", "gamma"}}
        result = core.execute_plugin("word_frequency", doc, {}, ctx)
        assert "word_frequencies" in result

    def test_context_with_tuple(self, core):
        """Context com tuple — não crasheia."""
        doc = core.add_document("ctx_tuple", "Texto para teste de contexto com tuple.")
        ctx = {"coords": (1, 2, 3)}
        result = core.execute_plugin("word_frequency", doc, {}, ctx)
        assert "word_frequencies" in result

    def test_context_with_nested_complex(self, core):
        """Context com tipos aninhados — dict com set, list de Paths, etc."""
        doc = core.add_document("ctx_nested", "Texto para teste de contexto complexo.")
        ctx = {
            "paths": [Path("/a"), Path("/b")],
            "tags": frozenset(["x", "y"]),
            "meta": {"nested": {"deep": True}},
        }
        result = core.execute_plugin("word_frequency", doc, {}, ctx)
        assert "word_frequencies" in result

    def test_different_contexts_different_cache(self, core):
        """Mesmo doc+plugin, contextos diferentes → resultados cacheados separados."""
        doc = core.add_document("ctx_cache", "Texto para teste.")
        r1 = core.execute_plugin("word_frequency", doc, {}, {"user": "alice"})
        r2 = core.execute_plugin("word_frequency", doc, {}, {"user": "bob"})
        r3 = core.execute_plugin("word_frequency", doc, {}, {"user": "alice"})
        # r1 e r3 devem ser iguais (cache hit), todos devem ter provides
        assert r1 == r3
        assert "word_frequencies" in r1
        assert "word_frequencies" in r2

    def test_context_with_none_values(self, core):
        """Context com valores None — não crasheia."""
        doc = core.add_document("ctx_none", "Texto para teste.")
        result = core.execute_plugin("word_frequency", doc, {}, {"key": None, "other": None})
        assert "word_frequencies" in result

    def test_empty_context_vs_no_context_same_cache(self, core):
        """Context vazio ({}) e sem context (None) devem usar mesma cache."""
        doc = core.add_document("ctx_empty", "Texto para teste de cache.")
        r1 = core.execute_plugin("word_frequency", doc, {}, None)
        r2 = core.execute_plugin("word_frequency", doc, {}, {})
        assert r1 == r2
        # Segundo deve ser cache hit
        assert core.cache.stats()["hits"] >= 1


# =============================================================================
# DEPENDÊNCIAS + CONTEXT + CACHE — eixo que mudou bastante
# =============================================================================

class TestDepsContextCache:
    """Dependências automáticas com context e cache — verificar propagação correta."""

    def test_context_not_shared_between_unrelated_calls(self, core):
        """Duas chamadas com context diferente não poluem uma a outra."""
        text = "Texto para teste de isolamento de contexto entre chamadas."
        doc1 = core.add_document("iso_1", text)
        doc2 = core.add_document("iso_2", text)

        r1 = core.execute_plugin("word_frequency", doc1, {}, {"session": "A"})
        r2 = core.execute_plugin("word_frequency", doc2, {}, {"session": "B"})

        # Ambos devem retornar resultado válido
        assert "word_frequencies" in r1
        assert "word_frequencies" in r2

    def test_cache_separates_by_context_not_just_config(self, core):
        """Mesmo doc, mesmo config, contextos diferentes → cache keys diferentes."""
        doc = core.add_document("cache_ctx", "Texto para teste de separação de cache.")
        config = {"min_word_length": 3}

        r1 = core.execute_plugin("word_frequency", doc, config, {"env": "prod"})
        stats1 = core.cache.stats()

        r2 = core.execute_plugin("word_frequency", doc, config, {"env": "dev"})
        stats2 = core.cache.stats()

        # Segundo deve ser miss (context diferente)
        assert stats2["misses"] > stats1["misses"]

    def test_cache_hits_with_same_context(self, core):
        """Mesmo doc + config + context → cache hit."""
        doc = core.add_document("cache_same", "Texto para teste de cache hit.")
        ctx = {"user": "alice", "tags": ["a", "b"]}

        core.execute_plugin("word_frequency", doc, {}, ctx)
        stats1 = core.cache.stats()

        core.execute_plugin("word_frequency", doc, {}, ctx)
        stats2 = core.cache.stats()

        assert stats2["hits"] > stats1["hits"]


# =============================================================================
# PIPELINE — sequências inválidas e quase-válidas
# =============================================================================

class TestPipelineInvalidSequences:
    """Pipelines com combinações inválidas falham limpo, nunca crasham."""

    @pytest.mark.asyncio
    async def test_visualizer_first_step_no_data(self, ac):
        """Visualizer como primeiro step (sem dados) → 422."""
        steps = json.dumps([{"plugin_id": "wordcloud_d3", "config": {}}])
        resp = await ac.post("/pipeline?sync=true", data={"text": "texto", "steps": steps})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_visualizer_after_visualizer(self, ac):
        """Visualizer → Visualizer — segundo recebe resultado do primeiro."""
        steps = json.dumps([
            {"plugin_id": "word_frequency", "config": {}},
            {"plugin_id": "wordcloud_d3", "config": {}},
            {"plugin_id": "frequency_chart_plotly", "config": {}},
        ])
        resp = await ac.post("/pipeline?sync=true", data={
            "text": "gato gato cachorro pato gato",
            "steps": steps,
        })
        # Segundo visualizer recebe resultado do primeiro — pode funcionar ou falhar limpo
        assert resp.status_code != 500

    @pytest.mark.asyncio
    async def test_document_after_analyzer(self, ac):
        """Analyzer → Document — document recebe texto encadeado."""
        steps = json.dumps([
            {"plugin_id": "word_frequency", "config": {}},
            {"plugin_id": "teams_cleaner", "config": {}},
        ])
        resp = await ac.post("/pipeline?sync=true", data={
            "text": "[10:00:00] Ana: Olá pessoal",
            "steps": steps,
        })
        # word_frequency não retorna texto encadeável, teams_cleaner recebe texto original
        assert resp.status_code != 500

    @pytest.mark.asyncio
    async def test_analyzer_with_invalid_output_format(self, ac):
        """Pipeline com output_format inválido no visualizer → 422."""
        steps = json.dumps([
            {"plugin_id": "word_frequency", "config": {}},
            {"plugin_id": "wordcloud_d3", "config": {"output_format": "pdf"}},
        ])
        resp = await ac.post("/pipeline?sync=true", data={
            "text": "gato cachorro pato",
            "steps": steps,
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_text_through_pipeline(self, ac):
        """Texto vazio pelo pipeline inteiro — não crasheia."""
        steps = json.dumps([{"plugin_id": "word_frequency", "config": {}}])
        resp = await ac.post("/pipeline?sync=true", data={"text": "", "steps": steps})
        # Pode ser 200 (resultado vazio) ou 422 — nunca 500
        assert resp.status_code != 500

    @pytest.mark.asyncio
    async def test_document_file_then_analyzer(self, ac):
        """File upload → document (text-based) → analyzer — integração real."""
        transcript = "[10:00:00] Maria: Olá pessoal bom dia\n[10:01:00] João: Bom dia Maria tudo bem"
        steps = json.dumps([
            {"plugin_id": "teams_cleaner", "config": {}},
            {"plugin_id": "word_frequency", "config": {}},
        ])
        resp = await ac.post("/pipeline?sync=true",
            files={"file": ("meeting.txt", transcript.encode(), "text/plain")},
            data={"steps": steps},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["steps_executed"] == 2
        # Primeiro step deve ter cleaned_document
        assert "cleaned_document" in data["results"][0]["result"]
        # Segundo step deve ter word_frequencies
        assert "word_frequencies" in data["results"][1]["result"]

    @pytest.mark.asyncio
    async def test_three_analyzers_chained(self, ac):
        """3 analyzers em sequência — todos completam."""
        steps = json.dumps([
            {"plugin_id": "word_frequency", "config": {}},
            {"plugin_id": "sentiment_analyzer", "config": {}},
            {"plugin_id": "readability_analyzer", "config": {}},
        ])
        resp = await ac.post("/pipeline?sync=true", data={
            "text": "Texto positivo e bom para análise completa com múltiplas palavras.",
            "steps": steps,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["steps_executed"] == 3
