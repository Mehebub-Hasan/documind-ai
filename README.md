# DocuMind AI

**DocuMind AI** is a full-stack PDF chatbot application that allows users to upload a PDF document and ask natural-language questions about its content.

The system extracts text from the PDF, splits it into chunks, creates embeddings, stores them in a FAISS vector index, retrieves relevant document context, and generates answers using an LLM with source page references.

---

## Live Project Goal

DocuMind AI is designed to help users understand documents faster by allowing them to chat with PDF files instead of manually reading through long documents.

Users can:

- Upload a PDF
- Ask questions about the document
- Get AI-generated answers
- View source page references
- Inspect retrieved PDF chunks
- Continue a chat history for the uploaded document

---

## Features

### PDF Upload

- Upload PDF files from the frontend
- Backend receives and saves the document
- Each uploaded PDF receives a unique `document_id`

### PDF Text Extraction

- Extracts PDF text page by page using PyMuPDF
- Tracks page numbers for source references

### Text Chunking

- Splits extracted text into overlapping chunks
- Keeps page metadata with every chunk

### Embeddings and Vector Search

- Generates embeddings using SentenceTransformers
- Stores vectors in FAISS
- Retrieves the most relevant chunks for each question

### AI Question Answering

- Uses an LLM API to answer questions from retrieved PDF context
- Prevents unsupported hallucination by instructing the model to answer only from context
- Returns source page numbers

### Full-Stack Architecture

- FastAPI backend
- Next.js frontend
- Tailwind CSS UI
- FAISS vector search
- DeepSeek API integration

---

## Tech Stack

### Backend

- Python
- FastAPI
- Uvicorn
- PyMuPDF
- SentenceTransformers
- FAISS
- OpenAI-compatible DeepSeek API
- python-dotenv

### Frontend

- Next.js
- React
- Tailwind CSS
- Axios

---

## Project Workflow

```text
Upload PDF
↓
Extract text page by page
↓
Clean and chunk text
↓
Generate embeddings
↓
Store chunks in FAISS vector index
↓
User asks a question
↓
Retrieve relevant chunks
↓
Send context + question to LLM
↓
Return answer with source pages

PDF_Chatbot_AI/
│
├── backend/
│   ├── main.py
│   ├── pdf_processor.py
│   ├── chunker.py
│   ├── vector_store.py
│   ├── chatbot.py
│   ├── requirements.txt
│   ├── .env
│   └── .gitignore
│
├── frontend/
│   ├── app/
│   ├── package.json
│   ├── .env.local
│   └── ...
│
├── README.md
└── .gitignore