# SAIBAP v2 — Smart AI Business Assistant Platform

> An enterprise-ready, multi-tenant AI platform for Small and Medium Businesses (SMBs) to automate customer support, capture and qualify leads, execute real tool integrations, and perform advanced hybrid RAG over isolated corporate knowledge bases.

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Project Structure](#project-structure)
- [Setup & Run](#setup--run)
  - [Docker (recommended)](#docker-recommended)
  - [Manual (local)](#manual-local)
- [Default Credentials](#default-credentials)
- [API Reference](#api-reference)
- [Technical Decisions](#technical-decisions)
- [Assumptions & Limitations](#assumptions--limitations)

---

## Architecture

```
         [Unauthenticated Customer]           [Authenticated Staff / Admin]
                    │                                      │
                    │  X-Tenant-ID header                  │  Bearer JWT token
                    ▼                                      ▼
          ┌─────────────────┐                    ┌──────────────────┐
          │   Public /chat  │                    │  Secure API /docs│
          └────────┬────────┘                    └────────┬─────────┘
                   │                                      │
                   └──────────────────┬───────────────────┘
                                      ▼
                            ┌──────────────────┐
                            │   Planner Node   │  Routes by intent
                            └────────┬─────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                       ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │  Retriever Node  │   │  Executor Node   │   │   CHAT Node      │
   │ Hybrid + Rerank  │   │  Tool calling    │   │  Direct reply    │
   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
            └──────────────────────┼──────────────────────┘
                                   ▼
                         ┌──────────────────┐
                         │   Critic Node    │  Hallucination check
                         └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │   AgentTrace     │  Logs latency, tokens, cost, eval scores
                         └──────────────────┘
```

**Multi-tenancy is enforced at two layers:**

- **Relational layer** — every row in `Lead`, `User`, `CustomerPreference`, and `AgentTrace` carries a `tenant_id` foreign key. All queries filter strictly on this column.
- **Vector layer** — every document chunk stored in ChromaDB is tagged with `{"tenant_id": tenant_id}`. All semantic lookups apply this metadata filter, so one business can never retrieve another's documents.

---

## Features

### 1. Deterministic Multi-Agent Supervisor Workflow (LangGraph)

The agent runs as a compiled `StateGraph` with four sequential nodes. Each node has a single responsibility and passes its outputs via a shared `AgentState` dict.

| Node | Responsibility |
|---|---|
| **Planner** | Classifies user intent into `RAG`, `LEAD`, `TOOL`, or `CHAT` using a few-shot prompt. Loads long-term customer memory. |
| **Retriever** | Runs only for `RAG` intent. Performs hybrid search and reranking. |
| **Executor** | Runs tool calls (`save_lead`, `search_web`, `send_email`, `get_current_datetime`) for `LEAD` and `TOOL` intents. |
| **Critic** | Generates the final response. For RAG answers, scores faithfulness, hallucination rate, and retrieval quality using LLM-as-a-judge. Writes an `AgentTrace` row to the database. |

### 2. Advanced Hybrid RAG Pipeline

- **Dense retrieval** — ChromaDB with `all-MiniLM-L6-v2` HuggingFace embeddings (runs locally, no API cost)
- **Sparse retrieval** — BM25 keyword search across the full tenant document corpus (not just the vector results)
- **Deduplication** — merged results are fingerprint-deduplicated before reranking
- **Reranking** — `FlashrankRerank` cross-encoder runs locally on CPU; no external API call needed

### 3. Three-Layer Memory System

| Layer | Storage | Scope |
|---|---|---|
| Short-term | LangGraph `AgentState` message list | Current session only |
| Long-term | `CustomerPreference` SQL table | Persists across sessions per customer per tenant |
| Semantic | Extracted via LLM on every message | Key-value preferences auto-saved in snake_case |

### 4. Real Tool Calling (No Mocks)

All four tools are fully implemented with no stub responses.

| Tool | What it does |
|---|---|
| `save_lead` | Saves customer as a lead to SQLite. Auto-triggers email on hot leads. |
| `search_web` | Live Tavily Search API integration for real-time information. |
| `send_email` | Gmail SMTP via App Password. Logs to console if unconfigured. |
| `get_current_datetime` | Returns real current date and time for scheduling queries. |

### 5. Observability & Evaluation Dashboard

Every conversation is automatically logged as an `AgentTrace` row containing:

- `latency_ms` — wall-clock time from input to response
- `input_tokens` / `output_tokens` — from Gemini response metadata
- `estimated_cost_usd` — calculated from token counts and model pricing
- `faithfulness` — LLM-as-judge score (0.0–1.0), RAG answers only
- `hallucination_rate` — inverse faithfulness score
- `retrieval_quality` — relevance of retrieved chunks to the query

---

## Project Structure

```
SAIBAP-Imperion-V2/
├── agent/
│   ├── agent.py          # LangGraph StateGraph — nodes, routing, run_agent()
│   ├── memory.py         # Long-term preference read/write/extraction
│   ├── rag.py            # Hybrid retrieval pipeline and FlashRank reranker
│   └── tools.py          # Tool implementations — Gmail, Tavily, Leads, Datetime
├── backend/
│   ├── auth.py           # JWT creation, validation, RBAC guards
│   ├── database.py       # SQLModel table definitions and seed function
│   ├── Dockerfile        # Multi-stage container build
│   ├── main.py           # FastAPI routes, lifespan startup, request models
│   └── requirements.txt  # All Python dependencies
├── frontend/
│   ├── .streamlit/
│   │   └── config.toml   # Streamlit theme configuration
│   └── app.py            # Customer chat widget + staff dashboard
├── chroma_db/            # Persisted ChromaDB vector files (auto-created)
├── assistant.db          # SQLite database (auto-created on first run)
├── docker-compose.yml    # Two-container orchestration (backend + frontend)
├── .env                  # API keys and secrets (not committed)
└── .gitignore
```

---

## Setup & Run

### Docker (recommended)

Runs the backend on port `8000` and the frontend on port `8501` in isolated containers.

**1. Clone the repository**

```bash
git clone https://github.com/your-username/SAIBAP-Imperion-V2.git
cd SAIBAP-Imperion-V2
```

**2. Create the `.env` file**

```env
# Gemini LLM
GEMINI_API_KEY=your_google_gemini_api_key

# Tavily Search (get free key at app.tavily.com)
TAVILY_API_KEY=your_tavily_api_key

# JWT signing
SECRET_ENV_KEY=change_this_to_a_random_32_char_string

# Gmail SMTP — optional, logs to console if not set
NOTIFICATION_EMAIL=your_email@gmail.com
EMAIL_PASSWORD=your_16_char_gmail_app_password

# Frontend → backend bridge (use service name for Docker)
BACKEND_URL=http://backend:8000
```

> **Gmail App Password:** Google Account → Security → 2-Step Verification → App Passwords. Generate one for "Mail". Use the 16-character result as `EMAIL_PASSWORD`.

**3. Start the containers**

```bash
docker-compose up --build
```

| Service | URL |
|---|---|
| Customer chat & staff dashboard | http://localhost:8501 |
| API documentation (Swagger) | http://localhost:8000/docs |

---

### Manual (local)

**1. Install dependencies**

```bash
pip install -r backend/requirements.txt
```

> First run downloads two local models: `all-MiniLM-L6-v2` (~90 MB) and the FlashRank reranker (~50 MB). Both are cached after the first download.

**2. Set `BACKEND_URL` in `.env`**

```env
BACKEND_URL=http://127.0.0.1:8000
```

**3. Run the backend**

```bash
uvicorn backend.main:app --reload
```

**4. Run the frontend** (in a separate terminal)

```bash
streamlit run frontend/app.py
```

---

## Default Credentials

The application seeds a default tenant and admin account on first startup. No manual setup required.

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |
| Role | `admin` |
| Tenant | Acme Corp (ID: 1) |

To create additional tenants or staff accounts, log in and use the Staff Dashboard or the Swagger UI at `/docs`.

---

## API Reference

### Public endpoints (no auth)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Customer chat. Send `X-Tenant-ID` header to specify business. |
| `GET` | `/tenants/public` | List all tenant names and IDs for the chat widget dropdown. |
| `GET` | `/health` | Health check. |

### Staff endpoints (requires Bearer JWT)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/login` | Login with username + password. Returns JWT token. |
| `GET` | `/me` | Returns current user's username, role, and tenant_id. |
| `POST` | `/upload` | Upload a PDF to the business knowledge base. |
| `GET` | `/leads` | Get all captured leads for the authenticated user's tenant. |
| `GET` | `/traces` | Get agent observability traces. Supports `?limit=N`. |

### Admin-only endpoints (requires admin role in JWT)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/register` | Create a new staff account for a given tenant. |
| `POST` | `/tenants` | Create a new business tenant workspace. |
| `GET` | `/tenants` | List all tenants with creation timestamps. |

### Chat request format

```http
POST /chat
X-Tenant-ID: 1
Content-Type: application/json
```

```json
{
  "message": "I want to buy 10 units of your premium plan",
  "history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi! How can I help?" }
  ],
  "customer_id": "customer@email.com"
}
```

---

## Technical Decisions

**LangGraph over vanilla LangChain agent loops** — LangGraph's compiled `StateGraph` enforces a deterministic execution order. The Critic node always runs last, guaranteeing that hallucination scoring happens before a response reaches the user. A standard ReAct loop doesn't offer this guarantee.

**Shared-database row isolation over separate databases** — One SQLite file with `tenant_id` foreign keys on every table is simpler to operate than N database files and eliminates connection pool overhead. Suitable for SMB-scale deployments.

**Local FlashRank + HuggingFace embeddings** — Running `all-MiniLM-L6-v2` and `FlashrankRerank` locally keeps document processing private (no data leaves the machine) and cost-free (no embeddings API charges). Trade-off is a slower cold start on first run.

**BM25 over the full document corpus** — BM25 is applied to the complete tenant document pool (not just the top vector results). This means keyword-exact matches for things like product codes or proper nouns that vector search might miss.

**Role-based access control (RBAC)**

| Role | Scope |
|---|---|
| `admin` (Tenant 1) | Platform-wide visibility — can see all tenants, create new workspaces |
| `admin` (Tenant > 1) | Workspace-scoped — can register and manage staff within their tenant |
| `staff` | Operational access — leads, traces, and document uploads for their tenant |

---

## Assumptions & Limitations

- **SQLite** is used for simplicity and portability. For production workloads, replace with PostgreSQL and use Alembic for migrations.
- **ChromaDB** persists to a local `./chroma_db` directory. The BM25 index is in-memory and rebuilt from uploaded documents; it does not survive a backend restart. Re-upload documents after a fresh start if keyword search is needed.
- **Gemini 2.0 Flash** is the target model. Cost estimates in `AgentTrace` are based on its approximate pricing and will be inaccurate if the model is changed.
- **Email** requires a valid Gmail account with App Passwords enabled. If `NOTIFICATION_EMAIL` or `EMAIL_PASSWORD` are not set, email calls log to the console instead of failing.
- **Tavily free tier** allows 1,000 searches per month. The `search_web` tool degrades gracefully with a fallback message if the API is unavailable.
- The platform is designed for demonstration and assessment purposes. Production deployment would require HTTPS, secret rotation, rate limiting, and persistent vector storage.