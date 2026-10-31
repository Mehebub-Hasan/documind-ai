## Live Demo

- Frontend: your Vercel live URL
- Backend API: https://documind-ai-backend-g9yi.onrender.com
- API Docs: https://documind-ai-backend-g9yi.onrender.com/docs

# DocuMind AI

DocuMind AI is a full-stack PDF chatbot that lets users upload a document and ask natural-language questions with trusted, source-grounded answers.

The system extracts text from the PDF, splits it into chunks, builds embeddings, retrieves relevant context with FAISS, and generates an answer using DeepSeek with source page references.

---

## Features

- Upload PDFs or Word .docx files and generate a unique `document_id`
- Page-aware PDF text extraction with PyMuPDF
- Word .docx support: paragraphs and tables extracted in document order, with block-level source references (no invented page numbers)
- Overlapping chunk creation for better retrieval
- OpenAI embeddings + FAISS vector search, with automatic fallback to local SentenceTransformers (`all-MiniLM-L6-v2`) when `OPENAI_API_KEY` is absent — uploads and search keep working fully offline
- DeepSeek-powered Q&A with source references (pages for PDFs, block ranges for Word)
- User accounts (register/login) with JWT auth and strict per-user document isolation
- Persistent storage: documents, chunks, and per-document chat history in a database
- FAISS indexes saved to disk and rebuilt automatically from the database if missing
- Private document library and restored chat history in the UI

---

## Tech Stack

### Backend

- Python, FastAPI, Uvicorn
- PyMuPDF (PDF text extraction), python-docx (Word text extraction)
- OpenAI embeddings + FAISS vector search (falls back to local SentenceTransformers when no API key is set)
- OpenAI-compatible DeepSeek API
- SQLAlchemy (SQLite for development, PostgreSQL for production)
- bcrypt password hashing + PyJWT tokens
- python-dotenv

### Frontend

- Next.js App Router
- Tailwind CSS
- Axios

---

## Project Workflow

```text
Upload PDF or DOCX
	-> Extract text (page by page / block by block)
	-> Clean + chunk text
	-> Generate embeddings
	-> Build FAISS vector index
Ask a question
	-> Retrieve relevant chunks
	-> Send context to LLM
	-> Return answer with source pages
```

---

## Environment Variables

### Backend (`backend/.env`)

```bash
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key
EMBEDDING_MODEL=text-embedding-3-small
# Local fallback embedder used when OPENAI_API_KEY is absent
LOCAL_EMBEDDING_MODEL=all-MiniLM-L6-v2

# Auth & persistence (defaults shown; SQLite default is for development only)
JWT_SECRET_KEY=change-me-to-a-long-random-string
# DATABASE_URL=sqlite:///./backend/documind.db
# DATABASE_URL=postgresql://user:pass@host/db   (postgres:// is auto-fixed)
# INDEX_STORAGE_DIR=backend/storage/indexes
# UPLOAD_DIR=backend/uploads

# Optional: allow extra CORS origins in production
# ALLOWED_ORIGINS=https://your-frontend-domain.com

# Email verification (6-digit OTP on signup) — delivered via the Resend
# HTTPS API (Render free instances block outbound SMTP). Without
# RESEND_API_KEY the backend runs in console mode: codes are printed to the
# server log instead of being emailed, and signup still works. The sandbox
# sender is onboarding@resend.dev; verify a domain at resend.com to send
# from your own address in production.
# RESEND_API_KEY=re_xxxxxxxxxx
```

Notes:

- If `JWT_SECRET_KEY` is not set, the backend falls back to an insecure
  development secret and logs a warning at startup. Always set it in production.
- `postgres://` URIs (e.g. from Render) are automatically normalized to the
  psycopg2 driver; `postgresql://` and `postgresql+psycopg2://` also work.

### Frontend (`frontend/.env.local`)

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

> Do not commit `.env` or `.env.local` files.

---

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

### Tests (backend)

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

### RAG Triad evaluation

```bash
cd backend
python -m eval.runner                                   # starter dataset
python -m eval.runner --dataset eval/golden_dataset.json --gate
```

Runs benchmark cases through the real pipeline (retrieval gate, DeepSeek
generation, attribution checks) and scores them with LLM-as-a-Judge metrics
on the RAG Triad: Context Relevance, Groundedness, and Answer Relevance.
Prints a scoring table and writes a detailed `backend/eval/eval_report.json`
(gitignored). Requires `DEEPSEEK_API_KEY`; benchmark documents and the eval
user persist in the configured database and are reused across runs.

`--gate` enforces regression floors (groundedness >= 0.8, answer relevance
>= 0.7, context relevance >= 0.5, plus deterministic refusal and citation
checks per case) and exits non-zero on failure. CI runs the golden dataset
with gates on every pull request and push to `main`
(`.github/workflows/rag-eval.yml`, needs the `DEEPSEEK_API_KEY` repo
secret; the report is uploaded as a workflow artifact).

---

## API Endpoints

Authentication (no token required): `POST /auth/register`, `POST /auth/login`.
All other endpoints require an `Authorization: Bearer <token>` header and only
touch the authenticated user's own documents.

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `GET /`
- `GET /health`
- `POST /upload-pdf`
- `POST /upload-docx`
- `GET /documents`
- `GET /documents/{document_id}` — document detail incl. the executive summary
  (generated lazily on first open for documents uploaded before the feature)
- `GET /documents/{document_id}/messages`
- `POST /search`
- `POST /ask`
- `DELETE /documents/{document_id}`

---

## Persistence & Multi-User Architecture

- **Database (SQLAlchemy):** `users`, `documents`, `document_chunks`, and
  `chat_messages` tables. Document and chunk rows cascade-delete with their
  document; uploads, chunks, summaries, and Q&A history all survive restarts.
- **Executive summaries:** every document gets a grounded executive summary
  (overview + cited key takeaways) generated once at upload and stored on the
  `documents` row; documents uploaded earlier get one lazily on first open.
  Generated by DeepSeek when `DEEPSEEK_API_KEY` is set — with takeaway
  citations validated against the excerpts actually provided — and otherwise
  by a deterministic extractive fallback (verbatim excerpts with page/block
  labels), so uploads work fully offline. Existing databases gain the column
  via a startup migration; no manual steps.
- **FAISS indexes:** written to `INDEX_STORAGE_DIR/{document_id}.faiss` at
  upload time. On query, indexes are served from an in-memory cache, loaded
  from disk when cold, and rebuilt from the stored `document_chunks` rows if
  the file is missing (e.g. after a container restart).
- **Isolation:** every document/Q&A route resolves the user from the verified
  JWT and filters by `user_id`. Another user's document is indistinguishable
  from a missing one (404). User ids are never read from request bodies.
- **Deletion:** removes the DB rows (cascading), the uploaded file, and the
  `.faiss` index.

---

## Deployment Notes

### Frontend (Vercel)

- Set `NEXT_PUBLIC_API_URL` to your backend URL.
- Ensure the build command is `npm run build`.
- Use the default Next.js output configuration.
- Confirm no secrets are stored in `frontend/.env.local` before deployment
  (only `NEXT_PUBLIC_*` values belong there; backend API keys never reach the
  frontend). The auth token is kept in the browser's localStorage.

### Backend (Render or Railway)

- Create a PostgreSQL database and set `DATABASE_URL` to its connection
  string (`postgres://` prefixes are fixed automatically). Do not use the
  SQLite default in production — it is local/disk-only.
- Set `JWT_SECRET_KEY` to a long random string.
- Add `DEEPSEEK_API_KEY` and `OPENAI_API_KEY` to environment variables.
- Optionally set `ALLOWED_ORIGINS` to the deployed frontend domain.
- Run with `uvicorn main:app --host 0.0.0.0 --port 8000`.
- Confirm `.env` files are not committed and keep keys in the host dashboard.
- Note: on ephemeral filesystems, uploaded files and `.faiss` indexes are lost
  on redeploy, but documents/chunks/chat history live in the database and
  indexes are rebuilt automatically on first query.

---

## Repository Hygiene

The root `.gitignore` already blocks the following:

- `backend/.env`, `frontend/.env.local`
- `backend/.venv`, `frontend/node_modules`
- `backend/uploads`, `__pycache__`

Keep uploads and caches out of version control.