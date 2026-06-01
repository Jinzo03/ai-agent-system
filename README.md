#  Factory AI Monitor : Multi-Agent Industrial Diagnostic System

> **Context-bound, document-driven fault diagnostics for industrial DC motors, powered by a CrewAI multi-agent pipeline running on Groq's Llama 3.3 70B.**

---

##  About

Factory AI Monitor is an end-to-end intelligent diagnostic platform designed for industrial environments where motor health monitoring is mission-critical. Rather than relying on a fixed knowledge base, the system is **context-bound** — operators upload their own machine handbooks, schematics, or dataset manuals at runtime, and a coordinated crew of AI agents uses that document as the authoritative reference for every diagnostic decision it makes.

Three specialized AI agents collaborate in a sequential pipeline: a Data Engineer pulls live telemetry readings for the selected motor, a Diagnostic Analyst cross-references those readings against the operator-supplied PDF manual, and an Operations Manager synthesizes all findings into a clean, actionable Markdown incident report. The entire workflow runs asynchronously in the background, with the frontend polling for results in real time, making the system fully non-blocking and production-safe.

---

##  System Architecture

```
┌─────────────────────────┐          ┌──────────────────────────────────────────────┐
│   Streamlit Frontend    │          │              FastAPI Backend                  │
│  (frontend.py :8501)    │          │               (main.py :8000)                 │
│                         │          │                                               │
│  [Motor Selector]       │  POST    │  /api/v1/analyze  ──► Background Task        │
│  [PDF Upload Widget] ───┼─────────►│       │                    │                  │
│  [Run Diagnostics Btn]  │          │       ▼                    ▼                  │
│                         │  GET     │  jobs_db (in-memory)   CrewAI Crew           │
│  [Progress Bar]    ◄────┼─────────►│  /api/v1/status/{id}      │                  │
│  [Report Display]       │          │                        ┌───┴────────────┐     │
└─────────────────────────┘          │                        │  Agent 1       │     │
                                     │                        │  Data Engineer │     │
                                     │                        │  (Telemetry)   │     │
                                     │                        ├────────────────┤     │
                                     │                        │  Agent 2       │     │
                                     │                        │  Diagnostic    │     │
                                     │                        │  Analyst (PDF) │     │
                                     │                        ├────────────────┤     │
                                     │                        │  Agent 3       │     │
                                     │                        │  Ops Manager   │     │
                                     │                        │  (Report)      │     │
                                     │                        └────────────────┘     │
                                     └──────────────────────────────────────────────┘
```

Both services are containerized and orchestrated via Docker Compose. The backend mounts an isolated `/uploads` scratch directory for ephemeral PDF storage per job, and cleans up after every completed run.

---

## 🤖 The AI Crew — Agent Breakdown

### Agent 1 — Senior Industrial Data Engineer
- **Responsibility:** Queries the in-memory telemetry database for the selected motor and identifies statistical anomalies in the raw readings.
- **Tool:** `fetch_motor_telemetry(motor_id)` — Returns a timestamped snapshot of Current (A), Voltage (V), and Speed (RPM).
- **Model:** Groq / Llama-3.3-70B-Versatile

### Agent 2 — Mechanical Diagnostic Analyst
- **Responsibility:** Takes the telemetry summary from Agent 1 and searches the operator-uploaded PDF manual to find pages that contextually explain the anomaly or physical root cause.
- **Tool:** `search_technical_manual(query)` — A dynamically scoped closure tool that locks to the specific PDF file uploaded for the current job. This prevents cross-contamination between concurrent runs.
- **Model:** Groq / Llama-3.3-70B-Versatile

### Agent 3 — Factory Operations Manager
- **Responsibility:** Receives the raw diagnosis from Agent 2 and produces a clean, formatted Markdown incident report suitable for maintenance teams.
- **Tools:** None (synthesis-only agent)
- **Model:** Groq / Llama-3.3-70B-Versatile

---

##  Key Design Decisions

### Dynamic Tool Scoping via Closure
Each background job creates its own `search_technical_manual` tool instance using a **closure over `pdf_path`**. This means Agent 2 is always bound to the PDF uploaded for *that specific request*, ensuring that concurrent jobs from different operators never read each other's documents.

### Asynchronous Job Pattern
The `/api/v1/analyze` endpoint immediately returns a `job_id` and offloads the entire CrewAI execution to FastAPI's `BackgroundTasks`. The frontend polls `/api/v1/status/{job_id}` every 2 seconds until the job reports `completed` or `failed`. This design keeps the API non-blocking and HTTP timeouts irrelevant.

### Ephemeral File Handling
Uploaded PDFs are written to a sandboxed `/uploads/` directory using `shutil.copyfileobj` (chunked streaming, memory-safe), named after the UUID job ID. The file is unconditionally deleted in the `finally` block of the worker — even if the crew fails — preventing server storage accumulation in long-running deployments.

### LangSmith Observability
All three execution layers — tool calls, retrieval operations, and the top-level crew chain — are decorated with `@traceable`, giving full end-to-end visibility in LangSmith. The system gracefully disables tracing if no API key is provided, with no crash or degradation.

---

##  Project Structure

```
factory-ai-monitor/
│
├── main.py                   # FastAPI backend — agents, tools, job runner, endpoints
├── frontend.py               # Streamlit UI — upload, motor select, polling loop
│
├── Dockerfile.backend        # Python 3.11-slim image, uvicorn entrypoint
├── Dockerfile.frontend       # Python 3.11-slim image, streamlit entrypoint
├── docker-compose.yml        # Two-service orchestration (backend + frontend)
│
├── requirements.txt          # All Python dependencies
├── .env.example              # Template for required environment variables
└── .gitignore                # Excludes .env, venv, storage, PDF, pycache
```

---

##  Getting Started

### Prerequisites
- [Docker](https://www.docker.com/get-started) and Docker Compose installed
- A [Groq](https://console.groq.com/) API key (free tier available)
- *(Optional)* A [LangSmith](https://smith.langchain.com/) API key for tracing

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/factory-ai-monitor.git
cd factory-ai-monitor
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```env
GROQ_API_KEY=gsk_your_actual_groq_key_here

# Optional — remove or leave blank to disable tracing
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_your_langsmith_key_here
LANGSMITH_PROJECT=Factory_AI_Diagnostics
```

> **Note:** If `LANGSMITH_API_KEY` is absent, tracing is automatically disabled. The system will not crash.

### 3. Build and Launch

```bash
docker compose up --build
```

This builds both images and starts:
| Service  | URL                         |
|----------|-----------------------------|
| Frontend | http://localhost:8501       |
| Backend  | http://localhost:8000       |
| API Docs | http://localhost:8000/docs  |

### 4. Run a Diagnostic

1. Open **http://localhost:8501** in your browser.
2. Select a motor from the dropdown (`M-404` or `M-200`).
3. Upload a PDF — your machine handbook, datasheet, or technical manual.
4. Click **Run Dynamic AI Diagnostics**.
5. Watch the progress bar and wait for the Markdown report to appear.

---

##  API Reference

### `POST /api/v1/analyze`

Triggers a new diagnostic job. Accepts `multipart/form-data`.

| Field      | Type   | Description                              |
|------------|--------|------------------------------------------|
| `motor_id` | string | Target motor identifier (e.g. `M-404`)  |
| `file`     | file   | PDF technical manual (binary upload)    |

**Response:**
```json
{
  "status": "accepted",
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "check_status_url": "/api/v1/status/f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

---

### `GET /api/v1/status/{job_id}`

Returns the current state of a diagnostic job.

**While processing:**
```json
{
  "status": "processing",
  "target_motor": "M-404"
}
```

**On success:**
```json
{
  "status": "completed",
  "target_motor": "M-404",
  "report": "## Incident Report\n\n..."
}
```

**On failure:**
```json
{
  "status": "failed",
  "error": "Description of what went wrong"
}
```

---

##  Supported Motor Profiles

| Motor ID | Typical Current | Voltage | Speed    | Expected Status    |
|----------|-----------------|---------|----------|--------------------|
| `M-404`  | 18.5 A          | 10.2 V  | 450 RPM  | Anomaly / Overload |
| `M-200`  | 2.3 A           | 12.0 V  | 1150 RPM | Normal Operation   |

> Telemetry values are sourced from an in-memory mock database representative of ESP32 + ACS712 sensor readings. Extending to live sensor feeds requires replacing `_fetch_motor_telemetry_impl`.

---

##  Technology Stack

| Layer           | Technology                                        |
|-----------------|---------------------------------------------------|
| LLM Inference   | [Groq](https://groq.com/) — Llama 3.3 70B Versatile |
| Agent Framework | [CrewAI](https://www.crewai.com/) — Sequential multi-agent pipeline |
| PDF Parsing     | [pypdf](https://pypdf.readthedocs.io/) — Keyword-based page extraction |
| Backend API     | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn |
| Frontend UI     | [Streamlit](https://streamlit.io/)                |
| Observability   | [LangSmith](https://smith.langchain.com/) — `@traceable` decorators |
| Containerization| Docker + Docker Compose                           |

---

##  Observability with LangSmith

When a valid `LANGSMITH_API_KEY` is provided, every run is automatically traced at three levels:

- **Chain level** — `Factory AI Diagnostics Crew` (full crew execution)
- **Retriever level** — `Search Technical Manual` (PDF page retrieval per query)
- **Tool level** — `Fetch Motor Telemetry Data` (database lookup)

Access your traces at [smith.langchain.com](https://smith.langchain.com) under the project `Factory_AI_Diagnostics`.

---

##  Limitations & Known Constraints

- **In-memory job store:** `jobs_db` is a plain Python dict. Restarting the backend process clears all job history. For persistent state, replace with Redis or a lightweight database.
- **PDF keyword search:** The manual retrieval uses simple keyword matching, not semantic vector search. Dense or specialized documents may not match well with broad queries.
- **Single-node concurrency:** BackgroundTasks runs in the same process as FastAPI. Under heavy load, consider offloading to Celery + Redis.
- **Mock telemetry:** The motor database is static. Production integration requires wiring `_fetch_motor_telemetry_impl` to a real MQTT broker, InfluxDB, or REST sensor API.

---

##  Potential Extensions

- **Live sensor integration** — Replace mock telemetry with real ESP32 MQTT feeds
- **Semantic PDF retrieval** — Replace keyword search with a vector store (FAISS, ChromaDB) for better context extraction
- **Multi-motor dashboard** — Extend the Streamlit UI to support fleet-wide monitoring panels
- **Persistent job history** — Add Redis or SQLite backend for `jobs_db`
- **Alert system** — Auto-trigger diagnostics on threshold breach events and notify via email/Slack
- **Classification model integration** — Feed the Logistic Regression motor classifier output directly into the telemetry tool

---

##  License

This project is released for academic and educational purposes.

---

*Built as part of an end-of-year engineering project — ENSTAB, Advanced Technologies Program.*
