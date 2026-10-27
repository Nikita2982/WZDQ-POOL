"""Profile totals and shared generation leaderboard; set contents stay private."""
from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert

from api.miniapp_auth import TelegramUser, current_user
from api.miniapp_models import MiniAppMember, MiniAppSet
from config.settings import get_settings
from database.db import SessionLocal

router = APIRouter(prefix="/miniapp-api")


async def remember_member(session, user):
    if user.id <= 0:
        return
    await session.execute(insert(MiniAppMember).values(user_id=user.id, first_name=user.first_name[:128])
                          .on_conflict_do_update(index_elements=[MiniAppMember.user_id],
                                                 set_={"first_name": user.first_name[:128]}))


async def profile_data(session, user_id, local=False):
    totals = (await session.execute(select(
        func.count(MiniAppSet.id), func.coalesce(func.sum(MiniAppSet.total_duration_sec), 0),
        func.coalesce(func.sum(case((MiniAppSet.favorite.is_(True), 1), else_=0)), 0)
    ).where(MiniAppSet.user_id == user_id))).one()
    genres = (await session.execute(select(MiniAppSet.genre, func.count().label("n"))
                                    .where(MiniAppSet.user_id == user_id).group_by(MiniAppSet.genre)
                                    .order_by(func.count().desc(), MiniAppSet.genre))).all()
    counts = select(MiniAppSet.user_id.label("uid"), func.count().label("generations"))\
        .where(MiniAppSet.user_id > 0).group_by(MiniAppSet.user_id).subquery()
    ranked = select(counts.c.uid, counts.c.generations,
                    func.rank().over(order_by=counts.c.generations.desc()).label("place")).subquery()
    ranked_names = select(ranked, MiniAppMember.first_name).outerjoin(
        MiniAppMember, MiniAppMember.user_id == ranked.c.uid)
    top = (await session.execute(ranked_names.order_by(ranked.c.place, ranked.c.uid).limit(20))).all()
    own = (await session.execute(ranked_names.where(ranked.c.uid == user_id))).first() if not local else None
    participants = await session.scalar(select(func.count()).select_from(counts))

    def entry(row):
        return {"name": row.first_name or "Участник пула", "generations": row.generations,
                "rank": row.place, "is_me": row.uid == user_id}

    return {"stats": {"generations": totals[0], "minutes": round(totals[1] / 60), "favorites": totals[2],
                      "favorite_genre": genres[0][0] if genres else None},
            "leaderboard": [entry(row) for row in top] if not local else [],
            "me": entry(own) if own else None,
            "participants": participants if not local else 0, "local": local}


@router.get("/profile")
async def profile(user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        await remember_member(session, user)
        await session.commit()
        return await profile_data(session, user.id, get_settings().miniapp_local)
