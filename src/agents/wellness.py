"""
Wellness Worker Agent (A2A)
FastAPI service that provides wellness data to the Supervisor Agent
Implements the A2A protocol for agent-to-agent communication.
Fixes: Binds to 0.0.0.0 so Docker containers can communicate with it.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from src.services.wellness_data import wellness_data_service
from src.config import get_logger

logger = get_logger(__name__)

wellness_app = FastAPI(title="StudyBuddy Wellness Agent", version="2.1.0")


class AgentCard(BaseModel):
    name: str
    description: str
    version: str
    capabilities: list[str]
    endpoints: dict[str, str]
    protocols: list[str]


class VitalsResponse(BaseModel):
    sleep_hours: float
    sleep_quality: Optional[int]
    activity_level: str
    heart_rate_avg: Optional[int]
    steps: Optional[int]
    stress_level: Optional[int]
    source: str
    timestamp: str
    user_id: str


@wellness_app.get("/agent.json", response_model=AgentCard)
async def get_agent_card():
    return AgentCard(
        name="StudyBuddyWellness",
        description="Provides sleep, activity, and stress data for adaptive study planning",
        version="2.1.0",
        capabilities=["get_vitals", "get_historical", "analyze_trends"],
        endpoints={
            "vitals": "/vitals",
            "history": "/history",
            "health": "/health"
        },
        protocols=["a2a/1.0", "http/rest"]
    )


@wellness_app.get("/vitals", response_model=VitalsResponse)
async def get_vitals(user_id: str = "user_123"):
    try:
        wellness = await wellness_data_service.get_wellness_data(user_id)
        return VitalsResponse(
            sleep_hours=wellness.sleep_hours,
            sleep_quality=wellness.sleep_quality,
            activity_level=wellness.activity_level,
            heart_rate_avg=wellness.heart_rate_avg,
            steps=wellness.steps,
            stress_level=wellness.stress_level,
            source=wellness.source,
            timestamp=wellness.timestamp.isoformat(),
            user_id=user_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch vitals: {str(e)}")


@wellness_app.get("/history")
async def get_history(user_id: str = "user_123", days: int = 7):
    try:
        history = await wellness_data_service.get_historical_wellness(user_id, days)
        return [
            {
                "sleep_hours": h.sleep_hours,
                "sleep_quality": h.sleep_quality,
                "activity_level": h.activity_level,
                "stress_level": h.stress_level,
                "timestamp": h.timestamp.isoformat()
            }
            for h in history
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")


@wellness_app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "wellness-agent",
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Wellness Agent on http://0.0.0.0:8001")
    uvicorn.run(wellness_app, host="0.0.0.0", port=8001)
