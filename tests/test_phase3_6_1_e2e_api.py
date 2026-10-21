"""
JARVIS Phase 3.6.1 — End-to-End API Integration Test Suite
Tests real FastAPI application endpoints and WebSocket communication:
- POST /chat with store=true and store=false (verifying memory policy)
- POST /chat/stream (SSE streaming)
- POST /task (task execution & ExecutionContext forwarding)
- WebSocket authenticated chat
- WebSocket interruption of active tasks
- WebSocket confirmation flow (WAITING_FOR_CONFIRMATION -> approve -> task resumes)
- Attacker session isolation (cannot approve victim confirmation)
"""

import json
import time
import pytest
import asyncio
import threading
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from api.server import app, set_server_brain
from api.auth import create_access_token
from api.ws_manager import ws_manager
from core.brain import Brain
from core.memory import JarvisMemory
from core.security import guard, RiskLevel, owner_auth
from core.brain.task_model import ExecutionContext


@pytest.fixture(scope="module")
def api_test_setup():
    """Setup real API client, Brain, Memory, and auth tokens."""
    memory = JarvisMemory()
    brain = Brain(memory=memory)

    # Mock reasoning engine to produce fast deterministic responses without network calls
    brain.reasoning.send_message = MagicMock(return_value="Deterministic response from JARVIS.")
    brain.reasoning.generate_text = MagicMock(return_value="Deterministic response from JARVIS.")
    brain.reasoning._fallback_generate = MagicMock(return_value="Deterministic response from JARVIS.")
    
    def mock_stream_generator(message, system_prompt, raw_message=None, *args, **kwargs):
        yield "Hello "
        yield "world!"
    brain.reasoning.stream_message = mock_stream_generator

    set_server_brain(brain, memory)
    client = TestClient(app)

    token_owner, _ = create_access_token(subject="owner")
    token_attacker, _ = create_access_token(subject="attacker")

    return {
        "client": client,
        "brain": brain,
        "memory": memory,
        "token_owner": token_owner,
        "token_attacker": token_attacker,
    }


def test_api_chat_store_policy(api_test_setup):
    """
    POST /chat:
    - store=false leaves long-term conversational memory unchanged
    - store=true persists conversation turns
    """
    client = api_test_setup["client"]
    memory = api_test_setup["memory"]
    token = api_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Chat with store=False
    last_turn_before = memory.conversations.get_recent(1, user_id="owner")
    resp_false = client.post(
        "/chat",
        json={"message": "Do not store this secret: CODE_SECRET_123", "store": False},
        headers=headers
    )
    assert resp_false.status_code == 200
    assert resp_false.json()["response"] is not None
    last_turn_after = memory.conversations.get_recent(1, user_id="owner")
    assert last_turn_before == last_turn_after, "Conversational memory must NOT change when store=False"

    # 2. Chat with store=True
    resp_true = client.post(
        "/chat",
        json={"message": "Hello Jarvis, please record message: TEST_PERSIST_TURN", "store": True},
        headers=headers
    )
    assert resp_true.status_code == 200
    recent_turns = memory.conversations.get_recent(2, user_id="owner")
    assert any("TEST_PERSIST_TURN" in t["content"] for t in recent_turns), "Conversational memory must persist turn when store=True"


def test_api_chat_stream(api_test_setup):
    """
    POST /chat/stream:
    Verifies Server-Sent Events stream delivering response chunks and [DONE] terminator.
    """
    client = api_test_setup["client"]
    token = api_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/chat/stream",
        json={"message": "Stream this test", "store": False},
        headers=headers
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    lines = [line.strip() for line in resp.text.split("\n") if line.strip()]
    chunks = []
    has_done = False

    for line in lines:
        if line.startswith("data: "):
            payload_str = line[6:]
            if payload_str == "[DONE]":
                has_done = True
            else:
                data = json.loads(payload_str)
                if "chunk" in data:
                    chunks.append(data["chunk"])

    assert has_done is True
    assert len(chunks) > 0


def test_api_execute_task(api_test_setup):
    """
    POST /task:
    Verifies autonomous task execution through real API endpoint,
    confirming ExecutionContext forwarding and TaskResponse structure.
    """
    client = api_test_setup["client"]
    token = api_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/task",
        json={"task": "Run system health check", "store": False},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"] == "Run system health check"
    assert "completed" in data
    assert "steps" in data
    assert len(data["steps"]) >= 1


def test_websocket_authenticated_chat_flow(api_test_setup):
    """
    WebSocket:
    - Connect (read initial status)
    - Send auth command
    - Receive AUTH_SUCCESS
    - Send chat command
    - Receive stream chunks until stream_done
    """
    client = api_test_setup["client"]
    token = api_test_setup["token_owner"]

    with client.websocket_connect("/ws/jarvis") as ws:
        # Initial status from ws_manager.connect
        init_msg = ws.receive_json()
        assert init_msg.get("type") == "status_update"

        # Send authentication
        ws.send_json({"command": "auth", "token": token})
        auth_resp = ws.receive_json()
        assert auth_resp.get("type") == "AUTH_SUCCESS"
        assert auth_resp.get("user") == "owner"

        # Send chat message over authenticated WebSocket
        ws.send_json({"command": "chat", "message": "Hello Jarvis via WS"})
        
        # Read stream events until stream_done
        received_chunks = []
        for _ in range(15):
            msg = ws.receive_json()
            m_type = msg.get("type")
            if m_type == "stream_chunk":
                received_chunks.append(msg.get("chunk"))
            elif m_type in ("stream_done", "stream_end"):
                break

        assert len(received_chunks) > 0


def test_websocket_interrupt_active_task(api_test_setup):
    """
    WebSocket:
    - Connect and authenticate
    - Start an active task in ws_manager
    - Send interrupt command from client
    - Receive TASK_CANCELLED with cancelled=True
    """
    client = api_test_setup["client"]
    token = api_test_setup["token_owner"]

    with client.websocket_connect("/ws/jarvis") as ws:
        # Initial status
        ws.receive_json()

        # Authenticate
        ws.send_json({"command": "auth", "token": token})
        auth_resp = ws.receive_json()
        assert auth_resp.get("type") == "AUTH_SUCCESS"
        session_id = auth_resp.get("session_id")

        # Register a mock active task for this server session
        mock_task = MagicMock()
        mock_task.is_cancelled = False
        def cancel_impl(reason):
            mock_task.is_cancelled = True
        mock_task.cancel = cancel_impl

        ws_manager.register_active_task(session_id, mock_task)

        # Trigger interrupt
        ws.send_json({"command": "interrupt"})
        # Read status/cancelled messages
        resp = ws.receive_json()
        while resp.get("type") == "status_update":
            resp = ws.receive_json()

        assert resp.get("type") == "TASK_CANCELLED"
        assert resp.get("cancelled") is True
        assert mock_task.is_cancelled is True


def test_websocket_confirmation_approval_flow(api_test_setup):
    """
    WebSocket Confirmation Flow:
    - Connect and authenticate
    - A pending confirmation is created
    - The authenticated owner sends confirm command (approved=True)
    - Receives CONFIRMATION_RESULT with success=True
    - The confirmation event is unblocked
    """
    client = api_test_setup["client"]
    token = api_test_setup["token_owner"]

    with client.websocket_connect("/ws/jarvis") as ws:
        # Initial status
        ws.receive_json()

        # Authenticate
        ws.send_json({"command": "auth", "token": token})
        auth_resp = ws.receive_json()
        assert auth_resp.get("type") == "AUTH_SUCCESS"

        session_id = auth_resp.get("session_id")
        user_id = auth_resp.get("user")

        # Create confirmation bound to this session and user
        conf_id, event = guard.create_pending_confirmation(
            tool_name="delete_database",
            args={"db": "test_db"},
            risk_level=RiskLevel.HIGH_RISK,
            session_id=session_id,
            user_id=user_id,
            timeout_sec=10
        )

        # Send approval via authenticated WebSocket
        ws.send_json({
            "command": "confirm",
            "confirmation_id": conf_id,
            "approved": True
        })

        resp = ws.receive_json()
        assert resp.get("type") == "CONFIRMATION_RESULT"
        assert resp.get("success") is True
        assert resp.get("approved") is True
        assert event.is_set()


def test_attacker_cannot_approve_victim_confirmation(api_test_setup):
    """
    Confirmation Security (Attacker Isolation):
    - Victim creates a pending confirmation in session_A
    - Attacker connects on session_B (or another user)
    - Attacker attempts to approve Victim's confirmation
    - Attacker is REJECTED (success=False), and Victim's event remains UNSET.
    """
    client = api_test_setup["client"]
    token_victim = api_test_setup["token_owner"]
    token_attacker = api_test_setup["token_attacker"]

    # Victim creates confirmation
    conf_id, victim_event = guard.create_pending_confirmation(
        tool_name="drop_table",
        args={"table": "users"},
        risk_level=RiskLevel.HIGH_RISK,
        session_id="victim_session_101",
        user_id="victim_user",
        timeout_sec=10
    )

    # Attacker connects and tries to approve
    with client.websocket_connect("/ws/jarvis") as attacker_ws:
        # Initial status
        attacker_ws.receive_json()

        # Authenticate as attacker
        attacker_ws.send_json({"command": "auth", "token": token_attacker})
        auth_resp = attacker_ws.receive_json()
        assert auth_resp.get("type") == "AUTH_SUCCESS"

        attacker_ws.send_json({
            "command": "confirm",
            "confirmation_id": conf_id,
            "approved": True,
            # Attacker even tries to pass spoofed session_id in payload
            "session_id": "victim_session_101"
        })

        resp = attacker_ws.receive_json()
        assert resp.get("type") == "CONFIRMATION_RESULT"
        assert resp.get("success") is False, "Attacker must NOT be allowed to approve Victim's confirmation"
        assert not victim_event.is_set(), "Victim's confirmation event must NEVER be set by an attacker"

    # Clean up
    guard.remove_confirmation(conf_id)


def test_api_chat_stream_store_policy(api_test_setup):
    """
    P1-5 Single-Owner Streaming Persistence:
    POST /chat/stream:
    - store=false streams tokens but produces ZERO conversational or long-term persistence (assert exact counts)
    - store=true streams tokens and persists interaction exactly once
    """
    client = api_test_setup["client"]
    memory = api_test_setup["memory"]
    token = api_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    # Ensure conversation history has headroom below MAX_TURNS (100) to test exact turn count increments
    if len(memory.conversations._turns) >= 80 or memory.conversations.count(user_id="owner") >= 80:
        memory.conversations._turns = memory.conversations._turns[-40:]
        memory.conversations._save()

    # 1. Stream with store=False: Zero persistence
    turns_before = memory.conversations.count(user_id="owner")
    json_before = memory._json_store.count(user_id="owner")
    chroma_before = memory._collection.count() if getattr(memory, "_collection", None) else 0

    resp_false = client.post(
        "/chat/stream",
        json={"message": "Do not store this streaming secret: STREAM_SECRET_999", "store": False},
        headers=headers
    )
    assert resp_false.status_code == 200
    assert memory.conversations.count(user_id="owner") == turns_before, "Conversational turn count must NOT change when stream store=False"
    assert memory._json_store.count(user_id="owner") == json_before, "JSON long-term memory count must NOT change when stream store=False"
    if getattr(memory, "_collection", None):
        assert memory._collection.count() == chroma_before, "ChromaDB memory count must NOT change when stream store=False"

    # 2. Stream with store=True: Exactly one interaction (user + assistant turns) persisted
    resp_true = client.post(
        "/chat/stream",
        json={"message": "Please store this streaming fact: STREAM_PERSIST_123", "store": True},
        headers=headers
    )
    assert resp_true.status_code == 200
    assert memory.conversations.count(user_id="owner") == turns_before + 2, "Conversational memory must persist exactly 2 turns (user + assistant) when stream store=True"
    recent_turns = memory.conversations.get_recent(2, user_id="owner")
    assert any("STREAM_PERSIST_123" in t["content"] for t in recent_turns), "Conversational memory must persist when stream store=True"


def test_rest_confirmation_authorization_and_privacy(api_test_setup):
    """
    P0-2 & P0-3 Confirmation Authorization and Privacy:
    - REST owner approve
    - REST owner deny
    - REST wrong user rejected (403)
    - REST wrong session rejected (403)
    - Expired rejected (403)
    - Unknown rejected (403)
    - Privacy: Two sessions (A and B); A creates confirmation -> A sees it; B does not see it in GET /security/confirmations; B receives no WAITING_FOR_CONFIRMATION event.
    """
    client = api_test_setup["client"]

    # Generate tokens for Session A (user owner), Session B (user owner, different session), and Attacker
    token_a, _ = create_access_token(subject="user_a", session_id="session_alpha")
    token_b, _ = create_access_token(subject="user_b", session_id="session_beta")
    token_wrong_session, _ = create_access_token(subject="user_a", session_id="session_other")
    token_attacker = api_test_setup["token_attacker"]

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    headers_wrong_session = {"Authorization": f"Bearer {token_wrong_session}"}
    headers_attacker = {"Authorization": f"Bearer {token_attacker}"}

    # 1. Session A creates a pending confirmation
    conf_id, event = guard.create_pending_confirmation(
        tool_name="critical_restart",
        args={"force": True},
        risk_level=RiskLevel.CRITICAL,
        session_id="session_alpha",
        user_id="user_a",
        timeout_sec=30
    )

    # 2. Confirmation Privacy (P0-3):
    # Session A sees it in GET /security/confirmations
    resp_list_a = client.get("/security/confirmations", headers=headers_a)
    assert resp_list_a.status_code == 200
    confs_a = resp_list_a.json().get("confirmations", [])
    assert any(c["id"] == conf_id for c in confs_a), "Session A must see its own pending confirmation"

    # Session B does NOT see it in GET /security/confirmations
    resp_list_b = client.get("/security/confirmations", headers=headers_b)
    assert resp_list_b.status_code == 200
    confs_b = resp_list_b.json().get("confirmations", [])
    assert not any(c["id"] == conf_id for c in confs_b), "Session B must NOT see Session A's confirmation"

    # Attacker does NOT see it
    resp_list_att = client.get("/security/confirmations", headers=headers_attacker)
    confs_att = resp_list_att.json().get("confirmations", [])
    assert not any(c["id"] == conf_id for c in confs_att)

    # 3. Wrong user rejected (403)
    resp_wrong_user = client.post(f"/security/confirmations/{conf_id}", json={"approved": True}, headers=headers_b)
    assert resp_wrong_user.status_code == 403
    assert not event.is_set()

    # 4. Wrong session rejected (403)
    resp_wrong_sess = client.post(f"/security/confirmations/{conf_id}", json={"approved": True}, headers=headers_wrong_session)
    assert resp_wrong_sess.status_code == 403
    assert not event.is_set()

    # 5. Attacker rejected (403)
    resp_att = client.post(f"/security/confirmations/{conf_id}", json={"approved": True}, headers=headers_attacker)
    assert resp_att.status_code == 403
    assert not event.is_set()

    # 6. Unknown confirmation rejected (403)
    resp_unknown = client.post("/security/confirmations/conf_nonexistent_999", json={"approved": True}, headers=headers_a)
    assert resp_unknown.status_code == 403

    # 7. Expired confirmation rejected (403)
    expired_id, exp_event = guard.create_pending_confirmation(
        tool_name="quick_expire",
        args={},
        risk_level=RiskLevel.HIGH_RISK,
        session_id="session_alpha",
        user_id="user_a",
        timeout_sec=0
    )
    import time
    time.sleep(0.01)
    resp_exp = client.post(f"/security/confirmations/{expired_id}", json={"approved": True}, headers=headers_a)
    assert resp_exp.status_code == 403

    # 8. REST owner approve
    resp_approve = client.post(f"/security/confirmations/{conf_id}", json={"approved": True}, headers=headers_a)
    assert resp_approve.status_code == 200
    assert event.is_set()
    assert guard._pending_confirmations[conf_id]["approved"] is True

    # 9. REST owner deny (separate confirmation)
    conf_id_deny, event_deny = guard.create_pending_confirmation(
        tool_name="critical_deny_tool",
        args={},
        risk_level=RiskLevel.HIGH_RISK,
        session_id="session_alpha",
        user_id="user_a",
        timeout_sec=30
    )
    resp_deny = client.post(f"/security/confirmations/{conf_id_deny}", json={"approved": False}, headers=headers_a)
    assert resp_deny.status_code == 200
    assert event_deny.is_set()
    assert guard._pending_confirmations[conf_id_deny]["approved"] is False

    # Cleanup
    guard.remove_confirmation(conf_id)
    guard.remove_confirmation(conf_id_deny)


def test_rest_task_interrupt_ownership(api_test_setup):
    """
    P0-4 REST Task Ownership:
    1. Session A cancels its own task successfully.
    2. User B cannot cancel User A's task (403).
    3. A second session belonging to the same user cannot cancel Session A's task if it does not own that task (403).
    4. Supplying another task's ID and spoofing its session ID is rejected (403).
    5. Unknown task cancels nothing (200 with clear message, no event set).
    6. Cancelling A leaves B running.
    """
    client = api_test_setup["client"]

    token_a, _ = create_access_token(subject="user_a", session_id="session_a")
    token_a_other_session, _ = create_access_token(subject="user_a", session_id="session_a_2")
    token_b, _ = create_access_token(subject="user_b", session_id="session_b")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_a_other = {"Authorization": f"Bearer {token_a_other_session}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    import threading
    event_a = threading.Event()
    event_b = threading.Event()

    task_a = type("MockTask", (), {"cancellation_token": event_a, "task_id": "task_a_id", "user_id": "user_a", "session_id": "session_a"})()
    task_b = type("MockTask", (), {"cancellation_token": event_b, "task_id": "task_b_id", "user_id": "user_b", "session_id": "session_b"})()

    ws_manager.register_active_task("session_a", task_a, task_id="task_a_id", user_id="user_a")
    ws_manager.register_active_task("session_b", task_b, task_id="task_b_id", user_id="user_b")

    try:
        # 5. Unknown task -> nothing cancelled
        resp_unknown = client.post("/tasks/interrupt", json={"task_id": "unknown_task_123"}, headers=headers_a)
        assert resp_unknown.status_code == 200
        assert "No active task found" in resp_unknown.json()["message"]
        assert not event_a.is_set()
        assert not event_b.is_set()

        # 2. User B cannot cancel User A's task by task_id -> 403 Forbidden
        resp_b_cancels_a = client.post("/tasks/interrupt", json={"task_id": "task_a_id"}, headers=headers_b)
        assert resp_b_cancels_a.status_code == 403
        assert not event_a.is_set()

        # 3. Same user but DIFFERENT session cannot cancel Session A's task -> 403 Forbidden
        resp_same_user_diff_session = client.post("/tasks/interrupt", json={"task_id": "task_a_id"}, headers=headers_a_other)
        assert resp_same_user_diff_session.status_code == 403
        assert not event_a.is_set()

        # 4. Supplying another task's ID and spoofing its session ID is rejected -> 403 Forbidden
        resp_spoof = client.post(
            "/tasks/interrupt",
            json={"task_id": "task_b_id", "session_id": "session_b"},
            headers=headers_a
        )
        assert resp_spoof.status_code == 403
        assert not event_b.is_set()

        # 1 & 6. Session A cancels its own task successfully; B remains running
        resp_a_cancels_a = client.post("/tasks/interrupt", json={"task_id": "task_a_id"}, headers=headers_a)
        assert resp_a_cancels_a.status_code == 200
        assert event_a.is_set()
        assert not event_b.is_set(), "Cancelling A must leave B running untouched"

    finally:
        ws_manager.unregister_active_task("session_a")
        ws_manager.unregister_active_task("session_b")
        ws_manager.unregister_active_task("task_a_id")
        ws_manager.unregister_active_task("task_b_id")


def test_websocket_two_session_private_event_isolation(api_test_setup):
    """
    P0-3 Two-Session WebSocket Private Event Isolation:
    - Session A connects and authenticates.
    - Session B connects and authenticates.
    - Session A streams a private message.
    - Session A receives its own chunks and stream_done.
    - Session B receives NO chunks, task descriptions, results, or private cancellation events from Session A.
    - Session A registers an active task and cancels it -> Session A receives TASK_CANCELLED.
    - Session B receives NO cancellation event.
    """
    client = api_test_setup["client"]
    token_a, _ = create_access_token(subject="user_a", session_id="session_alpha")
    token_b, _ = create_access_token(subject="user_b", session_id="session_beta")

    with client.websocket_connect("/ws/jarvis") as ws_a:
        with client.websocket_connect("/ws/jarvis") as ws_b:
            # Drain initial status updates
            init_a = ws_a.receive_json()
            assert init_a.get("type") == "status_update"
            init_b = ws_b.receive_json()
            assert init_b.get("type") == "status_update"

            # Authenticate Session A
            ws_a.send_json({"command": "auth", "token": token_a})
            auth_a = ws_a.receive_json()
            assert auth_a.get("type") == "AUTH_SUCCESS"
            session_a = auth_a.get("session_id")

            # Authenticate Session B
            ws_b.send_json({"command": "auth", "token": token_b})
            auth_b = ws_b.receive_json()
            assert auth_b.get("type") == "AUTH_SUCCESS"
            session_b = auth_b.get("session_id")

            # Session B's receive stream buffer must be clear
            assert ws_b._send_rx.statistics().current_buffer_used == 0

            # 1. Session A streams a private chat message
            ws_a.send_json({"command": "chat", "message": "Secret stream payload for Session A"})

            # Session A receives its stream chunks and completion
            chunks_a = []
            for _ in range(15):
                msg_a = ws_a.receive_json()
                if msg_a.get("type") == "stream_chunk":
                    chunks_a.append(msg_a.get("chunk"))
                elif msg_a.get("type") in ("stream_done", "stream_end"):
                    break
            assert len(chunks_a) > 0

            # Verify Session B receives NO stream chunks or private stream events
            import anyio
            messages_b = []
            while ws_b._send_rx.statistics().current_buffer_used > 0:
                try:
                    msg_b = ws_b.receive_json()
                    messages_b.append(msg_b)
                except anyio.WouldBlock:
                    break

            for msg in messages_b:
                m_type = msg.get("type")
                assert m_type not in ("stream_chunk", "stream_done", "stream_end"), f"Session B received stream event: {msg}"
                assert "Secret stream payload for Session A" not in json.dumps(msg)

            # 2. Session A registers an active task and cancels it
            import threading
            task_a_cancel = threading.Event()
            class MockTaskA:
                cancellation_token = task_a_cancel
                task_id = "priv_task_a"
                user_id = "user_a"
                session_id = session_a
                is_cancelled = False
                def cancel(self, reason=""):
                    self.is_cancelled = True
                    task_a_cancel.set()
            mock_task_a = MockTaskA()
            ws_manager.register_active_task(session_a, mock_task_a, task_id="priv_task_a", user_id="user_a")

            ws_a.send_json({"command": "interrupt"})
            # Session A reads cancelled event
            cancel_msg_a = ws_a.receive_json()
            while cancel_msg_a.get("type") == "status_update":
                cancel_msg_a = ws_a.receive_json()
            assert cancel_msg_a.get("type") == "TASK_CANCELLED"
            assert cancel_msg_a.get("cancelled") is True

            # Verify Session B receives NO cancellation event
            cancel_messages_b = []
            while ws_b._send_rx.statistics().current_buffer_used > 0:
                try:
                    msg_b = ws_b.receive_json()
                    cancel_messages_b.append(msg_b)
                except anyio.WouldBlock:
                    break

            for msg in cancel_messages_b:
                assert msg.get("type") != "TASK_CANCELLED", "Session B received unexpected TASK_CANCELLED event"
                assert "priv_task_a" not in json.dumps(msg)

            ws_manager.unregister_active_task(session_a)


def test_api_task_status_truth_and_task_id(api_test_setup):
    """
    P0-6 Task Status Truth API validation:
    Verifies that POST /task returns the real task_id and appropriate status mappings.
    """
    client = api_test_setup["client"]
    token = api_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/task",
        json={"task": "Inspect system memory and CPU", "store": False},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["task_id"] is not None
    assert "status" in data
    assert data["completed"] is True
    assert data["status"] == "success"


def test_api_task_status_truth_mappings_endpoint(api_test_setup):
    """
    P1-6 Task Status Truth API validation (API integration with a test double):
    Tests POST /task for every required status mapping using a mocked execution double:
    - TaskStatus.COMPLETED -> completed=True, status="success"
    - TaskStatus.CANCELLED -> completed=False, status="cancelled"
    - TaskStatus.FAILED -> completed=False, status="failed"
    - TaskStatus.WAITING_FOR_INPUT -> completed=False, status="waiting_for_input"
    - TaskStatus.WAITING_FOR_CONFIRMATION -> completed=False, status="waiting_for_confirmation"
    - TaskStatus.TIMED_OUT -> completed=False, status="timed_out"
    - Unknown/missing status -> completed=False, status="failed" (NEVER defaults to success)
    """
    client = api_test_setup["client"]
    brain = api_test_setup["brain"]
    token = api_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    from core.brain.task_model import TaskStatus, AssistantTask

    orig_execute = brain.execute_task

    test_cases = [
        (TaskStatus.COMPLETED, True, "success"),
        (TaskStatus.CANCELLED, False, "cancelled"),
        (TaskStatus.FAILED, False, "failed"),
        (TaskStatus.WAITING_FOR_INPUT, False, "waiting_for_input"),
        (TaskStatus.WAITING_FOR_CONFIRMATION, False, "waiting_for_confirmation"),
        (TaskStatus.TIMED_OUT, False, "timed_out"),
        (TaskStatus.PLANNING, False, "failed"),  # Non-terminal state
        (None, False, "failed"),  # Missing status
    ]

    try:
        for status_enum, expected_completed, expected_status_str in test_cases:
            def mock_execute(task_str, store, ctx):
                t = AssistantTask(user_request=task_str)
                if status_enum is not None:
                    t.status = status_enum
                else:
                    t.status = None
                ctx.task = t
                return f"Outcome for {status_enum}"

            brain.execute_task = mock_execute

            resp = client.post(
                "/task",
                json={"task": f"Test status {status_enum}", "store": False},
                headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["completed"] == expected_completed, f"Failed completed for {status_enum}: got {data['completed']}"
            assert data["status"] == expected_status_str, f"Failed status for {status_enum}: got {data['status']}"
    finally:
        brain.execute_task = orig_execute


# ─── P0-2: Real Two-Session DAG Cancellation Path & No-Session Fallback ───────

def test_two_session_orchestrator_dag_cancellation_isolation(api_test_setup):
    """
    P0-2: Real two-session test exercising AssistantOrchestrator._execute_plan_dag cancellation path:
    - Session A cancels a running DAG task.
    - Session A receives TASK_CANCELLED event.
    - Session B receives NO TASK_CANCELLED event and NO private task identifier.
    - Also verifies no-session fallback path does not broadcast private content.
    """
    client = api_test_setup["client"]
    token_a, _ = create_access_token(subject="user_a", session_id="dag_session_a")
    token_b, _ = create_access_token(subject="user_b", session_id="dag_session_b")

    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import AssistantTask, TaskStatus, TaskStep

    with client.websocket_connect("/ws/jarvis") as ws_a:
        with client.websocket_connect("/ws/jarvis") as ws_b:
            init_a = ws_a.receive_json()
            init_b = ws_b.receive_json()

            ws_a.send_json({"command": "auth", "token": token_a})
            auth_a = ws_a.receive_json()
            session_a = auth_a.get("session_id")

            ws_b.send_json({"command": "auth", "token": token_b})
            auth_b = ws_b.receive_json()
            session_b = auth_b.get("session_id")

            orch = AssistantOrchestrator()
            task_a = AssistantTask(
                task_id="private_dag_task_a_id",
                user_request="Private task A",
                session_id=session_a,
                status=TaskStatus.EXECUTING,
                plan=[TaskStep(step_id="step_1", description="Step 1")]
            )
            # Cooperatively cancel task A before DAG execution loop
            task_a.cancel("USER_STOP_DAG")

            # Run DAG loop for task_a
            orch._execute_plan_dag(task_a, "Private task A")

            # Session A should receive TASK_CANCELLED
            cancel_msg_a = ws_a.receive_json()
            while cancel_msg_a.get("type") == "status_update":
                cancel_msg_a = ws_a.receive_json()

            assert cancel_msg_a.get("type") == "TASK_CANCELLED", f"Expected TASK_CANCELLED, got {cancel_msg_a}"
            assert cancel_msg_a.get("task_id") == "private_dag_task_a_id"

            # Session B must receive ZERO cancellation events and NO private task id
            received_b = []
            while ws_b._send_rx.statistics().current_buffer_used > 0:
                msg = ws_b.receive_json()
                received_b.append(msg)

            for msg in received_b:
                assert msg.get("type") != "TASK_CANCELLED"
                assert "private_dag_task_a_id" not in json.dumps(msg)

            # Test no-session fallback path
            task_no_session = AssistantTask(
                task_id="un_sessioned_task_id",
                user_request="Un-sessioned task",
                session_id=None,
                status=TaskStatus.EXECUTING,
                plan=[TaskStep(step_id="step_1", description="Step 1")]
            )
            task_no_session.cancel("STOP_NO_SESSION")
            # Must execute safely without throwing and without broadcasting
            orch._execute_plan_dag(task_no_session, "Un-sessioned task")

            # Confirm again that WS A and WS B received no broadcast for un-sessioned task
            while ws_a._send_rx.statistics().current_buffer_used > 0:
                m = ws_a.receive_json()
                assert "un_sessioned_task_id" not in json.dumps(m)

            while ws_b._send_rx.statistics().current_buffer_used > 0:
                m = ws_b.receive_json()
                assert "un_sessioned_task_id" not in json.dumps(m)


# ─── P0-3: Make Returned Task ID Actually Interruptable ───────────────────────

def test_api_task_endpoint_returned_id_interruptable(api_test_setup):
    """
    P0-3 Endpoint-level integration test:
    1. Submit a long-running task through POST /task.
    2. Obtain the task_id from actual TaskResponse / registered execution metadata.
    3. Interrupt using that exact returned task_id.
    4. Verify only the expected cancellation token is set.
    5. Verify the task reaches CANCELLED.
    6. Verify any other session/task remains active.
    """
    client = api_test_setup["client"]
    brain = api_test_setup["brain"]

    token_a, _ = create_access_token(subject="user_a", session_id="session_long_a")
    token_b, _ = create_access_token(subject="user_b", session_id="session_long_b")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Setup Session B with an active task
    event_b = threading.Event()
    task_b = type("MockTaskB", (), {"cancellation_token": event_b, "task_id": "task_b_other", "user_id": "user_b", "session_id": "session_long_b"})()
    ws_manager.register_active_task("session_long_b", task_b, task_id="task_b_other", user_id="user_b")

    entered_task = threading.Event()
    orig_execute = brain.execute_task

    def mock_long_execute(task_str, store, ctx):
        # Notify test that task has started and registered
        entered_task.set()
        # Wait until test signals interruption or timeout
        cancelled = ctx.cancellation_token.wait(timeout=3.0)
        from core.brain.task_model import AssistantTask, TaskStatus
        task_obj = AssistantTask(
            task_id=ctx.task_id or ctx.request_id,
            user_request=task_str,
            status=TaskStatus.CANCELLED if cancelled else TaskStatus.COMPLETED
        )
        ctx.task = task_obj
        if cancelled:
            return "Task was cancelled."
        return "Task completed."

    brain.execute_task = mock_long_execute

    task_response_holder = {}

    def run_post_task():
        resp = client.post(
            "/task",
            json={"task": "Long running autonomous task", "store": False},
            headers=headers_a
        )
        task_response_holder["resp"] = resp

    worker = threading.Thread(target=run_post_task)
    worker.start()

    try:
        assert entered_task.wait(timeout=2.0), "Task did not start in time"

        # 2. Obtain the registered task metadata for Session A
        meta_a = ws_manager.get_task_metadata("session_long_a")
        assert meta_a is not None, "Task must be registered in ws_manager"
        registered_task_id = meta_a.get("task_id")
        assert registered_task_id is not None

        # 3. Interrupt using that exact returned/registered task_id
        resp_interrupt = client.post(
            "/tasks/interrupt",
            json={"task_id": registered_task_id},
            headers=headers_a
        )
        assert resp_interrupt.status_code == 200
        assert "cancellation signalled" in resp_interrupt.json()["message"].lower()

        # Wait for POST /task to return
        worker.join(timeout=3.0)
        assert "resp" in task_response_holder
        resp = task_response_holder["resp"]
        assert resp.status_code == 200
        data = resp.json()

        # 4 & 5. Verify the returned task_id matches, and task reaches CANCELLED
        assert data["task_id"] == registered_task_id
        assert data["completed"] is False
        assert data["status"] == "cancelled"

        # 6. Verify Session B remained untouched
        assert not event_b.is_set(), "Session B's task must remain untouched"
    finally:
        brain.execute_task = orig_execute
        ws_manager.unregister_active_task("session_long_b")
        ws_manager.unregister_active_task("task_b_other")


# ─── P0-4: Enforce Task History Ownership ─────────────────────────────────────

def test_api_task_history_ownership_enforcement(api_test_setup):
    """
    P0-4 Task History Ownership:
    - Owner can retrieve their own task history.
    - Owner can retrieve their own task details.
    - Different user cannot retrieve the task (403 Forbidden).
    - Different session cannot retrieve the task when session ownership is required (403 Forbidden).
    - History contains no records belonging to another owner.
    """
    client = api_test_setup["client"]
    token_owner, _ = create_access_token(subject="user_history_owner", session_id="session_hist_1")
    token_other_sess, _ = create_access_token(subject="user_history_owner", session_id="session_hist_2")
    token_stranger, _ = create_access_token(subject="user_stranger", session_id="session_stranger")

    headers_owner = {"Authorization": f"Bearer {token_owner}"}
    headers_other_sess = {"Authorization": f"Bearer {token_other_sess}"}
    headers_stranger = {"Authorization": f"Bearer {token_stranger}"}

    from core.brain.task_store import task_store
    from core.brain.task_model import AssistantTask, TaskStatus

    task_1 = AssistantTask(
        task_id="task_owner_hist_001",
        user_request="Owner request 1",
        user_id="user_history_owner",
        session_id="session_hist_1",
        status=TaskStatus.COMPLETED
    )
    task_2 = AssistantTask(
        task_id="task_stranger_hist_002",
        user_request="Stranger request 2",
        user_id="user_stranger",
        session_id="session_stranger",
        status=TaskStatus.COMPLETED
    )

    task_store.save_task(task_1)
    task_store.save_task(task_2)

    # 1. Owner can retrieve their own task history
    resp_hist_owner = client.get("/tasks/history", headers=headers_owner)
    assert resp_hist_owner.status_code == 200
    owner_tasks = resp_hist_owner.json()["tasks"]
    task_ids = [t["task_id"] for t in owner_tasks]
    assert "task_owner_hist_001" in task_ids
    # 5. History contains no records belonging to another owner
    assert "task_stranger_hist_002" not in task_ids

    # 2. Owner can retrieve their own task details
    resp_detail_owner = client.get("/tasks/task_owner_hist_001", headers=headers_owner)
    assert resp_detail_owner.status_code == 200
    assert resp_detail_owner.json()["task_id"] == "task_owner_hist_001"

    # 3. Different user cannot retrieve the task (403)
    resp_detail_stranger = client.get("/tasks/task_owner_hist_001", headers=headers_stranger)
    assert resp_detail_stranger.status_code == 403

    # 4. Different session cannot retrieve the task (403)
    resp_detail_other_sess = client.get("/tasks/task_owner_hist_001", headers=headers_other_sess)
    assert resp_detail_other_sess.status_code == 403

    # 5. Record with missing user_id is rejected (403)
    task_no_user = AssistantTask(
        task_id="task_missing_user_003",
        user_request="Legacy missing user request",
        user_id=None,
        session_id="session_hist_1",
        status=TaskStatus.COMPLETED
    )
    task_store.save_task(task_no_user)
    resp_no_user = client.get("/tasks/task_missing_user_003", headers=headers_owner)
    assert resp_no_user.status_code == 403
    assert "missing or incomplete" in resp_no_user.json()["detail"].lower()

    # 6. Record with missing session_id is rejected (403)
    task_no_sess = AssistantTask(
        task_id="task_missing_sess_004",
        user_request="Legacy missing session request",
        user_id="user_history_owner",
        session_id=None,
        status=TaskStatus.COMPLETED
    )
    task_store.save_task(task_no_sess)
    resp_no_sess = client.get("/tasks/task_missing_sess_004", headers=headers_owner)
    assert resp_no_sess.status_code == 403
    assert "missing or incomplete" in resp_no_sess.json()["detail"].lower()

    # Stranger history contains only stranger's tasks (legacy missing ownership records are excluded)
    resp_hist_stranger = client.get("/tasks/history", headers=headers_stranger)
    assert resp_hist_stranger.status_code == 200
    stranger_task_ids = [t["task_id"] for t in resp_hist_stranger.json()["tasks"]]
    assert "task_stranger_hist_002" in stranger_task_ids
    assert "task_owner_hist_001" not in stranger_task_ids
    assert "task_missing_user_003" not in stranger_task_ids
    assert "task_missing_sess_004" not in stranger_task_ids


# ─── P1-4: Stream Interruption and Failure States ─────────────────────────────

def test_stream_interruption_and_failure_states(api_test_setup):
    """
    P1-4:
    - Successful stream + store=true persists exactly once.
    - Successful stream + store=false persists nothing.
    - Mid-stream interrupt -> CANCELLED, no successful-completion persistence.
    - Stream exception -> FAILED, no successful-completion persistence.
    - Missing reasoning engine -> FAILED, no successful-completion persistence.
    - Abnormal stream termination (no clean completion signal) -> FAILED.
    """
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext, TaskStatus
    from core.memory import JarvisMemory
    from core.brain.memory_manager import MemoryManager
    from core.brain.streaming_manager import StreamingManager

    mem = JarvisMemory()
    mem_mgr = MemoryManager(memory=mem)

    class MockStreamingBrain:
        def __init__(self, reasoning=None):
            self.memory_manager = mem_mgr
            self._model_name = "test-model"
            self.reasoning = reasoning
            self.streaming = StreamingManager(reasoning_engine=reasoning)
            self.context = self
            self.intent_classifier = None
            self.tools = None

        def _get_system_prompt(self, **kwargs):
            return "System prompt"

        async def build_enriched_prompt(self, user_text):
            return user_text

    interrupt_signal = threading.Event()

    class MockEngine:
        def stream_message(self, prompt, system_prompt, raw_message=None):
            if "fail_me" in raw_message:
                raise RuntimeError("Mock stream engine explosion")
            for w in ["Hello", " dear", " user"]:
                if "interrupt_after_first" in raw_message and w == " dear":
                    interrupt_signal.set()
                yield w

    mock_brain_ok = MockStreamingBrain(reasoning=MockEngine())
    orch_ok = AssistantOrchestrator(memory_manager=mem_mgr)
    orch_ok.set_brain(mock_brain_ok)

    mock_brain_no_engine = MockStreamingBrain(reasoning=None)
    orch_no_engine = AssistantOrchestrator(memory_manager=mem_mgr)
    orch_no_engine.set_brain(mock_brain_no_engine)

    async def _run_tests():
        # 1. Successful stream + store=true persists exactly once
        ctx_store_true = ExecutionContext(store_memory=True, session_id="s_true", user_id="owner")
        chunks_true = []
        async for chunk in orch_ok.process_stream("My favorite drink is Earl Grey tea", context=ctx_store_true):
            chunks_true.append(chunk)

        assert "".join(chunks_true) == "Hello dear user"
        assert ctx_store_true.task.status == TaskStatus.COMPLETED
        turns = mem.conversations.get_recent(2, user_id="owner")
        assert len(turns) == 2
        assert turns[-1]["content"] == "Hello dear user"
        assert "Earl Grey tea" in turns[-2]["content"]

        # 2. Successful stream + store=false persists nothing
        turns_count_before = mem.conversations.count(user_id="owner")
        ctx_store_false = ExecutionContext(store_memory=False, session_id="s_false", user_id="owner")
        chunks_false = []
        async for chunk in orch_ok.process_stream("My secret PIN is 8844", context=ctx_store_false):
            chunks_false.append(chunk)

        assert "".join(chunks_false) == "Hello dear user"
        assert ctx_store_false.task.status == TaskStatus.COMPLETED
        assert mem.conversations.count(user_id="owner") == turns_count_before

        # 3. Mid-stream interrupt -> CANCELLED, no successful-completion persistence
        interrupt_signal.clear()
        ctx_interrupt = ExecutionContext(store_memory=True, session_id="s_int", cancellation_token=interrupt_signal, user_id="owner")
        chunks_int = []
        async for chunk in orch_ok.process_stream("interrupt_after_first message", interrupt_event=interrupt_signal, context=ctx_interrupt):
            chunks_int.append(chunk)

        assert ctx_interrupt.task.status == TaskStatus.CANCELLED
        assert mem.conversations.count(user_id="owner") == turns_count_before, "Cancelled stream must not persist to memory"

        # 4. Stream exception -> FAILED, no successful-completion persistence
        ctx_fail = ExecutionContext(store_memory=True, session_id="s_fail", user_id="owner")
        chunks_fail = []
        async for chunk in orch_ok.process_stream("fail_me now", context=ctx_fail):
            chunks_fail.append(chunk)

        assert ctx_fail.task.status == TaskStatus.FAILED
        assert mem.conversations.count(user_id="owner") == turns_count_before, "Failed stream must not persist to memory"

        # 5. Missing reasoning engine -> FAILED
        ctx_no_engine = ExecutionContext(store_memory=True, session_id="s_no_eng", user_id="owner")
        chunks_no_eng = []
        async for chunk in orch_no_engine.process_stream("hello without engine", context=ctx_no_engine):
            chunks_no_eng.append(chunk)

        assert ctx_no_engine.task.status == TaskStatus.FAILED
        assert "No reasoning engine" in ctx_no_engine.stream_error
        assert mem.conversations.count(user_id="owner") == turns_count_before

        # 6. Abnormal stream termination without clean completion signal -> FAILED
        class MockAbnormalBrain:
            def __init__(self):
                self.memory_manager = mem_mgr
                self._model_name = "test-model"
                self.streaming = self
                self.context = self
                self.intent_classifier = None
                self.reasoning = None
                self.tools = None

            def _get_system_prompt(self, **kwargs):
                return "System prompt"

            async def build_enriched_prompt(self, user_text):
                return user_text

            async def stream_response(self, text, enriched, sys_prompt, interrupt_event=None, store_memory=False, context=None):
                yield "Partial token only"
                # Does NOT set context.stream_completed = True

        mock_abnormal = MockAbnormalBrain()
        orch_abnormal = AssistantOrchestrator(memory_manager=mem_mgr)
        orch_abnormal.set_brain(mock_abnormal)

        ctx_abnormal = ExecutionContext(store_memory=True, session_id="s_abnormal", user_id="owner")
        async for chunk in orch_abnormal.process_stream("abnormal stream test", context=ctx_abnormal):
            pass

        assert ctx_abnormal.task.status == TaskStatus.FAILED
        assert "clean completion" in ctx_abnormal.task.error.lower()
        assert mem.conversations.count(user_id="owner") == turns_count_before

    asyncio.run(_run_tests())


# ─── P0-2: ToolRouter Private Event Isolation Test ────────────────────────────

def test_tool_router_no_broadcast_fallback_with_two_sessions(api_test_setup):
    """
    P0-2 ToolRouter Private Event Isolation:
    - Two WebSocket clients connect and authenticate (Session A and Session B).
    - ToolRouter executes a tool without an owning session.
    - Neither client receives the private tool-execution event.
    - ToolRouter executes a tool with Session A's context.
    - Session A receives the private event; Session B receives nothing.
    """
    client = api_test_setup["client"]
    token_a, _ = create_access_token(subject="user_a", session_id="session_alpha_tool")
    token_b, _ = create_access_token(subject="user_b", session_id="session_beta_tool")

    from core.brain.tool_router import ToolRouter
    from core.brain.task_model import current_execution_context, ExecutionContext
    import anyio

    router = ToolRouter()
    def sample_dummy_tool(param: str = "val"):
        return f"result_{param}"
    router.register_callable(sample_dummy_tool, name="sample_dummy_tool", category="custom")

    with client.websocket_connect("/ws/jarvis") as ws_a:
        with client.websocket_connect("/ws/jarvis") as ws_b:
            # Drain initial status updates
            ws_a.receive_json()
            ws_b.receive_json()

            # Authenticate Session A
            ws_a.send_json({"command": "auth", "token": token_a})
            auth_a = ws_a.receive_json()
            session_a = auth_a.get("session_id")

            # Authenticate Session B
            ws_b.send_json({"command": "auth", "token": token_b})
            auth_b = ws_b.receive_json()
            session_b = auth_b.get("session_id")

            # Drain any auth status messages
            while ws_a._send_rx.statistics().current_buffer_used > 0:
                ws_a.receive_json()
            while ws_b._send_rx.statistics().current_buffer_used > 0:
                ws_b.receive_json()

            # 1. Execute tool without an owning session
            ctx_none = ExecutionContext(session_id=None)
            tok_none = current_execution_context.set(ctx_none)
            try:
                res1 = router.execute_tool("sample_dummy_tool", {"param": "secret_no_session"}, interactive=False)
                assert res1.success is True
            finally:
                current_execution_context.reset(tok_none)

            # Neither client receives private tool execution event
            msgs_a_no_sess = []
            while ws_a._send_rx.statistics().current_buffer_used > 0:
                try:
                    msgs_a_no_sess.append(ws_a.receive_json())
                except anyio.WouldBlock:
                    break
            msgs_b_no_sess = []
            while ws_b._send_rx.statistics().current_buffer_used > 0:
                try:
                    msgs_b_no_sess.append(ws_b.receive_json())
                except anyio.WouldBlock:
                    break

            for m in msgs_a_no_sess + msgs_b_no_sess:
                assert m.get("event_type") != "tool_executing", f"Client received un-sessioned tool execution event: {m}"
                assert "secret_no_session" not in json.dumps(m)

            # 2. Execute tool targeted to Session A
            ctx_a = ExecutionContext(session_id=session_a)
            tok_a = current_execution_context.set(ctx_a)
            try:
                res2 = router.execute_tool("sample_dummy_tool", {"param": "secret_session_a"}, interactive=False)
                assert res2.success is True
            finally:
                current_execution_context.reset(tok_a)

            # Session A receives the tool_executing event
            msg_a_target = ws_a.receive_json()
            assert msg_a_target.get("type") == "execution_event"
            assert msg_a_target.get("event_type") == "tool_executing"
            assert msg_a_target.get("tool") == "sample_dummy_tool"
            assert "secret_session_a" in msg_a_target.get("args")

            # Session B must receive NOTHING
            assert ws_b._send_rx.statistics().current_buffer_used == 0


# ─── P1-5: Two-Session Shared Chat History Ownership Review ───────────────────

def test_two_session_chat_history_isolation(api_test_setup):
    """
    P1-5: Shared Chat History Ownership Review:
    - Session A sends a chat message with store=True.
    - Session B sends a chat message with store=True.
    - Session A GET /history retrieves ONLY Session A's messages.
    - Session B GET /history retrieves ONLY Session B's messages.
    - Session A DELETE /history clears ONLY Session A's history.
    - Session B GET /history verifies Session B's history is STILL intact.
    """
    client = api_test_setup["client"]
    token_a, _ = create_access_token(subject="user_chat_a", session_id="sess_chat_a")
    token_b, _ = create_access_token(subject="user_chat_b", session_id="sess_chat_b")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Clear any previous turns for clean test baseline
    client.delete("/history", headers=headers_a)
    client.delete("/history", headers=headers_b)

    # 1. Session A chats
    resp_chat_a = client.post(
        "/chat",
        json={"message": "Message from Session Alpha: ALPHA_SECRET_999", "store": True},
        headers=headers_a
    )
    assert resp_chat_a.status_code == 200

    # 2. Session B chats
    resp_chat_b = client.post(
        "/chat",
        json={"message": "Message from Session Beta: BETA_SECRET_777", "store": True},
        headers=headers_b
    )
    assert resp_chat_b.status_code == 200

    # 3. Session A gets history: sees Alpha, NOT Beta
    hist_a = client.get("/history", headers=headers_a)
    assert hist_a.status_code == 200
    turns_a = hist_a.json()["turns"]
    contents_a = [t["content"] for t in turns_a]
    assert any("ALPHA_SECRET_999" in c for c in contents_a)
    assert not any("BETA_SECRET_777" in c for c in contents_a), "Session A must not see Session B's history"

    # 4. Session B gets history: sees Beta, NOT Alpha
    hist_b = client.get("/history", headers=headers_b)
    assert hist_b.status_code == 200
    turns_b = hist_b.json()["turns"]
    contents_b = [t["content"] for t in turns_b]
    assert any("BETA_SECRET_777" in c for c in contents_b)
    assert not any("ALPHA_SECRET_999" in c for c in contents_b), "Session B must not see Session A's history"

    # 5. Session A clears history
    del_a = client.delete("/history", headers=headers_a)
    assert del_a.status_code == 200

    # Session A history is empty
    hist_a_after = client.get("/history", headers=headers_a)
    assert hist_a_after.status_code == 200
    assert len(hist_a_after.json()["turns"]) == 0

    # 6. Session B history is STILL INTACT
    hist_b_after = client.get("/history", headers=headers_b)
    assert hist_b_after.status_code == 200
    turns_b_after = hist_b_after.json()["turns"]
    assert any("BETA_SECRET_777" in t["content"] for t in turns_b_after), "Session A must not clear Session B's history"


# ─── P0-2: Authenticate WebSocket State-Changing Commands ─────────────────────

def test_websocket_unauthenticated_interrupt_and_voice_protection(api_test_setup):
    """
    P0-2: Authenticate WebSocket state-changing commands:
    1. Unauthenticated interrupt returns AUTH_FAILED error, does not cancel any task,
       does not stop voice playback, and does not send TASK_CANCELLED.
    2. Authenticated Session A can interrupt its own task.
    3. Session B's task remains running.
    4. Unauthenticated status_update cannot trigger context prefetch.
    """
    client = api_test_setup["client"]
    token_a, _ = create_access_token(subject="user_ws_a", session_id="ws_sess_a")
    token_b, _ = create_access_token(subject="user_ws_b", session_id="ws_sess_b")

    event_a = threading.Event()
    event_b = threading.Event()
    task_a = type("MockTask", (), {"cancellation_token": event_a, "task_id": "ws_task_a", "user_id": "user_ws_a", "session_id": "ws_sess_a"})()
    task_b = type("MockTask", (), {"cancellation_token": event_b, "task_id": "ws_task_b", "user_id": "user_ws_b", "session_id": "ws_sess_b"})()

    ws_manager.register_active_task("ws_sess_a", task_a, task_id="ws_task_a", user_id="user_ws_a")
    ws_manager.register_active_task("ws_sess_b", task_b, task_id="ws_task_b", user_id="user_ws_b")

    from unittest.mock import MagicMock
    import api.server as server_module
    mock_voice = MagicMock()
    mock_voice_mgr = type("MockVoiceMgr", (), {
        "voice": mock_voice,
        "active_session_id": "ws_sess_b",
        "stop_speaking_for_session": MagicMock(return_value=False)
    })()
    old_voice_mgr = getattr(server_module, "_voice_mgr", None)
    server_module._voice_mgr = mock_voice_mgr

    try:
        # 1. Unauthenticated interrupt
        with client.websocket_connect("/ws/jarvis") as ws_unauth:
            init_msg = ws_unauth.receive_json()
            assert init_msg.get("type") == "status_update"

            # Attempt interrupt without authenticating
            ws_unauth.send_json({"command": "interrupt"})
            resp = ws_unauth.receive_json()
            assert resp.get("type") == "AUTH_FAILED"
            assert "Unauthorised" in resp.get("error", "")
            # Task A and Task B must NOT be cancelled
            assert not event_a.is_set()
            assert not event_b.is_set()
            # Voice manager must NOT have stopped speaking
            assert mock_voice.stop_speaking.call_count == 0
            assert mock_voice_mgr.stop_speaking_for_session.call_count == 0

            # Attempt status_update without authenticating
            ws_unauth.send_json({"command": "status_update", "status": "LISTENING"})
            status_resp = ws_unauth.receive_json()
            assert status_resp.get("type") == "AUTH_FAILED"

        # 2. Authenticated Session A interrupts its own task
        with client.websocket_connect("/ws/jarvis") as ws_a:
            _ = ws_a.receive_json() # status_update IDLE
            ws_a.send_json({"command": "auth", "token": token_a})
            auth_resp = ws_a.receive_json()
            assert auth_resp.get("type") == "AUTH_SUCCESS"

            ws_a.send_json({"command": "interrupt"})
            # Expect status update and TASK_CANCELLED
            msg1 = ws_a.receive_json()
            msg2 = ws_a.receive_json()
            messages = [msg1, msg2]
            cancelled_event = next((m for m in messages if m.get("type") == "TASK_CANCELLED"), None)
            assert cancelled_event is not None
            assert cancelled_event.get("cancelled") is True
            assert event_a.is_set(), "Session A's task should be cancelled"
            assert not event_b.is_set(), "Session B's task must remain running"
    finally:
        server_module._voice_mgr = old_voice_mgr
        ws_manager.unregister_active_task("ws_sess_a")
        ws_manager.unregister_active_task("ws_sess_b")


# ─── P0-3: Session-Scoped Chat Reset ──────────────────────────────────────────

def test_session_scoped_chat_reset_rest_and_streaming(api_test_setup):
    """
    P0-3: Fix session-scoped chat reset:
    - POST /chat with "reset" does not raise TypeError and resets caller's session.
    - POST /chat/stream with "reset" returns valid completion SSE response.
    - Reset in Session A clears Session A's history while Session B's history is intact.
    - Active task in Session B is not affected by reset in Session A.
    """
    client = api_test_setup["client"]
    token_a, _ = create_access_token(subject="user_rst_a", session_id="sess_rst_a")
    token_b, _ = create_access_token(subject="user_rst_b", session_id="sess_rst_b")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Clean setup
    client.delete("/history", headers=headers_a)
    client.delete("/history", headers=headers_b)

    # 1. Populate Session A and Session B with conversation history
    res_a = client.post("/chat", json={"message": "Secret Alpha: RESET_ALPHA_123", "store": True}, headers=headers_a)
    assert res_a.status_code == 200
    res_b = client.post("/chat", json={"message": "Secret Beta: RESET_BETA_456", "store": True}, headers=headers_b)
    assert res_b.status_code == 200

    # Register an active task for Session B to ensure reset in Session A does not affect it
    event_b = threading.Event()
    task_b = type("MockTask", (), {"cancellation_token": event_b, "task_id": "task_b_rst", "user_id": "user_rst_b", "session_id": "sess_rst_b"})()
    ws_manager.register_active_task("sess_rst_b", task_b, task_id="task_b_rst", user_id="user_rst_b")

    try:
        # 2. Normal POST /chat with message="reset" succeeds (no TypeError)
        resp_reset_a = client.post("/chat", json={"message": "reset"}, headers=headers_a)
        assert resp_reset_a.status_code == 200
        assert "reset" in resp_reset_a.json()["response"].lower()

        # Session A history must be cleared
        hist_a = client.get("/history", headers=headers_a).json()["turns"]
        assert len(hist_a) == 0

        # Session B history must remain untouched!
        hist_b = client.get("/history", headers=headers_b).json()["turns"]
        assert any("RESET_BETA_456" in t["content"] for t in hist_b)

        # Task B must not be cancelled
        assert not event_b.is_set()

        # 3. Streaming reset path: POST /chat/stream with "reset"
        # First add a turn back to Session A
        client.post("/chat", json={"message": "Temp Alpha: TEMP_999", "store": True}, headers=headers_a)
        assert len(client.get("/history", headers=headers_a).json()["turns"]) > 0

        # Now stream reset
        resp_stream_reset = client.post("/chat/stream", json={"message": "reset"}, headers=headers_a)
        assert resp_stream_reset.status_code == 200
        lines = resp_stream_reset.text.split("\n")
        assert any("[DONE]" in l for l in lines)
        assert any("reset" in l.lower() for l in lines)

        # Session A history cleared again
        assert len(client.get("/history", headers=headers_a).json()["turns"]) == 0
        # Session B history STILL untouched
        hist_b_after = client.get("/history", headers=headers_b).json()["turns"]
        assert any("RESET_BETA_456" in t["content"] for t in hist_b_after)
    finally:
        ws_manager.unregister_active_task("sess_rst_b")


# ─── P0-4: Interleaved Two-Session Short-Term Reasoning & Prefetch Isolation ──

def test_two_session_short_term_reasoning_and_prefetch_isolation(api_test_setup):
    """
    P0-4: Isolate short-term reasoning and prefetch context:
    - Session A sends a private message.
    - Session B sends a different private message.
    - Requests are interleaved.
    - Neither response's prompt or short-term state includes the other session's private message.
    - Session A reset does not alter Session B's state.
    """
    brain = api_test_setup["brain"]
    from core.brain.reasoning_engine import ReasoningEngine
    reasoning = ReasoningEngine()

    # Interleave messages into reasoning engine fallback/chat sessions
    reasoning._fallback_generate("Session A Secret: APPLE_PIE_123", session_id="session_iso_a", user_id="user_iso_a")
    reasoning._fallback_generate("Session B Secret: BANANA_SPLIT_456", session_id="session_iso_b", user_id="user_iso_b")
    reasoning._fallback_generate("Session A Followup: What is my fruit?", session_id="session_iso_a", user_id="user_iso_a")
    reasoning._fallback_generate("Session B Followup: What is my dessert?", session_id="session_iso_b", user_id="user_iso_b")

    hist_a = reasoning._session_histories.get("user_iso_a:session_iso_a", [])
    hist_b = reasoning._session_histories.get("user_iso_b:session_iso_b", [])

    text_a = " ".join(turn.get("content", "") for turn in hist_a)
    text_b = " ".join(turn.get("content", "") for turn in hist_b)

    assert "APPLE_PIE_123" in text_a
    assert "BANANA_SPLIT_456" not in text_a, "Session A must not contain Session B's secret"

    assert "BANANA_SPLIT_456" in text_b
    assert "APPLE_PIE_123" not in text_b, "Session B must not contain Session A's secret"

    # Prefetch context isolation test
    key_a = "user_iso_a:session_iso_a"
    key_b = "user_iso_b:session_iso_b"

    with brain.context._prefetch_lock:
        brain.context._prefetched_contexts[key_a] = "[MEMORY: User A likes PEACH_COBBLER]"
        brain.context._prefetched_contexts[key_b] = "[MEMORY: User B likes CHERRY_TART]"

    # Session A consumes its own prefetch
    loop = asyncio.new_event_loop()
    enriched_a = loop.run_until_complete(brain.context.build_enriched_prompt("Prompt A", session_id="session_iso_a", user_id="user_iso_a"))
    loop.close()

    assert "PEACH_COBBLER" in enriched_a
    assert "CHERRY_TART" not in enriched_a, "Session A must not consume Session B's prefetched context"

    with brain.context._prefetch_lock:
        # A's cache was consumed, but B's cache is STILL intact
        assert key_a not in brain.context._prefetched_contexts
        assert key_b in brain.context._prefetched_contexts
        assert "CHERRY_TART" in brain.context._prefetched_contexts[key_b]

    # Reset Session A
    reasoning.reset_session("System", [], session_id="session_iso_a", user_id="user_iso_a")
    brain.reset_chat(session_id="session_iso_a", user_id="user_iso_a")

    # Session A history is empty
    hist_a_after = reasoning._session_histories.get("user_iso_a:session_iso_a", [])
    assert len(hist_a_after) == 0

    # Session B history is STILL intact
    hist_b_after = reasoning._session_histories.get("user_iso_b:session_iso_b", [])
    assert len(hist_b_after) > 0
    text_b_after = " ".join(turn.get("content", "") for turn in hist_b_after)
    assert "BANANA_SPLIT_456" in text_b_after


# ─── P1-5: Fail Closed On Task Cancellation Ownership ─────────────────────────

def test_rest_task_interrupt_fail_closed_on_missing_metadata(api_test_setup):
    """
    P1-5: Fail closed on task cancellation ownership:
    - Valid owner/session cancellation (200).
    - Wrong user (403).
    - Wrong session for the same user (403).
    - Task with missing owner metadata (403).
    - Task with missing session metadata (403).
    - Unknown task ID (200 no-op, nothing cancelled).
    - Other session's cancellation token remains unset.
    """
    client = api_test_setup["client"]
    token_valid, _ = create_access_token(subject="user_owner", session_id="sess_owner")
    token_wrong_user, _ = create_access_token(subject="user_other", session_id="sess_owner")
    token_wrong_sess, _ = create_access_token(subject="user_owner", session_id="sess_other")

    headers_valid = {"Authorization": f"Bearer {token_valid}"}
    headers_wrong_user = {"Authorization": f"Bearer {token_wrong_user}"}
    headers_wrong_sess = {"Authorization": f"Bearer {token_wrong_sess}"}

    event_valid = threading.Event()
    event_no_user = threading.Event()
    event_no_sess = threading.Event()
    event_other = threading.Event()

    task_valid = type("MockTask", (), {"cancellation_token": event_valid, "task_id": "task_valid_id", "user_id": "user_owner", "session_id": "sess_owner"})()
    task_no_user = type("MockTask", (), {"cancellation_token": event_no_user, "task_id": "task_no_user_id", "user_id": None, "session_id": "sess_owner"})()
    task_no_sess = type("MockTask", (), {"cancellation_token": event_no_sess, "task_id": "task_no_sess_id", "user_id": "user_owner", "session_id": None})()
    task_other = type("MockTask", (), {"cancellation_token": event_other, "task_id": "task_other_id", "user_id": "user_other", "session_id": "sess_other"})()

    ws_manager.register_active_task("sess_owner", task_valid, task_id="task_valid_id", user_id="user_owner")
    ws_manager.register_active_task("task_no_user_id", task_no_user, task_id="task_no_user_id", user_id=None)
    ws_manager.register_active_task("task_no_sess_id", task_no_sess, task_id="task_no_sess_id", user_id="user_owner")
    # Explicitly ensure session_id is None in task_metadata to simulate missing session metadata
    ws_manager.task_metadata["task_no_sess_id"]["session_id"] = None
    ws_manager.register_active_task("sess_other", task_other, task_id="task_other_id", user_id="user_other")

    try:
        # 1. Unknown task ID -> 200 no-op, nothing cancelled
        res_unknown = client.post("/tasks/interrupt", json={"task_id": "non_existent_task"}, headers=headers_valid)
        assert res_unknown.status_code == 200
        assert "No active task found" in res_unknown.json()["message"]
        assert not event_valid.is_set()

        # 2. Task with missing user_id metadata -> 403 Forbidden
        res_no_user = client.post("/tasks/interrupt", json={"task_id": "task_no_user_id"}, headers=headers_valid)
        assert res_no_user.status_code == 403
        assert "ownership metadata is absent or incomplete" in res_no_user.json()["detail"].lower()
        assert not event_no_user.is_set()

        # 3. Task with missing session_id metadata -> 403 Forbidden
        res_no_sess = client.post("/tasks/interrupt", json={"task_id": "task_no_sess_id"}, headers=headers_valid)
        assert res_no_sess.status_code == 403
        assert "ownership metadata is absent or incomplete" in res_no_sess.json()["detail"].lower()
        assert not event_no_sess.is_set()

        # 4. Wrong user -> 403 Forbidden
        res_wrong_u = client.post("/tasks/interrupt", json={"task_id": "task_valid_id"}, headers=headers_wrong_user)
        assert res_wrong_u.status_code == 403
        assert not event_valid.is_set()

        # 5. Wrong session for same user -> 403 Forbidden
        res_wrong_s = client.post("/tasks/interrupt", json={"task_id": "task_valid_id"}, headers=headers_wrong_sess)
        assert res_wrong_s.status_code == 403
        assert not event_valid.is_set()

        # 6. Valid owner + session cancellation -> 200 Success
        res_ok = client.post("/tasks/interrupt", json={"task_id": "task_valid_id"}, headers=headers_valid)
        assert res_ok.status_code == 200
        assert event_valid.is_set()

        # 7. Other session's cancellation token remains unset
        assert not event_other.is_set()
    finally:
        ws_manager.unregister_active_task("task_valid_id")
        ws_manager.unregister_active_task("task_no_user_id")
        ws_manager.unregister_active_task("task_no_sess_id")
        ws_manager.unregister_active_task("task_other_id")


# ─── P0-2 (Phase 3.6.7): Per-User Semantic and Episodic Memory Ownership ───────

def test_p0_2_per_user_semantic_and_episodic_memory_ownership(api_test_setup):
    """
    P0-2 Regression: Enforce per-user semantic and episodic memory ownership:
    A. User A stores a semantic memory.
    B. User B makes a relevant query.
    C. User B cannot retrieve User A's memory through the semantic-memory API or enriched-prompt context.
    D. User A can retrieve the memory in another session belonging to User A if user-wide sharing is intended.
    E. Episodic summaries obey the same owner isolation.
    F. JSON fallback and ChromaDB paths enforce equivalent ownership.
    G. Legacy entries without owner metadata are not exposed to arbitrary callers.
    H. store=false still produces zero conversational or semantic persistence.
    """
    client = api_test_setup["client"]
    brain = api_test_setup["brain"]
    memory = api_test_setup["memory"]

    token_a1, _ = create_access_token(subject="user_alpha", session_id="sess_a1")
    token_a2, _ = create_access_token(subject="user_alpha", session_id="sess_a2")
    token_b1, _ = create_access_token(subject="user_beta", session_id="sess_b1")

    headers_a1 = {"Authorization": f"Bearer {token_a1}"}
    headers_a2 = {"Authorization": f"Bearer {token_a2}"}
    headers_b1 = {"Authorization": f"Bearer {token_b1}"}

    secret_key = "quantum_crypto_key_xyz987"
    secret_text = f"User Alpha private research protocol: {secret_key}"

    # Clean slate for test users
    memory.clear_all(user_id="user_alpha")
    memory.clear_all(user_id="user_beta")

    # A. User A stores a semantic memory via API
    res_store = client.post(
        "/memory",
        json={"content": secret_text, "category": "knowledge", "encrypt": False},
        headers=headers_a1,
    )
    assert res_store.status_code == 200
    assert "Memory stored with ID:" in res_store.json()["message"]
    doc_id = res_store.json()["message"].split("ID: ")[1].strip()

    # B & C. User B makes a relevant query via /memory/search
    res_search_b = client.post(
        "/memory/search",
        json={"query": secret_key, "top_k": 5},
        headers=headers_b1,
    )
    assert res_search_b.status_code == 200
    b_results = res_search_b.json()["results"]
    assert not any(secret_key in r["content"] for r in b_results), "User B must not receive User A's private semantic memory"
    # C2. User B cannot retrieve User A's memory through enriched-prompt context
    loop = asyncio.new_event_loop()
    try:
        prompt_query = "User Alpha private research protocol"
        enriched_b = loop.run_until_complete(
            brain.context.build_enriched_prompt(
                prompt_query, session_id="sess_b1", user_id="user_beta"
            )
        )
        assert secret_key not in enriched_b, "User B's prompt must not contain User A's memory"

        # D. User A can retrieve the memory in another session (sess_a2) belonging to User A
        res_search_a2 = client.post(
            "/memory/search",
            json={"query": secret_key, "top_k": 5},
            headers=headers_a2,
        )
        assert res_search_a2.status_code == 200
        a2_results = res_search_a2.json()["results"]
        assert len(a2_results) >= 1
        assert any(secret_key in r["content"] for r in a2_results)

        enriched_a2 = loop.run_until_complete(
            brain.context.build_enriched_prompt(
                prompt_query, session_id="sess_a2", user_id="user_alpha"
            )
        )
        assert secret_key in enriched_a2, "User A must retrieve own memory in another session"
    finally:
        loop.close()

    # E. Episodic summaries obey owner isolation
    ep_summary_a = f"Episode summary for Alpha with secret: {secret_key}"
    memory.create_episode_summary(ep_summary_a, user_id="user_alpha", session_id="sess_a1")

    # User B searching episodes gets nothing of User A
    ep_search_b = memory.episodes.search(secret_key, user_id="user_beta")
    assert not any(secret_key in ep["summary"] for ep in ep_search_b), "User B must not see User A's episodic summaries"

    # User A searching episodes gets the summary
    ep_search_a = memory.episodes.search(secret_key, user_id="user_alpha")
    assert len(ep_search_a) >= 1
    assert any(secret_key in ep["summary"] for ep in ep_search_a)

    # F. JSON fallback store enforces equivalent ownership
    json_doc_id = "test_json_alpha_001"
    memory._json_store.add(
        json_doc_id,
        f"Fallback storage secret: {secret_key}",
        {"category": "knowledge", "user_id": "user_alpha"},
    )
    json_res_b = memory._json_store.search(secret_key, user_id="user_beta")
    assert not any(secret_key in r["content"] for r in json_res_b), "User B must not see User A's JSON store memories"

    json_res_a = memory._json_store.search(secret_key, user_id="user_alpha")
    assert len(json_res_a) >= 1
    assert any(json_doc_id == r["id"] for r in json_res_a)

    # G. Legacy entries without owner metadata are excluded from multi-user retrieval
    legacy_doc_id = "test_legacy_unowned_001"
    legacy_text = "Legacy database record: ancient_unowned_secret_12345"
    memory._json_store.add(
        legacy_doc_id,
        legacy_text,
        {"category": "knowledge"},  # No user_id!
    )
    if memory._collection:
        try:
            memory._collection.add(
                ids=[legacy_doc_id],
                documents=[legacy_text],
                metadatas=[{"category": "knowledge"}],  # No user_id!
            )
        except Exception:
            pass

    # Neither User A nor User B can retrieve unowned legacy record
    legacy_res_a = memory.retrieve_memories("ancient_unowned_secret_12345", user_id="user_alpha")
    legacy_res_b = memory.retrieve_memories("ancient_unowned_secret_12345", user_id="user_beta")
    assert not any("ancient_unowned_secret_12345" in r["content"] for r in legacy_res_a), "Legacy unowned records must be excluded from User A retrieval"
    assert not any("ancient_unowned_secret_12345" in r["content"] for r in legacy_res_b), "Legacy unowned records must be excluded from User B retrieval"

    legacy_json_a = memory._json_store.search("ancient_unowned_secret_12345", user_id="user_alpha")
    legacy_json_b = memory._json_store.search("ancient_unowned_secret_12345", user_id="user_beta")
    assert not any("ancient_unowned_secret_12345" in r["content"] for r in legacy_json_a), "Legacy unowned records excluded from User A JSON retrieval"
    assert not any("ancient_unowned_secret_12345" in r["content"] for r in legacy_json_b), "Legacy unowned records excluded from User B JSON retrieval"

    # User A / User B preference isolation
    client.post("/memory/preference", json={"key": "editor", "value": "vscode"}, headers=headers_a1)
    client.post("/memory/preference", json={"key": "editor", "value": "emacs"}, headers=headers_b1)

    pref_a = client.get("/memory/preference/editor", headers=headers_a1).json()["value"]
    pref_b = client.get("/memory/preference/editor", headers=headers_b1).json()["value"]
    assert pref_a == "vscode"
    assert pref_b == "emacs"

    # H. store=false still produces zero conversational or semantic persistence
    convo_count_before = memory.conversations.count(user_id="user_alpha")
    res_chat_nostore = client.post(
        "/chat",
        json={"message": "Do not remember this: secret_nostore_999", "store": False},
        headers=headers_a1,
    )
    assert res_chat_nostore.status_code == 200
    convo_count_after = memory.conversations.count(user_id="user_alpha")
    assert convo_count_after == convo_count_before, "store=False must not add conversational turns"

    nostore_search = memory.retrieve_memories("secret_nostore_999", user_id="user_alpha")
    assert not any("secret_nostore_999" in r["content"] for r in nostore_search), "store=False must not store semantic memory"

    # Deletion isolation: User B cannot delete User A's memory
    del_b = memory.delete_memory(memory_id=doc_id, user_id="user_beta")
    assert not del_b, "User B must not be permitted to delete User A's memory"
    assert memory._json_store.get(doc_id, user_id="user_alpha") is not None, "User A's memory must remain present"

    # Cleanup: User A clears own memory
    del_a = client.delete("/memory?confirm=true", headers=headers_a1)
    assert del_a.status_code == 200
    assert memory._json_store.get(doc_id, user_id="user_alpha") is None
    # User B's preference is still intact
    assert client.get("/memory/preference/editor", headers=headers_b1).json()["value"] == "emacs"


def test_phase3_6_8_internal_memory_ownership_and_deletion_safety(api_test_setup):
    """
    JARVIS Phase 3.6.8 — Internal Memory Ownership and Deletion Safety Regression Suite:
    1. Cross-user memory search through public API is owner-isolated.
    2. Cross-user memory retrieval through MemoryAgent is owner-isolated and fails closed without owner.
    3. Cross-user workflow optimization through RefinerAgent /optimize is owner-isolated.
    4. Cross-user natural-language memory deletion: User B cannot delete User A's memory.
    5. User A can delete their own memory via natural language.
    6. Missing user_id retrieval fails closed.
    7. Missing user_id deletion fails closed.
    8. Unowned legacy entries are excluded from retrieval and protected from deletion.
    9. Same-user cross-session semantic retrieval works.
    10. Natural language deletion without verified owner identity fails closed.
    """
    client = api_test_setup["client"]
    brain = api_test_setup["brain"]
    memory = api_test_setup["memory"]

    from api.auth import create_access_token
    from core.agents.base_agent import AgentMessage
    from core.agents.memory_agent import MemoryAgent
    from core.brain.task_model import ExecutionContext

    token_a, _ = create_access_token(subject="user_368_a", session_id="sess_368_a1")
    token_a2, _ = create_access_token(subject="user_368_a", session_id="sess_368_a2")
    token_b, _ = create_access_token(subject="user_368_b", session_id="sess_368_b1")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_a2 = {"Authorization": f"Bearer {token_a2}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    import uuid
    run_id = uuid.uuid4().hex[:6]
    token_alpha_str = f"AlphaSecretToken_{run_id}"
    token_beta_str = f"BetaSecretToken_{run_id}"
    passcode_str = f"DeltaPasscode_{run_id}"
    acct_str = f"ACCT_{run_id}"
    med_str = f"MED_{run_id}"
    car_str = f"XYZ_CAR_{run_id}"

    # ── 1. Store private memories for User A and User B via API ──
    res_a = client.post("/memory", json={"content": f"{token_alpha_str}: User A confidential project key", "category": "knowledge"}, headers=headers_a)
    assert res_a.status_code == 200

    res_b = client.post("/memory", json={"content": f"{token_beta_str}: User B confidential medical record", "category": "knowledge"}, headers=headers_b)
    assert res_b.status_code == 200

    # Cross-user search through public API
    search_a = client.post("/memory/search", json={"query": token_alpha_str}, headers=headers_a).json()["results"]
    assert any(token_alpha_str in r["content"] for r in search_a), "User A must find own memory"

    search_b_for_a = client.post("/memory/search", json={"query": token_alpha_str}, headers=headers_b).json()["results"]
    assert not any(token_alpha_str in r["content"] for r in search_b_for_a), "User B must NOT find User A's memory"

    # Same-user cross-session retrieval: User A in session 2 can retrieve session 1 memory
    search_a2 = client.post("/memory/search", json={"query": token_alpha_str}, headers=headers_a2).json()["results"]
    assert any(token_alpha_str in r["content"] for r in search_a2), "User A session 2 must find User A session 1 semantic memory"

    # ── 2. MemoryAgent Internal Ownership (P0-3) ──
    mem_agent = MemoryAgent(memory=memory, brain_send=lambda p: "Summary test")

    # Store via MemoryAgent for User A
    store_msg = AgentMessage(
        sender="user_368_a",
        recipient="memory",
        content=f"Internal vault passcode: {passcode_str}",
        user_id="user_368_a",
        metadata={"action": "store", "category": "knowledge", "user_id": "user_368_a"}
    )
    store_resp = mem_agent.process(store_msg)
    assert store_resp.success is True

    # User B attempts to retrieve User A's passcode via MemoryAgent
    ret_b_msg = AgentMessage(
        sender="user_368_b",
        recipient="memory",
        content=passcode_str,
        user_id="user_368_b",
        metadata={"action": "retrieve", "user_id": "user_368_b"}
    )
    ret_b_resp = mem_agent.process(ret_b_msg)
    assert passcode_str not in ret_b_resp.content, "MemoryAgent retrieval for User B must NOT return User A's memory"
    retrieved_b_mems = ret_b_resp.metadata.get("memories", [])
    assert not any(passcode_str in m.get("content", "") for m in retrieved_b_mems), "User A's memory must not be in User B's retrieved memories"
    assert all(m.get("metadata", {}).get("user_id") == "user_368_b" for m in retrieved_b_mems), "All retrieved memories must belong to User B"

    # User A retrieves own passcode via MemoryAgent
    ret_a_msg = AgentMessage(
        sender="user_368_a",
        recipient="memory",
        content=passcode_str,
        user_id="user_368_a",
        metadata={"action": "retrieve", "user_id": "user_368_a"}
    )
    ret_a_resp = mem_agent.process(ret_a_msg)
    assert passcode_str in ret_a_resp.content, "MemoryAgent retrieval for User A must return own memory"

    # Missing user_id in MemoryAgent retrieve fails closed
    ret_anon_msg = AgentMessage(
        sender="anonymous",
        recipient="memory",
        content=passcode_str,
        metadata={"action": "retrieve"}
    )
    ret_anon_resp = mem_agent.process(ret_anon_msg)
    assert ret_anon_resp.success is False
    assert ret_anon_resp.error == "UNAUTHORIZED_MISSING_OWNER"
    assert ret_anon_resp.content == ""

    # Missing user_id in MemoryAgent store fails closed
    store_anon_msg = AgentMessage(
        sender="anonymous",
        recipient="memory",
        content="Unowned data",
        metadata={"action": "store"}
    )
    store_anon_resp = mem_agent.process(store_anon_msg)
    assert store_anon_resp.success is False
    assert store_anon_resp.error == "UNAUTHORIZED_MISSING_OWNER"

    # ── 3. RefinerAgent & POST /optimize Ownership (P0-4) ──
    # Store distinct tasks for User A and User B
    memory.store_memory(
        f"Task executed: parse_quarterly_financials for account {acct_str}\nResult: Parsed EBITDA 1.2M",
        category="task",
        user_id="user_368_a"
    )
    memory.store_memory(
        f"Task executed: sync_patient_records for patient {med_str}\nResult: Synced HIPAA record",
        category="task",
        user_id="user_368_b"
    )

    captured_prompts = []
    original_send = brain.reasoning.send_message
    def mock_refiner_llm(prompt, *args, **kwargs):
        captured_prompts.append(prompt)
        return 'def automated_tool(data: str) -> str:\n    """A descriptive docstring for automated tool."""\n    return data.strip()'

    brain.reasoning.send_message = mock_refiner_llm
    try:
        # User A triggers /optimize
        captured_prompts.clear()
        opt_a = client.post("/optimize", headers=headers_a)
        assert opt_a.status_code == 200
        assert len(captured_prompts) > 0
        prompt_a = captured_prompts[-1]
        assert acct_str in prompt_a, "User A's refiner prompt must contain User A's task"
        assert med_str not in prompt_a, "User A's refiner prompt must NEVER contain User B's task"

        # User B triggers /optimize
        captured_prompts.clear()
        opt_b = client.post("/optimize", headers=headers_b)
        assert opt_b.status_code == 200
        assert len(captured_prompts) > 0
        prompt_b = captured_prompts[-1]
        assert med_str in prompt_b, "User B's refiner prompt must contain User B's task"
        assert acct_str not in prompt_b, "User B's refiner prompt must NEVER contain User A's task"

        # Missing user_id directly to RefinerAgent process fails closed
        if hasattr(brain, "_refiner") and brain._refiner:
            anon_refiner_msg = AgentMessage(sender="anon", recipient="refiner", content="optimize")
            anon_refiner_res = brain._refiner.process(anon_refiner_msg)
            assert anon_refiner_res.success is False
            assert anon_refiner_res.error == "UNAUTHORIZED_MISSING_OWNER"
    finally:
        brain.reasoning.send_message = original_send

    # ── 4. Natural-Language Memory Deletion Ownership (P0-2) ──
    orchestrator = brain.orchestrator
    doc_delete_target = memory.store_memory(f"My secret car registration number is {car_str}", category="knowledge", user_id="user_368_a")

    ctx_b = ExecutionContext(user_id="user_368_b", session_id="sess_368_b1")
    ctx_a = ExecutionContext(user_id="user_368_a", session_id="sess_368_a1")
    ctx_anon = ExecutionContext(user_id=None, session_id="sess_anon")

    # User B attempts natural language forget for User A's car registration
    res_forget_b = orchestrator.process(f"Please forget my secret car registration number {car_str} from memory", context=ctx_b)
    assert "deleted that information" not in res_forget_b, "User B must not receive deletion confirmation for User A's memory"
    assert "found no matching records" in res_forget_b

    # Verify User A's memory remains intact
    ret_a_after = memory.retrieve_memories(car_str, user_id="user_368_a")
    assert any(car_str in r["content"] for r in ret_a_after), "User A's memory must remain completely intact"

    # Unauthenticated / unowned deletion attempt fails closed
    res_forget_anon = orchestrator.process(f"Please forget {car_str} from my memory", context=ctx_anon)
    assert "cannot delete memories without verified user identity" in res_forget_anon

    # User A successfully deletes their own memory via natural language
    res_forget_a = orchestrator.process(f"Please forget my secret car registration number {car_str} from memory", context=ctx_a)
    assert "deleted that information from memory" in res_forget_a

    # Verify User A's memory is now deleted
    ret_a_deleted = memory.retrieve_memories(car_str, user_id="user_368_a")
    assert not any(car_str in r["content"] for r in ret_a_deleted), "Memory must be deleted after owner deletion"

    # ── 5. Generic Memory API Fail-Closed & Legacy Protection (P1-5) ──
    # Missing user_id on retrieval returns []
    assert memory.retrieve_memories("anything", user_id=None) == []
    assert memory._json_store.search("anything", user_id=None) == []
    assert memory.episodes.search("anything", user_id=None) == []
    assert memory.get_preference("editor", user_id=None) is None
    assert memory.build_context_snippet("anything", user_id=None) == ""

    # Missing user_id on deletion returns False
    assert memory.delete_memory(memory_id="some_id", user_id=None) is False
    assert memory.delete_memory(query="some_query", user_id=None) is False
    assert memory._json_store.delete("some_id", user_id=None) is False

    # Unowned legacy record protection
    legacy_id = f"legacy_{time.time()}"
    memory._json_store.add(legacy_id, "Secret unowned mainframe credentials", {"category": "knowledge"})
    if memory._collection:
        try:
            memory._collection.add(ids=[legacy_id], documents=["Secret unowned mainframe credentials"], metadatas=[{"category": "knowledge"}])
        except Exception:
            pass

    # Excluded from retrieval by both users
    assert not any("mainframe" in r["content"] for r in memory.retrieve_memories("mainframe", user_id="user_368_a"))
    assert not any("mainframe" in r["content"] for r in memory.retrieve_memories("mainframe", user_id="user_368_b"))

    # Deletion of unowned legacy record rejected
    assert memory.delete_memory(memory_id=legacy_id, user_id="user_368_a") is False
    assert memory.delete_memory(memory_id=legacy_id, user_id="user_368_b") is False
    assert memory._json_store.get(legacy_id, allow_system_scope=True) is not None, "Unowned legacy record must NOT be deleted by arbitrary user"

    # Direct ID deletion of wrong-owner record rejected
    doc_a_id = memory.store_memory("User A proprietary algorithm", category="knowledge", user_id="user_368_a")
    assert memory.delete_memory(memory_id=doc_a_id, user_id="user_368_b") is False
    assert memory._json_store.get(doc_a_id, user_id="user_368_a") is not None, "Wrong-owner record must NOT be deleted"


def test_phase3_6_9_trusted_identity_and_fail_closed_memory_completion():
    """
    Phase 3.6.9 Regression Tests:
    1. Trusted Identity Boundary & System Authorization (P0-1):
       - Message with metadata={"user_id": "user_A"} but no user_id cannot impersonate User A.
       - Message with metadata={"allow_system_scope": True} cannot elevate or bypass owner check.
       - Conflicting user_id and metadata["user_id"] forces metadata to trusted user_id.
       - User B cannot retrieve User A's memories through MemoryAgent or RefinerAgent.
       - Verified user retrieves own memories across sessions.
       - Authenticated /optimize remains owner-scoped.
       - Legitimate system maintenance works through create_system_message.
    2. Fail-Closed Generic Memory APIs (P1-2):
       - Ownerless reads fail closed (ConversationStore, JSONMemoryStore, EpisodicMemory, stats).
       - Ownerless clears fail closed and do NOT wipe global memory.
       - Cross-user clear isolation (Clearing User A leaves User B intact).
       - Authorized system maintenance clear works with allow_system_scope=True.
    3. Owner-Scoped Automatic Summarization (P1-3):
       - Turn tracking is scoped per (user_id, session_id).
       - Owner-authenticated summarization succeeds and resets only that user's counter.
       - User A's turns never enter User B's summary.
       - Anonymous summarization fails closed.
    """
    import os
    import tempfile
    import shutil
    from core.memory import JarvisMemory, ConversationStore, JSONMemoryStore, EpisodicMemory
    from core.agents.base_agent import AgentMessage, create_system_message
    from core.agents.memory_agent import MemoryAgent
    from core.agents.refiner_agent import RefinerAgent

    from pathlib import Path
    test_dir = tempfile.mkdtemp(prefix="jarvis_test_369_")
    try:
        mem = JarvisMemory()
        # Wire isolated stores for testing
        conv = ConversationStore(Path(test_dir) / "conversations.json")
        jstore = JSONMemoryStore(Path(test_dir) / "memory_fallback.json")
        episodes = EpisodicMemory(Path(test_dir) / "episodes.json")
        mem.conversations = conv
        mem._json_store = jstore
        mem.episodes = episodes

        # ─────────────────────────────────────────────────────────────
        # Part 1: Trusted Identity Boundary & Message Construction (P0-1)
        # ─────────────────────────────────────────────────────────────
        # 1.1 Metadata-based user_id spoofing rejected
        spoofed_msg = AgentMessage(
            sender="untrusted_client",
            recipient="MemoryAgent",
            content="secret",
            metadata={"action": "retrieve", "user_id": "victim_user"}
        )
        assert spoofed_msg.user_id is None, "user_id must NOT be elevated from metadata"
        assert "user_id" not in spoofed_msg.metadata, "untrusted metadata['user_id'] must be stripped"

        # 1.2 Metadata-based system-scope escalation rejected
        escalated_msg = AgentMessage(
            sender="untrusted_client",
            recipient="MemoryAgent",
            content="secret",
            metadata={"action": "retrieve", "allow_system_scope": True}
        )
        assert escalated_msg.system_authorized is False, "system_authorized must not be elevated from metadata"
        assert "allow_system_scope" not in escalated_msg.metadata, "unauthorized allow_system_scope must be stripped"

        # 1.3 Conflicting user_id and metadata['user_id'] forced to trusted user_id
        conflicting_msg = AgentMessage(
            sender="gateway",
            recipient="MemoryAgent",
            content="secret",
            user_id="legit_user",
            metadata={"action": "retrieve", "user_id": "spoofed_target"}
        )
        assert conflicting_msg.user_id == "legit_user"
        assert conflicting_msg.metadata.get("user_id") == "legit_user", "metadata['user_id'] must match trusted user_id"

        # 1.4 Legitimate system message via factory
        sys_msg = create_system_message(
            sender="maintenance_task",
            recipient="MemoryAgent",
            content="Project brain maintenance",
            metadata={"action": "update_project_brain"}
        )
        assert sys_msg.system_authorized is True
        assert sys_msg.metadata.get("allow_system_scope") is True

        # Store memories for User A and User B
        mem_a_id = mem.store_memory("User A secret vault code is 98765", category="knowledge", user_id="user_369_a")
        mem_b_id = mem.store_memory("User B favorite color is cyan", category="knowledge", user_id="user_369_b")

        memory_agent = MemoryAgent(memory=mem)

        brain_mock = MagicMock()
        brain_mock.memory_manager._memory = mem
        refiner_agent = RefinerAgent(brain=brain_mock)

        # 1.5 Spoofed message to MemoryAgent fails closed
        resp_spoofed = memory_agent.process(spoofed_msg)
        assert not resp_spoofed.success
        assert resp_spoofed.error == "UNAUTHORIZED_MISSING_OWNER"

        # 1.6 Escalated message to MemoryAgent fails closed
        resp_escalated = memory_agent.process(escalated_msg)
        assert not resp_escalated.success
        assert resp_escalated.error == "UNAUTHORIZED_MISSING_OWNER"

        # 1.7 User B cannot retrieve User A's private memories via MemoryAgent
        msg_b_read_a = AgentMessage(
            sender="api",
            recipient="MemoryAgent",
            content="vault code",
            metadata={"action": "retrieve"},
            user_id="user_369_b"
        )
        resp_b_read_a = memory_agent.process(msg_b_read_a)
        assert resp_b_read_a.success
        retrieved_items = resp_b_read_a.metadata.get("memories", [])
        assert not any("98765" in item.get("content", "") for item in retrieved_items), "User B must not see User A's vault code"

        # 1.8 User A can retrieve User A's memories across sessions
        msg_a_read_s1 = AgentMessage(
            sender="api",
            recipient="MemoryAgent",
            content="vault code",
            metadata={"action": "retrieve"},
            user_id="user_369_a",
            session_id="session_1"
        )
        resp_a_read_s1 = memory_agent.process(msg_a_read_s1)
        assert resp_a_read_s1.success
        assert any("98765" in item.get("content", "") for item in resp_a_read_s1.metadata.get("memories", []))

        msg_a_read_s2 = AgentMessage(
            sender="api",
            recipient="MemoryAgent",
            content="vault code",
            metadata={"action": "retrieve"},
            user_id="user_369_a",
            session_id="session_2"
        )
        resp_a_read_s2 = memory_agent.process(msg_a_read_s2)
        assert resp_a_read_s2.success
        assert any("98765" in item.get("content", "") for item in resp_a_read_s2.metadata.get("memories", []))

        # 1.9 RefinerAgent requires verified owner or system authorization
        refiner_ownerless = AgentMessage(
            sender="api",
            recipient="RefinerAgent",
            content="optimize",
            metadata={"action": "optimize"}
        )
        resp_ref_ownerless = refiner_agent.process(refiner_ownerless)
        assert not resp_ref_ownerless.success
        assert resp_ref_ownerless.error == "UNAUTHORIZED_MISSING_OWNER"

        refiner_spoofed = AgentMessage(
            sender="api",
            recipient="RefinerAgent",
            content="optimize",
            metadata={"action": "optimize", "user_id": "user_369_a"}
        )
        resp_ref_spoofed = refiner_agent.process(refiner_spoofed)
        assert not resp_ref_spoofed.success
        assert resp_ref_spoofed.error == "UNAUTHORIZED_MISSING_OWNER"

        # User B cannot optimize with User A's identity
        refiner_b = AgentMessage(
            sender="api",
            recipient="RefinerAgent",
            content="optimize",
            metadata={"action": "optimize"},
            user_id="user_369_b"
        )
        resp_ref_b = refiner_agent.process(refiner_b)
        # Should succeed with no tasks found for User B
        assert resp_ref_b.success

        # ─────────────────────────────────────────────────────────────
        # Part 2: Fail-Closed Generic Memory APIs (P1-2)
        # ─────────────────────────────────────────────────────────────
        # Add conversation turns for User A and User B
        conv.add_turn("user", "Hello Jarvis I am user A", metadata={"user_id": "user_369_a", "session_id": "sess_a"})
        conv.add_turn("assistant", "Hello user A!", metadata={"user_id": "user_369_a", "session_id": "sess_a"})
        conv.add_turn("user", "Hello Jarvis I am user B", metadata={"user_id": "user_369_b", "session_id": "sess_b"})

        # Add episodic memory for User A and User B
        episodes.add_episode("User A completed project onboarding", ["step1", "step2"], user_id="user_369_a", session_id="sess_a")
        episodes.add_episode("User B deployed web app", ["deploy1"], user_id="user_369_b", session_id="sess_b")

        # 2.1 ConversationStore fail-closed reads
        assert conv.get_recent(limit=10, user_id=None) == []
        assert conv.get_context_string(limit=10, user_id=None) == ""
        assert conv.get_unsummarized_turns(limit=10, user_id=None) == []
        assert conv.count(user_id=None) == 0

        # Scoped reads succeed for owner
        assert len(conv.get_recent(limit=10, user_id="user_369_a")) == 2
        assert "user A" in conv.get_context_string(limit=10, user_id="user_369_a")
        assert "user B" not in conv.get_context_string(limit=10, user_id="user_369_a")
        assert conv.count(user_id="user_369_a") == 2
        assert conv.count(user_id="user_369_b") == 1

        # 2.2 JSONMemoryStore fail-closed reads
        assert jstore.get(mem_a_id, user_id=None) is None
        assert jstore.get(mem_a_id, user_id="user_369_b") is None
        assert jstore.get(mem_a_id, user_id="user_369_a") is not None
        assert jstore.all_by_category("knowledge", user_id=None) == []
        assert len(jstore.all_by_category("knowledge", user_id="user_369_a")) == 1
        assert jstore.count(user_id=None) == 0
        assert jstore.count(user_id="user_369_a") >= 1

        # 2.3 EpisodicMemory fail-closed reads
        assert episodes.count(user_id=None) == 0
        assert episodes.count(user_id="user_369_a") == 1
        assert episodes.count(user_id="user_369_b") == 1

        # 2.4 JarvisMemory stats fail-closed reads
        stats_none = mem.stats(user_id=None)
        assert stats_none["conversation_turns"] == 0
        assert stats_none["long_term_memories"] == 0
        assert stats_none["episodes"] == 0

        stats_a = mem.stats(user_id="user_369_a")
        assert stats_a["conversation_turns"] == 2
        assert stats_a["episodes"] == 1

        # 2.5 Destructive clears with missing owner must fail closed (no-op)
        conv.clear(user_id=None)
        assert conv.count(user_id="user_369_a") == 2, "Ownerless conv.clear must NOT clear User A"
        assert conv.count(user_id="user_369_b") == 1, "Ownerless conv.clear must NOT clear User B"

        jstore.clear(user_id=None)
        assert jstore.get(mem_a_id, user_id="user_369_a") is not None, "Ownerless jstore.clear must NOT delete User A memory"
        assert jstore.get(mem_b_id, user_id="user_369_b") is not None, "Ownerless jstore.clear must NOT delete User B memory"

        episodes.clear(user_id=None)
        assert episodes.count(user_id="user_369_a") == 1, "Ownerless episodes.clear must NOT clear User A"
        assert episodes.count(user_id="user_369_b") == 1, "Ownerless episodes.clear must NOT clear User B"

        clear_all_res = mem.clear_all(user_id=None)
        assert clear_all_res is False, "mem.clear_all(user_id=None) must fail closed and return False"
        assert conv.count(user_id="user_369_a") == 2
        assert jstore.get(mem_a_id, user_id="user_369_a") is not None

        # 2.6 Cross-user clear isolation: Clearing User A leaves User B intact
        clear_a_res = mem.clear_all(user_id="user_369_a")
        assert clear_a_res is True
        assert conv.count(user_id="user_369_a") == 0
        assert jstore.get(mem_a_id, user_id="user_369_a") is None
        assert episodes.count(user_id="user_369_a") == 0

        # User B is completely intact
        assert conv.count(user_id="user_369_b") == 1
        assert jstore.get(mem_b_id, user_id="user_369_b") is not None
        assert episodes.count(user_id="user_369_b") == 1

        # 2.7 System-authorized clear_all works with allow_system_scope=True
        sys_clear_res = mem.clear_all(allow_system_scope=True)
        assert sys_clear_res is True
        assert conv.count(allow_system_scope=True) == 0
        assert episodes.count(allow_system_scope=True) == 0

        # ─────────────────────────────────────────────────────────────
        # Part 3: Owner-Scoped Automatic Summarization (P1-3)
        # ─────────────────────────────────────────────────────────────
        # Configure MemoryAgent with summary_threshold=3 for testing
        mem_agent_summ = MemoryAgent(
            memory=mem,
            brain_send=lambda p: "Quantum physics summary for user"
        )
        mem_agent_summ.SUMMARIZE_THRESHOLD = 3

        # 3.1 Anonymous summarization fails closed
        anon_turn_msg = AgentMessage(
            sender="api",
            recipient="MemoryAgent",
            content="some turn content",
            metadata={"action": "check_summarize"}
        )
        resp_anon = mem_agent_summ.process(anon_turn_msg)
        assert not resp_anon.success
        assert resp_anon.error == "UNAUTHORIZED_MISSING_OWNER"

        # 3.2 Add turns for User A and User B
        for i in range(2):
            conv.add_turn("user", f"User A turn {i}: discussing quantum physics", metadata={"user_id": "user_summ_a", "session_id": "sess_summ_a"})
            # Check summarize turn 1 and 2 (threshold is 3)
            msg_a = AgentMessage(
                sender="api",
                recipient="MemoryAgent",
                content=f"User A turn {i}",
                metadata={"action": "check_summarize"},
                user_id="user_summ_a",
                session_id="sess_summ_a"
            )
            resp = mem_agent_summ.process(msg_a)
            assert resp.success
            assert resp.metadata.get("turns") == i + 1

        # Add 1 turn for User B (User B counter should be 1, not combining with User A)
        conv.add_turn("user", "User B turn 0: discussing baking bread", metadata={"user_id": "user_summ_b", "session_id": "sess_summ_b"})
        msg_b = AgentMessage(
            sender="api",
            recipient="MemoryAgent",
            content="User B turn 0",
            metadata={"action": "check_summarize"},
            user_id="user_summ_b",
            session_id="sess_summ_b"
        )
        resp_b = mem_agent_summ.process(msg_b)
        assert resp_b.success
        assert resp_b.metadata.get("turns") == 1, "User B turn count must NOT combine with User A"

        # Now trigger turn 3 for User A -> Threshold 3 reached!
        conv.add_turn("user", "User A turn 2: quantum physics equations finished", metadata={"user_id": "user_summ_a", "session_id": "sess_summ_a"})
        msg_a_trigger = AgentMessage(
            sender="api",
            recipient="MemoryAgent",
            content="User A turn 2",
            metadata={"action": "check_summarize"},
            user_id="user_summ_a",
            session_id="sess_summ_a"
        )
        resp_a_trigger = mem_agent_summ.process(msg_a_trigger)
        assert resp_a_trigger.success
        assert "Quantum physics summary" in resp_a_trigger.content

        # Verify User A's counter was reset to 0
        assert mem_agent_summ._unsummarized_turns.get(("user_summ_a", "sess_summ_a")) == 0
        # Verify User B's counter is still 1
        assert mem_agent_summ._unsummarized_turns.get(("user_summ_b", "sess_summ_b")) == 1

        # Verify User A's episode was created and contains User A's content, but NOT User B's content
        episodes_a = episodes.get_recent(limit=5, user_id="user_summ_a")
        assert len(episodes_a) >= 1
        summary_text = episodes_a[0].get("summary", "")
        assert "Quantum physics summary" in summary_text
        assert "baking bread" not in summary_text, "User B's turns must NEVER enter User A's summary"

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

