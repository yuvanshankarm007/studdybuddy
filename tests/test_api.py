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



    def test_aws_lambda_eventbridge_handler(self):
        """Test AWS Builder Mini-Challenge EventBridge scheduled rule dispatch via lambda_handler"""
        from src.server import lambda_handler
        import json
        eb_event = {
            "source": "aws.events",
            "detail-type": "Scheduled Event",
            "detail": {
                "reminder_type": "sleep_reminder",
                "user_ids": ["aws_builder_test_user"]
            }
        }
        resp = lambda_handler(eb_event, None)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["status"], "dispatched")
        self.assertEqual(body["source"], "aws.events")
        self.assertGreaterEqual(body["notifications_created"], 1)

    def test_aws_lambda_apigw_mcp_handler(self):
        """Test AWS Builder Mini-Challenge API Gateway V2 HTTP API invocation via lambda_handler"""
        from src.server import lambda_handler
        import json
        apigw_event = {
            "rawPath": "/mcp",
            "requestContext": {"http": {"method": "POST"}},
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "jsonrpc": "2.0",
                "id": 99,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"}
            })
        }
        resp = lambda_handler(apigw_event, None)
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("Mcp-Session-Id", resp["headers"])
        data = json.loads(resp["body"])
        self.assertEqual(data["result"]["protocolVersion"], "2025-11-25")

    def test_cloudwatch_metric_payload_and_dynamodb_ttl(self):
        """Test CloudWatch PutMetricData payload format and DynamoDB TTL attribute"""
        from src.services.observability import observability
        from src.services.dynamodb import dynamodb_service
        payload = observability.build_cloudwatch_metric_payload(
            "check_in_latency", 42.5, "Milliseconds", {"Operation": "check_in"}
        )
        self.assertEqual(payload["Namespace"], "StudyBuddy")
        self.assertEqual(payload["MetricData"][0]["MetricName"], "check_in_latency")
        self.assertEqual(payload["MetricData"][0]["Unit"], "Milliseconds")

        traces = dynamodb_service.get_recent_traces("api_test_user", limit=5)
        if traces:
            self.assertIn("ttl", traces[0])


if __name__ == "__main__":

    unittest.main()
