from datetime import date, datetime

import pytest

from emporio.config import PROJECT_ROOT, STORE_TZ
from emporio.data import load_store_data
from emporio.knowledge import load_knowledge

TODAY = date(2026, 3, 25)  # a Wednesday, three days after the last order in the data


@pytest.fixture(scope="session")
def data():
    return load_store_data(PROJECT_ROOT / "data")


@pytest.fixture(scope="session")
def knowledge():
    return load_knowledge(PROJECT_ROOT / "knowledge")


@pytest.fixture
def today():
    return TODAY


@pytest.fixture
def now():
    return datetime(2026, 3, 25, 14, 30, tzinfo=STORE_TZ)
