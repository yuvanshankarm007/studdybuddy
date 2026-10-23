# StudyBuddy Developer Friction Log & Feature Requests
**Event**: Build, Ship, Shape: Amazon Developer Hackathon (`amazonappdev2026.devpost.com`)  
**Track**: Alexa+ Primary Track + AWS Builder Mini-Challenge + Open Source Mini-Challenge  
**Date**: October 23, 2026

> *Formatted per the official Build, Ship, Shape judging rubric (each entry includes: **Task Attempted**, **Steps Taken**, **Expected vs. Actual Result**, **Severity Rating**, **Workaround Used**, and **Actionable Suggestion**, followed by prioritized **Feature Requests**).*

---

## 🔧 Structured Friction Log Entries

### Entry 1: Mounting FastMCP Streamable HTTP Server Inside a Multi-Route FastAPI Application
- **Task Attempted**: Expose our Alexa+ MCP server tools (`check_in`, `get_user_profile`, `log_session_outcome`, `get_safety_status`) at `/mcp` over Streamable HTTP (MCP Spec `2025-11-25`) alongside a `/health` endpoint for Docker and ALB health checks in `src/server.py`.
- **Steps Taken**:
  1. Initialized `mcp = FastMCP("StudyBuddy-AlexaPlus")` and registered `@mcp.tool()` coroutines.
  2. Created a `FastAPI` instance (`app`) with `/health` and `/` endpoints.
  3. Attempted to mount `mcp` onto `app` and test tool discovery/execution via `fastapi.testclient.TestClient(app)`.
- **Expected vs. Actual Result**:
  - *Expected*: `POST /mcp` and `GET /mcp` on the parent FastAPI `app` should seamlessly handle JSON-RPC 2.0 `initialize` (returning `protocolVersion: "2025-11-25"`), `tools/list`, and `tools/call` with `Mcp-Session-Id` headers.
  - *Actual*: Mounting sub-apps in FastAPI strips the `/mcp` prefix or triggers `307 Temporary Redirect` on `/mcp` vs `/mcp/`, breaking strict MCP HTTP clients and returning `404 Not Found` when tested via `TestClient`.
- **Severity Rating**: **High** (Blocks Alexa+ MCP Streamable HTTP discovery if not handled explicitly).
- **Workaround Used**: Implemented explicit `GET /mcp` and `POST /mcp` Streamable HTTP JSON-RPC 2.0 handlers (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`) directly on the FastAPI router in `src/server.py` (and in `opensource/mcp-wellness-agent`), preserving `Mcp-Session-Id` headers while still registering `@mcp.tool()` decorators.
- **Actionable Suggestion**: Provide an official `register_mcp_routes(fastapi_app, mcp_instance, path="/mcp")` helper in the Alexa+ MCP Toolkit / FastMCP documentation that binds `/mcp` directly to an existing FastAPI router without ASGI sub-mount redirect issues.

---

### Entry 2: Synchronous `boto3` `bedrock-runtime` Blocking the Asyncio Event Loop in MCP Tools
- **Task Attempted**: Invoke Amazon Bedrock (`anthropic.claude-3-haiku-20240307-v1:0`) inside async MCP tool handlers (`check_in`) and FastAPI endpoints (`/checkin`) without blocking concurrent voice requests.
- **Steps Taken**:
  1. Created `boto3.client('bedrock-runtime', region_name='us-east-1')` in `src/services/bedrock.py`.
  2. Called `client.invoke_model(...)` inside `async def invoke_model(...)`.
- **Expected vs. Actual Result**:
  - *Expected*: Non-blocking async execution or an official async Bedrock runtime client in `boto3`.
  - *Actual*: `boto3`'s `invoke_model` is synchronous and blocks the entire Python `asyncio` event loop for 400–800ms per call, causing concurrent MCP health checks and A2A requests to stall.
- **Severity Rating**: **High** (Degrades voice response latency under concurrent load).
- **Workaround Used**: Wrapped `self.client.invoke_model` in `await asyncio.to_thread(...)`, configured `botocore.config.Config(connect_timeout=2, read_timeout=6, max_pool_connections=25)`, and added MD5 prompt-hash response caching plus a zero-latency local coaching fallback engine.
- **Actionable Suggestion**: Ship a first-class async client (`aioboto3` parity or native `async_invoke_model` in `boto3` / Strands SDK) in the standard AWS Python SDK examples on AWS Builder Center.

---

### Entry 3: `boto3` DynamoDB `Table.put_item` Rejecting Standard Python `float` Fields from Pydantic Models
- **Task Attempted**: Persist `WellnessData` (`sleep_hours: float`), `UserProfile` (`completion_rate: float`, `avg_sleep: float`), and `AgentDecisionTrace` (`latency_ms: float`, `confidence: float`) to Amazon DynamoDB in `src/services/dynamodb.py`.
- **Steps Taken**:
  1. Serialized Pydantic models via `.dict()` / `.model_dump()`.
  2. Passed the dictionary to `table.put_item(Item=...)`.
- **Expected vs. Actual Result**:
  - *Expected*: `boto3`'s high-level `Table` resource should automatically serialize standard Python `float` values or provide a config flag to convert floats to `Decimal`.
  - *Actual*: `boto3` raised `TypeError: Float types are not supported. Use Decimal types instead.` on every trace and profile write.
- **Severity Rating**: **Medium** (Crashes runtime persistence for any Pydantic model containing floats).
- **Workaround Used**: Wrote recursive `_to_decimal(obj)` and `_from_decimal(obj)` serialization helpers in `src/services/dynamodb.py` that convert all nested `float` values to `Decimal(str(round(val, 4)))` before `put_item` and back to `float`/`int` on `get_item`/`query`.
- **Actionable Suggestion**: Add `allow_floats=True` (auto-converting via `Decimal(str(val))`) to `boto3.resource('dynamodb')` `Table` serializer.

---

### Entry 4: Port `8000` Collision Between `amazon/dynamodb-local` and Standard MCP HTTP Servers
- **Task Attempted**: Run the full StudyBuddy stack locally via `docker-compose up` with `amazon/dynamodb-local` and the FastMCP server (`src/server.py`).
- **Steps Taken**:
  1. Configured `dynamodb-local` on its default port `8000:8000`.
  2. Configured `mcp-server` on the standard MCP HTTP port `8000:8000`.
  3. Ran `docker-compose up` and also tested standalone local execution when Docker was stopped.
- **Expected vs. Actual Result**:
  - *Expected*: Clean multi-container startup and graceful local execution when Docker isn't running.
  - *Actual*: Host port `8000` collided between `dynamodb-local` and `mcp-server`. Worse, when running outside Docker without DynamoDB Local running, `boto3` stalled for 9–12 seconds retrying `http://localhost:8000`, causing the dashboard and `/health` check to appear "Offline / Degraded".
- **Severity Rating**: **High** (Causes immediate startup failure in Docker and "Offline" status in standalone mode).
- **Workaround Used**: Remapped `dynamodb-local` host port to `8004:8000` in `docker-compose.yml` and built `LocalSQLiteStore` in `src/services/dynamodb.py` with a 0.35-second TCP socket reachability probe (`_is_endpoint_reachable`) that automatically switches to an in-memory SQLite + atomic JSON store when DynamoDB Local is unreachable.
- **Actionable Suggestion**: In AWS Builder Center templates that pair MCP servers with `dynamodb-local`, default `dynamodb-local` host port mapping to `8004:8000` so port `8000` remains free for MCP Streamable HTTP servers.

---

### Entry 5: Streamlit `st.markdown` Stripping Web Speech API `<script>` Tags in AG-UI Dashboards
- **Task Attempted**: Embed a browser-based Web Speech API (`webkitSpeechRecognition` + `speechSynthesis`) voice check-in widget inside the Streamlit AG-UI dashboard (`dashboard/pages/01_Session.py`).
- **Steps Taken**:
  1. Created `voice_service.get_voice_html()` containing `<script>` tags for `webkitSpeechRecognition` and `<button onclick="toggleVoice()">`.
  2. Rendered the HTML string via `st.markdown(voice_html, unsafe_allow_html=True)`.
- **Expected vs. Actual Result**:
  - *Expected*: Clicking the microphone button should start browser speech recognition and populate the check-in form.
  - *Actual*: Streamlit's `st.markdown` uses React's `dangerouslySetInnerHTML`, which silently ignores `<script>` tags. Clicking the button threw `ReferenceError: toggleVoice is not defined`, and hidden HTML `<input>` values never synced back to Streamlit's Python `st.session_state`.
- **Severity Rating**: **Critical** (Completely broke browser voice recognition in the dashboard).
- **Workaround Used**: Switched to `streamlit.components.v1.html()` so the JS executes in an active iframe, fixed the DOM target ID bindings, added parent-DOM input dispatching + a live NLU voice parser (`parse_voice_command`) + `.wav` audio upload STT (`speech_to_text`), and added a pure-Python harmonic `.wav` TTS synthesizer fallback so voice input and audio output work in 100% of environments.
- **Actionable Suggestion**: Provide a pre-built Alexa+ Voice Simulator Web Component (`<alexa-plus-voice-simulator mcp-url="http://localhost:8000/mcp">`) in the Amazon Devices Builder Tools so developers can test voice + APL multimodal cards in any web framework without custom Web Speech API boilerplate.

---

### Entry 6: Headless Container Audio Synthesis (`pyttsx3` / `gTTS`) Failing Without System Audio Drivers
- **Task Attempted**: Generate playable TTS coaching audio files inside the Python 3.12 slim Docker container (`Dockerfile`) and offline environments.
- **Steps Taken**:
  1. Installed `gTTS` and `pyttsx3` via `requirements.txt` in `python:3.12-slim`.
  2. Called `voice_service.text_to_speech(coaching)` during check-in.
- **Expected vs. Actual Result**:
  - *Expected*: A valid `.mp3` or `.wav` file path returned for playback.
  - *Actual*: `pyttsx3.init()` failed with `OSError: libespeak.so.1: cannot open shared object file` in slim containers lacking `espeak-ng`, and `gTTS` failed whenever outbound internet was restricted—returning `None` and leaving the audio module silent.
- **Severity Rating**: **Medium** (Breaks audio playback in offline or minimal container environments).
- **Workaround Used**: Added `espeak-ng`, `libportaudio2`, `portaudio19-dev`, and `ffmpeg` to `Dockerfile`, and implemented a zero-dependency pure-Python harmonic WAV synthesizer (`_generate_offline_coaching_wav`) in `src/services/voice.py` as a guaranteed third-tier fallback alongside Web Speech API `window.speechSynthesis`.
- **Actionable Suggestion**: Document container-level audio dependencies (`espeak-ng`, `ffmpeg`) in voice-track starter Dockerfiles, or provide an Amazon Polly local mock endpoint.

---

### Entry 7: AWS Lambda 3-Second Default Timeout Truncating Multi-Agent Bedrock Workflows
- **Task Attempted**: Deploy the Supervisor + Planner + Safety + Bedrock orchestration pipeline to AWS Lambda via CloudFormation (`infrastructure/cloudformation/template.yaml`).
- **Steps Taken**:
  1. Deployed `MCPServerFunction` with default Lambda settings.
  2. Triggered a cold-start `check_in` tool call over API Gateway.
- **Expected vs. Actual Result**:
  - *Expected*: Complete JSON-RPC tool response with study plan and coaching tone.
  - *Actual*: Cold start (`boto3` import + DynamoDB table check + two Bedrock Haiku calls for safety evaluation and coaching tone) took ~3.4 seconds, triggering `Task timed out after 3.00 seconds`.
- **Severity Rating**: **Medium** (Causes 502 Bad Gateway on cold starts).
- **Workaround Used**: Set `Timeout: 30` and `MemorySize: 512` in `infrastructure/cloudformation/template.yaml`, lazy-loaded clients with connection pooling, and cached frequent prompt states.
- **Actionable Suggestion**: Default agentic Lambda templates in AWS Builder Center to `Timeout: 30` and `MemorySize: 512` (or `1024` for faster CPU-bound `boto3` imports).

---

## 💡 Feature Requests for Amazon Developer & AWS Teams

| # | Feature Request | Why It Matters for Alexa+ & AWS Builders | Priority Rating |
| :--- | :--- | :--- | :--- |
| **1** | **Drop-in `<alexa-plus-simulator>` Web Component for MCP Servers** | Builders creating self-hosted MCP (`2025-11-25`) servers need a fast way to preview voice utterances, SSML prosody, and multimodal cards/carousels locally in a browser before connecting to an Echo Show device. | **Critical** |
| **2** | **Standardized Multimodal Card & Carousel Schema in Alexa+ MCP Toolkit** | Defining an official JSON schema inside MCP `CallToolResult.structuredContent` (e.g., `alexa_plus_card`, `alexa_plus_carousel`) would let any MCP server render native visual cards on Echo Show and Fire TV devices automatically. | **Critical** |
| **3** | **Native Async `bedrock-runtime` & `dynamodb` Clients in `boto3`** | Modern MCP servers (FastMCP, FastAPI) are 100% `asyncio`-native. Requiring `asyncio.to_thread()` around synchronous `boto3` calls adds boilerplate and thread-pool contention. | **Important** |
| **4** | **Auto-Conversion of Python `float` to `Decimal` in `boto3` DynamoDB Table Resource** | Virtually every AI/ML Pydantic schema uses Python `float` for confidence scores, latencies, and telemetry. Auto-converting floats in `put_item` would eliminate one of the most common runtime crashes in Python AWS apps. | **Important** |
| **5** | **Cross-Track Wearable Context Bridge (Bee MCP ↔ Alexa+ MCP)** | Allowing an Alexa+ MCP server to subscribe directly to a user's Bee Wearable AI MCP context stream (sleep, stress, ambient summaries) would unlock zero-friction physiological coaching across Amazon devices. | **Nice-to-have** |
