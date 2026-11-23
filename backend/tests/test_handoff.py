"""交接包验算、去重与退回规则。"""

import pytest

from src.domain import analysis, rules
from src.domain.demo import demo_rows
from src.models.handoff import HandoffBatch, HandoffReport
from src.services import handoff


def test_verified_package_is_accepted(db):
    package = handoff_module_package()
    report, _verification, batch_created, report_created = handoff.ingest(db, package, 'analyst')
    assert report.state == 'verified'
    assert batch_created and report_created
    assert report.rule_version == 'r1'
    assert report.result['positive_hits'] and report.result['negative_hits']


def test_reimport_same_package_adds_nothing(db):
    package = handoff_module_package()
    first, _, _, _ = handoff.ingest(db, package, 'analyst')
    again, _verification, batch_created, report_created = handoff.ingest(db, package, 'analyst')
    assert again.id == first.id
    assert not batch_created and not report_created
    assert db.query(HandoffBatch).count() == 1
    assert db.query(HandoffReport).count() == 1


def test_same_batch_appears_once_across_stations(db):
    one = handoff_module_package(report_no='R-001', station='东馆')
    two = handoff_module_package(report_no='R-009', station='西馆')
    handoff.ingest(db, one, 'analyst')
    handoff.ingest(db, two, 'analyst')
    assert db.query(HandoffBatch).count() == 1
    assert db.query(HandoffReport).count() == 2


def test_same_number_different_stations_kept_separately(db):
    east = handoff_module_package(station='东馆', report_no='R-001')
    west = handoff_module_package(station='西馆', report_no='R-001')
    handoff.ingest(db, east, 'analyst')
    handoff.ingest(db, west, 'analyst')
    assert db.query(HandoffReport).count() == 2


def test_same_station_same_number_with_changed_content_is_returned(db):
    first = handoff_module_package()
    handoff.ingest(db, first, 'analyst')
    changed = handoff_module_package(params={'humidity_threshold': 68})
    with pytest.raises(handoff.HandoffConflict):
        handoff.ingest(db, changed, 'analyst')
    assert db.query(HandoffReport).count() == 1


def test_ranking_mismatch_is_returned_not_stored(db):
    package = handoff_module_package()
    package['claimed']['ranking'][0]['positive_count'] += 1
    report, verification, _, created = handoff.ingest(db, package, 'analyst')
    assert report is None and not created
    assert verification['state'] == 'returned'
    assert verification['result']['ranking'], '退回结果仍保留本站重算排名供核对'
    assert verification['result']['positive_hits']
    assert db.query(HandoffReport).count() == 0
    assert db.query(HandoffBatch).count() == 0, '退回的交接包不占用批次编号'


def test_hit_list_mismatch_is_returned(db):
    package = handoff_module_package()
    package['claimed']['positive_hits'] = package['claimed']['positive_hits'][:-1]
    report, verification, _, created = handoff.ingest(db, package, 'analyst')
    assert report is None and not created
    assert verification['state'] == 'returned'
    assert any('见霉斑组命中单号' in item for item in verification['result']['differences'])
    assert db.query(HandoffReport).count() == 0


def test_unknown_rule_version_is_rejected(db):
    package = handoff_module_package()
    package['rule_version'] = 'r9'
    with pytest.raises(ValueError):
        handoff.ingest(db, package, 'analyst')
    assert db.query(HandoffBatch).count() == 0


def test_old_report_recomputed_with_its_own_version(db, monkeypatch):
    """本站升级后，旧交接包仍按原版本重算，结果不随当前规则改变。"""
    package = handoff_module_package(version='r1')
    baseline, _ = analysis.evaluate(package['rows'], {}, 'r1')
    handoff.ingest(db, package, 'analyst')

    upgraded = type('Rule', (), {
        'VERSION': 'r2', 'LABEL': '升级口径', 'RELEASED': '2026-12-01', 'NOTES': '',
        'PARAMS': rules.get('r1').PARAMS,
        'condition_labels': staticmethod(rules.get('r1').condition_labels),
        'row_patterns': staticmethod(lambda row, params: rules.get('r1').row_patterns(row, params)),
        'score': staticmethod(lambda hits, pos, neg, params: []),
    })
    monkeypatch.setitem(rules._MODULES, 'r2', upgraded)
    monkeypatch.setattr(rules, 'CURRENT', 'r2')

    report = db.query(HandoffReport).one()
    assert report.rule_version == 'r1'
    assert report.state == 'verified'
    assert report.headline == f"交接包 R-001 按规则 r1 验算一致，排名与两组命中单号均可复核。"
    assert analysis.evaluate(package['rows'], {}, 'r1')[0]['headline'] == baseline['headline']
    assert analysis.evaluate(package['rows'], {}, 'r2')[0]['metrics'][2]['value'] == 0


def test_duplicate_inspection_ids_rejected(db):
    rows = demo_rows()
    rows[1]['inspection_id'] = rows[0]['inspection_id']
    package = handoff_module_package(rows=rows, claimed={
        'ranking': [], 'positive_hits': [], 'negative_hits': []})
    with pytest.raises(ValueError):
        handoff.ingest(db, package, 'analyst')
    assert db.query(HandoffBatch).count() == 0


def test_equivalent_package_with_reordered_ids_is_not_a_change(db):
    package = handoff_module_package()
    reordered = handoff_module_package(claimed={
        'ranking': package['claimed']['ranking'],
        'positive_hits': list(reversed(package['claimed']['positive_hits'])),
        'negative_hits': list(reversed(package['claimed']['negative_hits'])),
    })
    first, _, _, _ = handoff.ingest(db, package, 'analyst')
    again, _, _, created = handoff.ingest(db, reordered, 'analyst')
    assert not created
    assert again.id == first.id
    assert db.query(HandoffReport).count() == 1


def test_returned_package_leaves_no_batch_and_can_be_resubmitted(db):
    bad = handoff_module_package()
    bad['claimed']['ranking'] = []
    report, verification, batch_created, created = handoff.ingest(db, bad, 'analyst')
    assert report is None and not batch_created and not created
    assert verification['state'] == 'returned'
    assert db.query(HandoffBatch).count() == 0
    # 外站修正排名后可重新提交同一个批次编号。
    good = handoff_module_package()
    accepted, _, batch_created, created = handoff.ingest(db, good, 'analyst')
    assert accepted.state == 'verified' and batch_created and created


def test_interrupted_after_batch_commit_resumes_without_new_report(db):
    """批次先落库；若报告写入前中断，重跑应复用该批次且只新增一份报告。"""
    from src.services.datasets import checksum

    package = handoff_module_package()
    batch, created = handoff._save_batch(db, package, checksum(package['rows']), package['rows'], 'analyst')
    db.commit()
    assert created and db.query(HandoffReport).count() == 0

    report, _, batch_created, report_created = handoff.ingest(db, package, 'analyst')
    assert not batch_created, '已验批次直接续用'
    assert report_created and report.batch_id == batch.id
    assert db.query(HandoffBatch).count() == 1
    assert db.query(HandoffReport).count() == 1


def test_same_batch_key_with_different_rows_is_returned(db):
    first = handoff_module_package()
    handoff.ingest(db, first, 'analyst')
    rows = demo_rows()
    rows[0]['humidity'] = 99
    altered = handoff_module_package(rows=rows, report_no='R-002')
    with pytest.raises(handoff.HandoffConflict):
        handoff.ingest(db, altered, 'analyst')
    assert db.query(HandoffReport).count() == 1


def test_concurrent_duplicate_insert_falls_back_to_existing(db, monkeypatch):
    """模拟并发：存在性检查未命中时，靠唯一约束兜底并复用已落库报告。"""
    package = handoff_module_package()
    first, _, _, _ = handoff.ingest(db, package, 'analyst')
    calls = {'count': 0}
    real = handoff._find_report

    def racing(session, station, report_no):
        calls['count'] += 1
        return None if calls['count'] <= 2 else real(session, station, report_no)

    monkeypatch.setattr(handoff, '_find_report', racing)
    again, _, batch_created, report_created = handoff.ingest(db, package, 'analyst')
    assert again.id == first.id
    assert not batch_created and not report_created
    assert db.query(HandoffReport).count() == 1
    assert db.query(HandoffBatch).count() == 1


def handoff_module_package(**kwargs):
    from tests.conftest import make_package
    return make_package(**kwargs)
