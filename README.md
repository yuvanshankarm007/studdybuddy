# 🧠 StudyBuddy: Energy-Aware Alexa+ Coach

[![AWS](https://img.shields.io/badge/AWS-Bedrock%20%7C%20DynamoDB%20%7C%20CloudWatch-orange)](https://aws.amazon.com)
[![MCP](https://img.shields.io/badge/MCP-2.0-green)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-AGPL_v3%20%2F%20NonCommercial-blue)](LICENSE)

**StudyBuddy** is an intelligent, voice-first study coach built for the **Amazon Build Ship Shape 2026** hackathon. It adapts study plans to your physiological state using multi-agent orchestration, AWS services, and the Model Context Protocol (MCP).

## 🏆 Competition Tracks

- **🏅 Alexa+ Track**: Voice-first MCP server with Streamable HTTP
- **🏗️ AWS Builder Mini-Challenge**: Bedrock + DynamoDB + CloudWatch integration
- **📦 Open Source Mini-Challenge**: Reusable MCP Wellness Agent (GNU AGPLv3 + PolyForm Noncommercial (Commercial Use Requires Permission))

## 💡 The Problem

Student burnout is real. Existing study apps act like rigid timers—they don't care if you slept 3 hours or 8 hours, or if you're feeling energized or exhausted. This one-size-fits-all approach leads to ineffective study sessions and mental fatigue.

## 🚀 The Solution

StudyBuddy performs a quick wellness check-in ("Alexa, I'm exhausted but need to study") and adapts your study plan, tone, and breaks based on your physiological state, while enforcing strict hard limits to prevent burnout.

### Key Features

- 🎙️ **Voice Interface**: Web Speech API + Text-to-Speech for natural interaction
- 🧠 **Multi-Agent System**: Supervisor, Planner, Safety, and Wellness agents
- 📊 **Real-time Wellness**: Sleep, activity, and stress data integration
- 🛡️ **Safety Guardrails**: 4-hour daily cap, sleep cutoff, minimum rest
- 🧬 **Learning Memory**: Adapts to your patterns over time
- 📬 **Proactive Coaching**: Scheduled reminders and encouragement
- 🔍 **Observability**: Full decision traces and CloudWatch metrics
- 🏥 **AG-UI Dashboard**: Human-in-the-Loop override and analytics

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Streamlit   │  │   Alexa      │  │   REST API       │  │
│  │  Dashboard   │  │   Skill      │  │   (FastAPI)      │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         └─────────────────┼───────────────────┘            │
│                           ▼                                │
│                  ┌─────────────────┐                       │
│                  │   API Gateway   │                       │
│                  └────────┬────────┘                       │
└───────────────────────────┼────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    AGENT ORCHESTRATION                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Supervisor Agent (LLM)                  │    │
│  │  • Intent Classification  • Memory Retrieval        │    │
│  │  • Tool Selection         • Safety Guardrails       │    │
│  └──────────────┬──────────────────────────────────────┘    │
│                 │                                            │
│    ┌────────────┼────────────┐                               │
│    ▼            ▼            ▼                               │
│ ┌──────┐   ┌────────┐   ┌─────────┐                        │
│ │Planner│   │Safety │   │Memory   │                        │
│ │Worker │   │Worker │   │Worker   │                        │
│ └──┬───┘   └───┬────┘   └────┬────┘                        │
│    │            │             │                              │
│    ▼            ▼             ▼                              │
│ ┌─────────────────────────────────────┐                     │
│ │         TOOL REGISTRY (MCP)         │                     │
│ │  • Wellness API  • Calendar  • DB   │                     │
│ └─────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────┼────────────────────────────────┐
│                    DATA & INFRASTRUCTURE                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ DynamoDB │  │  Bedrock │  │CloudWatch│  │ EventBridge│  │
│  │ (State)  │  │  (LLM)   │  │ (Metrics)│  │ (Schedule) │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### The 2026 Agentic Stack

1. **MCP (Agent ↔ Tools)**: FastMCP server exposing tools over Streamable HTTP
2. **A2A (Agent ↔ Agent)**: Supervisor coordinates with Wellness Worker via FastAPI
3. **AG-UI (Agent ↔ User)**: Streamlit dashboard for Human-in-the-Loop interaction

## ☁️ AWS Integration

| Service | Usage | Mini-Challenge |
|---------|-------|---------------|
| **Amazon Bedrock** | Claude 3 Haiku for coaching tone, safety eval, pattern analysis | AWS Builder |
| **Amazon DynamoDB** | Single-table design for user state, sessions, traces | AWS Builder |
| **Amazon CloudWatch** | Metrics, dashboards, agent decision logging | AWS Builder |
| **Amazon EventBridge** | Scheduled proactive notifications | AWS Builder |
| **AWS Lambda** | Serverless MCP server execution | AWS Builder |
| **API Gateway** | HTTP API for external integrations | AWS Builder |

## 🛡️ The 4 Study Modes

| Mode | Energy | Sleep | Study/Break | Total |
|------|--------|-------|-------------|-------|
| **Overkill** | 8-10 | 7+ hrs | 50 min / 10 min | ~150 min |
| **Sustenance** | 5-7 | 6+ hrs | 25 min / 5 min | ~100 min |
| **Low** | 3-4 | 5-6 hrs | 15 min / 5 min | ~30 min |
| **Custom/Rest** | 1-2 | < 5 hrs | 10 min / 10 min | ~10 min |

**Hard Guardrails**:
- ❌ No sessions if daily cap (240 min) reached
- ❌ No sessions past sleep cutoff (10 PM)
- ❌ No Overkill mode if sleep < 5 hours
- ❌ Mandatory rest if energy = 1/10

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Docker & Docker Compose
- AWS Account (for Bedrock)

### Local Development

```bash
# 1. Clone and setup
git clone https://github.com/yuvanshankarm007/studdybuddy
cd studybuddy
chmod +x scripts/setup.sh
./scripts/setup.sh

# 2. Start services
docker-compose up -d

# 3. Run dashboard
streamlit run dashboard/app.py

# 4. Open browser
# http://localhost:8501
```

### AWS Deployment

```bash
# Deploy CloudFormation stack
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

## 📁 Project Structure

```
studybuddy/
├── src/                          # Core application
│   ├── server.py                 # MCP Server
│   ├── api.py                    # REST API
│   ├── config.py                 # Configuration
│   ├── agents/                   # Multi-agent system
│   │   ├── supervisor.py         # Orchestrator
│   │   ├── planner.py            # Study plan creator
│   │   ├── safety.py             # Safety guardrails
│   │   └── wellness.py           # A2A wellness worker
│   ├── services/                 # Business logic
│   │   ├── bedrock.py            # AWS Bedrock LLM
│   │   ├── dynamodb.py           # DynamoDB operations
│   │   ├── memory.py             # Learning memory
│   │   ├── voice.py              # Voice interface
│   │   ├── wellness_data.py      # Wellness providers
│   │   ├── proactive.py          # Proactive agent
│   │   └── observability.py      # CloudWatch metrics
│   └── models/schemas.py         # Pydantic models
├── dashboard/                    # AG-UI Streamlit app
│   ├── app.py                    # Main app
│   └── pages/                    # Multi-page layout
│       ├── 01_Session.py
│       ├── 02_Analytics.py
│       └── 03_Settings.py
├── opensource/                   # Open Source contribution
│   └── mcp-wellness-agent/       # Reusable MCP agent
│       ├── src/
│       ├── tests/
│       └── pyproject.toml
├── infrastructure/               # AWS infrastructure
│   └── cloudformation/
│       └── template.yaml
├── tests/                        # Test suite
├── scripts/                      # Automation
│   ├── setup.sh
│   └── deploy.sh
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_agents.py -v
```

## 🎤 Demo Script

See [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the complete 5-minute demo script.

**30-Second Pitch**:
> *"Hi, I'm [Name] and this is StudyBuddy. Students don't need another rigid Pomodoro timer; they need a coach that understands their energy. StudyBuddy is an Alexa+ MCP server that fetches your sleep data via an A2A wellness agent, uses Amazon Bedrock to generate empathetic coaching, and enforces a strict 4-hour daily cap to prevent burnout. It features a full AG-UI dashboard for human-in-the-loop overrides. It's open-source, serverless, and built for the new agentic web."*

## 📄 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Detailed architecture decisions
- [DEMO_SCRIPT.md](DEMO_SCRIPT.md) - Demo presentation script
- [FRICTION_LOG.md](FRICTION_LOG.md) - Development friction log
- [opensource/CONTRIBUTION.md](opensource/CONTRIBUTION.md) - Open source contribution details

## 🤝 Contributing

Contributions welcome! Please read our [Contributing Guide](opensource/CONTRIBUTION.md).

## 📄 License

Dual-Licensed under **GNU AGPLv3 (`AGPL-3.0-only`)** and **PolyForm Noncommercial 1.0.0** — **No closed-source or commercial use is permitted without prior written permission** (see [LICENSE](LICENSE), [LICENSE.NONCOMMERCIAL.md](LICENSE.NONCOMMERCIAL.md), and [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)).

## 🏆 Acknowledgments

Built for **Amazon Build Ship Shape 2026** hackathon.

- **Alexa+ Track**: Voice-first agent experience
- **AWS Builder Mini-Challenge**: Enterprise-grade AWS integration
- **Open Source Mini-Challenge**: Modular, reusable wellness agent

---

**Team**: StudyBuddy Team  
**Repository**: [github.com/yuvanshankarm007/studdybuddy](https://github.com/yuvanshankarm007/studdybuddy)  
**Demo**: [studybuddy-demo.vercel.app](https://studybuddy-demo.vercel.app)
