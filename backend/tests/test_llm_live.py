"""Opt-in contract check; default local suites never call a live endpoint."""
from io import BytesIO

from PIL import Image
import pytest

from app.core.config import settings
from app.services.llm_client import chat, image_part, slot, text_part


@pytest.mark.llm
@pytest.mark.skipif(not settings.llm_api_url, reason="LLM_API_URL is empty")
def test_live_multimodal_contract(monkeypatch):
    # The general suite blocks TCP. Only an explicitly configured contract run opts in.
    import socket
    import _socket
    monkeypatch.setattr(socket.socket, "connect", _socket.socket.connect)
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, format="JPEG")
    with slot():
        result = chat([{"role": "user", "content": [text_part("Sebut warna gambar ini."), image_part(buffer.getvalue())]}],
                      timeout=settings.llm_timeout_ask_s)
    assert result.text.strip()
