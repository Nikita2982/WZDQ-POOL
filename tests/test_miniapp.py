"""Local app integration checks use a temporary database and never contact Telegram."""
import hashlib
import asyncio
import hmac
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.miniapp_auth import validate_init_data
from database.models import Base, Track


def signed_data(token="123:test", now=1000, user=None, **extra):
    data = {"auth_date": str(now), "user": json.dumps(user or {"id": 42, "first_name": "DJ"}), **extra}
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_telegram_auth_validates_signature_and_optional_signature_field():
    user = validate_init_data(signed_data(signature="telegram-ed25519"), "123:test", now=1000)
    assert user.id == 42


@pytest.mark.parametrize("raw,token,now", [
    (signed_data() + "&auth_date=1000", "123:test", 1000),
    (signed_data(), "456:wrong", 1000),
    (signed_data(), "123:test", 5000),
    (signed_data(), "123:test", 900),
    (signed_data(user={"id": -1}), "123:test", 1000),
    (signed_data(user={"id": True}), "123:test", 1000),
    ("user=broken", "123:test", 1000),
])
def test_telegram_auth_rejects_invalid_data(raw, token, now):
    with pytest.raises(HTTPException) as exc:
        validate_init_data(raw, token, now=now)
    assert exc.value.status_code == 401


@pytest.fixture(scope="module")
def local_app(tmp_path_factory):
    directory = tmp_path_factory.mktemp("miniapp")
    db = directory / "app.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for genre in ("electronic", "house", "rap"):
            for i in range(65):
                session.add(Track(telegram_message_id=i, telegram_channel_id=genre, genre=genre,
                                  title=f"Test Track {i}", artist="Test DJ", duration_sec=240,
                                  bpm=112 if genre == "rap" else 124, camelot_key="8A", energy_level=.5))
        session.commit()
    engine.dispose()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "MINIAPP_LOCAL": "true", "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "TELEGRAM_BOT_TOKEN": "123456:test", "TELEGRAM_API_ID": "1234",
           "TELEGRAM_API_HASH": "test", "SOURCE_CHAT": "test"}
    project = directory / "youtube-engine"
    (project / ".venv-shazam/bin").mkdir(parents=True)
    (project / ".venv-shazam/bin/python").symlink_to(sys.executable)
    package = project / "setlist_bot"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text("from types import SimpleNamespace\nclass Settings:\n @staticmethod\n def load(): return SimpleNamespace(max_duration=10800, step=30, youtube_proxy=None, cookies=None, published_search=True, comments_limit=40, max_requests=360)\n")
    (package / "core.py").write_text("from dataclasses import dataclass\nclass AnalysisError(Exception): pass\ndef youtube_url(url): return url\ndef timestamp(offset): return f'{offset//3600:02}:{offset//60%60:02}:{offset%60:02}'\n@dataclass\nclass Match:\n artist: str\n title: str\n offset: int | None = None\n @property\n def key(self): return (self.artist.casefold(),self.title.casefold())\ndef render(title,url,matches,*args,warning='',note=''):\n unique={m.key:m for m in matches}\n return '🎧 '+title+'\\n'+ '\\n'.join(f'{i:02} · {m.artist} — {m.title}  [{timestamp(m.offset)}]' for i,m in enumerate(unique.values(),1))+'\\n'+note+warning\n")
    (package / "tracklist_search.py").write_text("class SearchResult:\n def __init__(self): self.matches=[]\n")
    (package / "analyzer.py").write_text("import asyncio,json,sys\nfrom pathlib import Path\nfrom .core import Match\nfrom .tracklist_search import SearchResult\nasync def command(*args,**kwargs): return json.dumps({'title':'Test set','duration':60})\nasync def find_published(metadata,url,progress):\n result=SearchResult()\n result.matches=[Match('Artist A','First',30),Match('Artist C','Published',45)]\n return result\nasync def download_audio(args,progress):\n Path(args[args.index('-o')+1].replace('%(ext)s','m4a')).touch()\nasync def scan_audio(audio,duration,settings,progress):\n await progress('Проверено 1/2 фрагментов.\\n\\nПоследние найденные:\\n• Artist A — First')\n await asyncio.sleep(1.5)\n await progress('Проверено 2/2 фрагментов.\\n\\nПоследние найденные:\\n• Artist B — Second')\n return [Match('Artist A','First',30),Match('Artist B','Second',60)],[],2,0,0,''\n")
    (package / "audio_quality.py").write_text("def quality_caption(audio): return 'MP3 · тестовый источник'\n")
    (package / "audio_search.py").write_text("import asyncio\nfrom types import SimpleNamespace\nasync def find_audio(track,settings,directory,progress):\n await asyncio.sleep(.1)\n if track.artist=='Artist C': return None\n await progress('Скачиваю…')\n path=directory/'track.mp3'\n path.write_bytes(b'ID3'+b'x'*1500)\n return SimpleNamespace(path=path)\n")
    env["MINIAPP_YOUTUBE_AUDIO_DIR"] = str(directory / "audio-cache")
    env["YOUTUBE_SETLIST_PROJECT"] = str(project)
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.miniapp_app:create_app", "--factory",
                                "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers"],
                               cwd=Path(__file__).resolve().parents[1], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw.decode()
        return response.status, data
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail("Local app failed to start")
            try:
                if request("GET", "/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(.05)
        else:
            pytest.fail("Local app did not become ready")
        yield request
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_local_app_generates_saves_repeats_and_favorites(local_app):
    code, bootstrap = local_app("GET", "/miniapp-api/bootstrap")
    assert code == 200 and bootstrap["local"] is True
    assert bootstrap["user"]["id"] == 0
    code, first = local_app("POST", "/miniapp-api/sets", {"genre": "house", "duration": 30})
    assert code == 201 and len(first["tracks"]) == 15
    assert first["total_duration_sec"] == 1800
    code, second = local_app("POST", "/miniapp-api/sets", {
        "genre": "house", "duration": 30, "previous_set_id": first["id"]})
    assert code == 201
    assert not {t["id"] for t in first["tracks"]} & {t["id"] for t in second["tracks"]}
    code, favorite = local_app("PATCH", f'/miniapp-api/sets/{first["id"]}/favorite', {"favorite": True})
    assert code == 200 and favorite["favorite"] is True
    code, history = local_app("GET", "/miniapp-api/sets")
    assert code == 200 and len(history) == 2
    assert any(row["id"] == first["id"] and row["favorite"] for row in history)
    assert local_app("POST", f'/miniapp-api/sets/{first["id"]}/deliver')[0] == 403


def test_local_app_filters_rap_and_validates_parameters(local_app):
    assert local_app("POST", "/miniapp-api/sets", {"genre": "rap", "duration": 30})[0] == 422
    assert local_app("POST", "/miniapp-api/sets", {"genre": "house", "duration": 1})[0] == 422
    code, row = local_app("POST", "/miniapp-api/sets", {"genre": "rap", "duration": 30, "bpm_bucket": "mid"})
    assert code == 201 and all(107 <= track["bpm"] <= 117 for track in row["tracks"])
    assert local_app("POST", "/miniapp-api/sets", {"genre": "rap", "duration": 30, "bpm_bucket": "mid_high"})[0] == 409


def test_local_app_rejects_remote_host_invalid_auth_and_missing_sets(local_app):
    assert local_app("GET", "/miniapp-api/bootstrap", headers={"Host": "remote.example"})[0] == 403
    assert local_app("GET", "/miniapp-api/bootstrap", headers={"Authorization": "tma invalid"})[0] == 401
    assert local_app("GET", "/miniapp-api/sets/missing")[0] == 404
    assert local_app("GET", "/app/")[0] == 200
    assert local_app("POST", "/admin/scan")[0] == 404


def test_catalogue_filters_paginates_and_preserves_titles(local_app):
    code, page = local_app("GET", "/miniapp-api/tracks?genre=rap&bpm_min=110&bpm_max=115&key=8A&limit=20")
    assert code == 200 and page["total"] == 65 and len(page["tracks"]) == 20
    assert all(t["genre"] == "rap" and t["bpm"] == 112 for t in page["tracks"])
    _, next_page = local_app("GET", "/miniapp-api/tracks?genre=rap&offset=20&limit=20")
    assert not {t["id"] for t in page["tracks"]} & {t["id"] for t in next_page["tracks"]}
    code, found = local_app("GET", "/miniapp-api/tracks?q=Test%20Track%2064&genre=house")
    assert code == 200 and found["total"] == 1
    assert found["tracks"][0]["title"] == "Test Track 64"
    _, empty = local_app("GET", "/miniapp-api/tracks?q=%25")
    assert empty["total"] == 0
    assert local_app("GET", "/miniapp-api/tracks?bpm_min=150&bpm_max=70")[0] == 422
    assert local_app("GET", "/miniapp-api/tracks?limit=1000")[0] == 422
    assert local_app("GET", "/miniapp-api/tracks?key=13A")[0] == 422
    assert local_app("GET", "/miniapp-api/tracks", headers={"Host": "remote.example"})[0] == 403


def test_remote_auth_requires_signed_user_and_pool_membership(monkeypatch):
    from types import SimpleNamespace
    from starlette.requests import Request
    import api.miniapp_auth as auth
    from subscription import SubscriptionCheckError
    settings = SimpleNamespace(miniapp_local=False, telegram_bot_token="123:test", miniapp_auth_max_age=3600)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                       "app": SimpleNamespace(state=SimpleNamespace(miniapp_bot=object()))})
    calls = []
    async def subscribed(bot, user_id):
        calls.append(user_id)
        return True
    monkeypatch.setattr(auth, "is_subscribed", subscribed)
    raw = signed_data(now=int(time.time()))
    user = asyncio.run(auth.current_user(request, "tma " + raw))
    assert user.id == 42 and calls == [42]
    for value in ("", "tma invalid"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth.current_user(request, value))
        assert exc.value.status_code == 401
    assert calls == [42]
    async def denied(bot, user_id):
        return False
    monkeypatch.setattr(auth, "is_subscribed", denied)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.current_user(request, "tma " + raw))
    assert exc.value.status_code == 403
    async def unavailable(bot, user_id):
        raise SubscriptionCheckError
    monkeypatch.setattr(auth, "is_subscribed", unavailable)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.current_user(request, "tma " + raw))
    assert exc.value.status_code == 503


def test_sets_are_private_between_pool_members():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from api.miniapp import owned_set
    row = SimpleNamespace(id="private-set", user_id=42)
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    assert asyncio.run(owned_set(session, "private-set", 42)) is row
    with pytest.raises(HTTPException) as exc:
        asyncio.run(owned_set(session, "private-set", 99))
    assert exc.value.status_code == 404
