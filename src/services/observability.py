"""
Observability Service
Provides Amazon CloudWatch Logs (/StudyBuddy/agents), CloudWatch Custom Metrics (StudyBuddy namespace),
and non-blocking in-memory agent decision tracing for offline/local execution.
"""
import os
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from src.config import settings, get_logger

logger = get_logger(__name__)


def _has_real_aws_credentials() -> bool:
    ak = settings.AWS_ACCESS_KEY_ID or os.environ.get("AWS_ACCESS_KEY_ID", "")
    sk = settings.AWS_SECRET_ACCESS_KEY or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    if ak and sk and not ak.startswith("your_") and not ak.startswith("fake"):
        return True
    return os.path.exists(os.path.expanduser("~/.aws/credentials"))


class ObservabilityService:
    """Service for AWS CloudWatch observability and local in-memory telemetry"""

    def __init__(self):
        self.log_group = "/StudyBuddy/agents"
        self.metric_namespace = "StudyBuddy"
        self.metrics_history: List[Dict[str, Any]] = []
        self.cloudwatch = None
        self.logs = None
        self.enabled = bool(getattr(settings, "ENABLE_CLOUDWATCH", getattr(settings, "ENABLE_OBSERVABILITY", True)) and _has_real_aws_credentials())
        if self.enabled:
            try:
                import boto3
                from botocore.config import Config
                cfg = Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 1})
                self.cloudwatch = boto3.client("cloudwatch", region_name=settings.AWS_REGION, config=cfg)
                self.logs = boto3.client("logs", region_name=settings.AWS_REGION, config=cfg)
            except Exception as e:
                logger.warning("cloudwatch_init_fallback", error=str(e))
                self.enabled = False

    def build_cloudwatch_metric_payload(
        self,
        metric_name: str,
        value: float,
        unit: str = "Count",
        dimensions: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Build exact AWS CloudWatch PutMetricData payload structure"""
        dims = [{"Name": str(k), "Value": str(v)} for k, v in (dimensions or {}).items()]
        item: Dict[str, Any] = {
            "MetricName": metric_name,
            "Value": float(value),
            "Unit": unit,
            "Timestamp": datetime.utcnow().isoformat()
        }
        if dims:
            item["Dimensions"] = dims
        return {
            "Namespace": self.metric_namespace,
            "MetricData": [item]
        }

    def log_agent_decision(
        self,
        user_id: str,
        agent_name: str,
        decision: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        latency_ms: float,
        confidence: Optional[float] = None
    ):
        logger.info(
            "agent_decision",
            user_id=user_id,
            agent=agent_name,
            decision=decision,
            latency_ms=round(latency_ms, 2),
            confidence=confidence
        )

    def record_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "Count",
        dimensions: Optional[Dict[str, str]] = None
    ):
        payload = self.build_cloudwatch_metric_payload(metric_name, value, unit, dimensions)
        self.metrics_history.append({
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
            "dimensions": dimensions or {},
            "cloudwatch_payload": payload,
            "timestamp": datetime.now().isoformat()
        })
        if len(self.metrics_history) > 500:
            self.metrics_history = self.metrics_history[-500:]

        if self.enabled and self.cloudwatch is not None:
            try:
                self.cloudwatch.put_metric_data(
                    Namespace=payload["Namespace"],
                    MetricData=payload["MetricData"]
                )
            except Exception as e:
                logger.debug("cloudwatch_put_metric_skipped", error=str(e))

    def record_latency(self, operation: str, latency_ms: float):
        self.record_metric(f"{operation}_latency", latency_ms, "Milliseconds", {"Operation": operation})

    def record_agent_call(self, agent_name: str, success: bool):
        self.record_metric("agent_calls", 1, "Count", {"Agent": agent_name, "Status": "success" if success else "failure"})

    def record_user_engagement(self, user_id: str, event_type: str):
        self.record_metric("user_engagement", 1, "Count", {"User": user_id, "Event": event_type})

    @contextmanager
    def trace_operation(self, operation: str, user_id: str = "system"):
        start_time = time.time()
        trace_data = {"operation": operation, "user_id": user_id}
        try:
            yield trace_data
            latency = (time.time() - start_time) * 1000
            self.record_latency(operation, latency)
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            self.record_latency(operation, latency)
            logger.error("operation_failed", operation=operation, latency_ms=latency, error=str(e))
            raise


class AgentTraceCollector:
    """Collector for multi-agent decision traces"""

    def __init__(self, user_id: str, trace_id: str):
        self.user_id = user_id
        self.trace_id = trace_id
        self.steps: List[Dict[str, Any]] = []
        self.start_time = time.time()

    def add_step(
        self,
        agent: str,
        action: str,
        input_data: Any,
        output_data: Any,
        reasoning: Optional[str] = None
    ):
        self.steps.append({
            "step": len(self.steps) + 1,
            "agent": agent,
            "action": action,
            "input": input_data,
            "output": output_data,
            "reasoning": reasoning,
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": round((time.time() - self.start_time) * 1000, 2)
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "total_steps": len(self.steps),
            "total_latency_ms": round((time.time() - self.start_time) * 1000, 2),
            "steps": self.steps
        }

    def get_reasoning_chain(self) -> List[str]:
        return [
            f"Step {s['step']} ({s['agent']}): {s['reasoning'] or s['action']}"
            for s in self.steps
        ]


observability = ObservabilityService()
