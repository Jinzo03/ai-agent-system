import os
import sys
import uuid
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

# ==========================================
# STABILITY & COMPATIBILITY LAYER
# ==========================================
CREWAI_STORAGE_DIR = Path(__file__).parent / ".crewai_storage"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["LITELLM_LOG"] = "ERROR"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def local_crewai_storage_path() -> str:
    CREWAI_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return str(CREWAI_STORAGE_DIR)

import crewai.llms.cache as _crewai_cache
_crewai_cache.mark_cache_breakpoint = lambda msg: msg

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
import crewai.memory.storage.kickoff_task_outputs_storage as _kickoff_storage

_kickoff_storage.db_storage_path = local_crewai_storage_path

load_dotenv()

groq_llm = LLM(
    model="groq/llama-3.3-70b-versatile",
    api_key=os.environ.get("GROQ_API_KEY")
)

# ==========================================
# STEP 1: INITIALIZE FASTAPI & IN-MEMORY CACHE
# ==========================================
app = FastAPI(title="Async Industrial Incident API")

# Simple dictionary acting as an in-memory database to store crew reports
jobs_db = {}

class IncidentRequest(BaseModel):
    motor_id: str

# ==========================================
# STEP 2: TOOLS (Unchanged, Fast, Local)
# ==========================================
@tool("Fetch Motor Telemetry Data")
def fetch_motor_telemetry(motor_id: str) -> str:
    """Queries live telemetry logs for an active factory motor."""
    motor_database = {
        "M-404": "TIMESTAMP: 16:12:05 | CURRENT: 18.5 A | VOLTAGE: 10.2 V | SPEED: 450 RPM",
        "M-200": "TIMESTAMP: 16:12:05 | CURRENT: 2.3 A | VOLTAGE: 12.0 V | SPEED: 1150 RPM"
    }
    normalized_id = motor_id.strip().upper()
    return f"Telemetry snapshot for {normalized_id}: {motor_database.get(normalized_id, 'Not Found')}"

@tool("Search Technical Manual")
def search_technical_manual(query: str) -> str:
    """Searches the technical manual PDF for context pages."""
    from pypdf import PdfReader
    pdf_path = "rapport_technique_dataset_reel.pdf"
    if not os.path.exists(pdf_path): return "Error: Manual missing."
    try:
        reader = PdfReader(pdf_path)
        matched = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and any(k in text.lower() for k in query.lower().split()):
                matched.append(f"--- PAGE {i+1} ---\n{text.strip()}")
        return "\n\n".join(matched[:2]) if matched else "No context found."
    except Exception as e: return str(e)


# ==========================================
# STEP 3: BACKGROUND WORKER FUNCTION
# ==========================================
def run_crew_worker(job_id: str, motor_id: str):
    """This function runs inside an isolated background thread."""
    try:
        data_engineer = Agent(
            role='Senior Industrial Data Engineer',
            goal='Query raw motor telemetry via tools and identify statistical anomalies.',
            backstory='Expert in ESP32 sensor parsing for 12V DC motors.',
            llm=groq_llm, tools=[fetch_motor_telemetry]
        )
        diagnostic_analyst = Agent(
            role='Mechanical Diagnostic Analyst',
            goal='Determine physical root causes strictly based on technical manuals.',
            backstory='Electromechanical systems expert.',
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
            description='Analyze data. Search manual for "Surcharge" or "Courant" to diagnose.',
            expected_output='A 2-sentence diagnosis citing the manual.', agent=diagnostic_analyst
        )
        task_write_report = Task(
            description='Compile findings into a clean Markdown incident report.',
            expected_output='A professional clean Markdown formatted incident report.', agent=operations_manager
        )

        crew = Crew(
            agents=[data_engineer, diagnostic_analyst, operations_manager],
            tasks=[task_analyze_data, task_diagnose_fault, task_write_report],
            process=Process.sequential
        )
        
        # Execute the crew and save output to our database
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

# ==========================================
# STEP 4: ASYNC API ENDPOINTS
# ==========================================

@app.post("/api/v1/analyze")
def trigger_analysis(request: IncidentRequest, background_tasks: BackgroundTasks):
    # Generate a unique tracking token for this operation
    job_id = str(uuid.uuid4())
    
    # Register job state as working
    jobs_db[job_id] = {"status": "processing", "target_motor": request.motor_id}
    
    # Hand the job off to the FastAPI background worker thread instantly
    background_tasks.add_task(run_crew_worker, job_id, request.motor_id)
    
    # Return immediately to the client
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