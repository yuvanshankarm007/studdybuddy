"""
Tests for StudyBuddy Agents, Voice NLU, Audio TTS, and Offline Persistence
Compatible with both pytest and standard python3 -m unittest!
"""
import unittest
import asyncio
import os
from datetime import datetime

from src.models.schemas import CheckInRequest, WellnessData, Mood, StudyMode, StudyPlan, SessionOutcome
from src.agents.planner import PlannerAgent
from src.agents.safety import SafetyAgent
from src.agents.supervisor import SupervisorAgent
from src.services.voice import voice_service
from src.services.dynamodb import dynamodb_service


class TestPlannerAgent(unittest.TestCase):
    def setUp(self):
        self.planner = PlannerAgent()

    def test_overkill_mode(self):
        req = CheckInRequest(mood=Mood.MOTIVATED, energy=9, user_id="test_planner")
        wellness = WellnessData(sleep_hours=8.0, activity_level="normal")
        plan = self.planner.create_plan(req, wellness)
        self.assertEqual(plan.mode, StudyMode.OVERKILL)
        self.assertGreater(plan.planned_minutes, 0)
        self.assertIn("deep work", plan.blocks.lower())

    def test_sustenance_mode(self):
        req = CheckInRequest(mood=Mood.NEUTRAL, energy=6, user_id="test_planner")
        wellness = WellnessData(sleep_hours=6.5, activity_level="normal")
        plan = self.planner.create_plan(req, wellness)
        self.assertEqual(plan.mode, StudyMode.SUSTENANCE)

    def test_low_mode(self):
        req = CheckInRequest(mood=Mood.STRESSED, energy=3, user_id="test_planner")
        wellness = WellnessData(sleep_hours=5.0, activity_level="low")
        plan = self.planner.create_plan(req, wellness)
        self.assertEqual(plan.mode, StudyMode.LOW)

    def test_custom_mode_critical(self):
        req = CheckInRequest(mood=Mood.EXHAUSTED, energy=1, user_id="test_planner")
        wellness = WellnessData(sleep_hours=4.0, activity_level="low")
        plan = self.planner.create_plan(req, wellness)
        self.assertEqual(plan.mode, StudyMode.CUSTOM)
        self.assertLessEqual(plan.planned_minutes, 10)

    def test_no_description_mutation_across_calls(self):
        req = CheckInRequest(mood=Mood.NEUTRAL, energy=6, user_id="test_planner")
        wellness = WellnessData(sleep_hours=7.0, activity_level="normal")
        plan1 = self.planner.create_plan(req, wellness)
        plan2 = self.planner.create_plan(req, wellness)
        self.assertEqual(plan1.blocks, plan2.blocks)


class TestSafetyAgent(unittest.TestCase):
    def setUp(self):
        self.safety = SafetyAgent()
        dynamodb_service.clear_user_history("test_safety_user")

    def test_allows_normal_plan(self):
        req = CheckInRequest(mood=Mood.MOTIVATED, energy=7, user_id="test_safety_user", override_safety=True)
        plan = PlannerAgent().create_plan(req, WellnessData(sleep_hours=7.0))
        wellness = WellnessData(sleep_hours=7.0, activity_level="normal")
        result = self.safety.evaluate(req, plan, wellness)
        self.assertTrue(result.allowed)

    def test_rejects_critical_energy(self):
        req = CheckInRequest(mood=Mood.EXHAUSTED, energy=1, user_id="test_safety_user")
        plan = StudyPlan(mode=StudyMode.OVERKILL, blocks="test", planned_minutes=50, break_minutes=10)
        wellness = WellnessData(sleep_hours=4.0, activity_level="low")
        result = self.safety.evaluate(req, plan, wellness)
        self.assertFalse(result.allowed)

    def test_daily_cap_tracking_and_adjustment(self):
        user_id = "test_cap_user"
        dynamodb_service.clear_user_history(user_id)
        dynamodb_service.add_daily_minutes(user_id, 220, "Sustenance")
        req = CheckInRequest(mood=Mood.MOTIVATED, energy=8, user_id=user_id, override_safety=True)
        plan = StudyPlan(mode=StudyMode.OVERKILL, blocks="test", planned_minutes=50, break_minutes=10)
        wellness = WellnessData(sleep_hours=8.0, activity_level="high")
        result = self.safety.evaluate(req, plan, wellness)
        self.assertTrue(result.allowed)
        self.assertEqual(result.daily_minutes_used, 220)


class TestVoiceAndSupervisor(unittest.TestCase):
    def test_voice_nlu_parsing(self):
        cmd1 = voice_service.parse_voice_command("I am completely exhausted today and my energy is 2 out of 10")
        self.assertEqual(cmd1.mood, Mood.EXHAUSTED)
        self.assertEqual(cmd1.energy, 2)
        self.assertEqual(cmd1.intent, "check_in")

        cmd2 = voice_service.parse_voice_command("Feeling super motivated and pumped, energy level 9!")
        self.assertisin(cmd2.mood, [Mood.MOTIVATED, Mood.EXCITED])
        self.assertEqual(cmd2.energy, 9)

    def assertisin(self, item, container):
        self.assertIn(item, container)

    def test_offline_tts_wav_generation(self):
        path = asyncio.run(voice_service.text_to_speech("Take a gentle 10 minute review session today."))
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 1000)

    def test_supervisor_orchestration_and_dict_compat(self):
        supervisor = SupervisorAgent()
        req = CheckInRequest(
            mood=Mood.NEUTRAL,
            energy=5,
            user_id="test_sup_user",
            voice_input="I'm exhausted and my energy is 2 out of 10",
            override_safety=True
        )
        result = asyncio.run(supervisor.orchestrate_check_in(req))
        self.assertTrue(result["success"])
        plan = result["plan"]
        # Both attribute and dict access must work!
        self.assertIn(plan["mode"], [StudyMode.LOW.value, StudyMode.CUSTOM.value, StudyMode.REST.value])
        self.assertEqual(plan.get("mode"), plan.mode.value)


if __name__ == "__main__":
    unittest.main()
