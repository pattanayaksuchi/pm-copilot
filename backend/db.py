from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())  # loads the nearest .env up the tree

import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Index, UniqueConstraint, Boolean, inspect, text
)
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import JSON, Float

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pm_insight.db")

#Special config for SQLite
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    source = Column(String(32), index=True)            # 'zendesk' | 'jira' | 'slack'
    external_id = Column(String(128), nullable=False)  # source-specific ID
    title = Column(Text, default="")
    content = Column(Text, default="")
    type = Column(String(32), default="unknown")       # 'issue' | 'feature_request' | 'unknown'
    status = Column(String(64), default="")
    priority = Column(String(64), default="")
    requester = Column(String(128), default="")
    requester_role = Column(String(64), default="")
    requester_email = Column(String(256), default="")
    assignee = Column(String(128), default="")
    labels = Column(Text, default="")                  # comma-separated for MVP
    url = Column(Text, default="")
    project = Column(String(64), default="")           # jira project key if any
    submitter = Column(String(128), default="")
    submitter_role = Column(String(64), default="")
    submitter_email = Column(String(256), default="")
    is_shared = Column(Boolean, nullable=True, index=True)
    sharing_type = Column(String(32), default="")       # inbound|outbound|""
    is_internal = Column(Boolean, nullable=True, index=True)  # None=unknown, False=external, True=internal

    source_created_at = Column(DateTime)
    source_updated_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('source', 'external_id', name='uq_source_external'),
        Index('ix_source_updated', 'source', 'source_updated_at'),
    )

class TicketEmbedding(Base):
    __tablename__ = "ticket_embeddings"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, index=True, unique=True)     # FK to Ticket.id
    model = Column(String(64), default="all-MiniLM-L6-v2")
    dim = Column(Integer, default=384)
    # store as JSON array (works fine in SQLite)
    vector = Column(JSON) 
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Theme(Base):
    __tablename__ = "themes"

    id = Column(Integer, primary_key=True)
    run_id = Column(String(64), index=True)     # to group a clustering run
    label = Column(Integer, index=True)         # cluster id
    centroid_hint = Column(Text, default="")    # short text label (computed)
    type = Column(String(32), default="mixed")  # issue | feature_request | mixed
    size = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class SyncState(Base):
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True)
    source = Column(String(32), unique=True)          # 'zendesk', 'jira'
    last_run_at = Column(DateTime)
    last_cursor = Column(String(256))                 # optional: for cursor-based APIs
    last_updated_at = Column(DateTime)  
    
class TicketProductVertical(Base):
    __tablename__ = "ticket_product_verticals"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, index=True, unique=True)
    vertical_slug = Column(String(128), index=True)
    vertical_name = Column(String(256))
    confidence = Column(Float, default=0.0)
    explanation = Column(JSON)  # dict with matched keywords/rules
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class TicketGoldLabel(Base):
    __tablename__ = "ticket_gold_labels"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, index=True, unique=True)
    vertical_slug = Column(String(128), index=True)
    vertical_name = Column(String(256))
    reviewer = Column(String(128), default="")
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)              # incremental watermark

# --- Lightweight migration helpers (SQLite/Postgres safe) ---
def _ensure_ticket_is_internal_column():
    try:
        insp = inspect(engine)
        cols = {c['name'] for c in insp.get_columns('tickets')}
        if 'is_internal' not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tickets ADD COLUMN is_internal BOOLEAN"))
                # best-effort index (IF NOT EXISTS works on SQLite 3.8.0+ and Postgres)
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_is_internal ON tickets(is_internal)"))
    except Exception:
        # Do not crash app startup on migration issues; continue without the column.
        pass

_ensure_ticket_is_internal_column()


def _safe_add_column(table: str, col_sql: str, index_sql: str | None = None):
    try:
        insp = inspect(engine)
        cols = {c['name'] for c in insp.get_columns(table)}
        name = col_sql.split()[0].strip('"')
        if name not in cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_sql}"))
                if index_sql:
                    conn.execute(text(index_sql))
    except Exception:
        pass

# Additional migration columns for transparency/auditing
_safe_add_column('tickets', 'requester_role VARCHAR(64)')
_safe_add_column('tickets', 'requester_email VARCHAR(256)')
_safe_add_column('tickets', 'submitter VARCHAR(128)')
_safe_add_column('tickets', 'submitter_role VARCHAR(64)')
_safe_add_column('tickets', 'submitter_email VARCHAR(256)')
_safe_add_column('tickets', 'is_shared BOOLEAN', "CREATE INDEX IF NOT EXISTS ix_tickets_is_shared ON tickets(is_shared)")
_safe_add_column('tickets', 'sharing_type VARCHAR(32)')

def upsert_ticket(session, payload: dict):
    """
    payload keys should match Ticket columns.
    Dedups on (source, external_id).
    """
    existing = session.query(Ticket).filter_by(
        source=payload["source"], external_id=payload["external_id"]
    ).one_or_none()

    if existing:
        # Update changed fields
        for k, v in payload.items():
            setattr(existing, k, v)
        existing.updated_at = datetime.utcnow()
        return existing
    else:
        t = Ticket(**payload)
        session.add(t)
        return t

def get_or_create_sync_state(session, source: str) -> SyncState:
    st = session.query(SyncState).filter_by(source=source).one_or_none()
    if not st:
        st = SyncState(source=source)
        session.add(st)
    return st

def upsert_ticket_vertical(session, ticket_id: int, vertical_slug: str, vertical_name: str, confidence: float, explanation: dict | None = None):
    existing = session.query(TicketProductVertical).filter_by(ticket_id=ticket_id).one_or_none()
    if existing:
        existing.vertical_slug = vertical_slug
        existing.vertical_name = vertical_name
        existing.confidence = float(confidence or 0.0)
        existing.explanation = explanation or {}
        existing.updated_at = datetime.utcnow()
        return existing
    else:
        tv = TicketProductVertical(
            ticket_id=ticket_id,
            vertical_slug=vertical_slug,
            vertical_name=vertical_name,
            confidence=float(confidence or 0.0),
            explanation=explanation or {},
        )
        session.add(tv)
        return tv

def upsert_gold_label(session, ticket_id: int, vertical_slug: str, vertical_name: str, reviewer: str = "", note: str = ""):
    existing = session.query(TicketGoldLabel).filter_by(ticket_id=ticket_id).one_or_none()
    if existing:
        existing.vertical_slug = vertical_slug
        existing.vertical_name = vertical_name
        existing.reviewer = reviewer or existing.reviewer
        existing.note = note or existing.note
        existing.updated_at = datetime.utcnow()
        return existing
    else:
        gl = TicketGoldLabel(
            ticket_id=ticket_id,
            vertical_slug=vertical_slug,
            vertical_name=vertical_name,
            reviewer=reviewer,
            note=note,
        )
        session.add(gl)
        return gl
