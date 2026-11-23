"""交接包独立验算的最小测试夹具。

SQLite 只用于本地测试：唯一约束和事务语义足以覆盖去重与退回逻辑。
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('JWT_SECRET', 'test-secret-interface-only')

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.config.database import Base  # noqa: E402
from src.domain import analysis  # noqa: E402
from src.domain.demo import demo_rows  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    session = sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_package(rows=None, params=None, version='r1', station='东馆', report_no='R-001',
                 claimed=None, batch_key='B-001'):
    rows = demo_rows() if rows is None else rows
    if params is None:
        from src.domain import rules
        params = {field['key']: field['default'] for field in rules.get(version).PARAMS}
    if claimed is None:
        _result, checks = analysis.evaluate(rows, params, version)
        claimed = {
            'ranking': checks['ranking'],
            'positive_hits': checks['positive_hits'],
            'negative_hits': checks['negative_hits'],
        }
    return {
        'station': station, 'report_no': report_no, 'batch_key': batch_key,
        'rule_version': version, 'params': params, 'rows': rows, 'claimed': claimed,
    }
