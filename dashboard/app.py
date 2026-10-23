"""
StudyBuddy Dashboard - Main App
AG-UI (Agent-User Interface) for Human-in-the-Loop interaction
Multi-page Streamlit application
"""
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
from src.services.dynamodb import dynamodb_service
from src.agents.safety import SafetyAgent

st.set_page_config(
    page_title="StudyBuddy | Energy-Aware Study Coach",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    }
    .stMetric {
        background: rgba(255,255,255,0.05);
        border-radius: 10px;
        padding: 15px;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 25px;
        padding: 10px 24px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
    }
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("""
<div style="text-align: center; padding: 16px 0;">
    <h1 style="font-size: 2.2em; margin: 0;">🧠</h1>
    <h2 style="margin: 8px 0; color: #667eea;">StudyBuddy</h2>
    <p style="color: #94a3b8; font-size: 0.85em;">v2.1 | Alexa+ & Jarvis Edition</p>
</div>
""", unsafe_allow_html=True)

# System Connectivity Indicator
storage_mode = "☁️ DynamoDB Online" if dynamodb_service.using_dynamodb else "🟢 Online (Local SQLite Engine)"
st.sidebar.success(f"Status: {storage_mode}")

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Home", "📊 Analytics", "⚙️ Settings"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")

try:
    safety = SafetyAgent()
    safety_status = safety.get_safety_summary("user_123")

    st.sidebar.subheader("🛡️ Safety Status")
    st.sidebar.metric(
        "Daily Used",
        f"{safety_status['daily_used']}/{safety_status['daily_cap']} min"
    )
    st.sidebar.progress(min(1.0, safety_status['daily_percent'] / 100.0))

    if safety_status.get('past_sleep_cutoff'):
        st.sidebar.warning(f"🌙 Past sleep cutoff ({safety_status['sleep_cutoff']}:00) — Override available")
    elif safety_status.get('sleep_cutoff_approaching'):
        st.sidebar.warning("⏰ Sleep cutoff approaching")

    if safety_status['daily_remaining'] <= 0:
        st.sidebar.error("🚫 Daily study limit reached")
except Exception as e:
    st.sidebar.info("🛡️ Safety Guardrails Active")

if page == "🏠 Home":
    st.switch_page("pages/01_Session.py")
elif page == "📊 Analytics":
    st.switch_page("pages/02_Analytics.py")
elif page == "⚙️ Settings":
    st.switch_page("pages/03_Settings.py")
