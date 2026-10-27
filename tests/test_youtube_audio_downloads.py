import asyncio
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import api.miniapp_youtube as youtube
from api.miniapp_auth import current_user, TelegramUser
from api.miniapp_models import MiniAppYouTubeJob
from tests.test_knowledge_upload import request


def test_audio_files_are_owned_signed_seekable_and_expire(tmp_path,monkeypatch):
    root=tmp_path/'audio';job='a'*32;audio='b'*24
    (root/job).mkdir(parents=True);path=root/job/(audio+'.mp3');path.write_bytes(b'ID3'+b'x'*1000)
    monkeypatch.setattr(youtube,'AUDIO_ROOT',root)
    monkeypatch.setattr(youtube,'get_settings',lambda:SimpleNamespace(telegram_bot_token='123:test'))
    async def run():
        engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "files.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(MiniAppYouTubeJob.__table__.create)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        monkeypatch.setattr(youtube,'SessionLocal',sessions)
        async with sessions() as session:
            session.add(MiniAppYouTubeJob(id=job,user_id=42,url='https://youtu.be/abcdefghijk',status='completed',
                tracks=[{'artist':'DJ','title':'Private track','audio':{'id':audio,'status':'ready','filename':'DJ — Track.mp3'}}]))
            await session.commit()
        identity=[TelegramUser(99,'Other')]
        app=FastAPI();app.include_router(youtube.router)
        app.dependency_overrides[current_user]=lambda:identity[0]
        route=f'/miniapp-api/youtube/jobs/{job}/audio/{audio}/download'
        assert (await request(app,'POST',route))[0]==404
        identity[0]=TelegramUser(42,'Owner')
        status,body=await request(app,'POST',route);assert status==200
        ticket=json.loads(body)
        status,body=await request(app,'GET',ticket['url'],headers={'Range':'bytes=0-9'})
        assert status==206 and body==path.read_bytes()[:10]
        assert (await request(app,'HEAD',ticket['url']))[0]==200
        assert (await request(app,'GET',ticket['url']+'x'))[0]==403
        expired=int(time.time())-1
        old=f'/miniapp-api/youtube/files/{job}/{audio}?expires={expired}&signature={youtube.download_signature(job,audio,expired)}'
        assert (await request(app,'GET',old))[0]==403
        app.state.youtube_tasks={};app.state.youtube_lock=asyncio.Lock();app.state.youtube_limits={}
        monkeypatch.setattr(youtube,'engine_paths',lambda:(tmp_path,tmp_path/'python'))
        calls=[]
        async def fake_worker(app,job_id,url,audio_only=False):
            calls.append(audio_only);app.state.youtube_tasks.pop(job_id,None)
        monkeypatch.setattr(youtube,'analyze_worker',fake_worker)
        identity[0]=TelegramUser(99,'Other')
        assert (await request(app,'POST',f'/miniapp-api/youtube/jobs/{job}/audio'))[0]==404
        identity[0]=TelegramUser(42,'Owner')
        assert (await request(app,'POST',f'/miniapp-api/youtube/jobs/{job}/audio'))[0]==202
        await asyncio.sleep(0)
        assert calls==[True]
        path.unlink()
        assert (await request(app,'POST',route))[0]==410
        async with sessions() as session:
            row=await session.get(MiniAppYouTubeJob,job)
            assert youtube.serialize(row)['tracks'][0]['audio']['status']=='expired'
        await engine.dispose()
    asyncio.run(run())
