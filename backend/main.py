from pathlib import Path
import os
import shutil
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from pdf_processor import extract_text_from_pdf, get_pdf_summary
from chunker import create_chunks_from_pages
from vector_store import VectorStore
from chatbot import answer_question_with_deepseek
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(
    title="PDF Chatbot AI Backend",
    description="Backend API for uploading PDFs and asking questions using RAG.",
    version="1.0.0"
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


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


# In-memory document storage
# Later we can replace this with database + persistent vector storage.
documents = {}


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


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Upload a PDF file, extract text, create chunks, and build vector index.
    """

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed."
        )

    document_id = str(uuid.uuid4())

    safe_filename = Path(file.filename).name.replace(" ", "_")
    file_path = UPLOAD_DIR / f"{document_id}_{safe_filename}"

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        pages = extract_text_from_pdf(str(file_path))

        if not pages:
            raise HTTPException(
                status_code=422,
                detail="No pages were detected in the uploaded PDF."
            )

        summary = get_pdf_summary(pages)

        chunks = create_chunks_from_pages(
            pages=pages,
            chunk_size=1000,
            overlap=200
        )

        if not chunks:
            raise HTTPException(
                status_code=422,
                detail="No readable text was extracted from the PDF."
            )

        vector_store = VectorStore()
        index_summary = vector_store.build_index(chunks)

        documents[document_id] = {
            "document_id": document_id,
            "filename": safe_filename,
            "file_path": str(file_path),
            "summary": summary,
            "chunks": chunks,
            "vector_store": vector_store
        }

        return {
            "message": "PDF uploaded, text extracted, chunks created, and vector index built successfully.",
            "document_id": document_id,
            "filename": safe_filename,
            "file_path": str(file_path),
            "summary": summary,
            "chunk_summary": {
                "total_chunks": len(chunks),
                "chunk_size": 1000,
                "overlap": 200
            },
            "vector_index": index_summary,
            "sample_chunks": chunks[:3]
        }

    except HTTPException:
        if file_path.exists():
            file_path.unlink()
        raise

    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=500,
            detail=f"PDF processing failed: {str(e)}"
        )


@app.get("/documents")
def list_documents():
    """
    List uploaded documents stored in memory.
    """

    return {
        "total_documents": len(documents),
        "documents": [
            {
                "document_id": doc_id,
                "filename": data["filename"],
                "summary": data["summary"]
            }
            for doc_id, data in documents.items()
        ]
    }


@app.post("/search")
def search_pdf(request: SearchRequest):
    """
    Search a specific uploaded PDF for chunks relevant to the question.
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

    if request.document_id not in documents:
        raise HTTPException(
            status_code=404,
            detail="Document not found. Please upload the PDF first."
        )

    try:
        vector_store = documents[request.document_id]["vector_store"]

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

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )


@app.post("/ask")
def ask_pdf(request: AskRequest):
    """
    Ask a question about a specific uploaded PDF.
    Uses FAISS retrieval + DeepSeek LLM answer generation.
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

    if request.document_id not in documents:
        raise HTTPException(
            status_code=404,
            detail="Document not found. Please upload the PDF first."
        )

    try:
        vector_store = documents[request.document_id]["vector_store"]

        retrieved_chunks = vector_store.search(
            query=request.question,
            top_k=request.top_k
        )

        if not retrieved_chunks:
            return {
                "document_id": request.document_id,
                "question": request.question,
                "answer": "The PDF does not contain enough information to answer this question.",
                "sources": [],
                "retrieved_chunks": []
            }

        answer = answer_question_with_deepseek(
            question=request.question,
            retrieved_chunks=retrieved_chunks
        )

        source_pages = sorted(
            list(set(chunk["page"] for chunk in retrieved_chunks))
        )

        return {
            "document_id": request.document_id,
            "question": request.question,
            "answer": answer,
            "sources": source_pages,
            "retrieved_chunks": retrieved_chunks
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Answer generation failed: {str(e)}"
        )


@app.delete("/documents/{document_id}")
def delete_document(document_id: str):
    """
    Delete a document from memory.
    """

    if document_id not in documents:
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    file_path = Path(documents[document_id]["file_path"])

    if file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            pass

    del documents[document_id]

    return {
        "message": "Document deleted successfully.",
        "document_id": document_id
    }