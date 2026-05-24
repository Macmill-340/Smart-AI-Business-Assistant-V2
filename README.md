# Smart AI Business Assistant Platform (SAIBAP)

SAIBAP is a production-oriented MVP of an AI-powered business operations assistant. It enables Small and Medium Enterprises (SMEs) to automate customer support, capture and qualify leads, and perform Retrieval-Augmented Generation (RAG) over internal business documents.

---

## 🏗 Architecture

The system is built on a **Microservices Architecture**:

- **Agentic Orchestration:** Powered by **LangGraph**, utilizing a deterministic state machine (Planner → Executor → Critic) to ensure logical consistency and prevent hallucinations.
- **Backend API:** Built with **FastAPI**, featuring JWT-based authentication and SQLModel (ORM) integration.
- **Frontend/Dashboard:** A **Streamlit**-based interface providing a public-facing assistant and a secure staff dashboard for lead analytics and knowledge base management.
- **Vector Database:** **ChromaDB** with local HuggingFace embeddings for privacy-focused document retrieval.

---

## ✨ Features

- **Deterministic Multi-Agent Workflow:** Planner node routes user intent; Executor node triggers RAG or Lead Capture; Critic node validates response quality.
- **Automated Lead Capture:** Natural language extraction of customer name, intent, and requirements, stored in an indexed SQLite database.
- **Contextual Memory:** Rolling chat history is preserved across the frontend-backend bridge to support multi-turn complex requests.
- **Mock CRM/Calendar Integrations:** Extensible tool-calling logic that simulates real-world API triggers.

---

## 📁 Project Structure

```
SAIBAP-Imperion/
├── agent/
│   ├── agent.py
│   └── rag.py
├── backend/
│   ├── auth.py
│   ├── database.py
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── chroma_db/
├── frontend/
├── .env
├── .gitignore
├── assistant.db
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── uv.lock
```

---

## 🚀 Setup & Execution

### Prerequisites

- Python 3.12+
- A Google Gemini API Key

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/SAIBAP-Imperion.git
cd SAIBAP-Imperion
```

### 2. Environment Configuration

Create a `.env` file in the root directory:

```env
SECRET_ENV_KEY=your_secret_jwt_key
ALGORITHM_ENV_KEY=HS256
GEMINI_API_KEY=your_google_gemini_api_key
BACKEND_URL=http://backend:8000
```

### 3. Run with Docker (Recommended)

```bash
docker-compose up --build
```

- **Staff Dashboard:** http://localhost:8501
- **API Documentation (Swagger):** http://localhost:8000/docs

### 4. Run Locally (Manual)

**Install Dependencies:**

```bash
pip install -r backend/requirements.txt
```

**Start Backend:**

```bash
uvicorn backend.main:app --reload
```

**Start Frontend:**

```bash
streamlit run frontend/app.py
```

---

## 📝 Technical Decisions

- **LangGraph:** Chosen over standard autonomous agents to enforce a predictable "Critic" step, ensuring the AI never provides raw data without a human-friendly confirmation.
- **B2B2C Access Control:** The Assistant chat remains public for customers, while the Lead Dashboard and Document Upload are secured via JWT to protect business intelligence.