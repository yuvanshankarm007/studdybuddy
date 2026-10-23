"""
Tests for StudyBuddy REST API and MCP Server
Compatible with both pytest and standard python3 -m unittest!
"""
import unittest
from fastapi.testclient import TestClient

from src.api import api
from src.server import app as mcp_app
from src.services.dynamodb import dynamodb_service

client = TestClient(api)
mcp_client = TestClient(mcp_app)


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        dynamodb_service.clear_user_history("test_api_user")

    def test_root(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "StudyBuddy API")

    def test_health_never_offline(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["local_storage_available"])
        self.assertTrue(data["voice_service_available"])

    def test_checkin(self):
        payload = {
            "mood": "Motivated",
            "energy": 7,
            "user_id": "test_api_user",
            "override_safety": True
        }
        response = client.post("/checkin", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("plan", data)
        self.assertIn("coaching", data)
        self.assertIsNotNone(data.get("audio_path"))

    def test_voice_checkin_endpoint(self):
        payload = {
            "transcript": "Jarvis, I am feeling super exhausted today, energy is 2 out of 10",
            "user_id": "test_api_user",
            "override_safety": True
        }
        response = client.post("/voice/checkin", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["voice_command"]["mood"], "Exhausted")
        self.assertEqual(data["voice_command"]["energy"], 2)

    def test_log_session_without_crash(self):
        payload = {
            "user_id": "test_api_user",
            "session_id": "test_session_123",
            "planned_minutes": 25,
            "actual_minutes": 25,
            "completed": True,
            "focus_score": 8
        }
        response = client.post("/session/log", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["profile"]["total_minutes"], 25)

        # Verify daily usage was incremented!
        safety_resp = client.get("/safety?user_id=test_api_user")
        self.assertEqual(safety_resp.json()["daily_used"], 25)

    def test_mcp_server_endpoints(self):
        disc = mcp_client.get("/mcp")
        self.assertEqual(disc.status_code, 200)
        self.assertEqual(len(disc.json()["tools"]), 4)

        call_resp = mcp_client.post("/mcp", json={
            "tool": "check_in",
            "arguments": {"mood": "Motivated", "energy": 8, "user_id": "test_api_user"}
        })
        self.assertEqual(call_resp.status_code, 200)
        self.assertTrue(call_resp.json()["result"]["success"])



    def test_mcp_jsonrpc_2025_11_25_and_alexa_multimodal(self):
        """Verify official MCP Spec 2025-11-25 JSON-RPC 2.0 initialize, tools/list, and tools/call with Alexa+ cards"""
        init_resp = mcp_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "alexa-plus", "version": "1.0"}}
        })
        self.assertEqual(init_resp.status_code, 200)
        self.assertIn("Mcp-Session-Id", init_resp.headers)
        self.assertEqual(init_resp.json()["result"]["protocolVersion"], "2025-11-25")

        list_resp = mcp_client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()["result"]["tools"]), 4)

        call_resp = mcp_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "check_in",
                "arguments": {
                    "voice_input": "Alexa, I am exhausted today and my energy is 2 out of 10",
                    "user_id": "test_api_user",
                    "override_safety": True
                }
            }
        })
        self.assertEqual(call_resp.status_code, 200)
        structured = call_resp.json()["result"]["structuredContent"]
        self.assertTrue(structured["success"])
        self.assertIn("alexa_multimodal", structured)
        self.assertIn("alexa_plus_card", structured["alexa_multimodal"])
        self.assertEqual(len(structured["alexa_multimodal"]["alexa_plus_carousel"]), 3)


if __name__ == "__main__":

    unittest.main()
