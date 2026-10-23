"""
StudyBuddy Session Page
Main interaction page for voice check-in, audio feedback, human-in-the-loop override, and study sessions.
Fixes:
1. Uses `st.components.v1.html` instead of `st.markdown` so browser Web Speech API `<script>` actually executes!
2. Adds natural language voice command input & WAV audio upload with automatic NLU extraction of Mood and Energy.
3. Plays back generated TTS coaching audio via `st.audio` and browser SpeechSynthesis.
4. Implements the Human-in-the-Loop Override UI in `col_override`.
5. Passes `mode` to `SessionOutcome` on session completion/cancellation so logging never crashes.
"""
import streamlit as st
import streamlit.components.v1 as components
import asyncio
import concurrent.futures
import time
import uuid
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.models.schemas import CheckInRequest, Mood, StudyMode, SessionOutcome
from src.agents.supervisor import supervisor_agent
from src.agents.safety import SafetyAgent
from src.services.dynamodb import dynamodb_service
from src.services.memory import memory_service
from src.services.voice import voice_service
from src.services.observability import observability

st.set_page_config(page_title="Study Session | StudyBuddy", layout="wide")

st.title("🎙️ Study Session")
st.markdown("Start an energy-aware study session with **Voice Check-in**, NLU parsing, and audio coaching.")


def run_async(coro):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


if 'session_active' not in st.session_state:
    st.session_state.session_active = False
if 'current_plan' not in st.session_state:
    st.session_state.current_plan = None
if 'session_start' not in st.session_state:
    st.session_state.session_start = None
if 'session_id' not in st.session_state:
    st.session_state.session_id = None
if 'voice_transcript' not in st.session_state:
    st.session_state.voice_transcript = ""


# ========== Voice & Audio Input Section ==========
st.subheader("🗣️ Voice Check-in (Web Speech API + NLU Parser)")

# Render working browser Web Speech API widget via components.html (executes JS properly!)
auto_speak = None
if st.session_state.current_plan:
    auto_speak = st.session_state.current_plan.get("coaching")
voice_html = voice_service.get_voice_html("voice-transcript", auto_speak_text=auto_speak)
components.html(voice_html, height=105)

# Spoken transcript input / NLU parser
voice_col1, voice_col2 = st.columns([2, 1])
with voice_col1:
    spoken_text = st.text_input(
        "🗣️ Spoken Transcript (or type what you would say to Jarvis)",
        value=st.session_state.voice_transcript,
        placeholder="e.g., 'Jarvis, I am exhausted today and my energy is 2 out of 10' or 'Feeling super motivated, energy 9!'"
    )
with voice_col2:
    preset = st.selectbox(
        "⚡ Quick Voice Presets",
        [
            "(Select a voice preset to test NLU)",
            "I'm exhausted and barely slept, energy is 2 out of 10",
            "Feeling super motivated and ready to crush it, energy 9!",
            "A bit stressed about exams, energy around 4",
            "Feeling neutral and steady today, energy 6"
        ]
    )
    if preset != "(Select a voice preset to test NLU)":
        spoken_text = preset

# Optional audio file / mic recording upload if available
uploaded_audio = st.file_uploader("🎧 Or upload a recorded voice clip (.wav) for offline STT", type=["wav"])
if uploaded_audio is not None:
    stt_text, stt_conf = run_async(voice_service.speech_to_text(uploaded_audio.read(), uploaded_audio.name))
    if stt_text:
        spoken_text = stt_text
        st.info(f"🎙️ STT Transcribed ({stt_conf*100:.0f}% confidence): "{stt_text}"")

parsed_voice = None
if spoken_text and spoken_text.strip():
    parsed_voice = voice_service.parse_voice_command(spoken_text)
    st.success(
        f"🧠 **Voice NLU Parsed** → Intent: `{parsed_voice.intent}` | "
        f"Mood: **{parsed_voice.mood.value}** | Energy: **{parsed_voice.energy}/10** "
        f"(Confidence: {parsed_voice.confidence*100:.0f}%)"
    )

col1, col2 = st.columns([1, 1])

mood_options = [m.value for m in Mood]
default_mood_idx = mood_options.index(parsed_voice.mood.value) if (parsed_voice and parsed_voice.mood) else 1
default_energy = parsed_voice.energy if (parsed_voice and parsed_voice.energy) else 5

with col1:
    mood = st.selectbox("How are you feeling?", mood_options, index=default_mood_idx)
    energy = st.slider("Energy Level", 1, 10, default_energy, help="1 = Exhausted, 10 = Energized")
    energy_color = "🟢" if energy >= 7 else "🟡" if energy >= 4 else "🔴"
    st.caption(f"{energy_color} Energy: {energy}/10")

with col2:
    st.markdown("#### 📊 Quick Stats & Guardrails")
    safety = SafetyAgent()
    status = safety.get_safety_summary("user_123")

    st.metric("Daily Used", f"{status['daily_used']}/{status['daily_cap']} min")
    st.progress(min(1.0, status['daily_percent'] / 100.0))

    if status['can_study']:
        st.caption(f"✅ {status['daily_remaining']} minutes remaining today")
    else:
        st.warning(f"⚠️ Guardrail active: {status.get('block_reason', 'Limit reached')}")

    override_safety = st.checkbox(
        "🔓 Human-in-the-Loop Override (Allow 15-min review past sleep cutoff)",
        value=False
    )

st.divider()

col_checkin, col_override = st.columns([2, 1])

with col_checkin:
    if st.button("🎙️ Start Voice Check-in", use_container_width=True, type="primary"):
        if not status.get('can_study', True) and not override_safety:
            st.error(f"🚫 Cannot start session: {status.get('block_reason')}. Enable Human-in-the-Loop Override above for a 15-min review.")
        else:
            with st.spinner("🧠 StudyBuddy multi-agent pipeline is analyzing your state..."):
                try:
                    req = CheckInRequest(
                        mood=Mood(mood),
                        energy=energy,
                        user_id="user_123",
                        voice_input=spoken_text if spoken_text else None,
                        override_safety=override_safety
                    )
                    start = time.time()
                    result = run_async(supervisor_agent.orchestrate_check_in(req))
                    latency = (time.time() - start) * 1000

                    st.session_state.current_plan = result
                    st.session_state.session_id = str(uuid.uuid4())
                    st.success(f"✅ Check-in complete! ({latency:.0f}ms)")
                except Exception as e:
                    st.error(f"❌ Check-in failed: {e}")

with col_override:
    with st.expander("🛠️ Manual Mode Override"):
        custom_mode = st.selectbox("Force Mode", [m.value for m in StudyMode])
        override_reason = st.text_input("Reason", value="I know my current energy best")
        if st.button("Apply Override", use_container_width=True):
            observability.record_user_engagement("user_123", "override")
            if st.session_state.current_plan:
                plan_obj = st.session_state.current_plan["plan"]
                plan_obj.mode = StudyMode(custom_mode)
                plan_obj.safety_override = True
                plan_obj.reasoning = f"User manual override ({override_reason})"
                st.success(f"Overridden to {custom_mode} mode!")
            else:
                st.info("Run a check-in first, then override if needed.")


# ========== Results Display ==========
if st.session_state.current_plan:
    result = st.session_state.current_plan
    plan = result.get('plan', {})
    safety_res = result.get('safety', {})
    wellness = result.get('wellness', {})
    coaching = result.get('coaching', '')
    audio_path = result.get('audio_path')

    st.divider()
    st.subheader("📋 Your Personalized Study Plan")

    col_plan, col_wellness = st.columns([2, 1])

    with col_plan:
        mode = plan.get('mode', 'Unknown')
        if hasattr(mode, 'value'):
            mode = mode.value
        mode_colors = {
            'Overkill': '#2ed573',
            'Sustenance': '#74b9ff',
            'Low': '#ffa502',
            'Custom': '#ff6348',
            'Rest': '#a29bfe'
        }
        mode_color = mode_colors.get(mode, '#74b9ff')

        st.markdown(f"""
        <div style="
            background: {mode_color}20;
            border: 2px solid {mode_color};
            border-radius: 15px;
            padding: 20px;
            margin: 10px 0;
        ">
            <h3 style="color: {mode_color}; margin: 0;">⚡ {mode} Mode</h3>
            <p style="font-size: 1.2em; margin: 10px 0;">{plan.get('blocks', '')}</p>
            <p style="color: #cbd5e1;">📅 {plan.get('planned_minutes', 0)} minutes planned ({plan.get('num_blocks', 1)} block(s), {plan.get('break_minutes', 5)}m break)</p>
        </div>
        """, unsafe_allow_html=True)

        if coaching:
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, #667eea20, #764ba220);
                border-radius: 10px;
                padding: 15px;
                margin: 10px 0;
                border-left: 4px solid #667eea;
            ">
                <p style="font-style: italic; margin: 0;">💬 "{coaching}"</p>
            </div>
            """, unsafe_allow_html=True)

        if audio_path and os.path.exists(audio_path):
            st.caption("🔊 Audio Coaching Response:")
            st.audio(audio_path)

        reasoning = plan.get('reasoning', '')
        if reasoning:
            with st.expander("🧠 Why this plan?"):
                st.write(reasoning)

    with col_wellness:
        st.markdown("#### 🏥 Wellness Data (A2A)")
        st.metric("💤 Sleep", f"{wellness.get('sleep_hours', 0)}h")
        st.metric("📊 Sleep Quality", f"{wellness.get('sleep_quality', 'N/A')}/10")
        st.metric("🏃 Activity", str(wellness.get('activity_level', 'N/A')).title())
        if wellness.get('stress_level'):
            st.metric("😰 Stress", f"{wellness.get('stress_level')}/10")

    if safety_res:
        st.divider()
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            st.metric("⏱️ Daily Used", f"{safety_res.get('daily_minutes_used', 0)} min")
        with col_s2:
            st.metric("✅ Remaining", f"{safety_res.get('daily_minutes_remaining', 0)} min")
        with col_s3:
            warnings = safety_res.get('warnings', [])
            if warnings:
                st.warning(f"⚠️ {len(warnings)} warning(s)")
            else:
                st.success("✅ All safety checks passed")
        if warnings:
            with st.expander("⚠️ Safety Warnings"):
                for w in warnings:
                    st.warning(w)

    reasoning_chain = result.get('reasoning_chain', [])
    if reasoning_chain:
        with st.expander("🔍 Multi-Agent Decision Trace"):
            for step in reasoning_chain:
                st.code(step, language="text")

    # Session Controls
    st.divider()
    st.subheader("⏯️ Session Controls")

    col_start, col_cancel = st.columns(2)
    with col_start:
        if not st.session_state.session_active:
            if st.button("▶️ Start Session", use_container_width=True):
                st.session_state.session_active = True
                st.session_state.session_start = datetime.now()
                st.success("🚀 Session started! Focus up!")
                st.rerun()
        else:
            elapsed = max(1.0, (datetime.now() - st.session_state.session_start).total_seconds() / 60.0)
            st.metric("⏱️ Session Time", f"{elapsed:.1f} min")
            focus_rating = st.slider("Focus Score (1-10)", 1, 10, 8, key="focus_slider")

            if st.button("⏹️ Complete & Log Session", use_container_width=True):
                planned = int(plan.get('planned_minutes', 25))
                actual = max(1, int(round(elapsed)))
                mode_str = plan.get('mode', 'Sustenance')
                if hasattr(mode_str, 'value'):
                    mode_str = mode_str.value

                outcome = SessionOutcome(
                    session_id=st.session_state.session_id or str(uuid.uuid4()),
                    user_id="user_123",
                    mode=StudyMode(mode_str) if mode_str in [m.value for m in StudyMode] else StudyMode.SUSTENANCE,
                    planned_minutes=planned,
                    actual_minutes=actual,
                    completed=True,
                    focus_score=focus_rating,
                    energy=energy,
                    sleep_hours=float(wellness.get('sleep_hours', 7.0))
                )
                dynamodb_service.log_session(outcome)
                run_async(memory_service.update_profile_from_session(outcome))

                st.session_state.session_active = False
                st.session_state.current_plan = None
                st.session_state.session_start = None
                st.success("✅ Session logged and profile updated!")
                st.rerun()

    with col_cancel:
        if st.button("🛑 Cancel / Rest Mode", use_container_width=True):
            if st.session_state.session_active:
                elapsed = max(0, int((datetime.now() - st.session_state.session_start).total_seconds() / 60))
                mode_str = plan.get('mode', 'Rest')
                if hasattr(mode_str, 'value'):
                    mode_str = mode_str.value
                outcome = SessionOutcome(
                    session_id=st.session_state.session_id or str(uuid.uuid4()),
                    user_id="user_123",
                    mode=StudyMode(mode_str) if mode_str in [m.value for m in StudyMode] else StudyMode.REST,
                    planned_minutes=int(plan.get('planned_minutes', 0)),
                    actual_minutes=elapsed,
                    completed=False,
                    notes="User cancelled - switched to rest mode"
                )
                dynamodb_service.log_session(outcome)

            st.session_state.session_active = False
            st.session_state.current_plan = None
            st.session_state.session_start = None
            st.info("🛑 Session cancelled. Rest is productive too!")
            st.rerun()

# ========== Proactive Notifications ==========
st.divider()
st.subheader("📬 Proactive Coaching Notifications")

try:
    notifications = dynamodb_service.get_pending_notifications("user_123")
    if notifications:
        for n in notifications[:3]:
            col_n1, col_n2 = st.columns([4, 1])
            with col_n1:
                st.info(f"📢 {n.get('message', '')}")
            with col_n2:
                nid = n.get('notification_id', '')
                if st.button("✓ Acknowledge", key=f"ack_{nid}"):
                    dynamodb_service.acknowledge_notification("user_123", nid)
                    st.success("Acknowledged!")
                    st.rerun()
    else:
        if st.button("🔄 Generate Daily Coaching Reminders"):
            from src.services.proactive import proactive_service
            run_async(proactive_service.run_daily_schedule("user_123"))
            st.rerun()
        else:
            st.caption("No pending notifications.")
except Exception as e:
    st.caption(f"Notifications ready ({e})")
