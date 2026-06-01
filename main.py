import os
import sys
import uuid
import shutil
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Form

# ==========================================
# STABILITY & COMPATIBILITY LAYER
# ==========================================
CREWAI_STORAGE_DIR = Path(__file__).parent / ".crewai_storage"
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["LITELLM_LOG"] = "ERROR"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

def configure_langsmith_env() -> None:
    """Accept both current LangSmith env vars and older LangChain aliases."""
    aliases = {
        "LANGSMITH_TRACING": "LANGCHAIN_TRACING_V2",
        "LANGSMITH_ENDPOINT": "LANGCHAIN_ENDPOINT",
        "LANGSMITH_API_KEY": "LANGCHAIN_API_KEY",
        "LANGSMITH_PROJECT": "LANGCHAIN_PROJECT",
    }
    for current_name, legacy_name in aliases.items():
        current_value = os.environ.get(current_name)
        legacy_value = os.environ.get(legacy_name)
        if not current_value and legacy_value:
            os.environ[current_name] = legacy_value
        if not legacy_value and current_value:
            os.environ[legacy_name] = current_value

    if (
        os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
        and not os.environ.get("LANGSMITH_API_KEY")
    ):
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

configure_langsmith_env()

def local_crewai_storage_path() -> str:
    CREWAI_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return str(CREWAI_STORAGE_DIR)

import crewai.llms.cache as _crewai_cache
_crewai_cache.mark_cache_breakpoint = lambda msg: msg

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from langsmith import Client as LangSmithClient
from langsmith import traceable
import crewai.memory.storage.kickoff_task_outputs_storage as _kickoff_storage

_kickoff_storage.db_storage_path = local_crewai_storage_path

groq_llm = LLM(
    model="groq/llama-3.3-70b-versatile",
    api_key=os.environ.get("GROQ_API_KEY")
)

# ==========================================
# STEP 1: INITIALIZE FASTAPI & IN-MEMORY CACHE
# ==========================================
app = FastAPI(title="Async Industrial Incident API")

jobs_db = {}

# ==========================================
# STEP 2: GLOBAL TRACEABLE IMPLEMENTATIONS
# ==========================================
@traceable(name="Fetch Motor Telemetry Data", run_type="tool")
def _fetch_motor_telemetry_impl(motor_id: str) -> str:
    motor_database = {
        "M-404": "TIMESTAMP: 16:12:05 | CURRENT: 18.5 A | VOLTAGE: 10.2 V | SPEED: 450 RPM",
        "M-200": "TIMESTAMP: 16:12:05 | CURRENT: 2.3 A | VOLTAGE: 12.0 V | SPEED: 1150 RPM"
    }
    normalized_id = motor_id.strip().upper()
    return f"Telemetry snapshot for {normalized_id}: {motor_database.get(normalized_id, 'Not Found')}"

@tool("Fetch Motor Telemetry Data")
def fetch_motor_telemetry(motor_id: str) -> str:
    """Queries live telemetry logs for an active factory motor."""
    return _fetch_motor_telemetry_impl(motor_id)

# UPGRADED: Accepts dynamic path per execution thread
@traceable(name="Search Technical Manual", run_type="retriever")
def _search_technical_manual_impl(query: str, pdf_path: str) -> str:
    from pypdf import PdfReader
    if not os.path.exists(pdf_path): return "Error: Dynamic reference manual file is missing."
    try:
        reader = PdfReader(pdf_path)
        matched = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and any(k in text.lower() for k in query.lower().split()):
                matched.append(f"--- PAGE {i+1} ---\n{text.strip()}")
        return "\n\n".join(matched[:2]) if matched else f"No context found matching '{query}' inside uploaded document."
    except Exception as e: return str(e)


# ==========================================
# STEP 3: BACKGROUND WORKER FUNCTION
# ==========================================
@traceable(name="Factory AI Diagnostics Crew", run_type="chain")
def run_crew_worker(job_id: str, motor_id: str, pdf_path: str):
    """This function runs inside an isolated background thread with a targeted file path."""
    try:
        # Dynamic Tool Definition via Closure - Locks the Agent to this specific run's file
        @tool("Search Technical Manual")
        def search_technical_manual(query: str) -> str:
            """Searches the custom technical manual uploaded by the operator for context pages."""
            return _search_technical_manual_impl(query, pdf_path)

        data_engineer = Agent(
            role='Senior Industrial Data Engineer',
            goal='Query raw motor telemetry via tools and identify statistical anomalies.',
            backstory='Expert in ESP32 sensor parsing for 12V DC motors.',
            llm=groq_llm, tools=[fetch_motor_telemetry]
        )
        diagnostic_analyst = Agent(
            role='Mechanical Diagnostic Analyst',
            goal='Determine physical root causes strictly based on the provided technical manual tool.',
            backstory='Electromechanical systems expert who isolates failures using uploaded manuals.',
            llm=groq_llm, tools=[search_technical_manual]
        )
        operations_manager = Agent(
            role='Factory Operations Manager',
            goal='Draft a concise, actionable incident report for the maintenance team.',
            backstory='Floor supervisor requiring Markdown outputs.',
            llm=groq_llm
        )

        task_analyze_data = Task(
            description=f'Query active telemetry database for motor {motor_id} and assess operations.',
            expected_output='A summary analyzing metrics.', agent=data_engineer
        )
        task_diagnose_fault = Task(
            description='Analyze telemetry bounds. Search the custom uploaded manual via your tool to determine what system anomaly or physical limitation explains these numbers.',
            expected_output='A professional diagnosis citing manual findings.', agent=diagnostic_analyst
        )
        task_write_report = Task(
            description='Compile findings into a clean Markdown incident report detailing metrics tracked and the manual diagnosis.',
            expected_output='A professional clean Markdown formatted incident report.', agent=operations_manager
        )

        crew = Crew(
            agents=[data_engineer, diagnostic_analyst, operations_manager],
            tasks=[task_analyze_data, task_diagnose_fault, task_write_report],
            process=Process.sequential
        )
        
        output = crew.kickoff()
        jobs_db[job_id] = {
            "status": "completed",
            "target_motor": motor_id,
            "report": str(output)
        }
    except Exception as e:
        jobs_db[job_id] = {
            "status": "failed",
            "error": str(e)
        }
    finally:
        # Crucial Production Clean Up: Delete file when done to prevent server storage bloat
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass
        if os.environ.get("LANGSMITH_API_KEY"):
            LangSmithClient().flush()

# ==========================================
# STEP 4: MULTIPART FORM API ENDPOINTS
# ==========================================

@app.post("/api/v1/analyze")
def trigger_analysis(
    background_tasks: BackgroundTasks,
    motor_id: str = Form(...),          # Accepts form variables instead of flat JSON
    file: UploadFile = File(...)        # Intercepts incoming binary stream
):
    job_id = str(uuid.uuid4())
    
    # Track destination path safely inside the container's scratch directory
    temp_file_path = UPLOAD_DIR / f"{job_id}.pdf"
    
    try:
        # Stream the file chunk by chunk to prevent memory overflows
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process manual upload: {str(e)}")
    
    jobs_db[job_id] = {"status": "processing", "target_motor": motor_id}
    
    # Hand off the clean local path directly to your tracing worker thread
    background_tasks.add_task(run_crew_worker, job_id, motor_id, str(temp_file_path))
    
    return {
        "status": "accepted",
        "job_id": job_id,
        "check_status_url": f"/api/v1/status/{job_id}"
    }

@app.get("/api/v1/status/{job_id}")
def get_job_status(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job execution ID not found.")
    return jobs_db[job_id]