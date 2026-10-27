import asyncio
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import api.miniapp_knowledge as library
from api.miniapp_auth import TelegramUser
from tests.test_miniapp import local_app


def test_knowledge_initially_empty(local_app):
    code,data=local_app('GET','/miniapp-api/knowledge')
    assert code==200 and data['videos']==[] and data['can_upload'] is False
    assert local_app('POST','/miniapp-api/knowledge/videos?title=Test',{'user_id':42})[0]==403
    assert local_app('GET','/miniapp-api/knowledge',headers={'Host':'remote.example'})[0] == 403


def test_curated_catalog_and_invalid_catalog(tmp_path,monkeypatch):
    catalog=tmp_path/'catalog.json'
    monkeypatch.setattr(library,'CATALOG',catalog)
    video={'id':'mixing-basics','title':'Основы сведения','url':'https://www.youtube.com/watch?v=r6p1mQxOhLU'}
    catalog.write_text(json.dumps({'videos':[video]}))
    result=library.read_catalog()
    assert result[0].title=='Основы сведения'
    assert result[0].category=='Уроки'
    catalog.write_text(json.dumps({'videos':[video,video]}))
    with pytest.raises(HTTPException) as error:
        library.read_catalog()
    assert error.value.status_code==503
    catalog.write_text('broken')
    with pytest.raises(HTTPException):
        library.read_catalog()


@pytest.mark.parametrize('url',['javascript:alert(1)','http://example.com/a.mp4','https://user:password@example.com/a.mp4'])
def test_knowledge_rejects_unsafe_video_links(url):
    with pytest.raises(ValidationError):
        library.KnowledgeVideo(id='one',title='Урок',url=url)
