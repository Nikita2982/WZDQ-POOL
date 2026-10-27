import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.miniapp_models import Base, MiniAppMember, MiniAppSet
from api.miniapp_profile import profile_data, remember_member
from api.miniapp_auth import TelegramUser
from tests.test_miniapp import local_app


def test_profile_ranking_counts_all_sets_and_shares_only_name_and_count(tmp_path):
    async def run():
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "profile.db"}')
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            for uid, name, count in ((42,'DJ Me',105),(99,'DJ One',110),(100,'DJ Two',110),(0,'LOCAL',200)):
                await remember_member(session,TelegramUser(uid,name))
                for i in range(count):
                    session.add(MiniAppSet(id=f'{uid}-{i}',user_id=uid,genre='house',duration=30,
                        tracks=[{'title':'Private song'}],total_duration_sec=1800,
                        actual_duration_sec=2400,favorite=i<10))
            await session.commit()
            data = await profile_data(session,42)
            assert data['stats'] == {'generations':105,'minutes':3150,'favorites':10,'favorite_genre':'house'}
            assert [r['rank'] for r in data['leaderboard']] == [1,1,3]
            assert data['me']['rank'] == 3 and data['me']['is_me'] is True
            assert data['participants'] == 3
            assert all(set(r)=={'name','generations','rank','is_me'} for r in data['leaderboard'])
            assert all(r['name']!='LOCAL' for r in data['leaderboard'])
            await remember_member(session,TelegramUser(42,'Updated'))
            await session.commit()
            assert (await profile_data(session,42))['me']['name'] == 'Updated'
            assert (await profile_data(session,777))['me'] is None
            local = await profile_data(session,0,local=True)
            assert local['stats']['generations']==200 and not local['leaderboard'] and local['me'] is None
        await engine.dispose()
    asyncio.run(run())


def test_profile_includes_own_rank_outside_top_twenty(tmp_path):
    async def run():
        engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "outside.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session:
            for uid in range(1,23):
                session.add(MiniAppSet(id=str(uid),user_id=uid,genre='house',duration=30,tracks=[],
                                       total_duration_sec=1800,actual_duration_sec=1800))
            await session.commit()
            data=await profile_data(session,22)
            assert len(data['leaderboard'])==20
            assert not any(row['is_me'] for row in data['leaderboard'])
            assert data['me']['rank']==1 and data['me']['generations']==1
        await engine.dispose()
    asyncio.run(run())


def test_local_profile_endpoint_has_real_stats_and_no_community_rank(local_app):
    code,data=local_app('GET','/miniapp-api/profile')
    assert code==200 and data['local'] is True
    assert data['stats']['generations']==len(local_app('GET','/miniapp-api/sets')[1])
    assert data['leaderboard']==[] and data['me'] is None
