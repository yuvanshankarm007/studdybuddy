"""
Planner Agent
Creates adaptive study plans based on user energy, wellness data, and historical performance.
Fixes:
1. Never mutates `self.modes[mode]["description"]` in-place (previously appended "(adjusted for afternoon)" repeatedly).
2. Integrates `adjust_for_history` when user profile history is available.
"""
from datetime import datetime
from typing import Optional

from src.models.schemas import CheckInRequest, WellnessData, StudyPlan, StudyMode, UserProfile
from src.config import get_logger

logger = get_logger(__name__)


class PlannerAgent:
    """Planner Agent - Creates personalized study plans"""

    def __init__(self):
        self.modes = {
            StudyMode.OVERKILL: {
                "study_min": 50,
                "break_min": 10,
                "num_blocks": 3,
                "description": "50 min deep work / 10 min break"
            },
            StudyMode.SUSTENANCE: {
                "study_min": 25,
                "break_min": 5,
                "num_blocks": 4,
                "description": "25 min focus / 5 min break (Pomodoro)"
            },
            StudyMode.LOW: {
                "study_min": 15,
                "break_min": 5,
                "num_blocks": 2,
                "description": "15 min study / 5 min break"
            },
            StudyMode.CUSTOM: {
                "study_min": 10,
                "break_min": 10,
                "num_blocks": 1,
                "description": "10 min light review / 10 min rest"
            }
        }
        logger.info("planner_agent_initialized")

    def create_plan(
        self,
        req: CheckInRequest,
        wellness: WellnessData,
        profile: Optional[UserProfile] = None
    ) -> StudyPlan:
        energy = req.energy
        sleep = wellness.sleep_hours
        mood = req.mood

        mode = self._select_mode(energy, sleep, mood)
        mode_config = dict(self.modes[mode])  # Copy so we never mutate self.modes in-place!

        planned_minutes = mode_config["study_min"] * mode_config["num_blocks"]
        description = mode_config["description"]

        hour = datetime.now().hour
        if 14 <= hour <= 16 and mode != StudyMode.CUSTOM:
            planned_minutes = max(10, int(planned_minutes * 0.8))
            description = f"{description} (adjusted for afternoon)"
        elif 6 <= hour <= 9 and mode != StudyMode.CUSTOM:
            planned_minutes = min(240, int(planned_minutes * 1.1))

        reasoning = self._build_reasoning(mode, energy, sleep, mood, hour)

        plan = StudyPlan(
            mode=mode,
            blocks=description,
            planned_minutes=planned_minutes,
            break_minutes=mode_config["break_min"],
            num_blocks=mode_config["num_blocks"],
            reasoning=reasoning
        )

        if profile and profile.total_sessions >= 3 and profile.completion_rate is not None:
            plan = self.adjust_for_history(plan, profile.completion_rate, profile.best_mode)

        return plan

    def _select_mode(self, energy: int, sleep: float, mood) -> StudyMode:
        if energy <= 2 or sleep < 4.5:
            return StudyMode.CUSTOM
        if energy >= 8 and sleep >= 7.0:
            return StudyMode.OVERKILL
        if energy >= 5 or sleep >= 6.0:
            return StudyMode.SUSTENANCE
        if energy >= 3 and sleep >= 5.0:
            return StudyMode.LOW
        return StudyMode.CUSTOM

    def _build_reasoning(self, mode: StudyMode, energy: int, sleep: float, mood, hour: int) -> str:
        reasons = [
            f"Energy level is {energy}/10",
            f"Sleep was {sleep} hours",
        ]
        if mode == StudyMode.OVERKILL:
            reasons.append("High energy and good sleep enable deep work")
        elif mode == StudyMode.SUSTENANCE:
            reasons.append("Moderate energy suggests sustainable pacing")
        elif mode == StudyMode.LOW:
            reasons.append("Low energy requires short, focused bursts")
        else:
            reasons.append("Critical rest needed - gentle approach only")

        if 6 <= hour <= 9:
            reasons.append("Morning hours favor focused work")
        elif 14 <= hour <= 16:
            reasons.append("Afternoon dip suggests shorter sessions")
        elif 20 <= hour <= 23:
            reasons.append("Evening study should be light")

        return "; ".join(reasons)

    def adjust_for_history(
        self,
        base_plan: StudyPlan,
        completion_rate: float,
        best_mode: Optional[StudyMode]
    ) -> StudyPlan:
        if completion_rate < 0.4 and base_plan.planned_minutes > 15:
            base_plan.planned_minutes = max(10, int(base_plan.planned_minutes * 0.7))
            base_plan.reasoning = (base_plan.reasoning or "") + "; Reduced due to low historical completion"

        if best_mode and base_plan.mode != best_mode and best_mode != StudyMode.REST:
            mode_order = [StudyMode.CUSTOM, StudyMode.LOW, StudyMode.SUSTENANCE, StudyMode.OVERKILL]
            if base_plan.mode in mode_order and best_mode in mode_order:
                current_idx = mode_order.index(base_plan.mode)
                best_idx = mode_order.index(best_mode)
                if abs(current_idx - best_idx) <= 1:
                    base_plan.mode = best_mode
                    base_plan.reasoning = (base_plan.reasoning or "") + f"; Adjusted toward your best mode ({best_mode.value})"
        return base_plan
