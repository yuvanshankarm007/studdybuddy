"""
Supervisor Agent
Orchestrates the multi-agent workflow:
0. Parses voice input (if provided) via VoiceService NLU
1. Fetches wellness data (A2A / Simulated / Fitbit)
2. Fetches user profile & history (Memory Service)
3. Creates adaptive study plan (Planner Agent)
4. Evaluates safety guardrails (Safety Agent)
5. Generates empathetic coaching message (Bedrock / Local Coaching Engine)
6. Synthesizes voice coaching audio (VoiceService TTS)
7. Logs decision trace (DynamoDB / SQLite)
"""
import uuid
import time
from typing import Optional, Dict, Any

from src.config import settings, get_logger
from src.models.schemas import (
    CheckInRequest, StudyPlan, WellnessData, StudyMode,
    AgentDecisionTrace, SafetyCheck, Mood
)
from src.services.wellness_data import wellness_data_service
from src.services.dynamodb import dynamodb_service
from src.services.bedrock import bedrock_service
from src.services.memory import memory_service
from src.services.voice import voice_service
from src.services.observability import observability, AgentTraceCollector

logger = get_logger(__name__)


class SupervisorAgent:
    """Supervisor Agent - Central orchestrator for StudyBuddy"""

    def __init__(self):
        self.daily_cap = settings.DAILY_STUDY_CAP_MINUTES
        self.sleep_cutoff = settings.SLEEP_CUTOFF_HOUR
        logger.info("supervisor_agent_initialized")

    async def orchestrate_check_in(self, req: CheckInRequest) -> Dict[str, Any]:
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        trace_collector = AgentTraceCollector(req.user_id, trace_id)

        try:
            # Step 0: If voice_input transcript is provided, parse mood & energy via NLU
            voice_cmd = None
            if req.voice_input and req.voice_input.strip():
                voice_cmd = voice_service.parse_voice_command(req.voice_input)
                if voice_cmd.processed:
                    if voice_cmd.mood:
                        req.mood = voice_cmd.mood
                    if voice_cmd.energy:
                        req.energy = voice_cmd.energy
                    trace_collector.add_step(
                        agent="voice_nlu",
                        action="parse_voice_command",
                        input_data={"transcript": req.voice_input},
                        output_data=voice_cmd.to_serializable(),
                        reasoning=f"Parsed voice transcript -> mood={req.mood.value}, energy={req.energy}/10, intent={voice_cmd.intent}"
                    )

            # Step 1: Fetch Wellness Data
            wellness = await self._fetch_wellness(req.user_id, trace_collector)

            # Step 2: Get User Profile & History
            profile = await memory_service.get_or_create_profile(req.user_id)

            # Step 3: Planner Agent creates initial plan
            plan = await self._create_plan(req, wellness, profile, trace_collector)

            # Step 4: Safety Agent evaluates plan
            safety = await self._safety_check(req, plan, wellness, trace_collector)

            # Step 5: Apply safety adjustments if needed
            final_plan = self._apply_safety(plan, safety, trace_collector)

            # Step 6: Generate coaching tone
            coaching = await self._generate_coaching(req, final_plan, wellness, trace_collector)
            final_plan.coaching_tone = coaching

            # Step 7: Synthesize TTS audio if voice is enabled
            audio_path = None
            if settings.ENABLE_VOICE:
                audio_path = await voice_service.text_to_speech(coaching)
                final_plan.audio_path = audio_path

            # Step 8: Log decision trace
            latency = round((time.time() - start_time) * 1000, 2)
            await self._log_trace(trace_collector, req, wellness, plan, safety, final_plan, latency)

            observability.record_agent_call("supervisor", True)
            observability.record_latency("check_in", latency)

            return {
                "success": True,
                "trace_id": trace_id,
                "plan": final_plan,
                "safety": safety,
                "wellness": wellness,
                "coaching": coaching,
                "audio_path": audio_path,
                "voice_command": voice_cmd.to_serializable() if voice_cmd else None,
                "latency_ms": latency,
                "reasoning_chain": trace_collector.get_reasoning_chain()
            }

        except Exception as e:
            latency = round((time.time() - start_time) * 1000, 2)
            observability.record_agent_call("supervisor", False)
            observability.record_latency("check_in", latency)
            logger.error("check_in_failed", user_id=req.user_id, trace_id=trace_id, error=str(e))
            raise

    async def _fetch_wellness(self, user_id: str, trace: AgentTraceCollector) -> WellnessData:
        step_start = time.time()
        try:
            wellness = await wellness_data_service.get_wellness_data(user_id)
            latency = (time.time() - step_start) * 1000
            trace.add_step(
                agent="wellness_worker",
                action="fetch_wellness",
                input_data={"user_id": user_id},
                output_data=wellness.to_serializable(),
                reasoning=f"Fetched wellness: {wellness.sleep_hours}h sleep, {wellness.activity_level} activity"
            )
            observability.record_latency("wellness_fetch", latency)
            return wellness
        except Exception as e:
            logger.error("wellness_fetch_failed", error=str(e))
            wellness = WellnessData(sleep_hours=7.0, activity_level="normal")
            trace.add_step(
                agent="wellness_worker",
                action="fetch_wellness_fallback",
                input_data={"user_id": user_id},
                output_data=wellness.to_serializable(),
                reasoning="Wellness fetch failed, using fallback data"
            )
            return wellness

    async def _create_plan(
        self,
        req: CheckInRequest,
        wellness: WellnessData,
        profile,
        trace: AgentTraceCollector
    ) -> StudyPlan:
        step_start = time.time()
        from src.agents.planner import PlannerAgent
        planner = PlannerAgent()
        plan = planner.create_plan(req, wellness, profile=profile)
        latency = (time.time() - step_start) * 1000
        trace.add_step(
            agent="planner",
            action="create_plan",
            input_data={"mood": req.mood.value, "energy": req.energy, "wellness": wellness.to_serializable()},
            output_data=plan.to_serializable(),
            reasoning=f"Selected {plan.mode.value} mode based on energy={req.energy}, sleep={wellness.sleep_hours}h"
        )
        observability.record_latency("plan_creation", latency)
        return plan

    async def _safety_check(
        self,
        req: CheckInRequest,
        plan: StudyPlan,
        wellness: WellnessData,
        trace: AgentTraceCollector
    ) -> SafetyCheck:
        step_start = time.time()
        from src.agents.safety import SafetyAgent
        safety_agent = SafetyAgent()
        safety = safety_agent.evaluate(req, plan, wellness)
        # Also run AWS Bedrock LLM safety evaluation for multi-step AWS Builder orchestration
        llm_safety = await bedrock_service.safety_evaluation(
            plan=plan,
            wellness=wellness,
            daily_minutes_used=safety.daily_minutes_used
        )
        for w in llm_safety.get("warnings", []):
            if w not in safety.warnings:
                safety.warnings.append(w)
        latency = (time.time() - step_start) * 1000
        trace.add_step(
            agent="safety",
            action="evaluate",
            input_data={"plan": plan.to_serializable(), "wellness": wellness.to_serializable()},
            output_data={**safety.to_serializable(), "bedrock_safety_eval": llm_safety},
            reasoning=safety.reason or "Plan approved"
        )
        observability.record_latency("safety_check", latency)
        return safety

    def _apply_safety(
        self,
        plan: StudyPlan,
        safety: SafetyCheck,
        trace: AgentTraceCollector
    ) -> StudyPlan:
        if safety.allowed and not safety.adjusted_plan:
            return plan

        if not safety.allowed:
            adjusted = StudyPlan(
                mode=StudyMode.REST,
                blocks="Rest and recovery",
                planned_minutes=0,
                break_minutes=0,
                safety_override=True,
                reasoning=safety.reason
            )
            trace.add_step(
                agent="supervisor",
                action="apply_safety",
                input_data={"plan": plan.to_serializable(), "safety": safety.to_serializable()},
                output_data=adjusted.to_serializable(),
                reasoning=f"Plan rejected: {safety.reason}"
            )
            return adjusted

        if safety.adjusted_plan:
            trace.add_step(
                agent="supervisor",
                action="adjust_plan",
                input_data={"plan": plan.to_serializable(), "safety": safety.to_serializable()},
                output_data=safety.adjusted_plan.to_serializable(),
                reasoning=f"Plan adjusted: {safety.reason}"
            )
            return safety.adjusted_plan

        return plan

    async def _generate_coaching(
        self,
        req: CheckInRequest,
        plan: StudyPlan,
        wellness: WellnessData,
        trace: AgentTraceCollector
    ) -> str:
        step_start = time.time()
        coaching = await bedrock_service.generate_coaching_tone(plan.mode, req.mood, wellness)
        latency = (time.time() - step_start) * 1000
        trace.add_step(
            agent="bedrock",
            action="generate_coaching",
            input_data={"mode": plan.mode.value, "mood": req.mood.value},
            output_data={"coaching": coaching},
            reasoning="Generated empathetic coaching tone"
        )
        observability.record_latency("coaching_generation", latency)
        return coaching

    async def _log_trace(
        self,
        trace_collector: AgentTraceCollector,
        req: CheckInRequest,
        wellness: WellnessData,
        planner_plan: StudyPlan,
        safety: SafetyCheck,
        final_plan: StudyPlan,
        latency: float
    ):
        trace = AgentDecisionTrace(
            trace_id=trace_collector.trace_id,
            user_id=req.user_id,
            input_state={"mood": req.mood.value, "energy": req.energy, "voice_input": req.voice_input},
            wellness_data=wellness,
            planner_decision=planner_plan,
            safety_decision=safety.to_serializable(),
            final_plan=final_plan,
            reasoning_chain=trace_collector.get_reasoning_chain(),
            latency_ms=latency,
            confidence=0.85 if not final_plan.safety_override else 0.95
        )
        dynamodb_service.log_decision_trace(trace)


supervisor_agent = SupervisorAgent()


async def orchestrate_check_in(req: CheckInRequest) -> Dict[str, Any]:
    return await supervisor_agent.orchestrate_check_in(req)
