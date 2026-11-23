import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Handoff, Role
from src.controllers.auth import allow, current
from src.domain import rules
from src.models.handoff import HandoffReport
from src.models.identity import User
from src.schemas.requests import HandoffRequest
from src.services import handoff
from src.services.audit import record
from src.utils import views

router = APIRouter(prefix='/handoff')


@router.get('/rules')
def rule_versions(actor: User = Depends(current)):
    return {'current': rules.CURRENT, 'versions': rules.catalog()}


@router.get('/template')
def template(actor: User = Depends(current)):
    """导出当前参数的示例交接包，供外站按同一口径打包。"""
    from urllib.parse import quote

    package = handoff.example_package()
    filename = quote(f"交接包示例_{package['station']}_{package['report_no']}.json")
    return Response(
        json.dumps(package, ensure_ascii=False, indent=2),
        media_type='application/json; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get('/reports')
def reports(db: Session = Depends(connection), actor: User = Depends(current),
            station: str | None = Query(None, max_length=80),
            rule_version: str | None = Query(None, max_length=20)):
    query = select(HandoffReport).where(HandoffReport.state == Handoff.VERIFIED)
    if station:
        query = query.where(HandoffReport.station == station)
    if rule_version:
        query = query.where(HandoffReport.rule_version == rule_version)
    items = db.scalars(query.order_by(HandoffReport.id.desc()).limit(200))
    return [views.handoff_report(item, detail=False) for item in items]


@router.get('/reports/{report_id}')
def report_detail(report_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(HandoffReport, report_id)
    if not item or item.state != Handoff.VERIFIED:
        raise HTTPException(404, '找不到已验算通过的交接报告')
    return views.handoff_report(item, detail=True)


@router.post('', status_code=201)
def ingest(body: HandoffRequest, db: Session = Depends(connection),
           actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    package = body.model_dump()
    try:
        item, verification, batch_created, report_created = handoff.ingest(db, package, actor.username)
    except handoff.HandoffConflict as error:
        # 同站同号内容有变：不写报告、不占批次编号；已验批次可保留作续跑检查点。
        db.rollback()
        record(db, actor.username, 'handoff.returned', f'{body.station}/{body.report_no}',
               reason=str(error))
        db.commit()
        raise HTTPException(409, str(error)) from None
    if report_created:
        record(db, actor.username, 'handoff.imported', item.id,
               station=item.station, report_no=item.report_no, rule_version=item.rule_version,
               batch_created=batch_created)
    elif verification and verification['state'] != Handoff.VERIFIED:
        # 验算不一致：不入库，只留审计，返回差异供外站核对后重交。
        record(db, actor.username, 'handoff.returned', f'{body.station}/{body.report_no}',
               reason='、'.join(verification['differences'])[:500])
    db.commit()
    view = views.handoff_report(item, detail=True) if item else views.handoff_rejection(
        body.station, body.report_no, verification, actor.username)
    return {**view, 'created': report_created, 'batch_created': batch_created}
