from pathlib import Path
from urllib.request import urlopen

from recoverhand_host.desktop.particle_hand import ParticleAssetServer


def test_particle_asset_server_is_loopback_and_serves_embed_mode() -> None:
    assets = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "recoverhand_host"
        / "desktop"
        / "assets"
        / "particle_hand"
    )
    server = ParticleAssetServer(assets)
    try:
        url = server.start().toString()
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/renderer.html?embed=recoverhand")
        with urlopen(url, timeout=2.0) as response:
            renderer = response.read().decode("utf-8")
        assert "recoverhand-embed" in renderer
        assert "window.particleHand" in renderer
        assert "window.RECOVERHAND_EMBED_PROFILE" in renderer
        assert "maxDevicePixelRatio: 1" in renderer
        assert "antialias: !EMBED_MODE" in renderer
        assert "preserveDrawingBuffer: !EMBED_MODE" in renderer
        assert "useHdrTargets: false" in renderer
        assert "bloomPasses: 1" in renderer
    finally:
        server.stop()
