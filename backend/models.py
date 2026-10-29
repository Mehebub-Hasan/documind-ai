import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


def utcnow():
    # Naive UTC keeps SQLite and PostgreSQL round-trips consistent.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    documents = relationship("Document", back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=False)
    filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # "pdf" | "docx"
    summary_json = Column(Text, nullable=False, default="{}")
    # Grounded executive summary (JSON: overview + cited takeaways),
    # generated once at upload or on first open.
    summary = Column(Text, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    index_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", back_populates="documents")
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    messages = relationship(
        "ChatMessage", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        String, ForeignKey("documents.id"), index=True, nullable=False
    )
    chunk_index = Column(Integer, nullable=False)
    chunk_id = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")

    document = relationship("Document", back_populates="chunks")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        String, ForeignKey("documents.id"), index=True, nullable=False
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    document = relationship("Document", back_populates="messages")
