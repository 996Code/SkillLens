from app.db import engine
from app.models import Base, ExpectedDelta, ObservedDelta, DeltaReport


def test_change_tables_created():
    Base.metadata.create_all(engine)
    import sqlalchemy as sa
    insp = sa.inspect(engine)
    for t in ("expected_delta", "observed_delta", "delta_report"):
        assert insp.has_table(t), f"缺表 {t}"
