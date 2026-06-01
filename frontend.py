import streamlit as st
import requests
import time

st.set_page_config(page_title="Factory AI Monitor", page_icon="🏭", layout="centered")

st.title("🏭 Custom-Manual Factory AI Monitor")
st.markdown("Upload *any* technical specifications document to context-bound your Multi-Agent execution loop.")

# Dropdown UI
motor_id = st.selectbox("Select Target Equipment:", ["M-404", "M-200"])

# File Uploader UI Widget
uploaded_file = st.file_uploader("Upload machine handbook, schematic, or dataset manual (PDF format only):", type=["pdf"])

if st.button("Run Dynamic AI Diagnostics"):
    if not uploaded_file:
        st.warning("Action Blocked: Please upload a reference manual PDF before running diagnostics.")
        st.stop()
        
    with st.spinner("Streaming reference manual to backend and spinning up Crew..."):
        try:
            # Map parameters out as multi-part form payloads
            payload_data = {"motor_id": motor_id}
            payload_files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
            
            start_resp = requests.post(
                "http://backend:8000/api/v1/analyze", 
                data=payload_data, 
                files=payload_files
            )
            start_resp.raise_for_status()
            job_id = start_resp.json()["job_id"]
        except Exception as e:
            st.error(f"Failed to connect to backend microservice network: {e}")
            st.stop()

    # Dynamic UI Polling Loop
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    poll_count = 0
    while True:
        try:
            status_resp = requests.get(f"http://backend:8000/api/v1/status/{job_id}")
            status_data = status_resp.json()
            
            if status_data["status"] == "processing":
                poll_count += 1
                progress_bar.progress(min(poll_count * 10, 90))
                status_placeholder.info(f"⚙️ AI Crew is actively parsing your uploaded PDF pages and checking parameters... (Polling iteration {poll_count})")
                time.sleep(2)
                
            elif status_data["status"] == "completed":
                progress_bar.progress(100)
                status_placeholder.success("✅ Custom Document Diagnostics Complete!")
                st.markdown("---")
                st.markdown(status_data["report"])
                break
                
            else:
                status_placeholder.error(f"❌ Job execution error reported: {status_data.get('error', 'Details omitted.')}")
                break
                
        except Exception as e:
            st.error(f"Network error during status polling sequence: {e}")
            break