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
        # All existing plugins should have heavy: false
        for plugin in plugins:
            assert "heavy" in plugin
            assert plugin["heavy"] is False
