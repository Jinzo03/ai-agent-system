import os
import sys
from pathlib import Path
from dotenv import load_dotenv

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

# Fixes the 'cache_breakpoint' injection crash on Groq's API
import crewai.llms.cache as _crewai_cache
_crewai_cache.mark_cache_breakpoint = lambda msg: msg

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool  # 🔧 Import the tool decorator
import crewai.memory.storage.kickoff_task_outputs_storage as _kickoff_storage

_kickoff_storage.db_storage_path = local_crewai_storage_path

# Load the API key
load_dotenv()

print("Booting up the Autonomous Industrial Incident Team with Function Calling...")

# Set up the active Groq model
groq_llm = LLM(
    model="groq/llama-3.3-70b-versatile",
    api_key=os.environ.get("GROQ_API_KEY")
)

# ==========================================
# STEP 1: DEFINE CUSTOM TOOLS
# ==========================================

@tool("Fetch Motor Telemetry Data")
def fetch_motor_telemetry(motor_id: str) -> str:
    """
    Queries live telemetry logs for an active factory motor.
    Returns sensor values tracking Voltage (V), Current (A), and Speed (RPM) 
    matching the ESP32 physical configuration layout.
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
    for specific technical terms (such as 'Surcharge' or 'Courant') and extracts the text context.
    """
    from pypdf import PdfReader
    
    pdf_path = "rapport_technique_dataset_reel.pdf"
    if not os.path.exists(pdf_path):
        return f"Error: Technical manual file '{pdf_path}' not found in the current directory."
    
    try:
        reader = PdfReader(pdf_path)
        matched_pages = []
        
        # Breakdown query into independent search keywords
        keywords = [k.lower().strip() for k in query.split() if len(k.strip()) > 2]
        if not keywords:
            keywords = [query.lower().strip()]
            
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text:
                continue
            
            # Match keywords case-insensitively
            if any(kw in text.lower() for kw in keywords):
                matched_pages.append(f"--- PAGE {i+1} ---\n{text.strip()}")
                
        if matched_pages:
            # Return up to the first 3 relevant pages to stay within safe model context bounds
            return "\n\n".join(matched_pages[:3])
        else:
            return f"No direct text matched '{query}' in the manual. Try searching with individual terms like 'Surcharge' or 'Courant'."
            
    except Exception as e:
        return f"Error reading technical manual: {str(e)}"


# ==========================================
# STEP 2: DEFINE THE AGENTS (With Tools)
# ==========================================

data_engineer = Agent(
    role='Senior Industrial Data Engineer',
    goal='Query raw motor telemetry via tools and identify statistical anomalies.',
    backstory='You have 10 years of experience reading ESP32 sensor data for 12V DC motors. You know that a healthy motor runs under 5 Amps, and any sudden spike indicates a severe issue.',
    verbose=False,
    allow_delegation=False,
    llm=groq_llm,
    tools=[fetch_motor_telemetry]
)

diagnostic_analyst = Agent(
    role='Mechanical Diagnostic Analyst',
    goal='Determine the physical root cause of a motor fault strictly based on the company technical manual.',
    backstory='You are an expert in electromechanical systems. You do not guess. You always search the technical documentation to map data anomalies (like high current) to their official physical causes.',
    verbose=False,
    allow_delegation=False,
    llm=groq_llm,
    tools=[search_technical_manual]  # 🔧 Swapped to our secure local manual tool
)

operations_manager = Agent(
    role='Factory Operations Manager',
    goal='Draft a concise, actionable incident report for the maintenance team.',
    backstory='You manage the factory floor. You hate technical jargon. You need clear, bulleted reports telling your maintenance team exactly what broke and what to fix.',
    verbose=False,
    allow_delegation=False,
    llm=groq_llm
)

# ==========================================
# STEP 3: DEFINE THE TASKS (Dynamic Execution)
# ==========================================

task_analyze_data = Task(
    description='Use your tools to query the active telemetry database for motor M-404. Review the returned readings and assess if they indicate normal operations or an electrical/mechanical anomaly.',
    expected_output='A short summary analyzing the fetched telemetry profile and highlighting any out-of-bounds metrics.',
    agent=data_engineer
)

task_diagnose_fault = Task(
    description='Take the data engineer\'s analysis. Use the search_technical_manual tool to search the technical manual for "Surcharge" or "Courant" to determine what physical phenomenon causes these specific data spikes.',
    expected_output='A 2-sentence diagnosis citing the technical manual.',
    agent=diagnostic_analyst
)

task_write_report = Task(
    description='Compile the technical findings into a clean Markdown incident report. Outline what data was fetched by the tools, what physical fault was diagnosed, and list actionable mitigation steps for the repair crews.',
    expected_output='A professional, clean Markdown formatted incident report.',
    agent=operations_manager
)

# ==========================================
# STEP 4: RUN THE AUTOMATED SYSTEM
# ==========================================

incident_crew = Crew(
    agents=[data_engineer, diagnostic_analyst, operations_manager],
    tasks=[task_analyze_data, task_diagnose_fault, task_write_report],
    process=Process.sequential
)

result = incident_crew.kickoff()

print("\n\n================================================")
print("FINAL OUTPUT GENERATED BY THE SYSTEM (DYNAMIC TOOL EXECUTION):")
print("================================================\n")
print(result)