"use client";

import { useCallback, useEffect, useState } from "react";
import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const TOKEN_STORAGE_KEY = "documind_token";
const USER_STORAGE_KEY = "documind_user";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

const EXAMPLE_QUESTIONS = [
  "Summarize the main idea of this document.",
  "What are the top 5 key points?",
  "List the most important dates and decisions.",
  "Who are the main stakeholders mentioned?",
];

const WORKFLOW_STEPS = [
  "Upload a PDF or Word document",
  "Extract text from pages or blocks",
  "Chunk and embed content",
  "Retrieve relevant passages",
  "Generate grounded answers",
];

const getFileExtension = (name) => {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
};

const validateSelectedFile = (file) => {
  const extension = getFileExtension(file.name);

  if (extension === ".doc") {
    return "Legacy .doc files are not supported. Please convert the document to .docx and upload again.";
  }

  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return "Unsupported file type. Please select a .pdf or .docx file.";
  }

  return "";
};

const formatChunkLocation = (chunk) => {
  if (chunk.page !== undefined && chunk.page !== null) {
    return `Page ${chunk.page}`;
  }

  if (chunk.block_start !== undefined && chunk.block_start !== null) {
    return chunk.block_start === chunk.block_end
      ? `Block ${chunk.block_start}`
      : `Blocks ${chunk.block_start}-${chunk.block_end}`;
  }

  return "Unknown source";
};

const formatSourceChip = (source) => {
  return typeof source === "string"
    ? source.charAt(0).toUpperCase() + source.slice(1)
    : `Page ${source}`;
};

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

const formatDate = (isoString) => {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
};

// Shared Axios client: attaches the Bearer token to every request and
// broadcasts a session-expired event on 401 responses.
const api = axios.create({ baseURL: API_URL });

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

const unauthorizedListeners = new Set();

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url || "";
    const isAuthCall =
      url.includes("/auth/login") || url.includes("/auth/register");

    if (status === 401 && !isAuthCall) {
      unauthorizedListeners.forEach((listener) => listener());
    }

    return Promise.reject(error);
  }
);

export default function Home() {
  // ---- Auth state ----
  const [sessionChecked, setSessionChecked] = useState(false);
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ name: "", email: "", password: "" });
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");

  // ---- Document library state ----
  const [documents, setDocuments] = useState([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);

  // ---- Workspace state ----
  const [file, setFile] = useState(null);
  const [documentId, setDocumentId] = useState("");
  const [filename, setFilename] = useState("");
  const [summary, setSummary] = useState(null);
  const [sourceType, setSourceType] = useState("");

  const [question, setQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [retrievedChunks, setRetrievedChunks] = useState([]);

  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  const resetWorkspace = useCallback(() => {
    setFile(null);
    setDocumentId("");
    setFilename("");
    setSummary(null);
    setSourceType("");
    setQuestion("");
    setChatHistory([]);
    setRetrievedChunks([]);
    setError("");
  }, []);

  const logout = useCallback(() => {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    window.localStorage.removeItem(USER_STORAGE_KEY);
    setUser(null);
    setDocuments([]);
    setAuthError("");
    resetWorkspace();
  }, [resetWorkspace]);

  // Clear the session automatically whenever the API reports 401.
  useEffect(() => {
    const onUnauthorized = () => logout();
    unauthorizedListeners.add(onUnauthorized);
    return () => unauthorizedListeners.delete(onUnauthorized);
  }, [logout]);

  const loadDocuments = useCallback(async () => {
    setDocumentsLoading(true);
    try {
      const response = await api.get("/documents");
      setDocuments(response.data.documents || []);
    } catch {
      // 401 is handled by the interceptor; other failures keep the list.
    } finally {
      setDocumentsLoading(false);
    }
  }, []);

  // Restore a saved session on first load.
  useEffect(() => {
    let cancelled = false;

    const restoreSession = async () => {
      // Defer past the effect body so no state is set synchronously
      // while the effect runs.
      await Promise.resolve();
      if (cancelled) return;

      const storedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
      const storedUser = window.localStorage.getItem(USER_STORAGE_KEY);

      if (!storedToken || !storedUser) {
        setSessionChecked(true);
        return;
      }

      let cachedUser = null;

      try {
        cachedUser = JSON.parse(storedUser);
      } catch {
        window.localStorage.removeItem(USER_STORAGE_KEY);
      }

      if (!cachedUser) {
        setSessionChecked(true);
        return;
      }

      setUser(cachedUser);

      try {
        const response = await api.get("/auth/me");
        if (cancelled) return;

        setUser(response.data.user);
        await loadDocuments();
      } catch {
        // Invalid or expired token: the 401 interceptor logs the session out.
      } finally {
        if (!cancelled) {
          setSessionChecked(true);
        }
      }
    };

    restoreSession();

    return () => {
      cancelled = true;
    };
  }, [loadDocuments]);

  const updateAuthForm = (field) => (event) =>
    setAuthForm((prev) => ({ ...prev, [field]: event.target.value }));

  const handleAuthSubmit = async (event) => {
    event.preventDefault();
    setAuthError("");
    setAuthBusy(true);

    const endpoint = authMode === "login" ? "/auth/login" : "/auth/register";
    const payload =
      authMode === "login"
        ? { email: authForm.email, password: authForm.password }
        : {
            name: authForm.name,
            email: authForm.email,
            password: authForm.password,
          };

    try {
      const response = await api.post(endpoint, payload);

      window.localStorage.setItem(TOKEN_STORAGE_KEY, response.data.token);
      window.localStorage.setItem(
        USER_STORAGE_KEY,
        JSON.stringify(response.data.user)
      );

      setUser(response.data.user);
      setAuthForm({ name: "", email: "", password: "" });
      loadDocuments();
    } catch (err) {
      setAuthError(
        err.response?.data?.detail ||
          "Authentication failed. Make sure the backend is running."
      );
    } finally {
      setAuthBusy(false);
    }
  };

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null;

    if (selectedFile) {
      const validationError = validateSelectedFile(selectedFile);

      if (validationError) {
        event.target.value = "";
        setFile(null);
        setError(validationError);
        return;
      }
    }

    setFile(selectedFile);
    setError("");
  };

  const handleUpload = async () => {
    if (!file) {
      setError("Please select a file first.");
      return;
    }

    setError("");
    setChatHistory([]);
    setRetrievedChunks([]);
    setQuestion("");
    setUploading(true);

    try {
      const endpoint =
        getFileExtension(file.name) === ".docx" ? "/upload-docx" : "/upload-pdf";

      const formData = new FormData();
      formData.append("file", file);

      const response = await api.post(endpoint, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setDocumentId(response.data.document_id);
      setFilename(response.data.filename);
      setSummary(response.data.summary);
      setSourceType(response.data.source_type || "pdf");
      loadDocuments();
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Upload failed. Make sure the backend is running."
      );
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    if (!documentId) {
      setError("Upload or select a document before asking a question.");
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
      const response = await api.post("/ask", {
        document_id: documentId,
        question: currentQuestion,
        top_k: 6,
      });

      const newMessage = {
        id: Date.now(),
        question: currentQuestion,
        answer: response.data.answer,
        sources: response.data.sources || [],
        sourceType: response.data.source_type || "pdf",
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

  const handleDeleteDocument = async () => {
    if (!documentId) return;

    try {
      await api.delete(`/documents/${documentId}`);
      loadDocuments();
    } catch (err) {
      setError(
        err.response?.data?.detail || "Could not delete the document."
      );
      return;
    }

    resetWorkspace();
  };

  const selectDocument = async (doc) => {
    setError("");
    setFile(null);
    setRetrievedChunks([]);
    setQuestion("");
    setDocumentId(doc.document_id);
    setFilename(doc.filename);
    setSummary(doc.summary || null);
    setSourceType(doc.source_type || "pdf");

    try {
      const response = await api.get(`/documents/${doc.document_id}/messages`);
      const docSourceType = doc.source_type || "pdf";
      const history = [];
      let pendingQuestion = null;

      for (const message of response.data.messages || []) {
        if (message.role === "user") {
          pendingQuestion = message.content;
        } else if (message.role === "assistant") {
          history.push({
            id: message.id,
            question: pendingQuestion || "(no question recorded)",
            answer: message.content,
            sources: message.sources || [],
            sourceType: docSourceType,
          });
          pendingQuestion = null;
        }
      }

      setChatHistory(history.reverse());
    } catch {
      setChatHistory([]);
    }
  };

  // ---- Auth gate view ----

  if (!sessionChecked) {
    return <main className="min-h-screen bg-slate-950" />;
  }

  if (!user) {
    const isLogin = authMode === "login";

    return (
      <main className="relative min-h-screen overflow-hidden bg-slate-950 text-slate-100">
        <div className="pointer-events-none absolute inset-0">
          <div className="float-slow absolute -top-40 left-8 h-72 w-72 rounded-full bg-cyan-500/20 blur-3xl" />
          <div className="float-slower absolute bottom-10 right-10 h-72 w-72 rounded-full bg-purple-500/20 blur-3xl" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.18),_transparent_55%)]" />
        </div>

        <section className="relative mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12">
          <div className="animate-fade-in rounded-3xl border border-slate-800/80 bg-slate-900/70 p-8 shadow-[0_25px_60px_-30px_rgba(15,23,42,0.9)] backdrop-blur">
            <p className="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-300/80">
              DocuMind AI
            </p>

            <h1 className="mt-4 text-2xl font-semibold tracking-tight text-white">
              {isLogin ? "Welcome back" : "Create your account"}
            </h1>

            <p className="mt-3 text-sm leading-6 text-slate-300">
              Sign in to upload PDFs and Word documents, ask grounded
              questions, and keep your private document library and chat
              history.
            </p>

            <div className="mt-6 grid grid-cols-2 gap-2 rounded-xl border border-slate-800 bg-slate-950/70 p-1 text-sm font-semibold">
              <button
                type="button"
                onClick={() => {
                  setAuthMode("login");
                  setAuthError("");
                }}
                className={`rounded-lg px-3 py-2 transition ${
                  isLogin
                    ? "bg-cyan-400 text-slate-950"
                    : "text-slate-300 hover:bg-slate-800"
                }`}
              >
                Sign in
              </button>
              <button
                type="button"
                onClick={() => {
                  setAuthMode("register");
                  setAuthError("");
                }}
                className={`rounded-lg px-3 py-2 transition ${
                  !isLogin
                    ? "bg-cyan-400 text-slate-950"
                    : "text-slate-300 hover:bg-slate-800"
                }`}
              >
                Create account
              </button>
            </div>

            <form onSubmit={handleAuthSubmit} className="mt-6 space-y-4">
              {!isLogin && (
                <div>
                  <label
                    htmlFor="auth-name"
                    className="text-xs font-semibold text-slate-400"
                  >
                    Name
                  </label>
                  <input
                    id="auth-name"
                    type="text"
                    value={authForm.name}
                    onChange={updateAuthForm("name")}
                    required
                    autoComplete="name"
                    className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-400"
                  />
                </div>
              )}

              <div>
                <label
                  htmlFor="auth-email"
                  className="text-xs font-semibold text-slate-400"
                >
                  Email
                </label>
                <input
                  id="auth-email"
                  type="email"
                  value={authForm.email}
                  onChange={updateAuthForm("email")}
                  required
                  autoComplete="email"
                  className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-400"
                />
              </div>

              <div>
                <label
                  htmlFor="auth-password"
                  className="text-xs font-semibold text-slate-400"
                >
                  Password
                </label>
                <input
                  id="auth-password"
                  type="password"
                  value={authForm.password}
                  onChange={updateAuthForm("password")}
                  required
                  autoComplete={isLogin ? "current-password" : "new-password"}
                  className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-400"
                />
                {!isLogin && (
                  <p className="mt-1 text-xs text-slate-500">
                    At least 8 characters.
                  </p>
                )}
              </div>

              {authError && (
                <div className="rounded-xl border border-red-500/40 bg-red-950/50 p-4 text-sm text-red-200">
                  {authError}
                </div>
              )}

              <button
                type="submit"
                disabled={authBusy}
                className="w-full rounded-xl bg-cyan-400 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {authBusy
                  ? "Please wait..."
                  : isLogin
                    ? "Sign in"
                    : "Create account"}
              </button>
            </form>
          </div>
        </section>
      </main>
    );
  }

  // ---- Authenticated app view ----

  return (
    <main className="relative min-h-screen overflow-hidden bg-slate-950 text-slate-100">
      <div className="pointer-events-none absolute inset-0">
        <div className="float-slow absolute -top-40 left-8 h-72 w-72 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="float-slower absolute right-10 top-20 h-72 w-72 rounded-full bg-purple-500/20 blur-3xl" />
        <div className="float-slow absolute bottom-10 left-1/3 h-80 w-80 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.18),_transparent_55%)]" />
      </div>

      <header className="relative z-10 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-cyan-300/90">
            DocuMind AI
          </p>

          <div className="flex items-center gap-3 text-sm">
            <span className="font-semibold text-slate-200">{user.name}</span>
            <span className="hidden text-xs text-slate-500 sm:inline">
              {user.email}
            </span>
            <button
              onClick={logout}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-800"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      <section className="relative mx-auto flex max-w-6xl flex-col gap-10 px-6 py-10 lg:py-14">
        <header className="animate-fade-in rounded-3xl border border-slate-800/80 bg-slate-900/70 p-8 shadow-[0_25px_60px_-30px_rgba(15,23,42,0.9)] backdrop-blur">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-2xl">
              <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                Your AI document analyst for PDFs and Word files
              </h1>

              <p className="mt-4 text-base leading-7 text-slate-300">
                Upload a PDF or Word document and get grounded answers in
                seconds. DocuMind AI summarizes, extracts key points, and cites
                source pages or document blocks so you can trust every
                response.
              </p>

              <div className="mt-6 flex flex-wrap gap-3 text-sm">
                {[
                  "PDF & Word Upload",
                  "Text Extraction",
                  "RAG",
                  "FAISS Search",
                  "Source Citations",
                  "Chat History",
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
          <div className="flex flex-col gap-6">
            <div className="animate-fade-in-delayed rounded-3xl border border-slate-800/80 bg-slate-900/70 p-6 shadow-[0_20px_50px_-35px_rgba(15,23,42,0.9)] backdrop-blur">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">Upload your document</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    Securely upload a PDF or Word .docx file to extract, chunk,
                    and index the document for instant semantic search.
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
                htmlFor="document-upload"
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
                    Click to upload a PDF or Word document
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Select a .pdf or .docx file from your computer. Legacy .doc
                    files must be converted to .docx first.
                  </p>
                </div>
              </label>
              <input
                id="document-upload"
                type="file"
                accept=".pdf,.docx"
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
                {uploading ? "Processing document..." : "Upload & Process"}
              </button>

              {documentId && (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <button
                    onClick={resetWorkspace}
                    className="rounded-xl border border-slate-700/80 px-4 py-3 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
                  >
                    Upload Another
                  </button>
                  <button
                    onClick={handleDeleteDocument}
                    className="rounded-xl border border-red-500/40 px-4 py-3 text-sm font-semibold text-red-200 transition hover:bg-red-950/60"
                  >
                    Delete Document
                  </button>
                </div>
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
                  <p className="font-semibold">
                    Document ready
                    <span className="ml-2 rounded-full border border-emerald-400/40 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide">
                      {sourceType === "docx" ? "Word" : "PDF"}
                    </span>
                  </p>
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
                    {sourceType === "docx" ? (
                      <>
                        <div>
                          <p className="text-slate-500">Total blocks</p>
                          <p className="mt-1 text-base font-semibold text-slate-200">
                            {summary.total_blocks}
                          </p>
                        </div>
                        <div>
                          <p className="text-slate-500">Paragraphs</p>
                          <p className="mt-1 text-base font-semibold text-slate-200">
                            {summary.total_paragraphs}
                          </p>
                        </div>
                        <div>
                          <p className="text-slate-500">Tables</p>
                          <p className="mt-1 text-base font-semibold text-slate-200">
                            {summary.total_tables}
                          </p>
                        </div>
                      </>
                    ) : (
                      <>
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
                      </>
                    )}
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
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">Your documents</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    Your private library. Select a document to continue its
                    chat history.
                  </p>
                </div>
                <span className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-xs font-semibold text-slate-400">
                  {documentsLoading ? "Loading..." : documents.length}
                </span>
              </div>

              {!documentsLoading && documents.length === 0 && (
                <p className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-5 text-sm text-slate-400">
                  No documents yet. Upload a PDF or Word file to get started.
                </p>
              )}

              <div className="mt-5 space-y-3">
                {documents.map((doc) => {
                  const isActive = doc.document_id === documentId;

                  return (
                    <button
                      key={doc.document_id}
                      onClick={() => selectDocument(doc)}
                      className={`w-full rounded-2xl border p-4 text-left transition ${
                        isActive
                          ? "border-cyan-500/60 bg-cyan-500/10"
                          : "border-slate-800 bg-slate-950/70 hover:border-slate-600 hover:bg-slate-900"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-semibold text-slate-200">
                          {doc.filename}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                            doc.source_type === "docx"
                              ? "border-purple-500/50 bg-purple-500/10 text-purple-200"
                              : "border-cyan-500/50 bg-cyan-500/10 text-cyan-200"
                          }`}
                        >
                          {doc.source_type === "docx" ? "Word" : "PDF"}
                        </span>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                        <span>
                          {doc.chunk_count} chunk
                          {doc.chunk_count === 1 ? "" : "s"}
                        </span>
                        <span>{formatDate(doc.created_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800/80 bg-slate-900/70 p-6 shadow-[0_20px_50px_-35px_rgba(15,23,42,0.9)] backdrop-blur">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Ask DocuMind AI</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Ask detailed questions and receive grounded answers with
                  source page or block references.
                </p>
              </div>
              <span
                className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                  documentId
                    ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-200"
                    : "border-slate-700 bg-slate-950/60 text-slate-400"
                }`}
              >
                {documentId ? "Document connected" : "Upload a document first"}
              </span>
            </div>

            <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Example: Summarize the main idea of this document."
                className="min-h-32 w-full resize-none rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-100 outline-none focus:border-cyan-400"
              />

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <button
                  onClick={handleAsk}
                  disabled={asking || !documentId}
                  className="rounded-xl bg-purple-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-purple-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {asking ? "Generating answer..." : "Ask document"}
                </button>

                <span className="text-xs text-slate-500">
                  {documentId
                    ? "Answers cite source pages or document blocks when available."
                    : "Upload or select a document to enable questions."}
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
                Select or upload a document and ask your first question. Your
                conversation history is saved per document and restored
                automatically.
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
                        Sources
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.sources.map((source) => (
                          <span
                            key={source}
                            className="rounded-full border border-cyan-800 bg-cyan-950 px-3 py-1 text-xs text-cyan-200"
                          >
                            {formatSourceChip(source)}
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
                          {formatChunkLocation(chunk)}
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
