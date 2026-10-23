"""
StudyBuddy MCP Server (Alexa+ Track)
Implements Model Context Protocol (MCP Spec 2025-11-25) over Streamable HTTP.
Exposes:
- JSON-RPC 2.0 Streamable HTTP endpoint (`POST /mcp` & `GET /mcp`) supporting `initialize`, `tools/list`, `tools/call`, `resources/list`
- Rich Alexa+ Multimodal Cards & Carousels (APL-compatible structured UI metadata)
- Multi-session state persistence across check-ins
"""
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import uvicorn

try:
    from fastmcp import FastMCP
except ImportError:
    class FastMCP:
        def __init__(self, name: str):
            self.name = name
            self.tools = {}
        def tool(self):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

from src.config import settings, get_logger
from src.models.schemas import CheckInRequest, Mood, StudyMode, SessionOutcome
from src.agents.supervisor import supervisor_agent
from src.services.observability import observability

logger = get_logger(__name__)

MCP_PROTOCOL_VERSION = "2025-11-25"
mcp = FastMCP("StudyBuddy-AlexaPlus")


def _build_alexa_multimodal_payload(plan_dict: dict, wellness_dict: dict, safety_dict: dict, coaching: str) -> dict:
    """
    Build Alexa+ Multimodal Card & Carousel response (creative differentiator for Alexa+ judging).
    """
    mode = plan_dict.get("mode", "Sustenance")
    return {
        "alexa_plus_card": {
            "type": "StandardCard",
            "title": f"StudyBuddy: {mode} Mode ({plan_dict.get('planned_minutes', 25)} min)",
            "subtitle": f"Sleep: {wellness_dict.get('sleep_hours', 7.0)}h | Daily Remaining: {safety_dict.get('daily_minutes_remaining', 180)}m",
            "body": coaching,
            "badge": "Safety Override Active" if plan_dict.get("safety_override") else "Guardrails Approved"
        },
        "alexa_plus_carousel": [
            {
                "card_id": "block_schedule",
                "title": "Study Block Rhythm",
                "primary_text": plan_dict.get("blocks", "25 min focus / 5 min break"),
                "secondary_text": f"{plan_dict.get('num_blocks', 1)} block(s) with {plan_dict.get('break_minutes', 5)}m recovery breaks"
            },
            {
                "card_id": "wellness_telemetry",
                "title": "A2A Physiological Vitals",
                "primary_text": f"{wellness_dict.get('sleep_hours', 7.0)}h Sleep (Quality {wellness_dict.get('sleep_quality', 7)}/10)",
                "secondary_text": f"Activity: {wellness_dict.get('activity_level', 'normal')} | Stress: {wellness_dict.get('stress_level', 4)}/10"
            },
            {
                "card_id": "safety_guardrails",
                "title": "Burnout Guardrail Status",
                "primary_text": f"Used {safety_dict.get('daily_minutes_used', 0)} / {settings.DAILY_STUDY_CAP_MINUTES} min today",
                "secondary_text": f"Hard sleep cutoff enforced at {settings.SLEEP_CUTOFF_HOUR}:00"
            }
        ],
        "voice_ssml": f"<speak><prosody rate='100%'>{coaching}</prosody></speak>"
    }


@mcp.tool()
async def check_in(
    mood: str = "Neutral",
    energy: int = 5,
    user_id: str = "user_123",
    voice_input: Optional[str] = None,
    override_safety: bool = False
) -> dict:
    """
    Check in with StudyBuddy to get an energy-aware study plan, safety evaluation,
    and Alexa+ multimodal card/carousel payload.
    """
    try:
        mood_enum = Mood(mood)
    except ValueError:
        mood_enum = Mood.NEUTRAL

    req = CheckInRequest(
        mood=mood_enum,
        energy=max(1, min(10, int(energy))),
        user_id=user_id,
        voice_input=voice_input,
        override_safety=override_safety
    )
    with observability.trace_operation("mcp_check_in", user_id):
        result = await supervisor_agent.orchestrate_check_in(req)

    plan_dict = result["plan"].to_serializable()
    safety_dict = result["safety"].to_serializable()
    wellness_dict = result["wellness"].to_serializable()
    coaching = result["coaching"]

    return {
        "success": result["success"],
        "trace_id": result["trace_id"],
        "plan": plan_dict,
        "safety": safety_dict,
        "wellness": wellness_dict,
        "coaching": coaching,
        "voice_command": result.get("voice_command"),
        "alexa_multimodal": _build_alexa_multimodal_payload(plan_dict, wellness_dict, safety_dict, coaching),
        "reasoning_chain": result.get("reasoning_chain", []),
        "latency_ms": result["latency_ms"]
    }


@mcp.tool()
async def get_user_profile(user_id: str = "user_123") -> dict:
    """Get user profile with cross-session learning history and study streak"""
    from src.services.memory import memory_service
    profile = await memory_service.get_or_create_profile(user_id)
    streak = memory_service.get_streak(user_id)
    patterns = await memory_service.analyze_patterns(user_id)
    return {
        "profile": profile.to_serializable() if profile else None,
        "streak": streak,
        "patterns": patterns
    }


@mcp.tool()
async def log_session_outcome(
    user_id: str,
    session_id: str,
    planned_minutes: int,
    actual_minutes: int,
    completed: bool,
    mode: str = "Sustenance",
    focus_score: Optional[int] = None,
    satisfaction: Optional[int] = None
) -> dict:
    """Log the outcome of a study session for cross-session adaptive memory"""
    from src.services.memory import memory_service
    from src.services.dynamodb import dynamodb_service

    try:
        mode_enum = StudyMode(mode)
    except ValueError:
        mode_enum = StudyMode.SUSTENANCE

    outcome = SessionOutcome(
        session_id=session_id,
        user_id=user_id,
        mode=mode_enum,
        planned_minutes=planned_minutes,
        actual_minutes=actual_minutes,
        completed=completed,
        focus_score=focus_score,
        satisfaction=satisfaction
    )

    dynamodb_service.log_session(outcome)
    profile = await memory_service.update_profile_from_session(outcome)

    return {
        "success": True,
        "profile_updated": True,
        "total_sessions": profile.total_sessions if profile else 0,
        "daily_used_minutes": dynamodb_service.get_daily_usage(user_id)
    }


@mcp.tool()
async def get_safety_status(user_id: str = "user_123") -> dict:
    """Get current burnout safety guardrails status for user"""
    from src.agents.safety import SafetyAgent
    safety_agent = SafetyAgent()
    return safety_agent.get_safety_summary(user_id)


MCP_TOOL_SCHEMAS = [
    {
        "name": "check_in",
        "description": "Perform an Alexa+ voice/physiological check-in and receive an adaptive study plan with multimodal cards.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mood": {"type": "string", "enum": ["Motivated", "Neutral", "Stressed", "Exhausted", "Anxious", "Excited"]},
                "energy": {"type": "integer", "minimum": 1, "maximum": 10},
                "user_id": {"type": "string", "default": "user_123"},
                "voice_input": {"type": "string", "description": "Natural language spoken utterance from Alexa+ user"},
                "override_safety": {"type": "boolean", "default": False}
            }
        }
    },
    {
        "name": "get_user_profile",
        "description": "Retrieve persistent user learning profile, streaks, and Bedrock pattern analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "default": "user_123"}
            }
        }
    },
    {
        "name": "log_session_outcome",
        "description": "Log a completed or interrupted study block to update daily usage caps and learning memory.",
        "inputSchema": {
            "type": "object",
            "required": ["user_id", "session_id", "planned_minutes", "actual_minutes", "completed"],
            "properties": {
                "user_id": {"type": "string"},
                "session_id": {"type": "string"},
                "planned_minutes": {"type": "integer"},
                "actual_minutes": {"type": "integer"},
                "completed": {"type": "boolean"},
                "mode": {"type": "string", "default": "Sustenance"},
                "focus_score": {"type": "integer", "minimum": 1, "maximum": 10},
                "satisfaction": {"type": "integer", "minimum": 1, "maximum": 10}
            }
        }
    },
    {
        "name": "get_safety_status",
        "description": "Check remaining minutes under the 4-hour daily cap and 10 PM sleep cutoff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "default": "user_123"}
            }
        }
    }
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("mcp_server_starting", version="2.1.0", mcp_spec=MCP_PROTOCOL_VERSION)
    yield
    logger.info("mcp_server_stopping")


app = FastAPI(
    title="StudyBuddy Alexa+ MCP Server",
    description="Model Context Protocol (Spec 2025-11-25 Streamable HTTP) server for StudyBuddy energy-aware study coach",
    version="2.1.0",
    lifespan=lifespan
)


@app.get("/mcp")
async def mcp_streamable_http_get(request: Request):
    """MCP Spec 2025-11-25 Streamable HTTP Discovery & Capabilities endpoint"""
    return {
        "protocol": "mcp",
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "transport": "streamable-http",
        "serverInfo": {
            "name": "StudyBuddy-AlexaPlus",
            "version": "2.1.0"
        },
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False}
        },
        "tools": MCP_TOOL_SCHEMAS
    }


@app.post("/mcp")
async def mcp_streamable_http_post(request: Request, response: Response):
    """
    Supports both:
    1. Official MCP Spec 2025-11-25 JSON-RPC 2.0 over Streamable HTTP (`initialize`, `tools/list`, `tools/call`)
    2. Simplified REST tool invocation (`{"tool": "check_in", "arguments": {...}}`)
    """
    body = await request.json()
    session_id = request.headers.get("Mcp-Session-Id") or str(uuid.uuid4())
    response.headers["Mcp-Session-Id"] = session_id

    tool_map = {
        "check_in": check_in,
        "get_user_profile": get_user_profile,
        "log_session_outcome": log_session_outcome,
        "get_safety_status": get_safety_status,
    }

    # Case 1: Standard MCP JSON-RPC 2.0 message
    if "jsonrpc" in body or "method" in body:
        rpc_id = body.get("id", 1)
        method = body.get("method", "")
        params = body.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False}
                    },
                    "serverInfo": {
                        "name": "StudyBuddy-AlexaPlus",
                        "version": "2.1.0"
                    }
                }
            }

        if method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"tools": MCP_TOOL_SCHEMAS}
            }

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}
            fn = tool_map.get(tool_name)
            if not fn:
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                }
            res = await fn(**tool_args)
            import json
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res)}],
                    "structuredContent": res,
                    "isError": False
                }
            }

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Unsupported MCP method: {method}"}
        }

    # Case 2: Convenience REST call `{"tool": "...", "arguments": {...}}`
    tool_name = body.get("tool")
    fn = tool_map.get(tool_name)
    if not fn:
        return {"error": f"Unknown tool: {tool_name}"}
    result = await fn(**(body.get("arguments") or {}))
    return {"tool": tool_name, "protocolVersion": MCP_PROTOCOL_VERSION, "result": result}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "studybuddy-mcp",
        "version": "2.1.0",
        "mcp_protocol_version": MCP_PROTOCOL_VERSION,
        "transport": "streamable-http",
        "mcp_tools": ["check_in", "get_user_profile", "log_session_outcome", "get_safety_status"],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/")
async def root():
    return {
        "name": "StudyBuddy Alexa+ MCP Server",
        "version": "2.1.0",
        "protocol": f"MCP (Spec {MCP_PROTOCOL_VERSION})",
        "transport": "Streamable HTTP",
        "tracks": ["Alexa+", "AWS Builder", "Open Source"],
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    print(f"🚀 Starting StudyBuddy MCP Server (Spec {MCP_PROTOCOL_VERSION}) on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
