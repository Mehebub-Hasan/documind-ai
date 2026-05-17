"use client";

import { useState } from "react";
import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

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

  const handleUpload = async () => {
    if (!file) {
      setError("Please select a PDF file first.");
      return;
    }

    setError("");
    setChatHistory([]);
    setRetrievedChunks([]);
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
      setError("Please upload and process a PDF first.");
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
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto max-w-7xl px-6 py-10">
        <div className="rounded-3xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900 to-purple-950 p-8 shadow-2xl">
          <p className="mb-3 text-sm font-semibold uppercase tracking-widest text-cyan-300">
            DocuMind AI
          </p>

          <h1 className="text-4xl font-bold tracking-tight md:text-5xl">
            Chat with any PDF using AI
          </h1>

          <p className="mt-4 max-w-3xl text-lg leading-8 text-slate-300">
            Upload a PDF, ask natural-language questions, and get accurate
            answers grounded in the document with source page references.
          </p>

          <div className="mt-6 flex flex-wrap gap-3">
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
                className="rounded-full border border-slate-700 bg-slate-800/70 px-4 py-2 text-sm text-slate-200"
              >
                {item}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-3">
          <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 lg:col-span-1">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Upload PDF</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Upload a PDF document. The backend will extract text, create
                  chunks, generate embeddings, and build a vector index.
                </p>
              </div>
            </div>

            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="mt-5 w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-sm text-slate-300"
            />

            <button
              onClick={handleUpload}
              disabled={uploading}
              className="mt-4 w-full rounded-xl bg-cyan-500 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {uploading ? "Processing PDF..." : "Upload & Process"}
            </button>

            {documentId && (
              <button
                onClick={handleClearDocument}
                className="mt-3 w-full rounded-xl border border-slate-700 px-4 py-3 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
              >
                Clear Current Document
              </button>
            )}

            {error && (
              <div className="mt-5 rounded-xl border border-red-800 bg-red-950/40 p-4 text-sm text-red-300">
                {error}
              </div>
            )}

            {documentId && (
              <div className="mt-5 rounded-xl border border-emerald-800 bg-emerald-950/40 p-4 text-sm">
                <p className="font-semibold text-emerald-300">
                  PDF processed successfully
                </p>

                <p className="mt-3 text-slate-300">
                  <span className="text-slate-400">File:</span> {filename}
                </p>

                <p className="mt-2 break-all text-slate-300">
                  <span className="text-slate-400">Document ID:</span>{" "}
                  {documentId}
                </p>
              </div>
            )}

            {summary && (
              <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm">
                <p className="font-semibold text-slate-200">Document Summary</p>

                <div className="mt-3 space-y-2 text-slate-300">
                  <p>Total pages: {summary.total_pages}</p>
                  <p>Non-empty pages: {summary.non_empty_pages}</p>
                  <p>Total characters: {summary.total_characters}</p>
                </div>
              </div>
            )}

            <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400">
              <p className="font-semibold text-slate-300">How it works</p>
              <ol className="mt-3 list-decimal space-y-2 pl-4">
                <li>Upload a PDF</li>
                <li>Text is extracted page by page</li>
                <li>Document is split into chunks</li>
                <li>FAISS retrieves relevant chunks</li>
                <li>AI answers using document context</li>
              </ol>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 lg:col-span-2">
            <h2 className="text-xl font-semibold">Ask Questions</h2>

            <p className="mt-2 text-sm leading-6 text-slate-400">
              Ask anything about the uploaded PDF. DocuMind AI will answer using
              retrieved document context and show source pages.
            </p>

            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Example: Summarize the main idea of this PDF."
              className="mt-5 min-h-32 w-full rounded-xl border border-slate-700 bg-slate-950 p-4 text-slate-100 outline-none focus:border-cyan-400"
            />

            <div className="mt-4 flex flex-wrap gap-3">
              <button
                onClick={handleAsk}
                disabled={asking}
                className="rounded-xl bg-purple-500 px-6 py-3 font-semibold text-white transition hover:bg-purple-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {asking ? "Generating answer..." : "Ask PDF"}
              </button>

              <button
                onClick={() =>
                  setQuestion("Summarize the main idea of this PDF.")
                }
                className="rounded-xl border border-slate-700 px-5 py-3 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
              >
                Try Summary
              </button>

              <button
                onClick={() =>
                  setQuestion("What are the key points discussed in this PDF?")
                }
                className="rounded-xl border border-slate-700 px-5 py-3 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
              >
                Try Key Points
              </button>
            </div>

            {chatHistory.length === 0 && (
              <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950 p-6 text-slate-400">
                Upload a PDF and ask your first question. Your answers will
                appear here with source page references.
              </div>
            )}

            <div className="mt-6 space-y-5">
              {chatHistory.map((item) => (
                <div
                  key={item.id}
                  className="rounded-2xl border border-slate-800 bg-slate-950 p-6"
                >
                  <p className="text-sm font-semibold uppercase tracking-wide text-purple-300">
                    Question
                  </p>

                  <p className="mt-2 text-slate-100">{item.question}</p>

                  <h3 className="mt-5 text-lg font-semibold text-cyan-300">
                    Answer
                  </h3>

                  <p className="mt-3 whitespace-pre-wrap leading-7 text-slate-200">
                    {item.answer}
                  </p>

                  {item.sources.length > 0 && (
                    <div className="mt-5">
                      <p className="text-sm font-semibold text-slate-300">
                        Source pages
                      </p>

                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.sources.map((page) => (
                          <span
                            key={page}
                            className="rounded-full border border-cyan-800 bg-cyan-950 px-3 py-1 text-sm text-cyan-200"
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
              <details className="mt-6 rounded-2xl border border-slate-800 bg-slate-950 p-5">
                <summary className="cursor-pointer font-semibold text-slate-200">
                  View retrieved PDF chunks
                </summary>

                <div className="mt-4 space-y-4">
                  {retrievedChunks.map((chunk) => (
                    <div
                      key={chunk.chunk_id}
                      className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm"
                    >
                      <p className="font-semibold text-slate-300">
                        Page {chunk.page} · Score {chunk.score.toFixed(3)}
                      </p>

                      <p className="mt-2 leading-6 text-slate-400">
                        {chunk.text}
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