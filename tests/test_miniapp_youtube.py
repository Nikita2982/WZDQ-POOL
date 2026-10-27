import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.miniapp_youtube import normalize_url, owned_job
from scripts.miniapp_youtube_worker import report_tracks
from tests.test_miniapp import local_app


@pytest.mark.parametrize('url', [
    'https://youtu.be/abcdefghijk?si=share',
    'https://www.youtube.com/watch?v=abcdefghijk&t=30',
    'https://m.youtube.com/live/abcdefghijk',
    'https://youtube.com/embed/abcdefghijk',
])
def test_video_urls_are_canonical(url):
    assert normalize_url(url) == 'https://www.youtube.com/watch?v=abcdefghijk'


@pytest.mark.parametrize('url', [
    'http://localhost/a', 'https://youtube.com.evil.test/watch?v=abcdefghijk',
    'https://user@youtube.com/watch?v=abcdefghijk',
    'https://youtube.com:443/watch?v=abcdefghijk',
    'https://youtube.com/watch?v=short', 'file:///etc/passwd',
])
def test_invalid_or_untrusted_urls_rejected(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_report_tracks_keeps_real_timestamps_and_published_tracks():
    assert report_tracks('🎧 Title\n01 · Artist — Track  [00:01:30]\n02 · Other — Song\nПримечание') == [
        {'artist':'Artist', 'title':'Track', 'timestamp':'00:01:30'},
        {'artist':'Other', 'title':'Song', 'timestamp':None}]


def test_youtube_jobs_private():
    row = SimpleNamespace(user_id=42)
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    assert asyncio.run(owned_job(session, 'id', 42)) is row
    with pytest.raises(HTTPException) as error:
        asyncio.run(owned_job(session, 'id', 99))
    assert error.value.status_code == 404


def test_analysis_streams_tracks_and_persists_report(local_app):
    root = '/miniapp-api/youtube/jobs'
    assert local_app('POST', root, {'url':'https://evil.test/video'})[0] == 422
    code, job = local_app('POST', root, {'url':'https://youtu.be/abcdefghijk'})
    assert code == 202 and job['status'] == 'running'
    assert local_app('POST', root, {'url':'https://youtu.be/abcdefghijk'})[0] == 409
    saw_partial = False
    for _ in range(100):
        code, row = local_app('GET', root+'/'+job['id'])
        assert code == 200
        saw_partial |= row['status']=='running' and len(row['tracks']) == 2
        if row['status'] != 'running':
            break
        time.sleep(.05)
    assert saw_partial
    assert row['status'] == 'completed' and len(row['tracks']) == 3
    assert row['tracks'][0]['timestamp'] == '00:00:30'
    assert row['title'] == 'Test set' and 'Artist B' in row['report']
    audio=[track['audio'] for track in row['tracks']]
    assert [item['status'] for item in audio].count('ready')==2
    assert [item['status'] for item in audio].count('missing')==1
    ready=next(item for item in audio if item['status']=='ready')
    code,ticket=local_app('POST',root+'/'+job['id']+'/audio/'+ready['id']+'/download')
    assert code==200 and ticket['filename'].endswith('.mp3')
    code,download=local_app('GET',ticket['url'])
    assert code==200 and download.startswith('ID3')
    assert local_app('GET',ticket['url']+'broken')[0]==403

    assert local_app('GET',root)[1][0]['id'] == job['id']
    assert local_app('POST',root+'/'+job['id']+'/send')[0] == 403
    assert local_app('GET',root+'/missing')[0] == 404


@pytest.fixture
def cancel_app(tmp_path_factory):
    yield from local_app.__wrapped__(tmp_path_factory)


def test_cancel_stops_analysis_and_preserves_discoveries(cancel_app):
    root = '/miniapp-api/youtube/jobs'
    code, job = cancel_app('POST', root, {'url':'https://youtu.be/abcdefghijk'})
    assert code == 202
    path = root+'/'+job['id']
    for _ in range(100):
        row = cancel_app('GET', path)[1]
        if row['tracks']:
            break
        time.sleep(.02)
    assert len(row['tracks']) == 2 and row['status'] == 'running'
    assert cancel_app('POST',path+'/cancel')[0] == 200
    time.sleep(.2)
    row = cancel_app('GET',path)[1]
    assert row['status'] == 'cancelled' and len(row['tracks']) == 2
    time.sleep(1.5)
    assert cancel_app('GET',path)[1]['status'] == 'cancelled'
