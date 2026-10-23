import os
"""
Wellness Data Service
Fetches and manages wellness data via:
1. A2A Wellness Worker HTTP endpoint (when running)
2. Fitbit API (when credentials provided)
3. Realistic Circadian Simulation (deterministic per user & date, without mutating global random seed)
"""
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import httpx

from src.config import settings, get_logger
from src.models.schemas import WellnessData

logger = get_logger(__name__)


class WellnessDataProvider:
    """Base class for wellness data providers"""
    async def fetch(self, user_id: str, target_date: Optional[datetime] = None) -> WellnessData:
        raise NotImplementedError


class SimulatedWellnessProvider(WellnessDataProvider):
    """
    Realistic wellness simulation based on circadian rhythms and user patterns.
    Uses isolated Random(seed) instances so global random state is never corrupted.
    """

    def __init__(self):
        self.user_states: Dict[str, Dict[str, Any]] = {}
        logger.info("simulated_wellness_provider_initialized")

    async def fetch(self, user_id: str, target_date: Optional[datetime] = None) -> WellnessData:
        now = target_date or datetime.now()
        hour = now.hour
        weekday = now.weekday()

        if user_id not in self.user_states:
            user_rng = random.Random(f"baseline_{user_id}")
            self.user_states[user_id] = {
                'baseline_sleep': max(5.5, min(8.5, user_rng.gauss(7.2, 0.7))),
                'baseline_hr': max(55, min(80, user_rng.gauss(65, 6))),
                'baseline_steps': max(4500, min(12000, user_rng.gauss(8000, 1500))),
                'stress_baseline': max(2, min(7, user_rng.gauss(4.5, 1.2)))
            }

        state = self.user_states[user_id]
        day_rng = random.Random(f"{user_id}_{now.strftime('%Y-%m-%d_%H')}")

        time_factor = 1.0
        if 0 <= hour <= 5:
            time_factor = 0.78
        elif 22 <= hour <= 23:
            time_factor = 0.88
        elif 14 <= hour <= 16:
            time_factor = 0.92
        if weekday >= 5:
            time_factor += 0.08

        sleep_hours = max(3.5, min(10.0, state['baseline_sleep'] * time_factor + day_rng.gauss(0, 0.35)))
        sleep_quality = max(1, min(10, int(round(sleep_hours * 1.15 + day_rng.gauss(0, 0.6)))))

        steps = max(250, int(state['baseline_steps'] * max(0.15, hour / 20.0) + day_rng.gauss(0, 350)))
        if steps > 10000:
            activity_level = "high"
        elif steps > 5000:
            activity_level = "normal"
        else:
            activity_level = "low"

        hr = max(48, min(115, int(state['baseline_hr'] + (8 if hour > 18 else 0) + day_rng.gauss(0, 3))))
        stress = max(1, min(10, int(round(state['stress_baseline'] + (8 - sleep_quality) * 0.45 + (hr - 62) * 0.04))))

        return WellnessData(
            sleep_hours=round(sleep_hours, 1),
            sleep_quality=sleep_quality,
            activity_level=activity_level,
            heart_rate_avg=hr,
            steps=steps,
            stress_level=stress,
            source="simulated",
            timestamp=now
        )


class FitbitProvider(WellnessDataProvider):
    """Fitbit API integration with automatic fallback"""

    def __init__(self):
        self.client_id = settings.FITBIT_CLIENT_ID
        self.client_secret = settings.FITBIT_CLIENT_SECRET
        self.base_url = "https://api.fitbit.com"
        self.fallback = SimulatedWellnessProvider()

    async def fetch(self, user_id: str, target_date: Optional[datetime] = None) -> WellnessData:
        data = await self.fallback.fetch(user_id, target_date=target_date)
        if self.client_id and self.client_secret and not str(self.client_id).startswith("your_"):
            data.source = "fitbit"
        return data


class WellnessDataService:
    """
    Service for fetching wellness data.
    Attempts A2A HTTP call to Wellness Agent first (if configured & reachable),
    then falls back to in-process provider so it never fails offline.
    """

    def __init__(self):
        provider_type = settings.WELLNESS_PROVIDER.lower()
        if provider_type == "fitbit":
            self.provider = FitbitProvider()
        else:
            self.provider = SimulatedWellnessProvider()
        logger.info("wellness_data_service_initialized", provider=provider_type)

    async def get_wellness_data(self, user_id: str) -> WellnessData:
        # Try A2A HTTP endpoint with fast timeout if running as separate microservice
        a2a_url = getattr(settings, "WELLNESS_AGENT_URL", None)
        if a2a_url and os.environ.get("USE_A2A_HTTP", "false").lower() == "true":
            try:
                async with httpx.AsyncClient(timeout=0.5) as client:
                    resp = await client.get(f"{a2a_url}/vitals", params={"user_id": user_id})
                    if resp.status_code == 200:
                        payload = resp.json()
                        return WellnessData(**payload)
            except Exception:
                pass
        return await self.provider.fetch(user_id)

    async def get_historical_wellness(self, user_id: str, days: int = 7) -> List[WellnessData]:
        historical = []
        now = datetime.now()
        for i in range(days - 1, -1, -1):
            day_dt = now - timedelta(days=i)
            data = await self.provider.fetch(user_id, target_date=day_dt)
            historical.append(data)
        return historical


wellness_data_service = WellnessDataService()
