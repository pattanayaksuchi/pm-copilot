from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())  # loads the nearest .env up the tree

import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Index, UniqueConstraint
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
    assignee = Column(String(128), default="")
    labels = Column(Text, default="")                  # comma-separated for MVP
    url = Column(Text, default="")
    project = Column(String(64), default="")           # jira project key if any

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
    
Base.metadata.create_all(bind=engine)              # incremental watermark

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