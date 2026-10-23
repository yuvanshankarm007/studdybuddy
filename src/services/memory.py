"""
Learning Memory Service
Manages user learning patterns, preferences, and adaptive recommendations
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from src.models.schemas import UserProfile, StudyMode, SessionOutcome
from src.services.dynamodb import dynamodb_service
from src.services.bedrock import bedrock_service
from src.config import get_logger

logger = get_logger(__name__)


class MemoryService:
    """Service for managing user learning memory and adaptive behavior."""

    def __init__(self):
        self.db = dynamodb_service
        logger.info("memory_service_initialized")

    async def get_or_create_profile(self, user_id: str) -> UserProfile:
        profile = self.db.get_user_profile(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.db.update_user_profile(profile)
            logger.info("new_profile_created", user_id=user_id)
        return profile

    async def update_profile_from_session(self, outcome: SessionOutcome) -> UserProfile:
        profile = await self.get_or_create_profile(outcome.user_id)

        sessions = self.db.get_user_sessions(outcome.user_id, limit=200)
        if sessions:
            profile.total_sessions = len(sessions)
            profile.total_minutes = sum(int(s.get('actual_minutes', 0)) for s in sessions)
            completed = sum(1 for s in sessions if s.get('completed'))
            profile.completion_rate = round(completed / len(sessions), 3)

            energies = [float(s['energy']) for s in sessions if s.get('energy') is not None]
            sleeps = [float(s['sleep_hours']) for s in sessions if s.get('sleep_hours') is not None]
            if energies:
                profile.avg_energy = round(sum(energies) / len(energies), 1)
            if sleeps:
                profile.avg_sleep = round(sum(sleeps) / len(sleeps), 1)

            mode_success: Dict[str, Dict[str, int]] = {}
            for s in sessions:
                mode = s.get('mode')
                if mode:
                    mode_success.setdefault(mode, {'total': 0, 'completed': 0})
                    mode_success[mode]['total'] += 1
                    if s.get('completed'):
                        mode_success[mode]['completed'] += 1

            if mode_success:
                best_mode = max(
                    mode_success.items(),
                    key=lambda x: (x[1]['completed'] / max(1, x[1]['total']), x[1]['completed'])
                )[0]
                if best_mode in [m.value for m in StudyMode]:
                    profile.best_mode = StudyMode(best_mode)
        else:
            profile.total_sessions += 1
            profile.total_minutes += outcome.actual_minutes
            profile.completion_rate = 1.0 if outcome.completed else 0.0

        self.db.update_user_profile(profile)
        return profile

    async def get_personalized_recommendation(
        self,
        user_id: str,
        current_energy: int,
        current_mood: str
    ) -> Dict[str, Any]:
        profile = await self.get_or_create_profile(user_id)
        recommendation = {
            "suggested_mode": profile.best_mode.value if profile.best_mode else StudyMode.SUSTENANCE.value,
            "expected_completion": profile.completion_rate if profile.completion_rate is not None else 0.75,
            "reasoning": "Based on your study history,",
            "tips": []
        }

        if profile.best_mode:
            recommendation["reasoning"] += f" you have the highest completion rate in {profile.best_mode.value} mode."
        else:
            recommendation["reasoning"] += " Sustenance (Pomodoro) mode is recommended to establish your rhythm."

        if profile.completion_rate is not None and profile.completion_rate < 0.5:
            recommendation["tips"].append("Try shorter study blocks to build momentum and completion consistency.")
        if current_energy <= 3:
            recommendation["suggested_mode"] = StudyMode.LOW.value
            recommendation["tips"].append("Your energy is low today—focus on short review bursts.")

        return recommendation

    async def analyze_patterns(self, user_id: str) -> Dict[str, Any]:
        sessions = self.db.get_user_sessions(user_id, limit=50)
        if len(sessions) < 1:
            return {
                "status": "insufficient_data",
                "message": "Complete at least 1 study session to unlock personalized pattern analytics.",
                "patterns": {}
            }

        history = [
            {
                "mode": s.get('mode'),
                "planned": s.get('planned_minutes'),
                "actual": s.get('actual_minutes'),
                "completed": s.get('completed'),
                "focus": s.get('focus_score'),
                "timestamp": s.get('timestamp')
            }
            for s in sessions[:25]
        ]
        analysis = await bedrock_service.analyze_user_pattern(history)
        return {
            "status": "success",
            "patterns": analysis,
            "total_sessions": len(sessions)
        }

    def get_streak(self, user_id: str) -> Dict[str, Any]:
        sessions = self.db.get_user_sessions(user_id, limit=200)
        if not sessions:
            return {"current_streak": 0, "longest_streak": 0, "last_study_date": None, "total_study_days": 0}

        study_dates = set()
        for s in sessions:
            if s.get('completed'):
                ts = s.get('timestamp', '')
                if ts:
                    study_dates.add(ts[:10])

        if not study_dates:
            return {"current_streak": 0, "longest_streak": 0, "last_study_date": None, "total_study_days": 0}

        sorted_dates = sorted(study_dates, reverse=True)
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        current_streak = 0
        check_date = today if today in study_dates else yesterday
        while check_date in study_dates:
            current_streak += 1
            check_date = (datetime.strptime(check_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')

        longest_streak = 1
        current_longest = 1
        sorted_asc = sorted(study_dates)
        for i in range(1, len(sorted_asc)):
            prev_date = datetime.strptime(sorted_asc[i - 1], '%Y-%m-%d')
            curr_date = datetime.strptime(sorted_asc[i], '%Y-%m-%d')
            if (curr_date - prev_date).days == 1:
                current_longest += 1
                longest_streak = max(longest_streak, current_longest)
            else:
                current_longest = 1

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_study_date": sorted_dates[0],
            "total_study_days": len(study_dates)
        }


memory_service = MemoryService()
