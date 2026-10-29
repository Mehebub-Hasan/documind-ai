"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const TOKEN_STORAGE_KEY = "documind_token";
const USER_STORAGE_KEY = "documind_user";
const THEME_STORAGE_KEY = "documind_theme";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

const NOT_FOUND_ANSWER =
  "The document does not contain enough information to answer this question.";

const STARTER_PROMPTS = [
  "Summarize key findings",
  "Extract action items & dates",
  "List main entities & stakeholders",
  "Explain methodology or structure",
];

const FOLLOW_UPS = [
  "Summarize this in three bullet points",
  "What does the document not cover?",
];

const WORKSPACE_STEPS = [
  "Upload PDF / DOCX",
  "Auto-Index in FAISS",
  "Ask with Citations",
];

const TRUST_ITEMS = [
  "PDF & DOCX Support",
  "Per-User Isolated Storage",
  "Grounded Citations",
];

const cleanTitle = (filename) =>
  filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();

const referenceLine = (chunk) => {
  if (chunk.page !== undefined && chunk.page !== null) {
    return `Page ${chunk.page}`;
  }
  if (chunk.block_start !== undefined && chunk.block_start !== null) {
    return chunk.block_start === chunk.block_end
      ? `Block ${chunk.block_start}`
      : `Blocks ${chunk.block_start}\u2013${chunk.block_end}`;
  }
  return "Source";
};

const getFileExtension = (name) => {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
};

const validateSelectedFile = (file, documents) => {
  const extension = getFileExtension(file.name);

  if (extension === ".doc") {
    return "Legacy .doc files are not supported. Please convert the document to .docx and upload again.";
  }

  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return "Unsupported file type. Please select a .pdf or .docx file.";
  }

  const safeName = file.name.replace(/ /g, "_");
  const duplicate = documents.some((doc) => doc.filename === safeName);

  if (duplicate) {
    return `"${file.name}" is already in your library. Delete it first or upload a renamed copy.`;
  }

  return "";
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

const getInitials = (name) => {
  if (!name) return "?";
  return name
    .trim()
    .split(/\s+/)
    .map((word) => word.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();
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

/* ---- Icons (stroke = currentColor, no sparkles) ---- */

const Icon = ({ children, size = 16, ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    {...props}
  >
    {children}
  </svg>
);

const UploadIcon = (props) => (
  <Icon size={17} {...props}>
    <path d="M12 16V5M12 5l-4 4M12 5l4 4" />
    <path d="M4 19h16" />
  </Icon>
);

const SendIcon = () => (
  <Icon size={15}>
    <path d="M12 19V6M12 6l-6 6M12 6l6 6" />
  </Icon>
);

const TrashIcon = () => (
  <Icon size={14}>
    <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" />
  </Icon>
);

const EyeIcon = () => (
  <Icon size={15}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
);

const EyeOffIcon = () => (
  <Icon size={15}>
    <path d="M3 3l18 18" />
    <path d="M10.6 5.2A9.8 9.8 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4M6.6 6.6A16.4 16.4 0 0 0 2 12s3.5 7 10 7c1.9 0 3.6-.6 5-1.5" />
  </Icon>
);

const UserIcon = () => (
  <Icon size={15}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20a7 7 0 0 1 14 0" />
  </Icon>
);

const MailIcon = () => (
  <Icon size={15}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="M3 7l9 6 9-6" />
  </Icon>
);

const LockIcon = () => (
  <Icon size={15}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </Icon>
);

const LogoutIcon = () => (
  <Icon size={15}>
    <path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3" />
    <path d="M15 8l4 4-4 4M19 12H9" />
  </Icon>
);

const CloseIcon = () => (
  <Icon size={16}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Icon>
);

const LibraryIcon = () => (
  <Icon size={16}>
    <path d="M4 5a2 2 0 0 1 2-2h5v18H6a2 2 0 0 1-2-2zM13 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5z" />
  </Icon>
);

const ArrowIcon = (props) => (
  <Icon size={14} {...props}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
);

const SunIcon = () => (
  <Icon size={15}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
);

const MoonIcon = () => (
  <Icon size={15}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </Icon>
);

const ChevronLeftIcon = () => (
  <Icon size={15}>
    <path d="M15 6l-6 6 6 6" />
  </Icon>
);

const ChevronRightIcon = () => (
  <Icon size={15}>
    <path d="M9 6l6 6-6 6" />
  </Icon>
);

const CopyIcon = () => (
  <Icon size={13}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 0 1 2-2h9" />
  </Icon>
);

const RefreshIcon = () => (
  <Icon size={13}>
    <path d="M21 12a9 9 0 1 1-2.6-6.3" />
    <path d="M21 3v6h-6" />
  </Icon>
);

const SearchXIcon = (props) => (
  <Icon size={18} {...props}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-4-4M8.5 8.5l5 5M13.5 8.5l-5 5" />
  </Icon>
);

/* ---- Citation primitives ---- */

const CitationButton = ({ n, active, title, onSelect }) => (
  <button
    type="button"
    aria-pressed={active}
    aria-label={title ? `Source ${n}: ${title}` : `Source ${n}`}
    title={title}
    onClick={onSelect}
    className={`inline-flex h-6 min-w-6 shrink-0 items-center justify-center rounded-md border px-1 align-middle font-mono text-[11px] font-medium transition-colors duration-150 ${
      active
        ? "border-citeborder bg-citeactive text-ink"
        : "border-hairstrong bg-surface text-accent hover:border-accent"
    }`}
  >
    {n}
  </button>
);

const InlineText = ({ text, message, activeCitation, onSelectCitation }) => {
  const boldParts = text.split(/(\*\*[^*]+\*\*)/g);

  return boldParts.flatMap((part, partIndex) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return [
        <strong
          key={`b-${partIndex}`}
          className="font-semibold text-ink"
        >
          {part.slice(2, -2)}
        </strong>,
      ];
    }

    const citeParts = part.split(/(\[\d{1,2}\])/g);

    return citeParts.map((segment, segIndex) => {
      const match = segment.match(/^\[(\d{1,2})\]$/);

      if (match) {
        const n = Number(match[1]);
        const chunk = message.evidence[n - 1];

        if (chunk && n >= 1 && n <= message.evidence.length) {
          const active =
            activeCitation &&
            activeCitation.messageId === message.id &&
            activeCitation.index === n;

          return (
            <CitationButton
              key={`c-${partIndex}-${segIndex}`}
              n={n}
              active={active}
              title={getSnippet(chunk.text, 120)}
              onSelect={() => onSelectCitation(message.id, n)}
            />
          );
        }
      }

      return <span key={`t-${partIndex}-${segIndex}`}>{segment}</span>;
    });
  });
};

const AnswerMarkdown = ({
  answer,
  message,
  activeCitation,
  onSelectCitation,
}) => {
  const blocks = [];
  let paragraph = [];
  let listItems = null;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", text: paragraph.join("\n") });
      paragraph = [];
    }
  };

  const flushList = () => {
    if (listItems) {
      blocks.push({ type: "list", items: listItems });
      listItems = null;
    }
  };

  for (const rawLine of (answer || "").split("\n")) {
    const line = rawLine.trimEnd();
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);

    if (bullet) {
      flushParagraph();
      if (!listItems) listItems = [];
      listItems.push(bullet[1]);
      continue;
    }

    flushList();

    if (line.trim() === "") {
      flushParagraph();
    } else {
      paragraph.push(line);
    }
  }

  flushParagraph();
  flushList();

  return (
    <div className="space-y-3">
      {blocks.map((block, index) =>
        block.type === "paragraph" ? (
          <p key={index} className="whitespace-pre-wrap">
            <InlineText
              text={block.text}
              message={message}
              activeCitation={activeCitation}
              onSelectCitation={onSelectCitation}
            />
          </p>
        ) : (
          <ul key={index} className="my-2 space-y-2 pl-4">
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex} className="flex items-start gap-2">
                <span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-faint" />
                <span>
                  <InlineText
                    text={item}
                    message={message}
                    activeCitation={activeCitation}
                    onSelectCitation={onSelectCitation}
                  />
                </span>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
};

const TypeTag = ({ type }) => (
  <span
    className={`inline-flex shrink-0 items-center rounded border px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-wider ${
      type === "docx"
        ? "border-hairstrong bg-panel text-muted"
        : "border-hairstrong bg-panel text-muted"
    }`}
  >
    {type === "docx" ? "Docx" : "Pdf"}
  </span>
);

const LogoMark = ({ size = 28 }) => (
  <span
    className="grid shrink-0 place-items-center rounded-lg bg-primary text-onprimary"
    style={{ width: size, height: size }}
  >
    <span
      className="font-serif font-semibold leading-none"
      style={{ fontSize: size * 0.5 }}
    >
      D
    </span>
  </span>
);

const FileGlyphIcon = (props) => (
  <Icon size={16} {...props}>
    <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
    <path d="M14 3v4h4" />
  </Icon>
);

const SourceLinkIcon = (props) => (
  <Icon size={11} {...props}>
    <path d="M9 15l6-6" />
    <path d="M11 6.5l1-1a3.18 3.18 0 0 1 4.5 4.5l-1 1" />
    <path d="M13 17.5l-1 1a3.18 3.18 0 0 1-4.5-4.5l1-1" />
  </Icon>
);

// Landing showcase personas. Each persona's highlights are illustrative
// marketing copy, not real retrieval results.
const PERSONAS = [
  {
    role: "Students",
    file: "CS101_Course_Syllabus.pdf",
    format: "PDF",
    formatColor:
      "bg-amber-50 text-amber-700 border border-amber-200 text-[10px] font-semibold px-2 py-0.5 rounded",
    question: "When is the final project deadline and how much does it count?",
    highlight: "December 14 at 11:59 PM",
    highlight2: "25%",
    answerBefore: "The final project submission is due on ",
    answerMid: ", making up ",
    answerAfter: " of your total course grade.",
    citations: ["Page 3", "Grading Policy"],
  },
  {
    role: "Researchers",
    file: "Attention_Mechanism_Study.pdf",
    format: "PDF",
    formatColor:
      "bg-amber-50 text-amber-700 border border-amber-200 text-[10px] font-semibold px-2 py-0.5 rounded",
    question:
      "What dataset was used for evaluation and what was the BLEU score?",
    highlight: "WMT 2014 English-to-German",
    highlight2: "28.4",
    answerBefore: "The model was evaluated on the ",
    answerMid: " benchmark, achieving a state-of-the-art score of ",
    answerAfter: " on the test set.",
    citations: ["Page 7", "Table 3: Results"],
  },
  {
    role: "Professionals",
    file: "Employment_Agreement.docx",
    format: "DOCX",
    formatColor:
      "bg-sky-50 text-sky-700 border border-sky-200 text-[10px] font-semibold px-2 py-0.5 rounded",
    question: "What is the annual paid time off policy and remote work stipend?",
    highlight: "20 days paid leave",
    highlight2: "$1,200 stipend",
    answerBefore: "Full-time employees receive ",
    answerMid: " per year and an initial ",
    answerAfter: " for home workstation setup.",
    citations: ["Section 6.2", "Benefits Schedule"],
  },
];

const SHOWCASE_ROTATION_MS = 4500;

const HighlightMark = ({ children }) => (
  <mark className="rounded border border-indigo-100 bg-indigo-50 px-1.5 py-0.5 font-medium text-indigo-700">
    {children}
  </mark>
);

const AuthShowcase = () => {
  const [personaIndex, setPersonaIndex] = useState(0);

  // Auto-advance every cycle; a manual tab click re-runs this effect, which
  // restarts the full interval for the newly selected persona.
  useEffect(() => {
    const timer = setTimeout(() => {
      setPersonaIndex((index) => (index + 1) % PERSONAS.length);
    }, SHOWCASE_ROTATION_MS);

    return () => clearTimeout(timer);
  }, [personaIndex]);

  const persona = PERSONAS[personaIndex];

  return (
    <div className="animate-fade-up-delayed mt-8 max-w-lg overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-[0_16px_40px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)]">
      {/* Persona selector */}
      <div
        className="flex items-center gap-1 border-b border-zinc-100 px-6 pb-4 pt-5"
        role="tablist"
        aria-label="Showcase personas"
      >
        {PERSONAS.map((item, index) => {
          const active = index === personaIndex;

          return (
            <button
              key={item.role}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setPersonaIndex(index)}
              className={
                active
                  ? "rounded-full border border-black/[0.08] bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-900 shadow-xs transition-all"
                  : "cursor-pointer px-3 py-1 text-xs text-zinc-500 transition-colors hover:text-zinc-800"
              }
            >
              {item.role}
            </button>
          );
        })}
      </div>

      {/* Card body — keyed re-mount drives the fade/slide swap */}
      <div key={persona.role} className="animate-showcase-swap px-6 py-5">
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex min-w-0 items-center gap-2 rounded-md border border-zinc-200 bg-zinc-50 px-2.5 py-1">
            <FileGlyphIcon className="shrink-0 text-zinc-400" />
            <span className="truncate font-mono text-xs text-zinc-700">
              {persona.file}
            </span>
          </span>
          <span
            className={`inline-flex shrink-0 items-center font-mono uppercase tracking-wider ${persona.formatColor}`}
          >
            {persona.format}
          </span>
        </div>

        <div className="mt-4 rounded-xl border border-zinc-200/80 bg-zinc-50 p-3">
          <p className="font-sans text-xs leading-relaxed text-zinc-700">
            {persona.question}
          </p>
        </div>

        <div className="mt-3.5 flex gap-3">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[#111827] font-serif text-[11px] font-semibold text-white">
            D
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-sans text-xs leading-relaxed text-zinc-800 sm:text-sm">
              {persona.answerBefore}
              <HighlightMark>{persona.highlight}</HighlightMark>
              {persona.answerMid}
              <HighlightMark>{persona.highlight2}</HighlightMark>
              {persona.answerAfter}
            </p>

            <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
              {persona.citations.map((citation) => (
                <span
                  key={citation}
                  className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-zinc-50 px-2.5 py-1 font-sans text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                >
                  <SourceLinkIcon className="text-zinc-400" />
                  {citation}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Cycle progress — re-mounted per persona so it restarts in sync */}
      <div className="h-0.5 w-full bg-zinc-100">
        <div
          key={`progress-${persona.role}`}
          className="showcase-progress h-full bg-indigo-400"
        />
      </div>
    </div>
  );
};

export default function Home() {
  // ---- Auth state ----
  const [sessionChecked, setSessionChecked] = useState(false);
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ name: "", email: "", password: "" });
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // ---- Theme ----
  const [theme, setTheme] = useState("light");

  // ---- Document library state ----
  const [documents, setDocuments] = useState([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [dragging, setDragging] = useState(false);

  // ---- Workspace state ----
  const [file, setFile] = useState(null);
  const [documentId, setDocumentId] = useState("");
  const [filename, setFilename] = useState("");
  const [summary, setSummary] = useState(null);
  const [sourceType, setSourceType] = useState("");
  const [docSummary, setDocSummary] = useState(null);
  const [docSummaryLoading, setDocSummaryLoading] = useState(false);

  const [question, setQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [activeCitation, setActiveCitation] = useState(null);
  const [copiedId, setCopiedId] = useState(null);

  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  const questionInputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const sidebarInputRef = useRef(null);
  const excerptRef = useRef(null);

  const resetWorkspace = useCallback(() => {
    setFile(null);
    setDocumentId("");
    setFilename("");
    setSummary(null);
    setSourceType("");
    setDocSummary(null);
    setDocSummaryLoading(false);
    setQuestion("");
    setChatHistory([]);
    setActiveCitation(null);
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

  // ---- Theme: restore (stored choice, else system preference), persist. ----
  // Read storage synchronously here: the apply-effect below runs right after
  // and would otherwise overwrite the stored choice with the initial "light"
  // before the deferred setTheme reads it.
  const themeRestoredRef = useRef(false);
  useEffect(() => {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    const preferred = window.matchMedia("(prefers-color-scheme: dark)")
      .matches
      ? "dark"
      : "light";
    const next = stored === "dark" || stored === "light" ? stored : preferred;
    Promise.resolve().then(() => {
      themeRestoredRef.current = true;
      setTheme(next);
    });
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    if (themeRestoredRef.current) {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

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

  const stageFile = (selectedFile) => {
    if (selectedFile) {
      const validationError = validateSelectedFile(selectedFile, documents);

      if (validationError) {
        setFile(null);
        setError(validationError);
        return;
      }
    }

    setFile(selectedFile);
    setError("");
  };

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null;

    if (selectedFile && validateSelectedFile(selectedFile, documents)) {
      event.target.value = "";
    }

    stageFile(selectedFile);
  };

  const handleSidebarPick = (event) => {
    const selectedFile = event.target.files?.[0] || null;
    event.target.value = "";

    if (!selectedFile) return;

    const validationError = validateSelectedFile(selectedFile, documents);

    if (validationError) {
      setError(validationError);
      return;
    }

    uploadFile(selectedFile);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragging(false);

    const droppedFile = event.dataTransfer.files?.[0] || null;
    stageFile(droppedFile);
  };

  const uploadFile = async (selectedFile) => {
    if (!selectedFile) {
      setError("Please select a file first.");
      return;
    }

    setError("");
    setChatHistory([]);
    setActiveCitation(null);
    setQuestion("");
    setUploading(true);

    try {
      const endpoint =
        getFileExtension(selectedFile.name) === ".docx"
          ? "/upload-docx"
          : "/upload-pdf";

      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await api.post(endpoint, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setDocumentId(response.data.document_id);
      setFilename(response.data.filename);
      setSummary(response.data.summary);
      setSourceType(response.data.source_type || "pdf");
      setDocSummary(response.data.document_summary || null);
      setFile(null);
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

  const handleUpload = () => uploadFile(file);

  const askQuestion = async (questionText) => {
    if (!documentId) {
      setError("Upload or select a document before asking a question.");
      return;
    }

    if (!questionText.trim()) {
      setError("Please write a question.");
      return;
    }

    setError("");
    setAsking(true);
    setQuestion("");
    setActiveCitation(null);

    try {
      const response = await api.post("/ask", {
        document_id: documentId,
        question: questionText,
        top_k: 6,
      });

      const newMessage = {
        id: Date.now(),
        question: questionText,
        answer: response.data.answer,
        sources: response.data.sources || [],
        sourceType: response.data.source_type || "pdf",
        evidence: response.data.retrieved_chunks || [],
      };

      setChatHistory((prev) => [newMessage, ...prev]);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Question answering failed. Check backend or API key."
      );
    } finally {
      setAsking(false);
    }
  };

  const handleAsk = () => askQuestion(question.trim());

  const handleRegenerate = (item) => askQuestion(item.question);

  const handleCopyWithCitations = async (item) => {
    const lines = [
      item.question,
      "",
      item.answer,
      "",
      "Sources:",
      ...item.evidence.map(
        (chunk, index) => `[${index + 1}] ${referenceLine(chunk)} — ${getSnippet(chunk.text, 160)}`
      ),
    ];

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopiedId(item.id);
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch {
      setError("Could not copy to clipboard.");
    }
  };

  const handleQuestionKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!asking && documentId && question.trim()) {
        handleAsk();
      }
    }
  };

  const handleDeleteDoc = async (doc) => {
    try {
      await api.delete(`/documents/${doc.document_id}`);

      if (doc.document_id === documentId) {
        resetWorkspace();
      }

      loadDocuments();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not delete the document.");
    }
  };

  const selectDocument = async (doc) => {
    setError("");
    setFile(null);
    setActiveCitation(null);
    setQuestion("");
    setDocumentId(doc.document_id);
    setFilename(doc.filename);
    setSummary(doc.summary || null);
    setSourceType(doc.source_type || "pdf");

    // Executive summary: fetch the per-document detail (generated on the
    // backend at upload time, or on first open for older documents).
    setDocSummary(null);
    setDocSummaryLoading(true);

    try {
      const detail = await api.get(`/documents/${doc.document_id}`);
      setDocSummary(detail.data.document_summary || null);
    } catch {
      setDocSummary(null);
    } finally {
      setDocSummaryLoading(false);
    }

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
            evidence: [],
          });
          pendingQuestion = null;
        }
      }

      setChatHistory(history.reverse());
    } catch {
      setChatHistory([]);
    }
  };

  const handleSelectDoc = (doc) => {
    selectDocument(doc);
    setLibraryOpen(false);
  };

  const onSelectCitation = (messageId, index) => {
    setActiveCitation((prev) =>
      prev && prev.messageId === messageId && prev.index === index
        ? null
        : { messageId, index }
    );
  };

  const activeCitationMessage =
    activeCitation === null
      ? null
      : chatHistory.find((item) => item.id === activeCitation.messageId) ||
        null;

  const stepCitation = useCallback(
    (delta) => {
      if (!activeCitation || !activeCitationMessage) return;

      const count = activeCitationMessage.evidence.length;
      if (count === 0) return;

      const next =
        ((activeCitation.index - 1 + delta + count) % count) + 1;
      setActiveCitation({ messageId: activeCitation.messageId, index: next });
    },
    [activeCitation, activeCitationMessage]
  );

  // Left/Right arrows step through sources while the source panel is open.
  useEffect(() => {
    if (!activeCitation) return;

    const onKeyDown = (event) => {
      const tag = event.target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea") return;

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepCitation(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        stepCitation(1);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeCitation, stepCitation]);

  // Scroll the excerpt into view when the selected source changes.
  useEffect(() => {
    excerptRef.current?.scrollIntoView({ block: "start" });
  }, [activeCitation]);

  // Auto-grow the question textarea with its content.
  useEffect(() => {
    const el = questionInputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }, [question]);

  // Keep the newest message in view.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [chatHistory.length, asking]);

  // ---- Derived (presentational only) ----

  const selectedDoc =
    documents.find((doc) => doc.document_id === documentId) || null;

  const metaPills = [];
  if (summary) {
    if (sourceType === "docx") {
      metaPills.push(`${summary.total_paragraphs} paragraphs`);
      metaPills.push(`${summary.total_tables} tables`);
    } else {
      metaPills.push(`${summary.total_pages} pages`);
    }
  }
  if (selectedDoc) {
    metaPills.push(`${selectedDoc.chunk_count} chunks`);
  }

  const libraryMeta = (doc) => {
    const docSummary = doc.summary || {};
    if (doc.source_type === "docx" && docSummary.total_blocks) {
      return `${docSummary.total_blocks} blocks · indexed`;
    }
    if (doc.source_type === "pdf" && docSummary.total_pages) {
      return `${docSummary.total_pages} pages · indexed`;
    }
    return `${doc.chunk_count} chunks · indexed`;
  };

  const openPicker = () => fileInputRef.current?.click();

  // ---- Auth view ----

  if (!sessionChecked) {
    return <main className="h-screen w-screen bg-page" />;
  }

  if (!user) {
    const isLogin = authMode === "login";

    return (
      <main className="grid h-screen w-screen grid-cols-1 overflow-hidden bg-[#FBFBFA] md:grid-cols-12">
        {/* Left: brand showcase */}
        <section className="hidden flex-col justify-between overflow-hidden border-r border-black/[0.06] p-10 md:flex md:col-span-7 lg:p-14">
          <div className="flex items-center gap-2.5">
            <LogoMark />
            <span className="font-serif text-lg font-semibold tracking-tight text-[#111827]">
              DocuMind AI
            </span>
          </div>

          <div className="max-w-xl">
            <h1 className="animate-fade-up font-serif text-4xl font-semibold leading-[1.15] tracking-tight text-[#111827] lg:text-[44px]">
              Ask your documents.
              <br />
              Verify every claim.
            </h1>

            <p className="animate-fade-up mt-3 max-w-lg text-base leading-7 text-[#4B5563]">
              Upload PDFs and Word documents into your private AI workspace.
              Get instant, verified answers backed by exact page and block
              citations.
            </p>

            <AuthShowcase />
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-[#6B7280]">
            {TRUST_ITEMS.map((item, index) => (
              <span key={item} className="flex items-center gap-6">
                {index > 0 && <span className="text-zinc-300">·</span>}
                {item}
              </span>
            ))}
          </div>
        </section>

        {/* Right: auth card */}
        <section className="col-span-1 flex items-center justify-center p-6 md:col-span-5">
          <div className="animate-fade-up w-full max-w-[400px] rounded-2xl border border-black/[0.08] bg-white p-8 shadow-[0_12px_32px_rgba(0,0,0,0.05),0_1px_2px_rgba(0,0,0,0.05)]">
            <div className="mb-6 flex items-center gap-2.5 md:hidden">
              <LogoMark size={26} />
              <span className="font-serif text-base font-semibold text-[#111827]">
                DocuMind AI
              </span>
            </div>

            <h2 className="font-serif text-xl font-semibold tracking-tight text-[#111827]">
              {isLogin ? "Welcome back" : "Create your account"}
            </h2>
            <p className="mt-1 text-[13px] text-[#6B7280]">
              {isLogin
                ? "Sign in to your document library."
                : "One account for every document conversation."}
            </p>

            <div className="mt-5 grid grid-cols-2 gap-1 rounded-xl border border-black/[0.06] bg-zinc-100 p-1">
              <button
                type="button"
                onClick={() => {
                  setAuthMode("login");
                  setAuthError("");
                }}
                className={`h-9 rounded-lg text-[13px] font-medium transition-colors duration-150 ${
                  isLogin
                    ? "bg-white text-zinc-900 shadow-xs"
                    : "text-zinc-500 hover:text-zinc-800"
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
                className={`h-9 rounded-lg text-[13px] font-medium transition-colors duration-150 ${
                  !isLogin
                    ? "bg-white text-zinc-900 shadow-xs"
                    : "text-zinc-500 hover:text-zinc-800"
                }`}
              >
                Create account
              </button>
            </div>

            <form onSubmit={handleAuthSubmit} className="mt-5 space-y-3.5">
              {!isLogin && (
                <div>
                  <label
                    htmlFor="auth-name"
                    className="mb-1.5 block text-[13px] font-medium text-zinc-700"
                  >
                    Name
                  </label>
                  <div className="relative">
                    <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400">
                      <UserIcon />
                    </span>
                    <input
                      id="auth-name"
                      type="text"
                      value={authForm.name}
                      onChange={updateAuthForm("name")}
                      required
                      autoComplete="name"
                      placeholder="Your name"
                      className="h-10 w-full rounded-lg border border-zinc-200 bg-white pl-9 pr-3 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                    />
                  </div>
                </div>
              )}

              <div>
                <label
                  htmlFor="auth-email"
                  className="mb-1.5 block text-[13px] font-medium text-zinc-700"
                >
                  Email
                </label>
                <div className="relative">
                  <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400">
                    <MailIcon />
                  </span>
                  <input
                    id="auth-email"
                    type="email"
                    value={authForm.email}
                    onChange={updateAuthForm("email")}
                    required
                    autoComplete="email"
                    placeholder="you@example.com"
                    className="h-10 w-full rounded-lg border border-zinc-200 bg-white pl-9 pr-3 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="auth-password"
                  className="mb-1.5 block text-[13px] font-medium text-zinc-700"
                >
                  Password
                </label>
                <div className="relative">
                  <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400">
                    <LockIcon />
                  </span>
                  <input
                    id="auth-password"
                    type={showPassword ? "text" : "password"}
                    value={authForm.password}
                    onChange={updateAuthForm("password")}
                    required
                    autoComplete={
                      isLogin ? "current-password" : "new-password"
                    }
                    placeholder="Enter your password"
                    className="h-10 w-full rounded-lg border border-zinc-200 bg-white pl-9 pr-10 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    className="absolute right-1.5 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-md text-zinc-400 transition-colors hover:text-zinc-700"
                  >
                    {showPassword ? <EyeOffIcon /> : <EyeIcon />}
                  </button>
                </div>
                {!isLogin && (
                  <p className="mt-1.5 text-xs text-[#6B7280]">
                    At least 8 characters.
                  </p>
                )}
              </div>

              {authError && (
                <p
                  role="alert"
                  className="rounded-lg border border-zinc-200 bg-zinc-50 px-3.5 py-2.5 text-[13px] text-zinc-800"
                >
                  {authError}
                </p>
              )}

              <button
                type="submit"
                disabled={authBusy}
                className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#111827] text-sm font-medium text-white shadow-sm transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-50"
              >
                {authBusy ? (
                  <span className="flex items-center gap-2">
                    <span className="typing-dot" />
                    {isLogin ? "Signing in…" : "Creating account…"}
                  </span>
                ) : isLogin ? (
                  "Sign in"
                ) : (
                  "Create account"
                )}
              </button>
            </form>

            <p className="mt-5 text-center text-xs leading-5 text-[#6B7280]">
              Your documents are private to your account.
            </p>
          </div>
        </section>
      </main>
    );
  }

  // ---- Three-pane workspace ----

  const renderSidebar = () => (
    <div className="flex h-full min-h-0 flex-col bg-panel px-3 py-3">
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Wordmark */}
        <div className="flex items-center justify-between px-1 py-1">
          <div className="flex items-center gap-2.5">
            <LogoMark size={26} />
            <span className="font-serif text-[15px] font-semibold tracking-tight text-ink">
              DocuMind AI
            </span>
          </div>

          <button
            onClick={() => setLibraryOpen(false)}
            aria-label="Close library"
            className="grid h-8 w-8 place-items-center rounded-md text-muted transition-colors hover:text-ink lg:hidden"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Upload */}
        <div className="mt-3">
          <button
            onClick={() => sidebarInputRef.current?.click()}
            disabled={uploading}
            className="flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-xs font-medium text-onprimary transition-colors duration-200 hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? "Indexing…" : "Upload PDF or DOCX"}
          </button>
        </div>

        {/* Library */}
        <div className="mt-5 min-h-0 flex-1 overflow-y-auto">
          <p className="mb-1.5 flex items-center justify-between px-1 text-[11px] font-medium uppercase tracking-wider text-muted">
            Library
            <span className="font-mono text-[10px] normal-case text-faint">
              {documentsLoading ? "…" : documents.length}
            </span>
          </p>

          {documents.length === 0 && !documentsLoading ? (
            <p className="px-1 py-5 text-left text-xs leading-relaxed text-muted">
              No documents yet. Upload a PDF or Word file to get started.
            </p>
          ) : (
            <div className="space-y-1">
              {documents.map((doc) => {
                const isActive = doc.document_id === documentId;

                return (
                  <div
                    key={doc.document_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleSelectDoc(doc)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        handleSelectDoc(doc);
                      }
                    }}
                    className={`group cursor-pointer rounded-lg border px-2.5 py-2 transition-colors duration-200 ${
                      isActive
                        ? "border-hairline bg-surface shadow-[var(--shadow-card)]"
                        : "border-transparent hover:bg-surface/60"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <TypeTag type={doc.source_type} />
                      <span
                        className="line-clamp-2 min-w-0 flex-1 break-words text-[13px] font-medium leading-5 text-ink"
                        title={doc.filename}
                      >
                        {cleanTitle(doc.filename)}
                      </span>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDeleteDoc(doc);
                        }}
                        aria-label={`Delete ${doc.filename}`}
                        className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-faint opacity-0 transition-opacity hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                    <p className="mt-1 pl-0.5 font-mono text-[10px] text-faint">
                      {libraryMeta(doc)} · {formatDate(doc.created_at)}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* User footer */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-t border-hairline pt-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-hairline bg-surface text-[11px] font-semibold text-ink">
            {getInitials(user.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-ink">{user.name}</p>
            <p className="truncate text-[10px] text-faint">{user.email}</p>
          </div>
        </div>

        <button
          onClick={logout}
          aria-label="Log out"
          title="Log out"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted transition-colors duration-150 hover:bg-surface hover:text-ink"
        >
          <LogoutIcon />
        </button>
      </div>
    </div>
  );

  const renderSourcePanelBody = () => {
    if (!activeCitation || !activeCitationMessage) return null;

    const chunk =
      activeCitationMessage.evidence[activeCitation.index - 1] || null;

    if (!chunk) return null;

    return (
      <>
        <div className="flex items-center justify-between border-b border-hairline px-4 py-2.5">
          <p className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
            Source · {activeCitation.index} of{" "}
            {activeCitationMessage.evidence.length}
          </p>
          <div className="flex items-center gap-1">
            <button
              onClick={() => stepCitation(-1)}
              aria-label="Previous source"
              className="grid h-8 w-8 place-items-center rounded-md border border-hairline bg-surface text-muted transition-colors hover:text-ink"
            >
              <ChevronLeftIcon />
            </button>
            <button
              onClick={() => stepCitation(1)}
              aria-label="Next source"
              className="grid h-8 w-8 place-items-center rounded-md border border-hairline bg-surface text-muted transition-colors hover:text-ink"
            >
              <ChevronRightIcon />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <p className="font-mono text-xs font-medium text-accent">
            {referenceLine(chunk)}
            {chunk.score !== undefined && (
              <span className="ml-2 font-normal text-faint">
                similarity {chunk.score.toFixed(3)}
              </span>
            )}
          </p>

          <div
            ref={excerptRef}
            className="mt-3 rounded-xl border border-hairline bg-surface p-5 shadow-[var(--shadow-card)]"
          >
            <p className="font-serif text-[15px] leading-8 text-ink">
              <mark className="rounded bg-evidence px-0.5 text-ink">
                {chunk.text}
              </mark>
            </p>
          </div>

          <div className="mt-4 rounded-lg border border-hairline bg-page px-3.5 py-3">
            <p className="text-xs font-medium text-ink">Retrieved passage</p>
            <p className="mt-1 text-xs leading-5 text-muted">
              This is the exact passage retrieved for the claim. Per-claim
              grounding states (verified / partially supported / not found)
              appear once the backend judges claim support.
            </p>
          </div>

          <p className="mt-4 px-1 font-mono text-[10px] leading-5 text-faint">
            Use ← / → to step through sources.
          </p>
        </div>
      </>
    );
  };

  const sourcePanel = (
    <div className="flex h-full min-h-0 flex-col bg-panel">
      <div className="flex items-center justify-between border-b border-hairline px-4 py-2">
        <span className="font-serif text-sm font-semibold text-ink">
          Source
        </span>
        <button
          onClick={() => setActiveCitation(null)}
          aria-label="Close source panel"
          className="grid h-8 w-8 place-items-center rounded-md text-muted transition-colors hover:text-ink xl:hidden"
        >
          <CloseIcon />
        </button>
      </div>
      {renderSourcePanelBody()}
    </div>
  );

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-page text-ink">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx"
        onChange={handleFileChange}
        className="hidden"
      />
      <input
        ref={sidebarInputRef}
        type="file"
        accept=".pdf,.docx"
        onChange={handleSidebarPick}
        className="hidden"
      />

      <aside className="hidden w-[260px] shrink-0 border-r border-hairline lg:block">
        {renderSidebar()}
      </aside>

      {libraryOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setLibraryOpen(false)}
            aria-hidden="true"
          />
          <aside
            className="absolute left-0 top-0 h-full w-[280px] border-r border-hairline"
            role="dialog"
            aria-label="Document library"
            onKeyDown={(event) => {
              if (event.key === "Escape") setLibraryOpen(false);
            }}
          >
            {renderSidebar()}
          </aside>
        </div>
      )}

      {/* Center pane */}
      <section className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-hairline px-4 sm:px-5">
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setLibraryOpen(true)}
              aria-label="Open document library"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition-colors hover:text-ink lg:hidden"
            >
              <LibraryIcon />
            </button>

            <span className="shrink-0 text-xs text-muted">Workspace</span>
            <span className="text-hairstrong">/</span>
            <span className="truncate text-xs font-medium text-ink">
              {documentId ? cleanTitle(filename) : "Overview"}
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {uploading ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-panel px-2.5 py-1 text-[11px] text-muted">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                Indexing…
              </span>
            ) : documentId ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-panel px-2.5 py-1 text-[11px] text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
                Indexed
              </span>
            ) : null}

            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label="Toggle dark mode"
              aria-pressed={theme === "dark"}
              className="grid h-9 w-9 place-items-center rounded-md border border-hairline bg-surface text-muted transition-colors duration-150 hover:text-ink"
            >
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </header>

        {error && (
          <div
            role="alert"
            className="shrink-0 border-b border-hairline bg-panel px-4 py-2.5 text-sm text-ink sm:px-5"
          >
            {error}
          </div>
        )}

        {!documentId ? (
          /* Empty workspace hub */
          <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-6 py-10">
            <div className="w-full max-w-xl">
              <h1 className="text-center font-serif text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                What would you like to analyze?
              </h1>
              <p className="mt-1.5 text-center text-sm text-muted">
                Upload a document to begin — every answer cites its source.
              </p>

              <div
                role="button"
                tabIndex={0}
                aria-label="Upload a PDF or Word document"
                onClick={openPicker}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openPicker();
                  }
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                className={`mt-6 cursor-pointer rounded-xl border border-dashed p-7 text-center transition-colors duration-200 ${
                  uploading
                    ? "border-accent/50 bg-surface"
                    : dragging
                      ? "border-accent/60 bg-surface"
                      : "border-hairstrong bg-panel hover:border-accent/50 hover:bg-surface"
                }`}
              >
                {uploading ? (
                  <div>
                    <p className="text-sm font-medium text-ink">
                      Indexing document…
                    </p>
                    <span className="upload-progress mx-auto mt-4 block h-0.5 w-48 overflow-hidden rounded-full bg-hairline">
                      <span />
                    </span>
                  </div>
                ) : file ? (
                  <div>
                    <p className="truncate text-sm font-medium text-ink">
                      {file.name}
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      {formatFileSize(file.size)} · ready to index
                    </p>
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        handleUpload();
                      }}
                      className="mt-4 inline-flex h-9 items-center justify-center rounded-lg bg-primary px-4 text-xs font-medium text-onprimary transition-colors duration-150 hover:bg-primary-hover"
                    >
                      Upload &amp; Index
                    </button>
                  </div>
                ) : (
                  <div>
                    <span className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full border border-hairline bg-surface text-accent">
                      <UploadIcon />
                    </span>
                    <p className="text-sm font-medium text-ink">
                      Drop your PDF or Word (.docx) file here
                    </p>
                    <p className="mt-1 text-xs text-muted">
                      or click to browse from your computer
                    </p>
                    <span className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface px-3.5 py-2 text-xs font-medium text-ink">
                      Select File (.pdf, .docx)
                    </span>
                  </div>
                )}
              </div>

              {documents.length > 0 && (
                <div className="mt-7">
                  <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-muted">
                    Recent documents
                  </p>
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    {documents.slice(0, 6).map((doc) => (
                      <button
                        key={doc.document_id}
                        onClick={() => selectDocument(doc)}
                        className="rounded-xl border border-hairline bg-surface p-3.5 text-left transition-colors duration-200 hover:border-hairstrong"
                      >
                        <div className="flex items-center gap-2">
                          <TypeTag type={doc.source_type} />
                          <span
                            className="line-clamp-2 min-w-0 flex-1 break-words text-[13px] font-medium leading-5 text-ink"
                            title={doc.filename}
                          >
                            {cleanTitle(doc.filename)}
                          </span>
                        </div>
                        <p className="mt-1.5 font-mono text-[10px] text-faint">
                          {libraryMeta(doc)} · added {formatDate(doc.created_at)}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-7">
                <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-muted">
                  Try asking
                </p>
                <div className="flex flex-col gap-2">
                  {STARTER_PROMPTS.slice(0, 3).map((prompt) => (
                    <button
                      key={prompt}
                      disabled={documents.length === 0}
                      onClick={() => {
                        selectDocument(documents[0]);
                        setQuestion(prompt);
                      }}
                      className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface px-4 py-3 text-left text-sm text-ink transition-colors duration-200 hover:border-hairstrong disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span>{prompt}</span>
                      <span className="shrink-0 text-accent">
                        <ArrowIcon />
                      </span>
                    </button>
                  ))}
                </div>
                {documents.length === 0 && (
                  <p className="mt-2 text-xs text-muted">
                    Upload a document to enable questions.
                  </p>
                )}
              </div>

              <div className="mt-7 grid grid-cols-3 gap-2.5">
                {WORKSPACE_STEPS.map((step, index) => (
                  <div
                    key={step}
                    className="flex items-center gap-2.5 rounded-lg border border-hairline bg-panel px-3 py-2.5"
                  >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-hairline bg-surface font-mono text-[11px] font-semibold text-muted">
                      {index + 1}
                    </span>
                    <span className="text-xs leading-4 text-muted">{step}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Active document conversation */
          <>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-20 pt-8 sm:px-6">
              <div className="mx-auto w-full max-w-[740px]">
                {!asking && chatHistory.length === 0 ? (
                  <div className="flex flex-col items-center pt-4 text-center sm:pt-10">
                    <h2 className="font-serif text-xl font-semibold tracking-tight text-ink">
                      Ask this document anything
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-muted">
                      Every answer cites the pages or blocks it came from.
                    </p>

                    {docSummaryLoading ? (
                      <div className="mt-6 w-full rounded-xl border border-hairline bg-surface px-5 py-4 text-left shadow-[var(--shadow-card)]">
                        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-faint">
                          Generating document summary…
                        </p>
                        <div className="mt-3 space-y-2" aria-hidden="true">
                          <div className="h-3 w-4/5 animate-pulse rounded bg-panel" />
                          <div className="h-3 w-3/5 animate-pulse rounded bg-panel" />
                        </div>
                      </div>
                    ) : docSummary ? (
                      <div className="mt-6 w-full rounded-xl border border-hairline bg-surface text-left shadow-[var(--shadow-card)]">
                        <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3.5">
                          <p className="flex min-w-0 items-center gap-2 font-serif text-sm font-semibold text-ink">
                            <span aria-hidden="true">📄</span>
                            <span className="truncate">
                              Document Summary &amp; Key Takeaways
                            </span>
                          </p>
                          <TypeTag type={sourceType} />
                        </div>

                        <div className="px-5 py-4">
                          <p className="font-serif text-[13px] leading-6 text-ink">
                            {docSummary.overview}
                          </p>

                          <ul className="mt-4 space-y-2.5">
                            {docSummary.takeaways.map((item, index) => (
                              <li
                                key={`${item.source}-${index}`}
                                className="flex items-start justify-between gap-3"
                              >
                                <span className="mt-1 font-mono text-[11px] font-semibold text-accent">
                                  {String(index + 1).padStart(2, "0")}
                                </span>
                                <p className="min-w-0 flex-1 text-[13px] leading-6 text-muted">
                                  {item.text}
                                </p>
                                <span className="shrink-0 rounded-md border border-hairline bg-panel px-2 py-0.5 font-mono text-[10px] text-muted">
                                  {item.source}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-hairline px-5 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            {[
                              ...new Set(
                                docSummary.takeaways.map((item) => item.source)
                              ),
                            ].map((source) => (
                              <span
                                key={source}
                                className="inline-flex items-center rounded-md border border-citeborder bg-citeactive px-2 py-0.5 font-mono text-[10px] font-medium text-ink"
                              >
                                {source}
                              </span>
                            ))}
                          </div>
                          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
                            Auto-generated ·{" "}
                            {docSummary.method === "llm"
                              ? "AI summary"
                              : "Excerpts"}
                          </p>
                        </div>
                      </div>
                    ) : (
                      summary &&
                      summary.preview_text && (
                        <div className="mt-6 w-full rounded-xl border border-hairline bg-surface p-5 text-left shadow-[var(--shadow-card)]">
                          <div className="flex items-center justify-between gap-3">
                            <p className="truncate font-serif text-sm font-semibold text-ink">
                              {cleanTitle(filename)}
                            </p>
                            <TypeTag type={sourceType} />
                          </div>
                          <p className="mt-2 line-clamp-2 font-serif text-[13px] leading-6 text-muted">
                            {summary.preview_text}
                          </p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {metaPills.map((pill) => (
                              <span
                                key={pill}
                                className="rounded-md border border-hairline bg-panel px-2.5 py-1 font-mono text-[11px] text-muted"
                              >
                                {pill}
                              </span>
                            ))}
                          </div>
                        </div>
                      )
                    )}

                    <div className="mt-6 grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
                      {STARTER_PROMPTS.map((prompt) => (
                        <button
                          key={prompt}
                          onClick={() => {
                            setQuestion(prompt);
                            questionInputRef.current?.focus();
                          }}
                          className="group flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface px-4 py-3 text-left text-sm text-ink transition-colors duration-200 hover:border-hairstrong"
                        >
                          <span>{prompt}</span>
                          <span className="shrink-0 text-accent opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                            <ArrowIcon />
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-8">
                    {[...chatHistory].reverse().map((item) => {
                      const isNotFound =
                        item.answer.trim() === NOT_FOUND_ANSWER;
                      const hasInlineCites = /\[\d{1,2}\]/.test(item.answer);

                      return (
                        <div key={item.id} className="animate-fade-up">
                          <div className="flex justify-end">
                            <p className="max-w-[80%] rounded-2xl rounded-tr-sm border border-hairline bg-surface px-4 py-3 text-sm leading-relaxed text-ink">
                              {item.question}
                            </p>
                          </div>

                          <div className="mt-4 flex gap-3">
                            <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary text-onprimary">
                              <span className="font-serif text-sm font-semibold leading-none">
                                D
                              </span>
                            </span>

                            <div className="min-w-0 flex-1">
                              {isNotFound ? (
                                <div className="rounded-xl border border-hairline bg-panel px-4 py-4">
                                  <div className="flex items-center gap-2 text-sm font-medium text-ink">
                                    <SearchXIcon />
                                    Not found in this document
                                  </div>
                                  <p className="mt-1.5 text-sm leading-6 text-muted">
                                    Nothing in the document supports an answer
                                    to this question. Try rephrasing it, or ask
                                    about a topic the document covers.
                                  </p>
                                </div>
                              ) : (
                                <>
                                  <div className="text-[15px] leading-7 text-ink">
                                    <AnswerMarkdown
                                      answer={item.answer}
                                      message={item}
                                      activeCitation={activeCitation}
                                      onSelectCitation={onSelectCitation}
                                    />
                                  </div>

                                  {item.evidence.length > 0 && (
                                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                                      <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-faint">
                                        {hasInlineCites ? "" : "Sources"}
                                      </span>
                                      {item.evidence.map((chunk, index) => (
                                        <CitationButton
                                          key={`${item.id}-${index}`}
                                          n={index + 1}
                                          active={
                                            activeCitation &&
                                            activeCitation.messageId ===
                                              item.id &&
                                            activeCitation.index === index + 1
                                          }
                                          title={getSnippet(chunk.text, 120)}
                                          onSelect={() =>
                                            onSelectCitation(
                                              item.id,
                                              index + 1
                                            )
                                          }
                                        />
                                      ))}
                                    </div>
                                  )}
                                </>
                              )}

                              <div className="mt-3 flex flex-wrap items-center gap-2">
                                <button
                                  onClick={() => handleCopyWithCitations(item)}
                                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted transition-colors duration-150 hover:bg-surface hover:text-ink"
                                >
                                  <CopyIcon />
                                  {copiedId === item.id
                                    ? "Copied"
                                    : "Copy with citations"}
                                </button>
                                {!isNotFound && (
                                  <button
                                    onClick={() => handleRegenerate(item)}
                                    disabled={asking}
                                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted transition-colors duration-150 hover:bg-surface hover:text-ink disabled:opacity-50"
                                  >
                                    <RefreshIcon />
                                    Regenerate
                                  </button>
                                )}
                              </div>

                              {!isNotFound && (
                                <div className="mt-2 flex flex-col gap-1.5">
                                  {FOLLOW_UPS.map((followUp) => (
                                    <button
                                      key={followUp}
                                      onClick={() => {
                                        setQuestion(followUp);
                                        questionInputRef.current?.focus();
                                      }}
                                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] text-accent transition-colors duration-150 hover:bg-surface"
                                    >
                                      <ArrowIcon size={12} />
                                      {followUp}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}

                    {asking && (
                      <div className="flex items-center gap-3" aria-live="polite">
                        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary text-onprimary">
                          <span className="font-serif text-sm font-semibold leading-none">
                            D
                          </span>
                        </span>
                        <span className="flex items-center gap-1.5 px-1">
                          <span className="typing-dot" />
                          <span className="typing-dot" />
                          <span className="typing-dot" />
                        </span>
                      </div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                )}
              </div>
            </div>

            {/* Composer */}
            <div className="shrink-0 px-4 pb-4 pt-1 sm:px-6">
              <div className="mx-auto w-full max-w-[740px]">
                <div className="flex items-end gap-3 rounded-2xl border border-hairline bg-surface px-4 py-3 shadow-[var(--shadow-card)] transition-colors focus-within:border-hairstrong">
                  <textarea
                    ref={questionInputRef}
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={handleQuestionKeyDown}
                    placeholder="Ask a question…"
                    rows={1}
                    aria-label="Question"
                    className="max-h-40 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-sm leading-6 text-ink placeholder:text-faint focus:outline-none"
                  />

                  <button
                    onClick={handleAsk}
                    disabled={asking || !documentId || !question.trim()}
                    aria-label="Send question"
                    className="grid h-9 w-9 shrink-0 place-items-center self-end rounded-lg bg-primary text-onprimary transition-colors duration-200 hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <SendIcon />
                  </button>
                </div>

                <p className="mt-2 hidden text-center font-mono text-[10px] text-faint sm:block">
                  Enter to send · Shift+Enter for a new line
                </p>
              </div>
            </div>
          </>
        )}
      </section>

      {/* Source panel: third pane on wide screens, bottom sheet below xl */}
      {activeCitation && activeCitationMessage && (
        <>
          <aside className="hidden w-[400px] shrink-0 border-l border-hairline xl:flex xl:flex-col">
            {sourcePanel}
          </aside>

          <div className="fixed inset-x-0 bottom-0 z-40 xl:hidden">
            <div
              className="absolute inset-x-0 bottom-0 top-0 -z-10 bg-black/30"
              onClick={() => setActiveCitation(null)}
              aria-hidden="true"
            />
            <div
              className="animate-sheet relative mx-auto flex max-h-[70vh] max-w-xl flex-col overflow-hidden rounded-t-2xl border-x border-t border-hairline bg-panel shadow-2xl"
              role="dialog"
              aria-label="Source"
            >
              {sourcePanel}
            </div>
          </div>
        </>
      )}
    </main>
  );
}
