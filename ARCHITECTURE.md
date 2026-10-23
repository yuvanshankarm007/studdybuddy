# StudyBuddy Architecture

## Overview

StudyBuddy is a distributed agentic system utilizing the 2026 AI Agent Protocol Stack. It implements three key protocol layers: MCP (Agent ↔ Tools), A2A (Agent ↔ Agent), and AG-UI (Agent ↔ User).

## Architecture Layers

### 1. MCP Layer (Agent ↔ Tools)

The core `server.py` uses **FastMCP** to expose tools to Alexa+ over **Streamable HTTP**.

**Exposed Tools**:
- `check_in(mood, energy)` - Main check-in with full orchestration
- `get_user_profile(user_id)` - Retrieve user learning history
- `log_session_outcome(...)` - Log session for learning
- `get_safety_status(user_id)` - Get current safety status

**Transport**: Streamable HTTP (required for Alexa+ compatibility)

### 2. A2A Layer (Agent ↔ Agent)

The Supervisor Agent acts as a client to a separate **Wellness Worker Agent** (FastAPI), simulating an Apple Health/Fitbit integration.

**Agent Card** (`/agent.json`):
```json
{
    "name": "StudyBuddyWellness",
    "capabilities": ["get_vitals", "get_historical", "analyze_trends"],
    "protocols": ["a2a/1.0", "http/rest"]
}
```

**Communication Flow**:
1. Supervisor discovers Wellness Agent via Agent Card
2. Supervisor requests vitals via HTTP GET `/vitals`
3. Wellness Agent returns structured wellness data
4. Supervisor incorporates data into planning

### 3. AG-UI Layer (Agent ↔ User)

A **Streamlit dashboard** provides the Human-in-the-Loop interface.

**Features**:
- Voice input via Web Speech API
- Real-time agent state visualization
- Decision trace viewer
- Safety status monitoring
- Plan override controls

**Pages**:
- **Session**: Voice check-in and session controls
- **Analytics**: Study patterns and progress
- **Settings**: Preferences and limits

## Multi-Agent System

### Supervisor Agent

Central orchestrator that coordinates all other agents.

**Workflow**:
1. Receive check-in request
2. Fetch wellness data (A2A)
3. Get user profile (memory)
4. Create plan (Planner Agent)
5. Evaluate safety (Safety Agent)
6. Generate coaching (Bedrock)
7. Log trace (DynamoDB)
8. Return response

### Planner Agent

Creates adaptive study plans based on evidence-based cognitive science.

**Decision Matrix**:
```
Energy | Sleep  | Mode
-------|--------|--------
  8-10 | 7+ hrs | Overkill
  5-7  | 6+ hrs | Sustenance
  3-4  | 5-6 hrs| Low
  1-2  | < 5 hrs| Custom/Rest
```

**Adjustments**:
- Post-lunch dip (2-4 PM): Reduce load by 20%
- Morning peak (6-9 AM): Increase load by 10%
- Historical performance: Adjust based on completion rate

### Safety Agent

Enforces hard guardrails using the "First, do no harm" principle.

**Checks** (in order):
1. Daily cap (240 min) - Absolute hard limit
2. Sleep cutoff (10 PM) - Protect sleep schedule
3. Minimum sleep (4.5 hrs) - Downgrade mode if needed
4. Critical energy (1/10) - Mandatory rest
5. Consecutive days (7) - Suggest rest day
6. High stress (8/10) - Warn and suggest relaxation

### Wellness Worker Agent

A2A-compatible FastAPI service providing wellness data.

**Providers**:
- **Simulated**: Realistic physiological model using circadian rhythms
- **Fitbit**: Real API integration (requires OAuth2)
- **Apple Health**: Planned (macOS/iOS only)

**Simulated Data Model**:
- User-specific baselines (seeded by user_id)
- Time-of-day factors (post-lunch dip, morning peak)
- Day-of-week variation (weekend sleep bonus)
- Correlation between metrics (poor sleep → high stress)

## AWS Integration

### Amazon Bedrock (Claude 3 Haiku)

**Use Cases**:
1. **Coaching Tone**: Generate empathetic responses based on mood + energy
2. **Safety Evaluation**: LLM-based safety assessment with reasoning
3. **Pattern Analysis**: Analyze user history for personalized insights
4. **Proactive Messages**: Generate contextual reminders

**Optimization**:
- Wrapped in `asyncio.to_thread` to prevent blocking
- Response caching for common states
- Connection pooling via `botocore.config.Config`
- Retry logic with adaptive backoff

### Amazon DynamoDB

**Single-Table Design**:

| PK | SK | GSI1PK | GSI1SK | Attributes |
|----|----|--------|--------|------------|
| USER#123 | PROFILE | USER | USER#123 | name, prefs, stats |
| USER#123 | DAILY#2024-01-15 | - | - | total_minutes, mode |
| USER#123 | SESSION#ts | SESSION#123 | ts | plan, outcome |
| USER#123 | TRACE#uuid | TRACE | ts | decisions, latency |

**Patterns**:
- Atomic counters for daily minutes
- TTL for old session data (1 year)
- GSI for time-series queries
- Conditional writes for race condition safety

### Amazon CloudWatch

**Metrics**:
- Agent latency (per operation)
- Agent call success/failure rates
- User engagement events
- Daily active users

**Logs**:
- Structured JSON logging via `structlog`
- Agent decision traces
- Error tracking

**Dashboard**:
- Real-time latency monitoring
- Agent call volume
- User engagement trends

### Amazon EventBridge

**Scheduled Rules**:
- Evening check-in reminder (7 PM daily)
- Sleep reminder (9 PM daily)
- Weekly pattern analysis (Sunday)

## Data Flow

### Check-In Flow

```
User → Voice Input → Streamlit Dashboard
    ↓
CheckInRequest → Supervisor Agent
    ↓
Parallel Fetch:
    ├── Wellness Worker (A2A) → WellnessData
    ├── Memory Service → UserProfile
    └── DynamoDB → DailyUsage
    ↓
Planner Agent → StudyPlan (initial)
    ↓
Safety Agent → SafetyCheck
    ↓
[If rejected] → Rest Plan
[If adjusted] → Modified Plan
[If approved] → Original Plan
    ↓
Bedrock → Coaching Tone
    ↓
DynamoDB → Log Session + Trace
    ↓
Response → Dashboard → User
```

### Session Completion Flow

```
User → End Session → Dashboard
    ↓
SessionOutcome → DynamoDB (log_session)
    ↓
Memory Service → Update Profile
    ├── completion_rate
    ├── avg_energy
    ├── best_mode
    └── streak
    ↓
Pattern Analysis (async)
    ↓
Proactive Notifications (if applicable)
```

## Performance

### Latency Budget

| Operation | Target | Max |
|-----------|--------|-----|
| Wellness Fetch | 100ms | 500ms |
| Plan Creation | 10ms | 50ms |
| Safety Check | 10ms | 50ms |
| Bedrock Invoke | 500ms | 2000ms |
| DynamoDB Write | 50ms | 200ms |
| **Total** | **670ms** | **2800ms** |

### Optimization Strategies

1. **Connection Pooling**: Bedrock and DynamoDB clients with `max_pool_connections=50`
2. **Response Caching**: Bedrock responses cached by prompt hash
3. **Async Operations**: All I/O is async via `asyncio`
4. **Parallel Fetch**: Wellness + Memory fetched concurrently
5. **Lazy Loading**: Services initialized on first use

## Security

### Data Protection
- DynamoDB encryption at rest (SSE)
- No PII stored (user_id is hash)
- TTL for automatic data expiration

### Access Control
- IAM roles with least privilege
- Lambda execution roles scoped to specific tables
- API Gateway CORS configuration

### Safety
- Hard limits cannot be overridden by user
- All overrides are logged for analysis
- Bedrock Guardrails prevent harmful advice

## Observability

### Decision Traces

Every check-in generates a trace:
```json
{
    "trace_id": "uuid",
    "user_id": "user_123",
    "timestamp": "2024-01-15T10:30:00Z",
    "steps": [
        {"agent": "wellness", "action": "fetch", "latency_ms": 120},
        {"agent": "planner", "action": "create_plan", "latency_ms": 5},
        {"agent": "safety", "action": "evaluate", "latency_ms": 8},
        {"agent": "bedrock", "action": "coaching", "latency_ms": 450}
    ],
    "total_latency_ms": 583
}
```

### Metrics

- `check_in_latency` (ms)
- `agent_calls` (count, by agent and status)
- `user_engagement` (count, by event type)
- `daily_active_users` (count)

## Scalability

### Horizontal Scaling
- Stateless MCP server (state in DynamoDB)
- Multiple Lambda instances handle load
- DynamoDB on-demand capacity

### Vertical Scaling
- Bedrock model selection (Haiku for speed, Sonnet for quality)
- Lambda memory allocation (512MB default)
- Redis caching layer (optional)

## Future Enhancements

1. **Federated Learning**: Learn across users without sharing data
2. **Causal Inference**: Understand cause-effect, not just correlation
3. **Emotional Intelligence**: Sentiment analysis on voice tone
4. **Social Features**: Study groups, accountability partners
5. **Wearable Integration**: Real Apple Health, Garmin, Oura Ring
6. **Multi-Modal**: Video check-ins, facial expression analysis
