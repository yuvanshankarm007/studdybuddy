"""
StudyBuddy Pydantic Models
Defines all data structures for the agentic system.
Supports both attribute access (model.field) and dictionary access (model['field'], model.get('field'))
for seamless compatibility across FastAPI, Streamlit, and MCP consumers.
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class DictCompatibleModel(BaseModel):
    """Base model that supports both attribute and dictionary-style access (.get, [])
    and provides both .dict() and .model_dump() without deprecation warnings."""

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            if isinstance(val, Enum):
                return val.value
            return val
        return default

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            if isinstance(val, Enum):
                return val.value
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_serializable(self) -> Dict[str, Any]:
        import json
        if hasattr(self, "model_dump_json"):
            return json.loads(self.model_dump_json())
        return json.loads(self.json())


class StudyMode(str, Enum):
    """Study modes based on energy and wellness"""
    OVERKILL = "Overkill"
    SUSTENANCE = "Sustenance"
    LOW = "Low"
    CUSTOM = "Custom"
    REST = "Rest"


class Mood(str, Enum):
    """User mood states"""
    MOTIVATED = "Motivated"
    NEUTRAL = "Neutral"
    STRESSED = "Stressed"
    EXHAUSTED = "Exhausted"
    ANXIOUS = "Anxious"
    EXCITED = "Excited"


class WellnessData(DictCompatibleModel):
    """Wellness metrics from wearable/simulated data"""
    sleep_hours: float = Field(..., ge=0, le=24, description="Hours of sleep")
    sleep_quality: Optional[int] = Field(7, ge=1, le=10, description="Sleep quality score")
    activity_level: str = Field("normal", description="Activity level: low, normal, high")
    heart_rate_avg: Optional[int] = Field(68, ge=30, le=200, description="Average resting heart rate")
    steps: Optional[int] = Field(6500, ge=0, description="Daily step count")
    stress_level: Optional[int] = Field(4, ge=1, le=10, description="Stress level")
    source: str = Field("simulated", description="Data source: fitbit, apple_health, simulated")
    timestamp: datetime = Field(default_factory=datetime.now)


class CheckInRequest(DictCompatibleModel):
    """User check-in request"""
    mood: Mood = Field(Mood.NEUTRAL, description="Current mood")
    energy: int = Field(5, ge=1, le=10, description="Energy level 1-10")
    user_id: str = Field("user_123", description="User identifier")
    voice_input: Optional[str] = Field(None, description="Raw voice transcript")
    override_safety: bool = Field(False, description="Whether user explicitly requested safety override")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    
    @validator('energy')
    def validate_energy(cls, v):
        if v < 1 or v > 10:
            raise ValueError('Energy must be between 1 and 10')
        return v


class StudyPlan(DictCompatibleModel):
    """Generated study plan"""
    mode: StudyMode = Field(..., description="Selected study mode")
    blocks: str = Field(..., description="Study block description")
    planned_minutes: int = Field(..., ge=0, le=240, description="Planned study minutes")
    break_minutes: int = Field(5, ge=0, le=60, description="Break minutes between blocks")
    num_blocks: int = Field(1, ge=1, le=10, description="Number of study blocks")
    coaching_tone: Optional[str] = Field(None, description="Empathetic coaching message")
    reasoning: Optional[str] = Field(None, description="Agent reasoning for this plan")
    safety_override: bool = Field(False, description="Whether safety agent intervened")
    audio_path: Optional[str] = Field(None, description="Optional generated TTS audio file path")
    
    @validator('planned_minutes')
    def validate_minutes(cls, v):
        if v < 0 or v > 240:
            raise ValueError('Planned minutes must be between 0 and 240')
        return v


class SessionOutcome(DictCompatibleModel):
    """Outcome of a study session"""
    session_id: str = Field(..., description="Unique session ID")
    user_id: str = Field(..., description="User ID")
    mode: StudyMode = Field(StudyMode.SUSTENANCE, description="Study mode used")
    planned_minutes: int = Field(..., ge=0, description="Planned duration")
    actual_minutes: int = Field(..., ge=0, description="Actual duration")
    completed: bool = Field(..., description="Whether session was completed")
    focus_score: Optional[int] = Field(None, ge=1, le=10, description="Self-reported focus")
    satisfaction: Optional[int] = Field(None, ge=1, le=10, description="Satisfaction score")
    energy: Optional[int] = Field(None, ge=1, le=10, description="Energy level during session")
    sleep_hours: Optional[float] = Field(None, ge=0, le=24, description="Sleep hours recorded")
    notes: Optional[str] = Field(None, description="User notes")
    timestamp: datetime = Field(default_factory=datetime.now)


class UserProfile(DictCompatibleModel):
    """User profile with learning history"""
    user_id: str = Field(..., description="Unique user ID")
    created_at: datetime = Field(default_factory=datetime.now)
    preferred_mode: Optional[StudyMode] = Field(None, description="Preferred study mode")
    avg_energy: Optional[float] = Field(None, description="Average energy level")
    avg_sleep: Optional[float] = Field(None, description="Average sleep hours")
    total_sessions: int = Field(0, description="Total completed sessions")
    total_minutes: int = Field(0, description="Total study minutes")
    completion_rate: Optional[float] = Field(None, description="Session completion rate")
    best_mode: Optional[StudyMode] = Field(None, description="Mode with highest completion")
    learning_patterns: Optional[Dict[str, Any]] = Field(None, description="Detected patterns")


class AgentDecisionTrace(DictCompatibleModel):
    """Trace of agent decisions for observability"""
    trace_id: str = Field(..., description="Unique trace ID")
    user_id: str = Field(..., description="User ID")
    timestamp: datetime = Field(default_factory=datetime.now)
    input_state: Dict[str, Any] = Field(..., description="Input state")
    wellness_data: Optional[WellnessData] = Field(None)
    planner_decision: Optional[StudyPlan] = Field(None)
    safety_decision: Optional[Dict[str, Any]] = Field(None)
    final_plan: Optional[StudyPlan] = Field(None)
    reasoning_chain: List[str] = Field(default_factory=list)
    latency_ms: Optional[float] = Field(None, description="Total latency in ms")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="Agent confidence")


class ProactiveNotification(DictCompatibleModel):
    """Proactive agent notification"""
    notification_id: str = Field(..., description="Unique notification ID")
    user_id: str = Field(..., description="User ID")
    type: str = Field(..., description="Notification type: checkin, sleep, break, encouragement")
    message: str = Field(..., description="Notification message")
    scheduled_time: datetime = Field(..., description="When to send")
    sent: bool = Field(False, description="Whether sent")
    acknowledged: bool = Field(False, description="Whether acknowledged")
    created_at: datetime = Field(default_factory=datetime.now)


class SafetyCheck(DictCompatibleModel):
    """Safety agent evaluation"""
    allowed: bool = Field(..., description="Whether plan is allowed")
    reason: Optional[str] = Field(None, description="Reason for decision")
    adjusted_plan: Optional[StudyPlan] = Field(None, description="Adjusted plan if modified")
    warnings: List[str] = Field(default_factory=list, description="Safety warnings")
    daily_minutes_used: int = Field(0, description="Current daily usage")
    daily_minutes_remaining: int = Field(240, description="Remaining daily minutes")
    sleep_cutoff_approaching: bool = Field(False, description="Sleep cutoff is near")


class VoiceCommand(DictCompatibleModel):
    """Voice command processing"""
    transcript: str = Field(..., description="Voice transcript")
    intent: Optional[str] = Field("check_in", description="Detected intent: check_in, start_session, end_session, rest, status")
    mood: Optional[Mood] = Field(None, description="Detected mood from transcript")
    energy: Optional[int] = Field(None, ge=1, le=10, description="Detected energy level 1-10")
    entities: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Extracted entities")
    confidence: Optional[float] = Field(0.9, ge=0, le=1, description="Recognition confidence")
    processed: bool = Field(True, description="Whether processed")


class SystemHealth(DictCompatibleModel):
    """System health metrics"""
    status: str = Field(..., description="System status: healthy, local_mode, degraded, down")
    mode: str = Field("online", description="Operation mode: aws_cloud, local_sqlite, hybrid")
    version: str = Field("2.1.0", description="System version")
    uptime_seconds: Optional[float] = Field(None)
    bedrock_available: bool = Field(False)
    dynamodb_available: bool = Field(False)
    local_storage_available: bool = Field(True)
    redis_available: bool = Field(False)
    wellness_agent_available: bool = Field(True)
    voice_service_available: bool = Field(True)
    avg_latency_ms: Optional[float] = Field(None)
    active_users: int = Field(1)
    total_sessions_today: int = Field(0)
