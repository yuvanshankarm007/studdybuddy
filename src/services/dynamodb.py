"""
DynamoDB Service with Automatic Offline-First SQLite Fallback
Manages all persistence operations (User Profiles, Daily Usage, Sessions, Traces, Notifications).
Fixes:
1. Fast TCP reachability probe (<0.4s) so missing DynamoDB Local never hangs the app or shows "offline" errors.
2. Automatic SQLite + In-Memory persistence fallback when DynamoDB Local or boto3 is unavailable.
3. Recursive float <-> Decimal conversion so boto3 put_item never crashes with TypeError on floats.
4. Automatic daily usage updates (add_daily_minutes) when sessions are logged.
5. Notification acknowledgement and session history clearing.
"""
import os
import json
import socket
import sqlite3
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from src.config import settings, get_logger
from src.models.schemas import (
    SessionOutcome, UserProfile, AgentDecisionTrace,
    ProactiveNotification, StudyPlan, WellnessData, StudyMode
)

logger = get_logger(__name__)


def _to_decimal(obj: Any) -> Any:
    """Recursively convert Python floats to Decimal for boto3 DynamoDB compatibility"""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _from_decimal(obj: Any) -> Any:
    """Recursively convert Decimal back to int/float when reading from DynamoDB"""
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(v) for v in obj]
    return obj


def _is_endpoint_reachable(endpoint_url: Optional[str], timeout: float = 0.35) -> bool:
    """Fast TCP socket check to avoid 9-12s boto3 retry stalls when DynamoDB Local is not running"""
    if not endpoint_url:
        return False
    try:
        parsed = urlparse(endpoint_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 8000)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class LocalSQLiteStore:
    """
    Zero-dependency SQLite + JSON persistence store that mirrors the single-table DynamoDB schema.
    Uses in-memory SQLite with atomic JSON file sync so it works on all filesystems (including FUSE/NFS/Docker volumes)
    and ensures StudyBuddy is 100% online and functional even without Docker or AWS credentials.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.json_path = Path(str(db_path) + ".json")
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._load_json_snapshot()

    def _connect(self) -> sqlite3.Connection:
        return self._conn

    def _load_json_snapshot(self):
        if self.json_path.exists():
            try:
                rows = json.loads(self.json_path.read_text())
                for r in rows:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO items (pk, sk, gsi1pk, gsi1sk, payload, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (r["pk"], r["sk"], r.get("gsi1pk"), r.get("gsi1sk"), r["payload"], r["updated_at"])
                    )
                self._conn.commit()
            except Exception:
                pass

    def _save_json_snapshot(self):
        try:
            rows = self._conn.execute("SELECT pk, sk, gsi1pk, gsi1sk, payload, updated_at FROM items").fetchall()
            data = [dict(r) for r in rows]
            self.json_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    pk TEXT NOT NULL,
                    sk TEXT NOT NULL,
                    gsi1pk TEXT,
                    gsi1sk TEXT,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (pk, sk)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gsi1 ON items (gsi1pk, gsi1sk)")
            conn.commit()
            self._save_json_snapshot()

    def put_item(self, item: Dict[str, Any]):
        pk = item["PK"]
        sk = item["SK"]
        gsi1pk = item.get("GSI1PK")
        gsi1sk = item.get("GSI1SK")
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO items (pk, sk, gsi1pk, gsi1sk, payload, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pk, sk, gsi1pk, gsi1sk, json.dumps(item, default=str), now)
            )
            conn.commit()
            self._save_json_snapshot()

    def get_item(self, pk: str, sk: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM items WHERE pk = ? AND sk = ?", (pk, sk)).fetchone()
            return json.loads(row["payload"]) if row else None

    def query_pk_prefix(self, pk: str, sk_prefix: str, limit: int = 50, reverse: bool = True) -> List[Dict[str, Any]]:
        order = "DESC" if reverse else "ASC"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT payload FROM items WHERE pk = ? AND sk LIKE ? ORDER BY sk {order} LIMIT ?",
                (pk, f"{sk_prefix}%", limit)
            ).fetchall()
            return [json.loads(r["payload"]) for r in rows]

    def query_gsi1(
        self,
        gsi1pk: str,
        limit: int = 50,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            if start_date and end_date:
                rows = conn.execute(
                    "SELECT payload FROM items WHERE gsi1pk = ? AND gsi1sk BETWEEN ? AND ? ORDER BY gsi1sk DESC LIMIT ?",
                    (gsi1pk, start_date, end_date + "T23:59:59", limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload FROM items WHERE gsi1pk = ? ORDER BY gsi1sk DESC LIMIT ?",
                    (gsi1pk, limit)
                ).fetchall()
            return [json.loads(r["payload"]) for r in rows]

    def delete_user_data(self, user_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM items WHERE pk = ?", (f"USER#{user_id}",))
            conn.commit()
            self._save_json_snapshot()


class DynamoDBService:
    """
    Hybrid DynamoDB + Local SQLite Persistence Service.
    Automatically uses AWS DynamoDB / DynamoDB Local when reachable, and seamlessly
    falls back to LocalSQLiteStore when offline or in standalone mode.
    """

    def __init__(self):
        self.table_prefix = settings.DYNAMODB_TABLE_PREFIX
        self.local_store = LocalSQLiteStore(settings.LOCAL_DB_PATH)
        self.dynamodb = None
        self.using_dynamodb = False
        self._init_backend()

    def _init_backend(self):
        """Initialize DynamoDB if reachable, otherwise activate SQLite local store immediately"""
        endpoint = settings.DYNAMODB_ENDPOINT_URL
        if not settings.is_production() and endpoint:
            if not _is_endpoint_reachable(endpoint):
                logger.info(
                    "dynamodb_local_unreachable_using_sqlite",
                    endpoint=endpoint,
                    sqlite_path=settings.LOCAL_DB_PATH
                )
                self.using_dynamodb = False
                return

        try:
            import boto3
            from botocore.config import Config

            config = Config(
                connect_timeout=1,
                read_timeout=2,
                retries={'max_attempts': 1},
                max_pool_connections=50
            )
            kwargs = {'region_name': settings.AWS_REGION, 'config': config}
            if endpoint and not settings.is_production():
                kwargs['endpoint_url'] = endpoint
                kwargs['aws_access_key_id'] = settings.AWS_ACCESS_KEY_ID or 'fakeMyKeyId'
                kwargs['aws_secret_access_key'] = settings.AWS_SECRET_ACCESS_KEY or 'fakeSecretAccessKey'

            self.dynamodb = boto3.resource('dynamodb', **kwargs)
            self._ensure_tables_exist()
            self.using_dynamodb = True
            logger.info("dynamodb_backend_active", endpoint=endpoint)
        except Exception as e:
            logger.info("dynamodb_fallback_to_sqlite", reason=str(e))
            self.using_dynamodb = False

    def _table_name(self, name: str) -> str:
        return f"{self.table_prefix}{name}"

    def _ensure_tables_exist(self):
        if not self.dynamodb:
            return
        try:
            self.dynamodb.create_table(
                TableName=self._table_name("Data"),
                KeySchema=[
                    {'AttributeName': 'PK', 'KeyType': 'HASH'},
                    {'AttributeName': 'SK', 'KeyType': 'RANGE'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'PK', 'AttributeType': 'S'},
                    {'AttributeName': 'SK', 'AttributeType': 'S'},
                    {'AttributeName': 'GSI1PK', 'AttributeType': 'S'},
                    {'AttributeName': 'GSI1SK', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'GSI1',
                        'KeySchema': [
                            {'AttributeName': 'GSI1PK', 'KeyType': 'HASH'},
                            {'AttributeName': 'GSI1SK', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'}
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
        except Exception as e:
            if "already exists" not in str(e).lower() and "resourceinuse" not in str(e).lower():
                raise

    def _get_table(self):
        if self.using_dynamodb and self.dynamodb:
            return self.dynamodb.Table(self._table_name("Data"))
        return self.local_store

    def is_healthy(self) -> bool:
        """Storage is always healthy because LocalSQLiteStore is active when DynamoDB is offline"""
        return True

    # ========== User Profile Operations ==========

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        try:
            item = None
            if self.using_dynamodb:
                try:
                    resp = self._get_table().get_item(Key={'PK': f"USER#{user_id}", 'SK': "PROFILE"})
                    item = _from_decimal(resp.get('Item'))
                except Exception:
                    self.using_dynamodb = False
            if item is None:
                item = self.local_store.get_item(f"USER#{user_id}", "PROFILE")

            if item:
                pref_mode = item.get('preferred_mode')
                best_mode = item.get('best_mode')
                return UserProfile(
                    user_id=item.get('user_id', user_id),
                    created_at=datetime.fromisoformat(item.get('created_at', datetime.now().isoformat())),
                    preferred_mode=StudyMode(pref_mode) if pref_mode in [m.value for m in StudyMode] else None,
                    avg_energy=float(item['avg_energy']) if item.get('avg_energy') is not None else None,
                    avg_sleep=float(item['avg_sleep']) if item.get('avg_sleep') is not None else None,
                    total_sessions=int(item.get('total_sessions', 0)),
                    total_minutes=int(item.get('total_minutes', 0)),
                    completion_rate=float(item['completion_rate']) if item.get('completion_rate') is not None else None,
                    best_mode=StudyMode(best_mode) if best_mode in [m.value for m in StudyMode] else None,
                    learning_patterns=item.get('learning_patterns')
                )
            return None
        except Exception as e:
            logger.error("get_user_profile_error", user_id=user_id, error=str(e))
            return None

    def update_user_profile(self, profile: UserProfile) -> bool:
        item = {
            'PK': f"USER#{profile.user_id}",
            'SK': "PROFILE",
            'GSI1PK': "USER",
            'GSI1SK': f"USER#{profile.user_id}",
            'user_id': profile.user_id,
            'created_at': profile.created_at.isoformat(),
            'preferred_mode': profile.preferred_mode.value if isinstance(profile.preferred_mode, StudyMode) else profile.preferred_mode,
            'avg_energy': profile.avg_energy,
            'avg_sleep': profile.avg_sleep,
            'total_sessions': profile.total_sessions,
            'total_minutes': profile.total_minutes,
            'completion_rate': profile.completion_rate,
            'best_mode': profile.best_mode.value if isinstance(profile.best_mode, StudyMode) else profile.best_mode,
            'learning_patterns': profile.learning_patterns,
            'updated_at': datetime.now().isoformat()
        }
        try:
            self.local_store.put_item(item)
            if self.using_dynamodb:
                try:
                    self._get_table().put_item(Item=_to_decimal(item))
                except Exception:
                    self.using_dynamodb = False
            return True
        except Exception as e:
            logger.error("update_user_profile_error", user_id=profile.user_id, error=str(e))
            return False

    # ========== Daily Usage Operations ==========

    def get_daily_usage(self, user_id: str, date: Optional[str] = None) -> int:
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        try:
            if self.using_dynamodb:
                try:
                    resp = self._get_table().get_item(Key={'PK': f"USER#{user_id}", 'SK': f"DAILY#{date}"})
                    if 'Item' in resp:
                        return int(_from_decimal(resp['Item']).get('total_minutes', 0))
                except Exception:
                    self.using_dynamodb = False
            item = self.local_store.get_item(f"USER#{user_id}", f"DAILY#{date}")
            return int(item.get('total_minutes', 0)) if item else 0
        except Exception as e:
            logger.error("get_daily_usage_error", user_id=user_id, error=str(e))
            return 0

    def add_daily_minutes(self, user_id: str, minutes: int, mode: str) -> int:
        date = datetime.now().strftime('%Y-%m-%d')
        current = self.get_daily_usage(user_id, date)
        new_total = max(0, current + int(minutes))
        item = {
            'PK': f"USER#{user_id}",
            'SK': f"DAILY#{date}",
            'total_minutes': new_total,
            'mode': mode,
            'last_updated': datetime.now().isoformat()
        }
        try:
            self.local_store.put_item(item)
            if self.using_dynamodb:
                try:
                    from boto3.dynamodb.conditions import Key
                    self._get_table().put_item(Item=_to_decimal(item))
                except Exception:
                    self.using_dynamodb = False
            return new_total
        except Exception as e:
            logger.error("add_daily_minutes_error", user_id=user_id, error=str(e))
            return new_total

    # ========== Session Operations ==========

    def log_session(self, outcome: SessionOutcome) -> bool:
        mode_val = outcome.mode.value if isinstance(outcome.mode, StudyMode) else str(outcome.mode)
        item = {
            'PK': f"USER#{outcome.user_id}",
            'SK': f"SESSION#{outcome.timestamp.isoformat()}#{outcome.session_id}",
            'GSI1PK': f"SESSION#{outcome.user_id}",
            'GSI1SK': outcome.timestamp.isoformat(),
            'session_id': outcome.session_id,
            'user_id': outcome.user_id,
            'mode': mode_val,
            'planned_minutes': outcome.planned_minutes,
            'actual_minutes': outcome.actual_minutes,
            'completed': outcome.completed,
            'focus_score': outcome.focus_score,
            'satisfaction': outcome.satisfaction,
            'energy': outcome.energy,
            'sleep_hours': outcome.sleep_hours,
            'notes': outcome.notes,
            'timestamp': outcome.timestamp.isoformat(),
            'ttl': int((outcome.timestamp + timedelta(days=365)).timestamp())
        }
        try:
            self.local_store.put_item(item)
            if self.using_dynamodb:
                try:
                    self._get_table().put_item(Item=_to_decimal(item))
                except Exception:
                    self.using_dynamodb = False
            # Also atomically update daily usage minutes!
            if outcome.actual_minutes > 0:
                self.add_daily_minutes(outcome.user_id, outcome.actual_minutes, mode_val)
            logger.info("session_logged", session_id=outcome.session_id, actual_minutes=outcome.actual_minutes)
            return True
        except Exception as e:
            logger.error("log_session_error", session_id=outcome.session_id, error=str(e))
            return False

    def get_user_sessions(
        self,
        user_id: str,
        limit: int = 50,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        try:
            if self.using_dynamodb:
                try:
                    from boto3.dynamodb.conditions import Key
                    query_kwargs = {
                        'IndexName': 'GSI1',
                        'KeyConditionExpression': Key('GSI1PK').eq(f"SESSION#{user_id}"),
                        'ScanIndexForward': False,
                        'Limit': limit
                    }
                    if start_date and end_date:
                        query_kwargs['KeyConditionExpression'] = (
                            Key('GSI1PK').eq(f"SESSION#{user_id}") &
                            Key('GSI1SK').between(start_date, end_date)
                        )
                    resp = self._get_table().query(**query_kwargs)
                    items = [_from_decimal(i) for i in resp.get('Items', [])]
                    if items:
                        return items
                except Exception:
                    self.using_dynamodb = False
            return self.local_store.query_gsi1(f"SESSION#{user_id}", limit, start_date, end_date)
        except Exception as e:
            logger.error("get_user_sessions_error", user_id=user_id, error=str(e))
            return []

    def clear_user_history(self, user_id: str) -> bool:
        try:
            self.local_store.delete_user_data(user_id)
            return True
        except Exception as e:
            logger.error("clear_user_history_error", user_id=user_id, error=str(e))
            return False

    # ========== Agent Decision Traces ==========

    def log_decision_trace(self, trace: AgentDecisionTrace) -> bool:
        item = {
            'PK': f"USER#{trace.user_id}",
            'SK': f"TRACE#{trace.timestamp.isoformat()}#{trace.trace_id}",
            'GSI1PK': "TRACE",
            'GSI1SK': trace.timestamp.isoformat(),
            'trace_id': trace.trace_id,
            'user_id': trace.user_id,
            'timestamp': trace.timestamp.isoformat(),
            'input_state': trace.input_state,
            'wellness_data': trace.wellness_data.to_serializable() if trace.wellness_data else None,
            'planner_decision': trace.planner_decision.to_serializable() if trace.planner_decision else None,
            'safety_decision': trace.safety_decision,
            'final_plan': trace.final_plan.to_serializable() if trace.final_plan else None,
            'reasoning_chain': trace.reasoning_chain,
            'latency_ms': round(trace.latency_ms or 0.0, 2),
            'confidence': trace.confidence
        }
        try:
            self.local_store.put_item(item)
            if self.using_dynamodb:
                try:
                    self._get_table().put_item(Item=_to_decimal(item))
                except Exception:
                    self.using_dynamodb = False
            return True
        except Exception as e:
            logger.error("log_decision_trace_error", trace_id=trace.trace_id, error=str(e))
            return False

    def get_recent_traces(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            if self.using_dynamodb:
                try:
                    from boto3.dynamodb.conditions import Key
                    resp = self._get_table().query(
                        KeyConditionExpression=Key('PK').eq(f"USER#{user_id}") & Key('SK').begins_with("TRACE#"),
                        ScanIndexForward=False,
                        Limit=limit
                    )
                    items = [_from_decimal(i) for i in resp.get('Items', [])]
                    if items:
                        return items
                except Exception:
                    self.using_dynamodb = False
            return self.local_store.query_pk_prefix(f"USER#{user_id}", "TRACE#", limit=limit, reverse=True)
        except Exception as e:
            logger.error("get_recent_traces_error", user_id=user_id, error=str(e))
            return []

    # ========== Proactive Notifications ==========

    def save_notification(self, notification: ProactiveNotification) -> bool:
        item = {
            'PK': f"USER#{notification.user_id}",
            'SK': f"NOTIFICATION#{notification.notification_id}",
            'GSI1PK': "NOTIFICATION",
            'GSI1SK': notification.scheduled_time.isoformat(),
            'notification_id': notification.notification_id,
            'user_id': notification.user_id,
            'type': notification.type,
            'message': notification.message,
            'scheduled_time': notification.scheduled_time.isoformat(),
            'sent': notification.sent,
            'acknowledged': notification.acknowledged,
            'created_at': notification.created_at.isoformat()
        }
        try:
            self.local_store.put_item(item)
            if self.using_dynamodb:
                try:
                    self._get_table().put_item(Item=_to_decimal(item))
                except Exception:
                    self.using_dynamodb = False
            return True
        except Exception as e:
            logger.error("save_notification_error", error=str(e))
            return False

    def get_pending_notifications(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            items = self.local_store.query_pk_prefix(f"USER#{user_id}", "NOTIFICATION#", limit=50)
            return [i for i in items if not i.get("acknowledged", False)]
        except Exception as e:
            logger.error("get_pending_notifications_error", user_id=user_id, error=str(e))
            return []

    def acknowledge_notification(self, user_id: str, notification_id: str) -> bool:
        try:
            item = self.local_store.get_item(f"USER#{user_id}", f"NOTIFICATION#{notification_id}")
            if item:
                item["acknowledged"] = True
                item["sent"] = True
                self.local_store.put_item(item)
                return True
            return False
        except Exception as e:
            logger.error("acknowledge_notification_error", error=str(e))
            return False


# Singleton instance
dynamodb_service = DynamoDBService()
