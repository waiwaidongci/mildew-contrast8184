from src.domain.rules import CURRENT as CURRENT_RULE
from src.utils.time import iso


def dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename, 'row_count': item.row_count,
            'checksum': item.checksum, 'author': item.author, 'created_at': iso(item.created_at)}


def run(item, detail=False):
    item_view = {'id': item.id, 'dataset_id': item.dataset_id, 'name': item.name, 'status': item.status,
                 'author': item.author, 'review': item.review, 'decision': item.decision,
                 'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
                 'scheduled_at': iso(item.scheduled_at), 'schedule_id': item.schedule_id,
                 'rule_version': item.rule_version or CURRENT_RULE,
                 'has_export': bool(item.export_file), 'error': item.error}
    if detail:
        item_view.update(params=item.params, result=item.result, review_note=item.review_note)
    return item_view


def schedule(item):
    from src.domain.spec import SPEC
    return {'id': item.id, 'name': item.name, 'dataset_id': item.dataset_id, 'recipient': item.recipient,
            'next_at': iso(item.next_at), 'repeat_daily': item.repeat_daily, 'enabled': item.enabled,
            'next_report_day': item.params.get(SPEC['schedule_date_param']) if item.enabled else None}


def delivery(item):
    return {'id': item.id, 'run_id': item.run_id, 'recipient': item.recipient,
            'state': item.state, 'detail': item.detail, 'created_at': iso(item.created_at)}


def handoff_report(item, detail=False):
    view = {'id': item.id, 'station': item.station, 'report_no': item.report_no,
            'batch_id': item.batch_id, 'rule_version': item.rule_version, 'state': item.state,
            'headline': item.headline, 'author': item.author, 'created_at': iso(item.created_at),
            'params': item.params}
    if detail:
        view['result'] = item.result
    return view


def handoff_rejection(station, report_no, verification, author):
    """退回结果不入库，沿用报告字段形状返回给提交方核对。"""
    return {'id': None, 'station': station, 'report_no': report_no, 'batch_id': None,
            'rule_version': verification['rule_version'], 'state': verification['state'],
            'headline': verification['headline'], 'author': author, 'created_at': None,
            'params': verification['params'], 'result': verification['result']}
