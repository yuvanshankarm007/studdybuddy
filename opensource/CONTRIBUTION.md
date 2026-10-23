# Open Source Contribution - StudyBuddy

## Contribution Summary

**Project**: MCP Wellness Agent  
**Repository**: `opensource/mcp-wellness-agent/`  
**License**: MIT  
**Hackathon**: Amazon Build Ship Shape 2026

## What We Built

A **reusable, open-source Model Context Protocol (MCP) server** for wellness data that any AI agent can integrate with. This is our contribution for the **Open Source Mini-Challenge**.

### Why This Matters

1. **Protocol Standard**: Implements the emerging MCP standard for agent-tool communication
2. **Privacy-First**: On-device simulation option means no health data leaves your system
3. **Extensible**: Clean provider pattern makes adding new wearables trivial
4. **Voice-Ready**: Optimized for Alexa+ and voice-first interfaces

### Key Files

| File | Description | Lines |
|------|-------------|-------|
| `src/mcp_wellness_agent/server.py` | MCP server with 3 tools | 120 |
| `src/mcp_wellness_agent/providers.py` | Abstracted wellness providers | 95 |
| `tests/test_agent.py` | Test suite | 65 |
| `pyproject.toml` | Package configuration | 75 |

### How It Works

```python
from mcp_wellness_agent import create_server

# Create server with simulated data
server = create_server(provider="simulated")

# Tools exposed:
# - get_vitals(user_id) -> sleep, activity, stress
# - get_history(user_id, days) -> historical data
# - analyze_trends(user_id) -> insights & recommendations
```

### Integration with StudyBuddy

The MCP Wellness Agent is used by StudyBuddy's Supervisor Agent via A2A protocol:

1. **StudyBuddy Supervisor** (MCP Client) → `get_vitals("user_123")`
2. **MCP Wellness Agent** → Returns sleep, activity, stress data
3. **StudyBuddy Planner** → Adapts study plan based on wellness

This decoupling means:
- Any MCP-compatible agent can use the wellness agent
- Wellness data source can change without affecting StudyBuddy
- Multiple agents can share the same wellness data

### Future Roadmap

- [ ] Apple HealthKit integration
- [ ] Garmin Connect integration
- [ ] Oura Ring support
- [ ] Blood glucose trend analysis
- [ ] HRV (Heart Rate Variability) stress detection

## How to Use

```bash
# Install
pip install -e opensource/mcp-wellness-agent

# Run tests
pytest opensource/mcp-wellness-agent/tests

# Start server
python -m mcp_wellness_agent.server --provider simulated --port 8001
```

## GitHub Repository

[https://github.com/yuvanshankarm007/mcp-wellness-agent](https://github.com/yuvanshankarm007/mcp-wellness-agent)

## License

Dual-Licensed under **GNU AGPLv3 (`AGPL-3.0-only`)** & **PolyForm Noncommercial 1.0.0** — Free for personal, academic, and open-source use; **commercial use requires prior written permission** (see `COMMERCIAL_LICENSE.md`).
