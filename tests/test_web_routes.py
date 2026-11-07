"""안드로이드 앱 준비 경로 검증: manifest, 아이콘, 개인정보처리방침, assetlinks (실제 Gradio 서버에 붙여 확인)."""
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import web_routes  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    fastapi_app, _, _ = app.demo.launch(server_name="127.0.0.1", server_port=port, pwa=True,
                                        favicon_path=str(ROOT / "static" / "icon-192.png"),
                                        prevent_thread_lock=True, quiet=True)
    web_routes.install(fastapi_app)
    yield f"http://127.0.0.1:{port}"
    app.demo.close()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""


def test_manifest_overrides_gradio(base):
    status, ctype, body = _get(base + "/manifest.json")
    m = json.loads(body)
    assert status == 200 and "manifest+json" in ctype
    assert m["name"] == "고지서 쉽게 보기" and m["start_url"] == "/?app=1" and m["display"] == "standalone"
    assert {"maskable", "any"} == {i["purpose"] for i in m["icons"]}


@pytest.mark.parametrize("name, size", [("icon-192.png", (192, 192)), ("icon-512.png", (512, 512)),
                                        ("icon-maskable-512.png", (512, 512))])
def test_icons(base, name, size):
    status, ctype, body = _get(base + "/app-static/" + name)
    assert status == 200 and ctype == "image/png"
    assert (ROOT / "static" / name).read_bytes() == body and Image.open(ROOT / "static" / name).size == size


def test_static_whitelist(base):
    assert _get(base + "/app-static/..%2Fapp.py")[0] == 404
    assert _get(base + "/app-static/secret.txt")[0] == 404


def test_privacy_page(base, monkeypatch):
    monkeypatch.setenv("PRIVACY_CONTACT", "help@example.com")
    status, ctype, body = _get(base + "/privacy")
    page = body.decode("utf-8")
    assert status == 200 and "text/html" in ctype
    for text in ["개인정보처리방침", "Anthropic", "Hugging Face", "국외 이전", "정부·공공기관이 운영하는 서비스가 아닙니다",
                 "IP 주소", "만 14세", "help@example.com"]:
        assert text in page


def test_assetlinks_off_until_configured(base, monkeypatch):
    monkeypatch.delenv("ANDROID_PACKAGE", raising=False)
    monkeypatch.delenv("ANDROID_SHA256", raising=False)
    assert _get(base + "/.well-known/assetlinks.json")[0] == 404
    monkeypatch.setenv("ANDROID_PACKAGE", "io.github.sangmoo.easynotice")
    monkeypatch.setenv("ANDROID_SHA256", "aa:bb:cc, DD:EE:FF")
    status, _, body = _get(base + "/.well-known/assetlinks.json")
    data = json.loads(body)
    assert status == 200
    assert data[0]["target"]["package_name"] == "io.github.sangmoo.easynotice"
    assert data[0]["target"]["sha256_cert_fingerprints"] == ["AA:BB:CC", "DD:EE:FF"]


def test_gradio_page_still_served(base):
    status, ctype, body = _get(base + "/")
    assert status == 200 and "text/html" in ctype and b"manifest" in body


def test_privacy_defaults_operator(monkeypatch):
    monkeypatch.delenv("PRIVACY_OPERATOR", raising=False)
    monkeypatch.delenv("PRIVACY_CONTACT", raising=False)
    page = web_routes.privacy_html()
    assert "운영자: 전상문" in page and 'href="mailto:cossack275@gmail.com"' in page
