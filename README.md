# DocuMind AI

DocuMind AI is a full-stack PDF chatbot that lets users upload a document and ask natural-language questions with trusted, source-grounded answers.

The system extracts text from the PDF, splits it into chunks, builds embeddings, retrieves relevant context with FAISS, and generates an answer using DeepSeek with source page references.

---

## Features

- Upload PDFs and generate a unique `document_id`
- Page-aware text extraction with PyMuPDF
- Overlapping chunk creation for better retrieval
- SentenceTransformer embeddings + FAISS vector search
- DeepSeek-powered Q&A with source page references
- Collapsible retrieved-chunks panel in the UI

---

## Tech Stack

### Backend

- Python, FastAPI, Uvicorn
- PyMuPDF, SentenceTransformers, FAISS
- OpenAI-compatible DeepSeek API
- python-dotenv

### Frontend

- Next.js App Router
- Tailwind CSS
- Axios

---

## Project Workflow

```text
Upload PDF
	-> Extract text page by page
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
DEEPSEEK_API_KEY=your_key_here
# Optional: allow extra CORS origins in production
# ALLOWED_ORIGINS=https://your-frontend-domain.com
```

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

---

## API Endpoints

- `GET /`
- `GET /health`
- `POST /upload-pdf`
- `GET /documents`
- `POST /search`
- `POST /ask`
- `DELETE /documents/{document_id}`

---

## Deployment Notes

### Frontend (Vercel)

- Set `NEXT_PUBLIC_API_URL` to your backend URL.
- Ensure the build command is `npm run build`.
- Use the default Next.js output configuration.

### Backend (Render or Railway)

- Add `DEEPSEEK_API_KEY` to environment variables.
- Set `ALLOWED_ORIGINS` to the deployed frontend domain.
- Run with `uvicorn main:app --host 0.0.0.0 --port 8000`.

---

## Repository Hygiene

The root `.gitignore` already blocks the following:

- `backend/.env`, `frontend/.env.local`
- `backend/.venv`, `frontend/node_modules`
- `backend/uploads`, `__pycache__`

Keep uploads and caches out of version control.