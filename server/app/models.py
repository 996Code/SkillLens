from datetime import datetime, timezone

from sqlalchemy import BigInteger, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecordingSession(Base):
    __tablename__ = "recording_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    target_system: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(500), default="")


class RawEvent(Base):
    __tablename__ = "raw_event"
    __table_args__ = (
        UniqueConstraint("session_id", "page_id", "seq", name="uq_raw_event_session_page_seq"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    page_id: Mapped[str] = mapped_column(String(40), default="")
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SemanticAction(Base):
    __tablename__ = "semantic_action"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    anchor_seq: Mapped[int] = mapped_column()
    anchor_type: Mapped[str] = mapped_column(String(20))
    target: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    api_calls: Mapped[list] = mapped_column(JSON)
    state_signals: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class NormalizedEvent(Base):
    __tablename__ = "normalized_event"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[int] = mapped_column()
    template: Mapped[str] = mapped_column(String(500))
    page_id: Mapped[str] = mapped_column(String(40), default="")
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TransactionWindow(Base):
    __tablename__ = "transaction_window"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    anchor_event_id: Mapped[int] = mapped_column()
    member_event_ids: Mapped[list] = mapped_column(JSON)
    idle_ms: Mapped[int] = mapped_column()
    max_window_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Alignment(Base):
    __tablename__ = "alignment"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_ids: Mapped[list] = mapped_column(JSON)
    skeleton: Mapped[list] = mapped_column(JSON)
    param_variables: Mapped[list] = mapped_column(JSON)
    input_variables: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FieldChange(Base):
    __tablename__ = "field_change"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    api_template: Mapped[str] = mapped_column(String(500))
    before_seq: Mapped[int] = mapped_column()
    after_seq: Mapped[int] = mapped_column()
    changes: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LlmCallLog(Base):
    __tablename__ = "llm_call_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
