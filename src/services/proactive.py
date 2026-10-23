"""
Proactive Agent Service
Manages Amazon EventBridge scheduled check-ins, wind-down sleep reminders, and proactive outreach.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from src.config import settings, get_logger
from src.models.schemas import ProactiveNotification
from src.services.dynamodb import dynamodb_service
from src.services.bedrock import bedrock_service
from src.services.memory import memory_service
from src.services.observability import observability

logger = get_logger(__name__)


class ProactiveAgentService:
    """Handles scheduled notifications and EventBridge proactive outreach"""

    def __init__(self):
        self.enabled = settings.ENABLE_PROACTIVE
        self.checkin_hour = settings.CHECKIN_REMINDER_HOUR
        self.sleep_hour = settings.SLEEP_REMINDER_HOUR
        self.db = dynamodb_service

    async def generate_checkin_reminder(self, user_id: str) -> Optional[ProactiveNotification]:
        if not settings.ENABLE_PROACTIVE:
            return None
        daily_minutes = self.db.get_daily_usage(user_id)
        if daily_minutes > 120:
            return None
        profile = await memory_service.get_or_create_profile(user_id)
        user_state = {
            "daily_minutes": daily_minutes,
            "completion_rate": profile.completion_rate,
            "streak": memory_service.get_streak(user_id)
        }
        message = await bedrock_service.generate_proactive_message("checkin_reminder", user_state)
        notification = ProactiveNotification(
            notification_id=str(uuid.uuid4()),
            user_id=user_id,
            type="checkin",
            message=message,
            scheduled_time=datetime.now().replace(hour=min(23, max(0, self.checkin_hour)), minute=0)
        )
        self.db.save_notification(notification)
        observability.record_user_engagement(user_id, "proactive_checkin_reminder")
        return notification

    async def generate_sleep_reminder(self, user_id: str) -> Optional[ProactiveNotification]:
        if not settings.ENABLE_PROACTIVE:
            return None
        user_state = {
            "current_time": datetime.now().strftime("%H:%M"),
            "sleep_cutoff": f"{settings.SLEEP_CUTOFF_HOUR}:00"
        }
        message = await bedrock_service.generate_proactive_message("sleep_reminder", user_state)
        notification = ProactiveNotification(
            notification_id=str(uuid.uuid4()),
            user_id=user_id,
            type="sleep",
            message=message,
            scheduled_time=datetime.now().replace(hour=min(23, max(0, self.sleep_hour)), minute=0)
        )
        self.db.save_notification(notification)
        observability.record_user_engagement(user_id, "proactive_sleep_reminder")
        return notification

    async def generate_encouragement(self, user_id: str) -> Optional[ProactiveNotification]:
        streak = memory_service.get_streak(user_id)
        if streak["current_streak"] < 1:
            return None
        user_state = {
            "streak": streak["current_streak"],
            "longest_streak": streak["longest_streak"]
        }
        message = await bedrock_service.generate_proactive_message("encouragement", user_state)
        notification = ProactiveNotification(
            notification_id=str(uuid.uuid4()),
            user_id=user_id,
            type="encouragement",
            message=message,
            scheduled_time=datetime.now() + timedelta(hours=1)
        )
        self.db.save_notification(notification)
        observability.record_user_engagement(user_id, "proactive_encouragement")
        return notification

    async def run_daily_schedule(self, user_id: str) -> List[Dict[str, Any]]:
        if not settings.ENABLE_PROACTIVE:
            return []
        dispatched = []
        for fn in (self.generate_checkin_reminder, self.generate_sleep_reminder, self.generate_encouragement):
            notif = await fn(user_id)
            if notif:
                dispatched.append(notif.to_serializable())
        return dispatched

    async def handle_eventbridge_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process an Amazon EventBridge scheduled rule event (`aws.events`)"""
        detail = event.get("detail") or {}
        reminder_type = detail.get("reminder_type", "daily_schedule")
        target_users = detail.get("user_ids") or ["default_user"]

        results = []
        for uid in target_users:
            if reminder_type == "checkin_reminder":
                notif = await self.generate_checkin_reminder(uid)
                if notif:
                    results.append(notif.to_serializable())
            elif reminder_type == "sleep_reminder":
                notif = await self.generate_sleep_reminder(uid)
                if notif:
                    results.append(notif.to_serializable())
            else:
                batch = await self.run_daily_schedule(uid)
                results.extend(batch)

        observability.record_agent_call("proactive_eventbridge", True)
        return {
            "status": "dispatched",
            "source": "aws.events",
            "reminder_type": reminder_type,
            "notifications_created": len(results),
            "notifications": results,
            "timestamp": datetime.now().isoformat()
        }


proactive_service = ProactiveAgentService()
