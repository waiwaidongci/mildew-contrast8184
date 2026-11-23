"""交接接口行为：只展示验算通过报告，并可查两组命中单号。"""

import os

import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('JWT_SECRET', 'test-secret-interface-only')

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.config.database import Base, connection  # noqa: E402
from src.constants.enums import Role  # noqa: E402
from src.main import app  # noqa: E402
from src.models.identity import User  # noqa: E402
from src.utils.security import hash_password, token  # noqa: E402

from .conftest import make_package  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[connection] = override
    with Session.begin() as db:
        for role in Role:
            db.add(User(username=role.value, role=role,
                        password_hash=hash_password(f'{role.value}-demo-2611')))
    try:
        with TestClient(app) as test:
            yield test
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def auth(role):
    return {'Authorization': f'Bearer {token(role, role)}'}


def test_verified_report_is_listed_and_detail_has_both_hit_lists(client):
    package = make_package()
    created = client.post('/handoff', json=package, headers=auth('analyst'))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body['state'] == 'verified' and body['created']

    listed = client.get('/handoff/reports', headers=auth('viewer')).json()
    assert [item['id'] for item in listed] == [body['id']]

    detail = client.get(f"/handoff/reports/{body['id']}", headers=auth('viewer')).json()
    assert detail['result']['positive_hits']
    assert detail['result']['negative_hits']
    assert detail['result']['positive_hits'] == sorted(set(detail['result']['positive_hits']))


def test_returned_report_is_not_listed(client):
    package = make_package()
    package['claimed']['ranking'] = []
    response = client.post('/handoff', json=package, headers=auth('analyst'))
    assert response.status_code == 201
    assert response.json()['state'] == 'returned' and not response.json()['created']
    assert client.get('/handoff/reports', headers=auth('viewer')).json() == []


def test_same_station_same_number_changed_content_returns_conflict(client):
    first = make_package()
    assert client.post('/handoff', json=first, headers=auth('analyst')).status_code == 201
    changed = make_package(params={'humidity_threshold': 68})
    response = client.post('/handoff', json=changed, headers=auth('analyst'))
    assert response.status_code == 409
    assert client.get('/handoff/reports', headers=auth('viewer')).json()[0]['report_no'] == 'R-001'


def test_viewer_cannot_import(client):
    response = client.post('/handoff', json=make_package(), headers=auth('viewer'))
    assert response.status_code == 403


def test_rule_catalog_exposes_versions(client):
    body = client.get('/handoff/rules', headers=auth('viewer')).json()
    assert body['current'] in [item['version'] for item in body['versions']]


def test_template_package_verifies(client):
    template = client.get('/handoff/template', headers=auth('analyst'))
    assert template.status_code == 200
    package = template.json()
    response = client.post('/handoff', json=package, headers=auth('analyst'))
    assert response.status_code == 201, response.text
    assert response.json()['state'] == 'verified'
    assert response.json()['result']['positive_hits']
