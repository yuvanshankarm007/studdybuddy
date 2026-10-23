# StudyBuddy 3-Minute Demo Video Script (2:45 Total)
**Event**: Build, Ship, Shape: Amazon Developer Hackathon (`amazonappdev2026.devpost.com`)  
**Hard Limit**: **Under 3:00 minutes** *(Judges are not required to watch past 3:00 — this script is timed to **2:45** and leads with our strongest material in the first 45 seconds!)*

---

## ⏱️ 0:00 – 0:30 | Hook & Live Alexa+ Voice Check-In (Lead with Best Material!)
- **On Screen**: Split view of the **StudyBuddy / Jarvis v2.1** dashboard + live **MCP `2025-11-25` Streamable HTTP** trace inspector.
- **Narration**:
  > *"Students and developers don't burn out because they lack timers—they burn out because rigid Pomodoro apps ignore whether they slept 8 hours or 3 hours. This is **StudyBuddy**, a self-hosted **Alexa+ MCP server** (Spec `2025-11-25` over Streamable HTTP) powered by **Amazon Bedrock** and **DynamoDB** that adapts your study blocks to your physiological state and enforces hard burnout guardrails."*
- **Live Action**: Click **"🎙️ Speak to Jarvis"** (or click the voice preset):
  - Speak: *"Jarvis, I am completely exhausted and barely slept, my energy is 2 out of 10."*
- **Highlight**: Show the **Voice NLU Parser** immediately extracting `Intent: check_in`, `Mood: Exhausted`, `Energy: 2/10 (96% confidence)` and playing the synthesized audio coaching response aloud!

---

## ⏱️ 0:30 – 1:15 | Multi-Agent Orchestration (A2A Wellness + Planner + Safety Guardrails)
- **On Screen**: Point to the **Recommended Study Plan**, **Safety Adjusted Badge**, and **Live Multi-Agent Decision Trace**.
- **Narration**:
  > *"Behind that single voice command, our **Supervisor Agent** orchestrated a 4-stage pipeline in under 500ms:*
  > *1. It queried our **A2A Wellness Worker Agent** (`/vitals`) and detected a sleep deficit (4.0 hours).*
  > *2. Our **Planner Agent** evaluated the Energy × Sleep matrix.*
  > *3. Our **Safety Agent** and **Amazon Bedrock safety evaluator** intervened—downgrading the session to a 10-minute recovery review block and enforcing our hard 4-hour daily study cap and 10 PM sleep cutoff.*
  > *4. **Amazon Bedrock (Claude 3 Haiku)** generated an empathetic voice response and **Alexa+ Multimodal Card & Carousel** payload."*
- **Live Action**: Now click the energized preset: *"Feeling super motivated and energized today, energy level 9!"* with 8.0h sleep → Watch it switch to **⚡ Overkill Mode (50 min deep work / 10 min break)** with an uplifting coaching tone and audio chime.

---

## ⏱️ 1:15 – 1:55 | Human-in-the-Loop Override, Live Focus Timer & Cross-Session Memory
- **On Screen**: Click **▶️ Start Session**, then **✓ Complete & Log**, and switch to the **📊 Study Analytics & Traces** tab.
- **Narration**:
  > *"StudyBuddy isn't a stateless single-turn bot. When I complete a session, `log_session_outcome` atomically updates my daily study counter in **Amazon DynamoDB** (with automatic local SQLite fallback for offline resilience) and updates my **Learning Memory**.*
  > *If I ever disagree with the agent, I can use the **Human-in-the-Loop Override** panel—which logs my override to **Amazon CloudWatch** so Bedrock learns my preferences over time."*

---

## ⏱️ 1:55 – 2:25 | AWS Builder Architecture & MCP `2025-11-25` Streamable HTTP Verification
- **On Screen**: Show `src/server.py` (`/mcp` JSON-RPC 2.0 `initialize` + `tools/call` returning `protocolVersion: "2025-11-25"` and `alexa_multimodal` cards/carousels) and `infrastructure/cloudformation/template.yaml`.
- **Narration**:
  > *"For the **AWS Builder Mini-Challenge**, our CloudFormation stack provisions **Amazon Bedrock**, **Amazon DynamoDB** (single-table design with GSI1), **Amazon CloudWatch** metrics and dashboards, **Amazon EventBridge** proactive evening reminders, **AWS Lambda**, and **API Gateway**."*

---

## ⏱️ 2:25 – 2:45 | Open Source Mini-Challenge (`mcp-wellness-agent`) & Close
- **On Screen**: Show `opensource/mcp-wellness-agent/` (`server.py`, `providers.py`, `LICENSE`, passing tests).
- **Narration**:
  > *"Finally, for the **Open Source Mini-Challenge**, we extracted **`mcp-wellness-agent`** as a standalone, MIT-licensed MCP `2025-11-25` server so any AI developer can plug circadian and wearable wellness telemetry into their own agents in two minutes. Built for **Build, Ship, Shape 2026**—thank you!"*
