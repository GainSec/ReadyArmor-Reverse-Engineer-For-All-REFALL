import pytest
from coverage_service import db as dbmod


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(str(tmp_path / "c.db"))
    dbmod.init_schema(c)
    return c
