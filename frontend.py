import streamlit as st
import requests
import time

# Configure the UI
st.set_page_config(page_title="Factory AI Monitor", page_icon="🏭", layout="centered")

st.title("Factory Motor AI Diagnostics")
st.markdown("Select a motor from the factory floor to run an asynchronous multi-agent inspection.")

# UI Element: Dropdown menu
motor_id = st.selectbox("Select Target Equipment:", ["M-404", "M-200"])

# UI Element: Action Button
if st.button("Run AI Diagnostics"):
    
    # 1. Trigger the background API job
    with st.spinner("Initializing Multi-Agent Crew..."):
        try:
           start_resp = requests.post(
                "http://backend:8000/api/v1/analyze",  # 👈 CHANGED THIS
                json={"motor_id": motor_id}
            )
           start_resp.raise_for_status()
           job_id = start_resp.json()["job_id"]
        except Exception as e:
            st.error(f"Failed to connect to FastAPI backend: {e}")
            st.stop()

    # 2. Polling Loop
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    poll_count = 0
    while True:
        try:
            # Check the status endpoint
            status_resp = requests.get(f"http://backend:8000/api/v1/status/{job_id}")
            status_data = status_resp.json()
            
            if status_data["status"] == "processing":
                # Update UI to show we are waiting
                poll_count += 1
                progress_bar.progress(min(poll_count * 10, 90)) # Fake progress for UX
                status_placeholder.info(f"⚙️ AI Crew is analyzing telemetry and manuals... (Polling {poll_count})")
                time.sleep(2)
                
            elif status_data["status"] == "completed":
                # Job is done! Render the Markdown
                progress_bar.progress(100)
                status_placeholder.success("Analysis Complete!")
                st.markdown("---")
                st.markdown(status_data["report"])
                break
                
            else:
                status_placeholder.error(f"Job failed: {status_data.get('error', 'Unknown error')}")
                break
                
        except Exception as e:
            st.error(f"Polling error: {e}")
            break