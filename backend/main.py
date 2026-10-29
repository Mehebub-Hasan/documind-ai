import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from chatbot import NOT_FOUND_ANSWER, answer_question_with_deepseek
from chunker import create_chunks_from_pages, create_chunks_from_units
from database import get_db, init_db
from docx_processor import (
    DocxExtractionError,
    extract_blocks_from_docx,
    get_docx_summary,
    group_blocks_into_sections,
    create_units_from_sections,
)
import document_store
from models import ChatMessage, Document, DocumentChunk, User
from pdf_processor import extract_text_from_pdf, get_pdf_summary
from summarizer import generate_document_summary
from vector_store import VectorStore


app = FastAPI(
    title="DocuMind AI Backend",
    description=(
        "Backend API for uploading PDFs and Word documents and asking "
        "questions using RAG, with user accounts and persistent storage."
    ),
    version="2.0.0"
)

DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]
ENV_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
ALLOWED_ORIGINS = sorted(set(DEFAULT_ORIGINS + ENV_ORIGINS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


BACKEND_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BACKEND_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _validate_production_config():
    """
    Fail fast in production when a required secret is missing, instead of
    silently signing tokens with the insecure development fallback.
    """

    is_production = (
        os.getenv("RENDER") == "true"
        or os.getenv("ENVIRONMENT") == "production"
    )

    if is_production and not os.getenv("JWT_SECRET_KEY"):
        raise RuntimeError(
            "JWT_SECRET_KEY must be set in production. "
            "Generate one with: openssl rand -hex 32"
        )


_validate_production_config()

init_db()


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class SearchRequest(BaseModel):
    document_id: str
    question: str
    top_k: int = 5


class AskRequest(BaseModel):
    document_id: str
    question: str
    top_k: int = 6


@app.get("/")
def home():
    return {
        "message": "DocuMind AI Backend is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _parse_json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _build_docx_chunks(blocks):
    """
    Turn extracted docx blocks into chunks: group consecutive blocks into
    sections first, then reuse the generic overlapping chunker.
    """

    sections = group_blocks_into_sections(blocks)
    units = create_units_from_sections(sections)

    return create_chunks_from_units(
        units=units,
        chunk_size=1000,
        overlap=200
    )


def _build_source_references(source_type, retrieved_chunks):
    """
    Build the "sources" list for /ask responses.

    PDF chunks reference pages (ints). DOCX chunks reference document block
    ranges (e.g. "blocks 4-9") because Word files have no fixed pages.
    """

    if source_type == "docx":
        ranges = sorted(
            {
                (chunk["block_start"], chunk["block_end"])
                for chunk in retrieved_chunks
                if chunk.get("block_start") is not None
            }
        )

        return [
            f"blocks {start}-{end}" if start != end else f"block {start}"
            for start, end in ranges
        ]

    return sorted(
        list(
            set(
                chunk["page"]
                for chunk in retrieved_chunks
                if chunk.get("page") is not None
            )
        )
    )


def _get_owned_document(db: Session, document_id: str, user: User):
    """
    Fetch a document owned by the given user. Returns None when the document
    does not exist OR belongs to somebody else, so responses never leak the
    existence of other users' documents.
    """

    document = db.query(Document).filter(Document.id == document_id).first()

    if document is None or document.user_id != user.id:
        return None

    return document


def _cleanup_upload_artifacts(db: Session, file_path: Path, index_path: Path):
    db.rollback()

    for path in (file_path, index_path):
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    document_store.clear_cache()


def _process_and_store(
    file: UploadFile,
    db: Session,
    current_user: User,
    *,
    source_type: str,
    success_message: str,
    extract_units,
    build_summary,
    build_chunks,
    empty_extract_error: str,
    empty_chunks_error: str,
    processing_failed_prefix: str
):
    """
    Shared upload pipeline: save the file, extract text units, build the
    summary, chunks, and FAISS index, then persist everything (document row,
    chunk rows, index file) for the uploading user. The uploaded file and
    index file are removed again if any step fails.
    """

    document_id = str(uuid.uuid4())

    safe_filename = Path(file.filename).name.replace(" ", "_")
    file_path = UPLOAD_DIR / f"{document_id}_{safe_filename}"
    index_path = document_store.index_path_for(document_id)

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            units = extract_units(str(file_path))
        except DocxExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        if not units:
            raise HTTPException(status_code=422, detail=empty_extract_error)

        summary = build_summary(units)

        chunks = build_chunks(units)

        if not chunks:
            raise HTTPException(status_code=422, detail=empty_chunks_error)

        vector_store = VectorStore()
        index_summary = vector_store.build_index(chunks)

        # Grounded executive summary. Best-effort: the extractive fallback
        # keeps uploads working (fully offline) when no LLM key is set.
        executive_summary = generate_document_summary(chunks)

        document_store.persist_new_document(
            db,
            document_id=document_id,
            user_id=current_user.id,
            filename=safe_filename,
            stored_path=str(file_path),
            source_type=source_type,
            summary=summary,
            chunks=chunks,
            vector_store=vector_store,
            executive_summary=executive_summary
        )

        return {
            "message": success_message,
            "document_id": document_id,
            "filename": safe_filename,
            "file_path": str(file_path),
            "source_type": source_type,
            "summary": summary,
            "document_summary": executive_summary,
            "chunk_summary": {
                "total_chunks": len(chunks),
                "chunk_size": 1000,
                "overlap": 200
            },
            "vector_index": index_summary,
            "sample_chunks": chunks[:3]
        }

    except HTTPException:
        _cleanup_upload_artifacts(db, file_path, index_path)
        raise

    except Exception as e:
        _cleanup_upload_artifacts(db, file_path, index_path)
        raise HTTPException(
            status_code=500,
            detail=f"{processing_failed_prefix}: {str(e)}"
        )


@app.post("/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """
    Create a new user account and return a JWT token for it.
    """

    email = payload.email.strip().lower()
    name = payload.name.strip()
    password = payload.password

    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")

    if not EMAIL_PATTERN.match(email):
        raise HTTPException(
            status_code=400,
            detail="Please provide a valid email address."
        )

    if len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long."
        )

    existing = db.query(User).filter(User.email == email).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists."
        )

    user = User(
        email=email,
        name=name,
        password_hash=hash_password(password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "token": create_access_token(user),
        "user": _public_user(user)
    }


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Verify credentials and return a JWT token.
    """

    email = payload.email.strip().lower()

    user = db.query(User).filter(User.email == email).first()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )

    return {
        "token": create_access_token(user),
        "user": _public_user(user)
    }


@app.get("/auth/me")
def me(current_user: User = Depends(get_current_user)):
    """
    Return the profile of the currently authenticated user.
    """

    return {"user": _public_user(current_user)}


@app.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a PDF file, extract text, create chunks, and build vector index.
    """

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed."
        )

    return _process_and_store(
        file,
        db,
        current_user,
        source_type="pdf",
        success_message="PDF uploaded, text extracted, chunks created, and vector index built successfully.",
        extract_units=extract_text_from_pdf,
        build_summary=get_pdf_summary,
        build_chunks=create_chunks_from_pages,
        empty_extract_error="No pages were detected in the uploaded PDF.",
        empty_chunks_error="No readable text was extracted from the PDF.",
        processing_failed_prefix="PDF processing failed"
    )


@app.post("/upload-docx")
async def upload_docx(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a Word .docx file, extract text, create chunks, and build vector index.
    """

    if not file.filename or not file.filename.lower().endswith(".docx"):
        if file.filename and file.filename.lower().endswith(".doc"):
            raise HTTPException(
                status_code=400,
                detail="Legacy .doc files are not supported. Please convert the document to .docx and upload again."
            )

        raise HTTPException(
            status_code=400,
            detail="Only .docx Word files are allowed."
        )

    return _process_and_store(
        file,
        db,
        current_user,
        source_type="docx",
        success_message="DOCX uploaded, text extracted, chunks created, and vector index built successfully.",
        extract_units=extract_blocks_from_docx,
        build_summary=get_docx_summary,
        build_chunks=_build_docx_chunks,
        empty_extract_error="No blocks were detected in the uploaded document.",
        empty_chunks_error="No readable text was extracted from the document.",
        processing_failed_prefix="DOCX processing failed"
    )


@app.get("/documents")
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List the current user's documents.
    """

    documents = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .all()
    )

    return {
        "total_documents": len(documents),
        "documents": [
            {
                "document_id": document.id,
                "filename": document.filename,
                "source_type": document.source_type,
                "chunk_count": document.chunk_count,
                "summary": _parse_json(document.summary_json, {}),
                "created_at": (
                    document.created_at.isoformat()
                    if document.created_at
                    else None
                )
            }
            for document in documents
        ]
    }


def _ensure_executive_summary(db: Session, document: Document) -> dict | None:
    """
    Return the document's persisted executive summary, generating and storing
    it on first open. Documents uploaded before this feature existed (and any
    where generation is impossible) have summary = NULL until opened once.
    """

    parsed = _parse_json(document.summary, None)
    if parsed is not None:
        return parsed

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    chunks = document_store.chunks_from_rows(rows)

    if not chunks:
        return None

    summary = generate_document_summary(chunks)

    document.summary = json.dumps(summary)
    db.commit()

    return summary


@app.get("/documents/{document_id}")
def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Return metadata for one of the current user's documents, including the
    grounded executive summary (generated on first open if missing).
    """

    document = _get_owned_document(db, document_id, current_user)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    return {
        "document_id": document.id,
        "filename": document.filename,
        "source_type": document.source_type,
        "chunk_count": document.chunk_count,
        "summary": _parse_json(document.summary_json, {}),
        "document_summary": _ensure_executive_summary(db, document),
        "created_at": (
            document.created_at.isoformat()
            if document.created_at
            else None
        )
    }


@app.get("/documents/{document_id}/messages")
def get_document_messages(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Return the saved chat history for one of the current user's documents.
    """

    document = _get_owned_document(db, document_id, current_user)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == document_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )

    return {
        "document_id": document_id,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "sources": _parse_json(message.sources_json, []),
                "created_at": (
                    message.created_at.isoformat()
                    if message.created_at
                    else None
                )
            }
            for message in messages
        ]
    }


@app.post("/search")
def search_pdf(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Search one of the current user's documents for relevant chunks.
    """

    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    if request.top_k <= 0:
        raise HTTPException(
            status_code=400,
            detail="top_k must be a positive integer."
        )

    document = _get_owned_document(db, request.document_id, current_user)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found. Please upload the document first."
        )

    try:
        vector_store = document_store.get_vector_store(db, document)

        results = vector_store.search(
            query=request.question,
            top_k=request.top_k
        )

        return {
            "document_id": request.document_id,
            "question": request.question,
            "top_k": request.top_k,
            "results": results
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )


@app.post("/ask")
def ask_pdf(
    request: AskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ask a question about one of the current user's documents.
    Uses FAISS retrieval + DeepSeek LLM answer generation. Both the question
    and the answer (with sources) are persisted as chat history.
    """

    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    if request.top_k <= 0:
        raise HTTPException(
            status_code=400,
            detail="top_k must be a positive integer."
        )

    document = _get_owned_document(db, request.document_id, current_user)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found. Please upload the document first."
        )

    try:
        vector_store = document_store.get_vector_store(db, document)

        retrieved_chunks = vector_store.search(
            query=request.question,
            top_k=request.top_k
        )

        source_type = document.source_type

        if not retrieved_chunks:
            answer = NOT_FOUND_ANSWER
            sources = []
        else:
            answer = answer_question_with_deepseek(
                question=request.question,
                retrieved_chunks=retrieved_chunks
            )
            sources = _build_source_references(source_type, retrieved_chunks)

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(
            ChatMessage(
                document_id=document.id,
                user_id=current_user.id,
                role="user",
                content=request.question,
                sources_json=None,
                created_at=now
            )
        )
        db.add(
            ChatMessage(
                document_id=document.id,
                user_id=current_user.id,
                role="assistant",
                content=answer,
                sources_json=json.dumps(sources),
                created_at=now
            )
        )
        db.commit()

        return {
            "document_id": request.document_id,
            "question": request.question,
            "source_type": source_type,
            "answer": answer,
            "sources": sources,
            "retrieved_chunks": retrieved_chunks
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Answer generation failed: {str(e)}"
        )


@app.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete one of the current user's documents: database records (cascading
    chunks and chat history), the uploaded file, and the FAISS index.
    """

    document = _get_owned_document(db, document_id, current_user)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    document_store.delete_document_files(document)

    db.delete(document)
    db.commit()

    return {
        "message": "Document deleted successfully.",
        "document_id": document_id
    }
