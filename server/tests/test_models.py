from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, RawEvent, RecordingSession


def test_raw_event_append_only_shape():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        sess = RecordingSession(id="s1", target_system="njmind", note="poc")
        s.add(sess)
        s.add(RawEvent(session_id="s1", seq=1, ts=1700000000000, kind="action", payload={"x": 1}))
        s.commit()
        rows = s.execute(select(RawEvent).where(RawEvent.session_id == "s1")).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload == {"x": 1}
        assert rows[0].created_at is not None
