"""Read-only availability across all recorded groups; never expose occupancy details."""
import re
from datetime import datetime,time
from fastapi import APIRouter,Request
from .auth.service import resolve,AuthError
from .db import connection
from .schedule.service import calendar_date,MOSCOW


def interval(value, *, end=False):
    if end and value=='24:00':return 1440
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):
        raise ValueError('Invalid time')
    return int(value[:2])*60+int(value[3:])


def install_rooms(app,settings):
    router=APIRouter(prefix='/api/v1/me/rooms')
    def identity(request,db):
        actor=resolve(db,request.cookies.get(settings.session_cookie),int(app.state.auth_service.clock()),request.headers.get('x-mgimov-user'))
        if actor['role'] not in ('student','staff'):raise AuthError(403,'Unavailable')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE id='0025_room_availability'").fetchone():
            raise AuthError(503,'Room search needs a schema update')
        return actor
    @router.get('/catalogue')
    def catalogue(request:Request):
        with connection(settings) as db:
            db.execute('BEGIN');identity(request,db)
            if request.query_params:raise AuthError(422,'Invalid filters')
            return {'buildings':[dict(r) for r in db.execute('SELECT id,name FROM buildings ORDER BY name,id')]}
    @router.get('/availability')
    def search(request:Request):
        q=request.query_params
        with connection(settings) as db:
            db.execute('BEGIN');identity(request,db)
            try:
                if set(q)-{'date','start','end','building','capacity'} or any(len(q.getlist(k))!=1 for k in q):raise ValueError()
                day=calendar_date(q.get('date'));left=interval(q.get('start'));right=interval(q.get('end'),end=True)
                raw=q.get('capacity','1')
                if not re.fullmatch(r'[0-9]{1,4}',raw):raise ValueError()
                capacity=int(raw)
                if left>=right or not 1<=capacity<=1000:raise ValueError()
                building=q.get('building')
                if building is not None and not db.execute('SELECT 1 FROM buildings WHERE id=?',(building,)).fetchone():raise ValueError()
            except (ValueError,TypeError):raise AuthError(422,'Invalid date, interval or filter') from None
            midnight=int(datetime.combine(day,time(),MOSCOW).timestamp())
            starts,ends=midnight+left*60,midnight+right*60
            rows=db.execute("""SELECT r.id,r.number,r.capacity,b.id AS building_id,b.name AS building,
                CASE WHEN h.building_id IS NULL THEN 'unknown' ELSE 'known' END AS access_rules
                FROM rooms r JOIN buildings b ON b.id=r.building_id
                LEFT JOIN building_open_hours h ON h.building_id=b.id AND h.weekday=?
                WHERE r.capacity>=? AND (? IS NULL OR b.id=?)
                AND (h.building_id IS NULL OR (h.opens IS NOT NULL AND h.opens<=? AND h.closes>=?))
                AND NOT EXISTS(SELECT 1 FROM room_unavailability u WHERE u.room_id=r.id
                    AND u.starts_at<? AND (u.ends_at IS NULL OR u.ends_at>?))
                AND NOT EXISTS(SELECT 1 FROM lessons l WHERE l.room_id=r.id AND l.date=?
                    AND l.status='scheduled' AND l.start_minute<? AND l.end_minute>?)
                AND NOT EXISTS(SELECT 1 FROM attestation_slots s WHERE s.room_id=r.id
                    AND s.starts_at<? AND s.ends_at>? AND NOT EXISTS(
                        SELECT 1 FROM attestation_events e WHERE e.slot_id=s.id AND e.kind IN
                            ('cancelled','excused','unexcused','published','completed')))
                ORDER BY b.name,r.number,r.id""",
                (day.weekday(),capacity,building,building,left,right,ends,starts,day.isoformat(),right,left,ends,starts))
            return {'items':[dict(r) for r in rows],'date':day.isoformat(),'start':q['start'],'end':q['end'],'timezone':'Europe/Moscow'}
    app.include_router(router)
