"""
AWS Bedrock Service with Context-Aware Local Fallback Engine
Handles LLM interactions with Claude 3 Haiku when AWS credentials are configured,
and provides instant, context-aware local coaching, pattern analysis, and safety reasoning
when running offline or without AWS credentials.
"""
import json
import asyncio
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.config import settings, get_logger
from src.models.schemas import StudyMode, Mood, StudyPlan, WellnessData

logger = get_logger(__name__)

_bedrock_client = None


def _has_real_aws_credentials() -> bool:
    """Check if real AWS credentials exist to avoid slow boto3 retry timeouts in local dev"""
    ak = settings.AWS_ACCESS_KEY_ID or os.environ.get("AWS_ACCESS_KEY_ID", "")
    sk = settings.AWS_SECRET_ACCESS_KEY or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    if ak and sk and not ak.startswith("your_") and not ak.startswith("fake"):
        return True
    aws_creds_file = os.path.expanduser("~/.aws/credentials")
    return os.path.exists(aws_creds_file)


import os


def get_bedrock_client():
    """Get or create Bedrock client if boto3 and credentials are available"""
    global _bedrock_client
    if _bedrock_client is None and _has_real_aws_credentials():
        try:
            import boto3
            from botocore.config import Config
            config = Config(
                connect_timeout=2,
                read_timeout=6,
                retries={'max_attempts': 2, 'mode': 'adaptive'},
                max_pool_connections=25
            )
            _bedrock_client = boto3.client(
                'bedrock-runtime',
                region_name=settings.BEDROCK_REGION,
                config=config
            )
            logger.info("bedrock_client_initialized", region=settings.BEDROCK_REGION)
        except Exception as e:
            logger.info("bedrock_client_unavailable_using_local_engine", reason=str(e))
            _bedrock_client = None
    return _bedrock_client


class BedrockService:
    """Service for AWS Bedrock LLM operations with zero-latency local coaching fallback"""

    def __init__(self):
        self.client = get_bedrock_client()
        self.model_id = settings.BEDROCK_MODEL_ID
        self._cache: Dict[str, Any] = {}
        logger.info(
            "bedrock_service_initialized",
            model=self.model_id,
            cloud_enabled=self.client is not None
        )

    def is_available(self) -> bool:
        """Always operational: uses AWS Bedrock when configured, or built-in local coaching engine"""
        return True

    def _get_cache_key(self, prompt: str) -> str:
        return hashlib.md5(prompt.encode()).hexdigest()

    async def invoke_model(
        self,
        prompt: str,
        max_tokens: int = 150,
        temperature: float = 0.7,
        use_cache: bool = True
    ) -> str:
        if use_cache:
            cache_key = self._get_cache_key(prompt)
            if cache_key in self._cache:
                return self._cache[cache_key]

        if self.client is not None:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]
            })
            try:
                response = await asyncio.to_thread(
                    self.client.invoke_model,
                    body=body,
                    modelId=self.model_id,
                    contentType="application/json",
                    accept="application/json"
                )
                response_body = json.loads(response.get('body').read())
                text = response_body['content'][0]['text'].strip()
                if use_cache:
                    self._cache[cache_key] = text
                return text
            except Exception as e:
                logger.warning("bedrock_cloud_fallback_triggered", reason=str(e))

        # Local deterministic synthesis fallback
        text = self._local_Fallback_response(prompt)
        if use_cache:
            self._cache[cache_key] = text
        return text

    def _local_Fallback_response(self, prompt: str) -> str:
        lower = prompt.lower()
        if "checkin_reminder" in lower:
            return "Hey there! You still have study time available today—let's do a quick voice check-in and pick a pace that fits your energy."
        if "sleep_reminder" in lower:
            return "Your sleep cutoff is coming up soon. Wrap up your current notes so your brain can consolidate everything overnight!"
        if "encouragement" in lower:
            return "You're building an awesome study streak! Consistency beats intensity every single time."
        return "Let's match your study rhythm to your energy today—one focused block at a time."

    async def generate_coaching_tone(
        self,
        mode: StudyMode,
        mood: Mood,
        wellness: WellnessData,
        user_context: Optional[Dict[str, Any]] = None
    ) -> str:
        if self.client is not None:
            prompt = (
                f"You are StudyBuddy, an empathetic AI study coach. The user is feeling {mood.value} "
                f"and slept {wellness.sleep_hours} hours. Recommended mode: {mode.value}. "
                f"Respond with a warm, encouraging 1-2 sentence voice-friendly coaching message."
            )
            try:
                return await self.invoke_model(prompt, max_tokens=80, temperature=0.8)
            except Exception:
                pass

        # Rich context-aware coaching synthesis
        sleep = wellness.sleep_hours
        if mode == StudyMode.REST:
            return (
                f"I can hear that you're running on empty with {sleep} hours of sleep. "
                f"Protecting your recovery right now is the smartest study move you can make—rest up and we'll tackle this fresh."
            )
        if mode == StudyMode.CUSTOM:
            return (
                f"Since you're feeling {mood.value.lower()} on {sleep} hours of sleep, we're keeping things super gentle: "
                f"just one 10-minute light review block, then full rest."
            )
        if mode == StudyMode.LOW:
            return (
                f"It's completely okay to feel {mood.value.lower()} today. Let's take the pressure off with two short "
                f"15-minute focus sprints and plenty of breathing room."
            )
        if mode == StudyMode.OVERKILL:
            return (
                f"You're feeling {mood.value.lower()} and well-rested with {sleep} hours of sleep! "
                f"Let's channel that momentum into three 50-minute deep work blocks—remember to hydrate on your 10-minute breaks."
            )
        return (
            f"With {sleep} hours of sleep and a {mood.value.lower()} mindset, steady Pomodoro blocks (25 min focus / 5 min break) "
            f"will keep you productive without burning out."
        )

    async def analyze_user_pattern(
        self,
        user_history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not user_history:
            return {
                "best_mode": "Sustenance",
                "best_time": "Morning (9 AM - 12 PM)",
                "energy_pattern": "Steady completion in moderate blocks",
                "recommendation": "Start with 25-minute Sustenance blocks to establish your baseline."
            }

        # Deterministic statistical analysis over user_history
        mode_stats: Dict[str, Dict[str, int]] = {}
        hour_buckets = {"Morning": 0, "Afternoon": 0, "Evening": 0}
        completed_count = 0

        for s in user_history:
            m = s.get("mode", "Sustenance")
            done = bool(s.get("completed", False))
            mode_stats.setdefault(m, {"total": 0, "completed": 0})
            mode_stats[m]["total"] += 1
            if done:
                mode_stats[m]["completed"] += 1
                completed_count += 1
            ts = s.get("timestamp", "")
            try:
                hr = datetime.fromisoformat(ts).hour
                if 5 <= hr < 12:
                    hour_buckets["Morning"] += 1 if done else 0
                elif 12 <= hr < 17:
                    hour_buckets["Afternoon"] += 1 if done else 0
                else:
                    hour_buckets["Evening"] += 1 if done else 0
            except Exception:
                pass

        best_mode = max(
            mode_stats.items(),
            key=lambda kv: (kv[1]["completed"] / max(1, kv[1]["total"]), kv[1]["completed"])
        )[0] if mode_stats else "Sustenance"

        best_time = max(hour_buckets.items(), key=lambda kv: kv[1])[0]
        rate = completed_count / max(1, len(user_history))

        return {
            "best_mode": best_mode,
            "best_time": best_time,
            "energy_pattern": f"{rate*100:.0f}% session completion across {len(user_history)} recent sessions",
            "recommendation": (
                f"You perform best in {best_mode} mode during the {best_time.lower()}. "
                f"{'Keep riding that streak!' if rate >= 0.7 else 'Try slightly shorter blocks on low-sleep days to boost completion.'}"
            )
        }

    async def safety_evaluation(
        self,
        plan: StudyPlan,
        wellness: WellnessData,
        daily_minutes_used: int,
        user_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        allowed = (daily_minutes_used + plan.planned_minutes <= settings.DAILY_STUDY_CAP_MINUTES) and wellness.sleep_hours >= 4.5
        warnings = []
        if wellness.sleep_hours < 5.0:
            warnings.append("Low sleep detected (<5h); prioritize recovery.")
        if daily_minutes_used + plan.planned_minutes > settings.DAILY_STUDY_CAP_MINUTES:
            warnings.append("Approaching 240-minute daily cap.")
        return {
            "allowed": allowed,
            "reason": "Evaluated against physiological sleep and daily study cap guardrails.",
            "adjusted_minutes": min(plan.planned_minutes, max(0, settings.DAILY_STUDY_CAP_MINUTES - daily_minutes_used)),
            "warnings": warnings,
            "recommendation": "Proceed mindfully" if allowed else "Switch to Rest or Custom 10-min review."
        }

    async def generate_proactive_message(
        self,
        notification_type: str,
        user_state: Dict[str, Any]
    ) -> str:
        return await self.invoke_model(f"{notification_type}: {json.dumps(user_state)}", max_tokens=60)


# Singleton instance
bedrock_service = BedrockService()
