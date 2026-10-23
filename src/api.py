"""
StudyBuddy REST API
FastAPI-based REST API for dashboard, voice processing, and external integrations.
Fixes:
1. /session/log now accepts `mode` (defaulting to "Sustenance") and passes it to `SessionOutcome`.
2. /health accurately reports "healthy" in both AWS Cloud and Local SQLite modes so it never falsely shows offline.
3. Added /voice/parse, /voice/checkin, and /voice/tts endpoints for full voice & audio integration.
"""
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from src.config import settings, get_logger
from src.models.schemas import (
    CheckInRequest, StudyPlan, WellnessData, Mood, StudyMode,
    SessionOutcome, SystemHealth, VoiceCommand
)
from src.agents.supervisor import supervisor_agent
from src.agents.safety import SafetyAgent
from src.services.dynamodb import dynamodb_service
from src.services.memory import memory_service
from src.services.wellness_data import wellness_data_service
from src.services.proactive import proactive_service
from src.services.voice import voice_service
from src.services.bedrock import bedrock_service
from src.services.observability import observability

logger = get_logger(__name__)

api = FastAPI(
    title="StudyBuddy API",
    description="REST API for StudyBuddy energy-aware study coach",
    version="2.1.0"
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CheckInInput(BaseModel):
    mood: str = "Neutral"
    energy: int = 5
    user_id: str = "user_123"
    voice_input: Optional[str] = None
    override_safety: bool = False


class CheckInResponse(BaseModel):
    success: bool
    trace_id: str
    plan: Dict[str, Any]
    coaching: str
    safety: Dict[str, Any]
    wellness: Dict[str, Any]
    voice_command: Optional[Dict[str, Any]] = None
    audio_path: Optional[str] = None
    latency_ms: float


class VoiceCheckInInput(BaseModel):
    transcript: str
    user_id: str = "user_123"
    override_safety: bool = False


class TTSInput(BaseModel):
    text: str


class SessionLogInput(BaseModel):
    user_id: str
    session_id: str
    mode: str = "Sustenance"
    planned_minutes: int
    actual_minutes: int
    completed: bool
    focus_score: Optional[int] = None
    satisfaction: Optional[int] = None
    energy: Optional[int] = None
    sleep_hours: Optional[float] = None
    notes: Optional[str] = None


class OverrideInput(BaseModel):
    user_id: str
    trace_id: str
    reason: str
    new_mode: Optional[str] = None


@api.get("/")
async def root():
    return {
        "name": "StudyBuddy API",
        "version": "2.1.0",
        "status": "operational",
        "endpoints": [
            "/checkin",
            "/voice/parse",
            "/voice/checkin",
            "/voice/tts",
            "/session/log",
            "/session/history",
            "/wellness",
            "/safety",
            "/profile",
            "/proactive/schedule",
            "/health"
        ]
    }


@api.post("/checkin", response_model=CheckInResponse)
async def checkin(input_data: CheckInInput):
    try:
        mood = Mood(input_data.mood)
    except ValueError:
        mood = Mood.NEUTRAL

    energy = max(1, min(10, input_data.energy))

    req = CheckInRequest(
        mood=mood,
        energy=energy,
        user_id=input_data.user_id,
        voice_input=input_data.voice_input,
        override_safety=input_data.override_safety
    )

    with observability.trace_operation("api_checkin", input_data.user_id):
        result = await supervisor_agent.orchestrate_check_in(req)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Check-in processing failed")

    return CheckInResponse(
        success=True,
        trace_id=result["trace_id"],
        plan=result["plan"].to_serializable() if hasattr(result["plan"], "to_serializable") else result["plan"],
        coaching=result["coaching"],
        safety=result["safety"].to_serializable() if hasattr(result["safety"], "to_serializable") else result["safety"],
        wellness=result["wellness"].to_serializable() if hasattr(result["wellness"], "to_serializable") else result["wellness"],
        voice_command=result.get("voice_command"),
        audio_path=result.get("audio_path"),
        latency_ms=result["latency_ms"]
    )


@api.post("/voice/parse", response_model=VoiceCommand)
async def parse_voice(input_data: VoiceCheckInInput):
    """Parse spoken voice transcript into mood, energy (1-10), and intent"""
    return voice_service.parse_voice_command(input_data.transcript)


@api.post("/voice/checkin", response_model=CheckInResponse)
async def voice_checkin(input_data: VoiceCheckInInput):
    """End-to-end voice check-in from natural language transcript"""
    cmd = voice_service.parse_voice_command(input_data.transcript)
    req = CheckInRequest(
        mood=cmd.mood or Mood.NEUTRAL,
        energy=cmd.energy or 5,
        user_id=input_data.user_id,
        voice_input=input_data.transcript,
        override_safety=input_data.override_safety
    )
    result = await supervisor_agent.orchestrate_check_in(req)
    return CheckInResponse(
        success=True,
        trace_id=result["trace_id"],
        plan=result["plan"].to_serializable(),
        coaching=result["coaching"],
        safety=result["safety"].to_serializable(),
        wellness=result["wellness"].to_serializable(),
        voice_command=cmd.to_serializable(),
        audio_path=result.get("audio_path"),
        latency_ms=result["latency_ms"]
    )


@api.post("/voice/tts")
async def synthesize_tts(input_data: TTSInput):
    """Synthesize coaching text to an audio file (.wav or .mp3)"""
    path = await voice_service.text_to_speech(input_data.text)
    if not path:
        raise HTTPException(status_code=500, detail="TTS synthesis disabled or failed")
    return {"success": True, "audio_path": path}


@api.post("/session/log")
async def log_session(input_data: SessionLogInput):
    try:
        mode_enum = StudyMode(input_data.mode)
    except ValueError:
        mode_enum = StudyMode.SUSTENANCE

    outcome = SessionOutcome(
        session_id=input_data.session_id,
        user_id=input_data.user_id,
        mode=mode_enum,
        planned_minutes=input_data.planned_minutes,
        actual_minutes=input_data.actual_minutes,
        completed=input_data.completed,
        focus_score=input_data.focus_score,
        satisfaction=input_data.satisfaction,
        energy=input_data.energy,
        sleep_hours=input_data.sleep_hours,
        notes=input_data.notes
    )

    success = dynamodb_service.log_session(outcome)
    profile = await memory_service.update_profile_from_session(outcome)

    return {
        "success": success,
        "profile": profile.to_serializable() if profile else None
    }


@api.get("/session/history")
async def get_session_history(
    user_id: str = "user_123",
    limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    sessions = dynamodb_service.get_user_sessions(user_id, limit, start_date, end_date)
    return {
        "user_id": user_id,
        "count": len(sessions),
        "sessions": sessions
    }


@api.get("/wellness")
async def get_wellness(user_id: str = "user_123"):
    wellness = await wellness_data_service.get_wellness_data(user_id)
    return wellness.to_serializable()


@api.get("/safety")
async def get_safety(user_id: str = "user_123"):
    safety_agent = SafetyAgent()
    return safety_agent.get_safety_summary(user_id)


@api.get("/profile")
async def get_profile(user_id: str = "user_123"):
    profile = await memory_service.get_or_create_profile(user_id)
    streak = memory_service.get_streak(user_id)
    return {
        "profile": profile.to_serializable() if profile else None,
        "streak": streak
    }


@api.get("/profile/patterns")
async def get_patterns(user_id: str = "user_123"):
    return await memory_service.analyze_patterns(user_id)


@api.post("/proactive/schedule")
async def schedule_proactive(user_id: str = "user_123"):
    await proactive_service.run_daily_schedule(user_id)
    notifications = dynamodb_service.get_pending_notifications(user_id)
    return {
        "success": True,
        "notifications_created": len(notifications),
        "pending": notifications
    }


@api.get("/traces")
async def get_traces(user_id: str = "user_123", limit: int = 20):
    traces = dynamodb_service.get_recent_traces(user_id, limit)
    return {
        "user_id": user_id,
        "count": len(traces),
        "traces": traces
    }


@api.post("/override")
async def override_plan(input_data: OverrideInput):
    logger.info(
        "user_override",
        user_id=input_data.user_id,
        trace_id=input_data.trace_id,
        reason=input_data.reason
    )
    observability.record_user_engagement(input_data.user_id, "override")
    return {
        "success": True,
        "message": "Override logged. Your feedback helps StudyBuddy learn.",
        "trace_id": input_data.trace_id,
        "new_mode": input_data.new_mode or "Custom"
    }


@api.get("/health", response_model=SystemHealth)
async def health_check():
    """System health check - reports healthy in both AWS Cloud and Local SQLite modes"""
    storage_ok = dynamodb_service.is_healthy()
    bedrock_ok = bedrock_service.is_available()
    mode = "aws_cloud" if dynamodb_service.using_dynamodb else "local_sqlite"

    return SystemHealth(
        status="healthy" if (storage_ok and bedrock_ok) else "degraded",
        mode=mode,
        bedrock_available=bedrock_ok,
        dynamodb_available=dynamodb_service.using_dynamodb,
        local_storage_available=storage_ok,
        redis_available=False,
        wellness_agent_available=True,
        voice_service_available=settings.ENABLE_VOICE,
        active_users=1,
        total_sessions_today=dynamodb_service.get_daily_usage("user_123")
    )


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting StudyBuddy API on http://0.0.0.0:8002")
    uvicorn.run(api, host="0.0.0.0", port=8002)
