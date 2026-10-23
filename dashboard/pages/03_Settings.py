"""
StudyBuddy Settings Page
User preferences, limits, and system configuration with real persistence!
Fixes:
All buttons now persist changes to UserProfile (DynamoDB/SQLite) and runtime `settings`.
"""
import streamlit as st
import asyncio
import concurrent.futures
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config import settings
from src.models.schemas import StudyMode
from src.services.dynamodb import dynamodb_service
from src.services.memory import memory_service
from src.services.voice import voice_service

st.set_page_config(page_title="Settings | StudyBuddy", layout="wide")

st.title("⚙️ Settings")
st.markdown("Configure your study preferences, voice engine, and safety guardrails")


def run_async(coro):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


st.subheader("👤 Profile")
profile = run_async(memory_service.get_or_create_profile("user_123"))

col1, col2 = st.columns(2)
with col1:
    st.text_input("User ID", value=profile.user_id, disabled=True)
    st.date_input("Member Since", value=profile.created_at.date() if profile else None, disabled=True)

with col2:
    mode_choices = ["Auto", "Overkill", "Sustenance", "Low", "Custom"]
    current_pref = profile.preferred_mode.value if profile.preferred_mode else "Auto"
    pref_idx = mode_choices.index(current_pref) if current_pref in mode_choices else 0
    preferred = st.selectbox("Preferred Study Mode", mode_choices, index=pref_idx)

    if st.button("💾 Save Preferences"):
        profile.preferred_mode = StudyMode(preferred) if preferred != "Auto" else None
        dynamodb_service.update_user_profile(profile)
        st.success(f"Preferences saved! Preferred mode: {preferred}")

st.divider()

st.subheader("🛡️ Study Limits")
col_lim1, col_lim2 = st.columns(2)

with col_lim1:
    daily_cap = st.slider("Daily Study Cap (minutes)", 60, 480, int(settings.DAILY_STUDY_CAP_MINUTES), 15)
    st.caption(f"Current: {daily_cap} minutes ({daily_cap/60:.1f} hours)")

with col_lim2:
    sleep_cutoff = st.slider("Sleep Cutoff Hour (24h)", 18, 24, int(settings.SLEEP_CUTOFF_HOUR), 1)
    st.caption(f"No sessions after {sleep_cutoff}:00")

if st.button("💾 Update Limits"):
    settings.update_runtime(DAILY_STUDY_CAP_MINUTES=daily_cap, SLEEP_CUTOFF_HOUR=sleep_cutoff)
    st.success(f"Limits updated and persisted! Daily cap: {daily_cap} min, Sleep cutoff: {sleep_cutoff}:00")

st.divider()

st.subheader("🎙️ Voice & Audio Settings")
voice_enabled = st.toggle("Enable Voice Interface", value=settings.ENABLE_VOICE)
engine_options = ["auto", "gtts", "pyttsx3", "offline_wav"]
curr_eng_idx = engine_options.index(settings.TTS_ENGINE) if settings.TTS_ENGINE in engine_options else 0
tts_engine = st.selectbox(
    "Text-to-Speech Engine",
    engine_options,
    index=curr_eng_idx,
    help="auto = Tries pyttsx3/gTTS then offline WAV synth | gtts = Google TTS | pyttsx3 = Offline TTS"
)

if st.button("💾 Save Voice Settings"):
    settings.update_runtime(ENABLE_VOICE=voice_enabled, TTS_ENGINE=tts_engine)
    voice_service.enabled = voice_enabled
    voice_service.engine = tts_engine
    st.success(f"Voice settings saved! Enabled={voice_enabled}, Engine={tts_engine}")

st.divider()

st.subheader("🗄️ Data Management")
col_data1, col_data2 = st.columns(2)

with col_data1:
    if st.button("🗑️ Clear Session History", use_container_width=True):
        dynamodb_service.clear_user_history("user_123")
        st.success("Session history cleared for user_123!")

with col_data2:
    if st.button("📤 Export My Data", use_container_width=True):
        sessions = dynamodb_service.get_user_sessions("user_123", limit=1000)
        st.download_button(
            "Download JSON",
            data=json.dumps(sessions, indent=2, default=str),
            file_name="studybuddy_data.json",
            mime="application/json"
        )

st.divider()
st.subheader("ℹ️ System Information")
st.json({
    "version": "2.1.0",
    "environment": settings.APP_ENV,
    "storage_backend": "AWS DynamoDB" if dynamodb_service.using_dynamodb else f"Local SQLite ({settings.LOCAL_DB_PATH})",
    "voice_enabled": settings.ENABLE_VOICE,
    "tts_engine": settings.TTS_ENGINE,
    "daily_cap_minutes": settings.DAILY_STUDY_CAP_MINUTES,
    "sleep_cutoff_hour": settings.SLEEP_CUTOFF_HOUR
})
