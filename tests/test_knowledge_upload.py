import asyncio
import json
import subprocess
import pytest
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.miniapp_auth import TelegramUser, current_user
from api.miniapp_models import MiniAppKnowledgeVideo
import api.miniapp_knowledge as library


async def request(app,method,path,body=b'',headers=None):
    url=urlsplit(path)
    messages=[]
    async def receive():
        return {'type':'http.request','body':body,'more_body':False}
    async def send(message): messages.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
           'scheme':'http','path':url.path,'raw_path':url.path.encode(),'query_string':url.query.encode(),
           'headers':[(k.lower().encode(),v.encode()) for k,v in (headers or {}).items()],
           'client':('127.0.0.1',42),'server':('testserver',80)}
    await app(scope,receive,send)
    status=next(m['status'] for m in messages if m['type']=='http.response.start')
    result=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
    return status,result


@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_owner_upload_streaming_privacy_validation_and_cleanup(tmp_path,monkeypatch,codec):
    clip=tmp_path/'test.mp4'
    encoding=['-c:v','libx264'] if codec=='h264' else ['-c:v','libx265','-preset','ultrafast','-x265-params','pools=1:frame-threads=1:log-level=error','-tag:v','hvc1']
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                    'color=c=black:s=160x90:d=1',*encoding,'-pix_fmt','yuv420p',
                    '-movflags','+faststart',str(clip)],check=True)
    content=clip.read_bytes()
    media=tmp_path/'media'
    catalog=tmp_path/'catalog.json';catalog.write_text('{"videos":[]}')
    monkeypatch.setattr(library,'MEDIA_ROOT',media)
    monkeypatch.setattr(library,'CATALOG',catalog)
    monkeypatch.setattr(library,'get_settings',lambda:SimpleNamespace(
        miniapp_local=False,admin_user_ids={42},telegram_bot_token='123:test'))

    async def run():
        engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "uploads.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(MiniAppKnowledgeVideo.__table__.create)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        monkeypatch.setattr(library,'SessionLocal',sessions)
        app=FastAPI();app.include_router(library.router)
        identity=[TelegramUser(43,'Member')]
        app.dependency_overrides[current_user]=lambda:identity[0]
        status,_=await request(app,'POST','/miniapp-api/knowledge/videos?title=Lesson',content)
        assert status==403 and not media.exists()
        assert json.loads((await request(app,'GET','/miniapp-api/knowledge'))[1])['can_upload'] is False
        identity[0]=TelegramUser(42,'Owner')
        for title,body,expected in [('Lesson',b'',422),('Lesson',b'not video',422),('%20%20',content,422)]:
            assert (await request(app,'POST','/miniapp-api/knowledge/videos?title='+title,body))[0]==expected
        monkeypatch.setattr(library,'MAX_UPLOAD_BYTES',10)
        assert (await request(app,'POST','/miniapp-api/knowledge/videos?title=Lesson',content))[0]==413
        assert not list(media.iterdir())
        monkeypatch.setattr(library,'MAX_UPLOAD_BYTES',500*1024*1024)
        status,body=await request(app,'POST','/miniapp-api/knowledge/videos?title=Uploaded%20Lesson',content)
        assert status==201
        video_id=json.loads(body)['id']
        identity[0]=TelegramUser(43,'Member')
        data=json.loads((await request(app,'GET','/miniapp-api/knowledge'))[1])
        assert not data['can_upload'] and data['videos'][0]['title']=='Uploaded Lesson'
        video=data['videos'][0]
        assert video['uploaded'] and video['thumbnail_url']
        status,body=await request(app,'GET',video['url'],headers={'Range':'bytes=0-99'})
        assert status==206 and body==(media / (video_id+'.mp4')).read_bytes()[:100]
        assert (await library.inspect_video(media / (video_id+'.mp4')))[2] is False
        assert clip.read_bytes()==content
        assert (await request(app,'GET',f'/miniapp-api/knowledge/videos/{video_id}/video'))[0]==403
        assert (await request(app,'GET',video['url']+'broken'))[0]==403
        assert (await request(app,'GET',video['thumbnail_url']))[0]==200
        async with sessions() as session:
            rows=(await session.scalars(select(MiniAppKnowledgeVideo))).all()
            assert len(rows)==1 and rows[0].uploaded_by==42
        assert not list(media.glob('*.part'))
        await engine.dispose()
    asyncio.run(run())
