"""Static guards for nginx routing, DNS refresh, uploads, and WebSocket."""
from pathlib import Path
import re

CONF = Path(__file__).resolve().parents[1] / "web/nginx.conf"


def test_listens_on_7700():
    assert re.search(r"listen\s+7700\s*;", CONF.read_text())


def test_api_proxy_survives_api_container_recreate():
    text = CONF.read_text()
    assert re.search(r"resolver\s+127\.0\.0\.11\b", text)
    variable = re.search(r"set\s+(\$\w+)\s+http://api:7701\s*;", text)
    assert variable
    assert re.search(r"proxy_pass\s+" + re.escape(variable[1]) + r"\s*;", text)


def test_api_proxy_passes_websocket_upgrade():
    text = CONF.read_text()
    assert "proxy_http_version 1.1;" in text
    assert "proxy_set_header Upgrade $http_upgrade;" in text
    assert re.search(r"proxy_set_header\s+Connection\s+\$\w+;", text)


def test_upload_limit_allows_enrollment_photos_and_csv():
    limit = re.search(r"client_max_body_size\s+(\d+)m;", CONF.read_text())
    assert limit and int(limit[1]) >= 20


def test_spa_fallback():
    assert "try_files $uri /index.html;" in CONF.read_text()
