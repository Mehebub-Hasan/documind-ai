"use client";

import { useState } from "react";
import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const EXAMPLE_QUESTIONS = [
  "Summarize the main idea of this PDF.",
  "What are the top 5 key points?",
  "List the most important dates and decisions.",
  "Who are the main stakeholders mentioned?",
];

const WORKFLOW_STEPS = [
  "Upload a PDF",
  "Extract text page by page",
  "Chunk and embed content",
  "Retrieve relevant passages",
  "Generate grounded answers",
];

const formatFileSize = (bytes) => {
  if (!bytes) return "0 KB";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
};

const getSnippet = (text, maxLength = 280) => {
  if (!text) return "";
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= maxLength) return cleaned;
  return `${cleaned.slice(0, maxLength).trim()}...`;
};

export default function Home() {
  const [file, setFile] = useState(null);
  const [documentId, setDocumentId] = useState("");
  const [filename, setFilename] = useState("");
  const [summary, setSummary] = useState(null);

  const [question, setQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [retrievedChunks, setRetrievedChunks] = useState([]);

  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null;
    setFile(selectedFile);
    setError("");
  };

  const handleUpload = async () => {
    if (!file) {
      setError("Please select a PDF file first.");
      return;
    }

    setError("");
    setChatHistory([]);
    setRetrievedChunks([]);
    setQuestion("");
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await axios.post(`${API_URL}/upload-pdf`, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setDocumentId(response.data.document_id);
      setFilename(response.data.filename);
      setSummary(response.data.summary);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "PDF upload failed. Make sure the backend is running."
      );
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    if (!documentId) {
      setError("Upload a PDF before asking a question.");
      return;
    }

    if (!question.trim()) {
      setError("Please write a question.");
      return;
    }

    const currentQuestion = question.trim();

    setError("");
    setAsking(true);
    setQuestion("");
    setRetrievedChunks([]);

    try {
      const response = await axios.post(`${API_URL}/ask`, {
        document_id: documentId,
        question: currentQuestion,
        top_k: 6,
      });

      const newMessage = {
        id: Date.now(),
        question: currentQuestion,
        answer: response.data.answer,
        sources: response.data.sources || [],
      };

      setChatHistory((prev) => [newMessage, ...prev]);
      setRetrievedChunks(response.data.retrieved_chunks || []);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Question answering failed. Check backend or API key."
      );
    } finally {
      setAsking(false);
    }
  };

  const handleClearDocument = async () => {
    if (!documentId) return;

    try {
      await axios.delete(`${API_URL}/documents/${documentId}`);
    } catch (err) {
      console.warn("Document delete failed:", err);
    }

    setFile(null);
    setDocumentId("");
    setFilename("");
    setSummary(null);
    setQuestion("");
    setChatHistory([]);
    setRetrievedChunks([]);
    setError("");
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-slate-950 text-slate-100">
      <div className="pointer-events-none absolute inset-0">
        <div className="float-slow absolute -top-40 left-8 h-72 w-72 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="float-slower absolute right-10 top-20 h-72 w-72 rounded-full bg-purple-500/20 blur-3xl" />
        <div className="float-slow absolute bottom-10 left-1/3 h-80 w-80 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.18),_transparent_55%)]" />
      </div>

      <section className="relative mx-auto flex max-w-6xl flex-col gap-10 px-6 py-10 lg:py-14">
        <header className="animate-fade-in rounded-3xl border border-slate-800/80 bg-slate-900/70 p-8 shadow-[0_25px_60px_-30px_rgba(15,23,42,0.9)] backdrop-blur">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-300/80">
                DocuMind AI
              </p>

              <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white sm:text-5xl">
                Your AI document analyst for every PDF
              </h1>

              <p className="mt-4 text-base leading-7 text-slate-300">
                Upload a PDF and get grounded answers in seconds. DocuMind AI
                summarizes, extracts key points, and cites source pages so you
                can trust every response.
              </p>

              <div className="mt-6 flex flex-wrap gap-3 text-sm">
                {[
                  "PDF Upload",
                  "Text Extraction",
                  "RAG",
                  "FAISS Search",
                  "Source Pages",
                  "LLM Q&A",
                ].map((item) => (
                  <span
                    key={item}
                    className="rounded-full border border-slate-700/80 bg-slate-950/60 px-4 py-2 text-slate-200"
                  >
                    {item}
                  </span>
                ))}
              </div>
            </div>

            <div className="w-full max-w-sm rounded-2xl border border-slate-800/80 bg-slate-950/60 p-6 text-sm text-slate-300">
              <p className="font-semibold text-slate-200">How DocuMind works</p>
              <ol className="mt-4 space-y-3">
                {WORKFLOW_STEPS.map((step, index) => (
                  <li key={step} className="flex items-start gap-3">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-xs font-semibold text-cyan-300">
                      {index + 1}
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
              <div className="mt-5 rounded-xl border border-slate-800/70 bg-slate-900/60 p-4 text-xs text-slate-400">
                <p className="font-semibold text-slate-200">Best results</p>
                <p className="mt-2">
                  Ask for summaries, timelines, or decision points to get the
                  clearest answers.
                </p>
              </div>
            </div>
          </div>
        </header>

        {error && (
          <div className="animate-fade-in-delayed rounded-2xl border border-red-500/40 bg-red-950/50 p-5 text-sm text-red-200">
            <p className="font-semibold">Something went wrong</p>
            <p className="mt-2 text-red-300">{error}</p>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
          <div className="animate-fade-in-delayed rounded-3xl border border-slate-800/80 bg-slate-900/70 p-6 shadow-[0_20px_50px_-35px_rgba(15,23,42,0.9)] backdrop-blur">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Upload your PDF</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Securely upload a PDF to extract, chunk, and index the
                  document for instant semantic search.
                </p>
              </div>
              <span
                className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                  documentId
                    ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
                    : "border-slate-700 bg-slate-950/60 text-slate-400"
                }`}
              >
                {documentId ? "Ready" : "Waiting"}
              </span>
            </div>

            <label
              htmlFor="pdf-upload"
              className="mt-5 flex cursor-pointer flex-col items-center gap-3 rounded-2xl border border-dashed border-slate-700/80 bg-slate-950/60 px-4 py-6 text-center transition hover:border-cyan-400 hover:bg-slate-950"
            >
              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 p-3">
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M12 16V5M12 5L7 10M12 5L17 10"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M4 19H20"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
              <div>
                <p className="text-sm font-semibold text-slate-200">
                  Click to upload a PDF
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Select a PDF from your computer. Max file size depends on the
                  server.
                </p>
              </div>
            </label>
            <input
              id="pdf-upload"
              type="file"
              accept="application/pdf"
              onChange={handleFileChange}
              className="sr-only"
            />

            {file && (
              <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-300">
                <p className="font-semibold text-slate-200">Selected file</p>
                <div className="mt-2 flex items-center justify-between gap-4 text-xs text-slate-400">
                  <span className="truncate">{file.name}</span>
                  <span>{formatFileSize(file.size)}</span>
                </div>
              </div>
            )}

            <button
              onClick={handleUpload}
              disabled={uploading}
              className="mt-4 w-full rounded-xl bg-cyan-400 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {uploading ? "Processing PDF..." : "Upload & Process"}
            </button>

            {documentId && (
              <button
                onClick={handleClearDocument}
                className="mt-3 w-full rounded-xl border border-slate-700/80 px-4 py-3 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
              >
                Clear Current Document
              </button>
            )}

            {uploading && (
              <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-5 text-sm text-slate-300">
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-slate-200">
                    Processing document
                  </span>
                  <span className="loading-dots">
                    <span />
                    <span />
                    <span />
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  Extracting text, building embeddings, and indexing chunks.
                </p>
              </div>
            )}

            {documentId && (
              <div className="mt-5 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5 text-sm text-emerald-100">
                <p className="font-semibold">Document ready</p>
                <p className="mt-3 text-xs text-emerald-200/80">{filename}</p>
                <p className="mt-2 break-all text-xs text-emerald-200/80">
                  Document ID: {documentId}
                </p>
              </div>
            )}

            {summary && (
              <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-5 text-sm">
                <p className="font-semibold text-slate-200">Document summary</p>
                <div className="mt-3 grid gap-3 text-xs text-slate-400 sm:grid-cols-3">
                  <div>
                    <p className="text-slate-500">Total pages</p>
                    <p className="mt-1 text-base font-semibold text-slate-200">
                      {summary.total_pages}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500">Non-empty pages</p>
                    <p className="mt-1 text-base font-semibold text-slate-200">
                      {summary.non_empty_pages}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500">Characters</p>
                    <p className="mt-1 text-base font-semibold text-slate-200">
                      {summary.total_characters}
                    </p>
                  </div>
                </div>
                <p className="mt-4 text-xs text-slate-500">Preview</p>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  {summary.preview_text || "No preview text available."}
                </p>
              </div>
            )}

          </div>

          <div className="rounded-3xl border border-slate-800/80 bg-slate-900/70 p-6 shadow-[0_20px_50px_-35px_rgba(15,23,42,0.9)] backdrop-blur">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Ask DocuMind AI</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Ask detailed questions and receive grounded answers with
                  source page references.
                </p>
              </div>
              <span
                className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                  documentId
                    ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-200"
                    : "border-slate-700 bg-slate-950/60 text-slate-400"
                }`}
              >
                {documentId ? "Document connected" : "Upload a PDF first"}
              </span>
            </div>

            <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Example: Summarize the main idea of this PDF."
                className="min-h-32 w-full resize-none rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-100 outline-none focus:border-cyan-400"
              />

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <button
                  onClick={handleAsk}
                  disabled={asking || !documentId}
                  className="rounded-xl bg-purple-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-purple-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {asking ? "Generating answer..." : "Ask PDF"}
                </button>

                <span className="text-xs text-slate-500">
                  {documentId
                    ? "Answers reference source pages when available."
                    : "Upload a PDF to enable questions."}
                </span>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {EXAMPLE_QUESTIONS.map((text) => (
                <button
                  key={text}
                  onClick={() => setQuestion(text)}
                  className="rounded-full border border-slate-700/80 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:bg-slate-800"
                >
                  {text}
                </button>
              ))}
            </div>

            {asking && (
              <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-5 text-sm text-slate-300">
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-slate-200">
                    Generating answer
                  </span>
                  <span className="loading-dots">
                    <span />
                    <span />
                    <span />
                  </span>
                </div>
                <div className="mt-4 space-y-3">
                  <div className="h-3 w-3/4 rounded-full bg-slate-800" />
                  <div className="h-3 w-full rounded-full bg-slate-800" />
                  <div className="h-3 w-2/3 rounded-full bg-slate-800" />
                </div>
              </div>
            )}

            {!asking && chatHistory.length === 0 && (
              <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-sm text-slate-400">
                Upload a PDF and ask your first question. Your conversation
                history will appear here.
              </div>
            )}

            <div className="mt-6 space-y-5">
              {chatHistory.map((item) => (
                <div
                  key={item.id}
                  className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-purple-300">
                      Question
                    </p>
                    <span className="rounded-full border border-slate-700/80 px-3 py-1 text-xs text-slate-400">
                      Answered
                    </span>
                  </div>

                  <p className="mt-3 text-sm text-slate-100">
                    {item.question}
                  </p>

                  <div className="mt-5 rounded-xl border border-slate-800 bg-slate-900/80 p-4">
                    <h3 className="text-sm font-semibold text-cyan-300">
                      Answer
                    </h3>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-200">
                      {item.answer}
                    </p>
                  </div>

                  {item.sources.length > 0 && (
                    <div className="mt-4">
                      <p className="text-xs font-semibold text-slate-300">
                        Source pages
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.sources.map((page) => (
                          <span
                            key={page}
                            className="rounded-full border border-cyan-800 bg-cyan-950 px-3 py-1 text-xs text-cyan-200"
                          >
                            Page {page}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {retrievedChunks.length > 0 && (
              <details className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
                <summary className="cursor-pointer text-sm font-semibold text-slate-200">
                  View supporting evidence ({retrievedChunks.length})
                </summary>

                <div className="mt-4 space-y-4">
                  {retrievedChunks.map((chunk) => (
                    <div
                      key={chunk.chunk_id}
                      className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-semibold text-slate-200">
                          Page {chunk.page}
                        </p>
                        <span className="text-xs text-slate-500">
                          Relevance {chunk.score.toFixed(3)}
                        </span>
                      </div>
                      <p className="mt-2 leading-6 text-slate-300">
                        {getSnippet(chunk.text)}
                      </p>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}