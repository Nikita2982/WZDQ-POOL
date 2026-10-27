import io
import asyncio
import urllib.error
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.run_telegram_miniapp import check_public_app, ensure_menu_current, external_origin, tunnel_command, tunnel_origin


def test_external_origin_requires_https_without_paths_or_credentials():
    assert external_origin("https://wzdq.example.ts.net/") == "https://wzdq.example.ts.net"
    for value in ["", "http://example.com", "https://user:pass@example.com", "https://example.com/app/",
                  "https://example.com?token=secret", "https://example.com#fragment", "https://example.com:8082"]:
        with pytest.raises(ValueError):
            external_origin(value)


def test_tunnel_address_is_read_from_startup_and_rotation_messages():
    assert tunnel_origin("domain.lhr.life tunneled, https://abc123.lhr.life\r\n") == "https://abc123.lhr.life"
    assert tunnel_origin("new address: https://new456.lhr.life") == "https://new456.lhr.life"
    assert tunnel_origin("https://localhost.run/docs/") is None
    assert tunnel_origin("https://abc.lhr.life.example.com") is None
    assert tunnel_origin("https://test-1.free.pinggy.net\n") == "https://test-1.free.pinggy.net"
    assert tunnel_origin("https://test-1.run.pinggy-free.link") == "https://test-1.run.pinggy-free.link"
    assert tunnel_origin("https://test.free.pinggy.net.evil.example") is None


def test_pinggy_uses_a_separate_key_and_local_api_on_ssh_port_443():
    command = tunnel_command(8082, "pinggy")
    assert command[command.index("-p") + 1] == "443"
    assert command[command.index("-R") + 1] == "0:127.0.0.1:8082"
    assert command[-1] == "free.pinggy.io"
    assert command[command.index("-i") + 1].endswith(".sessions/miniapp_tunnel_ed25519")
    with pytest.raises(ValueError):
        tunnel_command(8082, "unknown")


def test_reset_default_menu_is_repaired_without_rewriting_current_admin_menu(monkeypatch):
    url = "https://test.free.pinggy.net/app/"
    bot = SimpleNamespace(get_chat_menu_button=AsyncMock(side_effect=[
        SimpleNamespace(type="commands"),
        SimpleNamespace(type="web_app", text="Открыть приложение", web_app=SimpleNamespace(url=url)),
    ]), set_chat_menu_button=AsyncMock())
    monkeypatch.setattr("scripts.run_telegram_miniapp.get_menu", bot.get_chat_menu_button)
    setter = AsyncMock()
    monkeypatch.setattr("scripts.run_telegram_miniapp.set_menu", setter)
    asyncio.run(ensure_menu_current(bot, [None, 42], url))
    assert setter.call_count == 1
    assert setter.call_args.args[1] is None
    assert setter.call_args.args[2].web_app.url == url


def test_probe_detects_no_tunnel_even_when_status_is_200(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(b"no tunnel"))
    with pytest.raises(ConnectionError):
        check_public_app("https://example.lhr.life")


def test_probe_requires_app_page_and_protected_catalogue(monkeypatch):
    probes=[]
    def protected(url, **kwargs):
        probes.append(url)
        if "/miniapp-api/" in url.full_url:
            raise urllib.error.HTTPError(url.full_url, 401, "Unauthorized", {}, None)
        return io.BytesIO(b'<script src="telegram-web-app.js"></script>')
    monkeypatch.setattr("urllib.request.urlopen", protected)
    check_public_app("https://example.lhr.life")
    assert [probe.get_method() for probe in probes]==['GET','GET','POST']
    assert all('Mozilla' in probe.get_header('User-agent') for probe in probes)
    assert probes[-1].data==b'{}'
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(b"telegram-web-app.js"))
    with pytest.raises(RuntimeError):
        check_public_app("https://example.lhr.life")
