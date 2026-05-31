import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ==========================================
# STABILITY & COMPATIBILITY LAYER (Codex Patches)
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

# Set up the active Groq model
groq_llm = LLM(
    model="groq/llama-3.3-70b-versatile",
    api_key=os.environ.get("GROQ_API_KEY")
)

# ==========================================
# STEP 1: INITIALIZE FASTAPI APP
# ==========================================
app = FastAPI(
    title="Autonomous Industrial Incident API",
    description="Microservice to trigger Multi-Agent CrewAI inspections for 12V DC Motors.",
    version="1.0.0"
)

# Define the structured request body requirements
class IncidentRequest(BaseModel):
    motor_id: str

# ==========================================
# STEP 2: DEFINE CUSTOM TOOLS
# ==========================================

@tool("Fetch Motor Telemetry Data")
def fetch_motor_telemetry(motor_id: str) -> str:
    """
    Queries live telemetry logs for an active factory motor.
    Returns sensor values tracking Voltage (V), Current (A), and Speed (RPM).
    """
    motor_database = {
        "M-404": "TIMESTAMP: 16:12:05 | CURRENT: 18.5 A | VOLTAGE: 10.2 V | SPEED: 450 RPM",
        "M-200": "TIMESTAMP: 16:12:05 | CURRENT: 2.3 A | VOLTAGE: 12.0 V | SPEED: 1150 RPM"
    }
    
    normalized_id = motor_id.strip().upper()
    if normalized_id in motor_database:
        return f"Telemetry snapshot for {normalized_id}: {motor_database[normalized_id]}"
    else:
        return f"Warning: Motor ID '{motor_id}' not found in active telemetry register."


@tool("Search Technical Manual")
def search_technical_manual(query: str) -> str:
    """
    Searches the company's technical manual (rapport_technique_dataset_reel.pdf) 
    for specific terms ('Surcharge', 'Courant') and extracts the page text context.
    """
    from pypdf import PdfReader
    
    pdf_path = "rapport_technique_dataset_reel.pdf"
    if not os.path.exists(pdf_path):
        return f"Error: Technical manual file '{pdf_path}' not found."
    
    try:
        reader = PdfReader(pdf_path)
        matched_pages = []
        keywords = [k.lower().strip() for k in query.split() if len(k.strip()) > 2]
        if not keywords:
            keywords = [query.lower().strip()]
            
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and any(kw in text.lower() for kw in keywords):
                matched_pages.append(f"--- PAGE {i+1} ---\n{text.strip()}")
                
        if matched_pages:
            return "\n\n".join(matched_pages[:3])
        return f"No context found matching '{query}' inside manual."
    except Exception as e:
        return f"Error reading manual: {str(e)}"


# ==========================================
# STEP 3: API ENDPOINT (The Operational Core)
# ==========================================

@app.post("/api/v1/analyze")
def trigger_incident_analysis(request: IncidentRequest):
    print(f"Received analysis request for target: {request.motor_id}")
    
    # 1. Re-initialize Agents cleanly per API call
    data_engineer = Agent(
        role='Senior Industrial Data Engineer',
        goal='Query raw motor telemetry via tools and identify statistical anomalies.',
        backstory='Expert in ESP32 sensor parsing for 12V DC motors. Knows healthy bounds (< 5 Amps).',
        verbose=False,
        allow_delegation=False,
        llm=groq_llm,
        tools=[fetch_motor_telemetry]
    )

    diagnostic_analyst = Agent(
        role='Mechanical Diagnostic Analyst',
        goal='Determine the physical root cause of a motor fault strictly based on the company technical manual.',
        backstory='Electromechanical systems expert who cross-references telemetry issues directly with documentation.',
        verbose=False,
        allow_delegation=False,
        llm=groq_llm,
        tools=[search_technical_manual]
    )

    operations_manager = Agent(
        role='Factory Operations Manager',
        goal='Draft a concise, actionable incident report for the maintenance team.',
        backstory='Floor supervisor who demands clean, technical-jargon-free Markdown lists outlining updates.',
        verbose=False,
        allow_delegation=False,
        llm=groq_llm
    )

    # 2. Dynamically pass the API payload (motor_id) straight into the task description
    task_analyze_data = Task(
        description=f'Use your tools to query the active telemetry database for motor {request.motor_id}. Review the returned readings and assess if they indicate normal operations or an anomaly.',
        expected_output='A short summary analyzing the fetched telemetry profile.',
        agent=data_engineer
    )

    task_diagnose_fault = Task(
        description='Take the data engineer\'s analysis. Use the search_technical_manual tool to check the manual for "Surcharge" or "Courant" to determine what physical phenomenon matches these specific numbers.',
        expected_output='A 2-sentence diagnosis citing the technical manual findings.',
        agent=diagnostic_analyst
    )

    task_write_report = Task(
        description='Compile findings into a clean Markdown incident report detailing data fetched, physical fault diagnosed, and mitigation actions.',
        expected_output='A professional, clean Markdown formatted incident report.',
        agent=operations_manager
    )

    # 3. Assemble and execute
    try:
        incident_crew = Crew(
            agents=[data_engineer, diagnostic_analyst, operations_manager],
            tasks=[task_analyze_data, task_diagnose_fault, task_write_report],
            process=Process.sequential
        )
        
        # Kickoff returns a CrewOutput object; convert it to string
        final_markdown_report = str(incident_crew.kickoff())
        
        return {
            "status": "success",
            "target_motor": request.motor_id,
            "report": final_markdown_report
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Execution Failure: {str(e)}")