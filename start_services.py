import subprocess
import sys
import time
from pathlib import Path

# Detach flags on Windows
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

# Start Live Trace Server
trace_log = open("live_trace_server.log", "w", encoding="utf-8")
p_trace = subprocess.Popen(
    [sys.executable, "-m", "live_trace.server"],
    stdout=trace_log,
    stderr=trace_log,
    creationflags=flags,
    close_fds=True,
)

# Start Streamlit Frontend
streamlit_log = open("streamlit_frontend.log", "w", encoding="utf-8")
p_streamlit = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "browser.py", "--server.port", "8501", "--server.headless", "true"],
    stdout=streamlit_log,
    stderr=streamlit_log,
    creationflags=flags,
    close_fds=True,
)

print(f"Launched Live Trace (PID: {p_trace.pid}) and Streamlit (PID: {p_streamlit.pid})")
time.sleep(3)
