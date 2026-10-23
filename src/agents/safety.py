"""
Safety Agent
Evaluates study plans against hard guardrails:
- Daily study cap (default 240 min)
- Sleep cutoff time (default 22:00) with optional human-in-the-loop override for short review
- Minimum rest requirements (4.5h sleep)
- Consecutive day limits (7 days)
"""
from datetime import datetime, timedelta
from typing import Optional

from src.config import settings, get_logger
from src.models.schemas import CheckInRequest, StudyPlan, WellnessData, SafetyCheck, StudyMode
from src.services.dynamodb import dynamodb_service

logger = get_logger(__name__)


class SafetyAgent:
    """Safety Agent - Enforces hard guardrails on study plans"""

    def __init__(self):
        self.daily_cap = settings.DAILY_STUDY_CAP_MINUTES
        self.sleep_cutoff = settings.SLEEP_CUTOFF_HOUR
        self.min_sleep_for_study = 4.5
        self.max_consecutive_days = 7

    def evaluate(
        self,
        req: CheckInRequest,
        plan: StudyPlan,
        wellness: WellnessData
    ) -> SafetyCheck:
        self.daily_cap = settings.DAILY_STUDY_CAP_MINUTES
        self.sleep_cutoff = settings.SLEEP_CUTOFF_HOUR

        user_id = req.user_id
        warnings = []

        current_usage = dynamodb_service.get_daily_usage(user_id)
        remaining = max(0, self.daily_cap - current_usage)

        # Check 1: Daily cap (strictly enforced)
        if current_usage >= self.daily_cap:
            return SafetyCheck(
                allowed=False,
                reason=f"Daily study cap ({self.daily_cap} min) already reached. Rest is essential.",
                daily_minutes_used=current_usage,
                daily_minutes_remaining=0,
                warnings=["Daily cap exceeded"]
            )

        # Check 2: Energy emergency (1/10)
        if req.energy <= 1 and not getattr(req, "override_safety", False):
            return SafetyCheck(
                allowed=False,
                reason="Energy level critical (1/10). Rest is mandatory.",
                daily_minutes_used=current_usage,
                daily_minutes_remaining=remaining,
                warnings=["Critical energy level", "Mandatory rest recommended"]
            )

        # Check 3: Sleep cutoff
        now = datetime.now()
        if now.hour >= self.sleep_cutoff:
            if getattr(req, "override_safety", False) and settings.ALLOW_LATE_NIGHT_OVERRIDE:
                warnings.append(f"Late-night override active past {self.sleep_cutoff}:00 — capped to 15 min light review.")
                adjusted_plan = StudyPlan(
                    mode=StudyMode.CUSTOM,
                    blocks="15 min light review (Late-Night Override)",
                    planned_minutes=min(15, remaining),
                    break_minutes=5,
                    num_blocks=1,
                    safety_override=True,
                    reasoning=f"User overrode sleep cutoff ({self.sleep_cutoff}:00); restricted to 15 min light review."
                )
                return SafetyCheck(
                    allowed=True,
                    reason="Late-night override granted with 15-minute safety cap.",
                    adjusted_plan=adjusted_plan,
                    warnings=warnings,
                    daily_minutes_used=current_usage,
                    daily_minutes_remaining=max(0, remaining - adjusted_plan.planned_minutes),
                    sleep_cutoff_approaching=True
                )
            return SafetyCheck(
                allowed=False,
                reason=f"It's past your sleep cutoff ({self.sleep_cutoff}:00). Protect your sleep for tomorrow (or use Override for a 15-min review).",
                daily_minutes_used=current_usage,
                daily_minutes_remaining=remaining,
                sleep_cutoff_approaching=True,
                warnings=["Sleep cutoff reached"]
            )

        if now.hour >= self.sleep_cutoff - 1:
            warnings.append(f"Sleep cutoff in {self.sleep_cutoff - now.hour} hour(s). Keep session short.")

        # Check 4: Fit within remaining daily allowance
        if current_usage + plan.planned_minutes > self.daily_cap:
            adjusted_minutes = self.daily_cap - current_usage
            warnings.append(f"Adjusted to fit remaining daily allowance ({adjusted_minutes} min)")
            adjusted_plan = StudyPlan(
                mode=plan.mode,
                blocks=f"{adjusted_minutes} min study / {plan.break_minutes} min break",
                planned_minutes=adjusted_minutes,
                break_minutes=plan.break_minutes,
                safety_override=True,
                reasoning=f"Adjusted to fit daily cap: {adjusted_minutes} min remaining"
            )
            return SafetyCheck(
                allowed=True,
                reason="Plan adjusted to fit daily cap",
                adjusted_plan=adjusted_plan,
                warnings=warnings,
                daily_minutes_used=current_usage,
                daily_minutes_remaining=0
            )

        # Check 5: Minimum sleep threshold
        if wellness.sleep_hours < self.min_sleep_for_study:
            if plan.mode not in [StudyMode.CUSTOM, StudyMode.REST]:
                warnings.append(f"Sleep ({wellness.sleep_hours}h) below minimum threshold. Recommend rest mode.")
                adjusted_plan = StudyPlan(
                    mode=StudyMode.CUSTOM,
                    blocks="10 min light review / 10 min rest",
                    planned_minutes=10,
                    break_minutes=10,
                    safety_override=True,
                    reasoning=f"Sleep below {self.min_sleep_for_study}h threshold. Emergency recovery mode."
                )
                return SafetyCheck(
                    allowed=True,
                    reason="Critical sleep deficit detected. Plan downgraded to recovery mode.",
                    adjusted_plan=adjusted_plan,
                    warnings=warnings,
                    daily_minutes_used=current_usage,
                    daily_minutes_remaining=max(0, remaining - 10)
                )

        # Check 6: Consecutive days
        sessions = dynamodb_service.get_user_sessions(user_id, limit=30)
        if sessions:
            study_dates = {s.get('timestamp', '')[:10] for s in sessions if s.get('timestamp')}
            if len(study_dates) >= self.max_consecutive_days:
                consecutive = 0
                check_date = datetime.now()
                for _ in range(self.max_consecutive_days + 3):
                    if check_date.strftime('%Y-%m-%d') in study_dates:
                        consecutive += 1
                        check_date -= timedelta(days=1)
                    else:
                        break
                if consecutive >= self.max_consecutive_days:
                    warnings.append(f"{consecutive} consecutive study days. Consider a full rest day.")

        # Check 7: High stress
        if wellness.stress_level and wellness.stress_level >= 8:
            warnings.append("High stress detected. Consider shorter session or relaxation techniques.")

        return SafetyCheck(
            allowed=True,
            reason="Plan approved. Stay within your limits.",
            warnings=warnings,
            daily_minutes_used=current_usage,
            daily_minutes_remaining=max(0, remaining - plan.planned_minutes),
            sleep_cutoff_approaching=(now.hour >= self.sleep_cutoff - 1)
        )

    def get_safety_summary(self, user_id: str) -> dict:
        self.daily_cap = settings.DAILY_STUDY_CAP_MINUTES
        self.sleep_cutoff = settings.SLEEP_CUTOFF_HOUR

        current_usage = dynamodb_service.get_daily_usage(user_id)
        remaining = max(0, self.daily_cap - current_usage)

        now = datetime.now()
        past_cutoff = now.hour >= self.sleep_cutoff
        sleep_cutoff_approaching = now.hour >= self.sleep_cutoff - 1

        block_reason = None
        if remaining <= 0:
            block_reason = f"Daily cap ({self.daily_cap} min) reached"
        elif past_cutoff:
            block_reason = f"Past sleep cutoff ({self.sleep_cutoff}:00)"

        return {
            "daily_cap": self.daily_cap,
            "daily_used": current_usage,
            "daily_remaining": remaining,
            "daily_percent": min(100.0, (current_usage / max(1, self.daily_cap)) * 100),
            "sleep_cutoff": self.sleep_cutoff,
            "past_sleep_cutoff": past_cutoff,
            "sleep_cutoff_approaching": sleep_cutoff_approaching,
            "can_study": remaining > 0 and not past_cutoff,
            "can_override": remaining > 0 and past_cutoff and settings.ALLOW_LATE_NIGHT_OVERRIDE,
            "block_reason": block_reason
        }
