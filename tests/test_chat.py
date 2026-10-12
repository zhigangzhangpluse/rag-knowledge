"""验证 SSE 协议、拒答、引用和历史上下文传递。"""
import json

from tests.conftest import upload_ready


def events(response):
    result = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        result.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return result


def test_empty_kb_refuses_without_llm(client, kb, monkeypatch):
    def forbidden(*args):
        raise AssertionError("空知识库不应调用生成模型")

    monkeypatch.setattr(client.app.state.services.chat.llm, "stream", forbidden)
    response = client.post(f"/api/knowledge-bases/{kb}/chat", json={"question": "请告诉我薪资"})
    output = dict(events(response))
    assert output["done"]["refused"]
    assert output["sources"]["items"] == []
    assert "证据不足" in output["delta"]["text"]


def test_sources_history_and_session_isolation(client, kb, monkeypatch):
    upload_ready(client, kb, "# 年假规定\n员工每年可以申请五天年假。试用期不能申请年假。")
    session_id = "a" * 32
    path = f"/api/knowledge-bases/{kb}/chat"
    response = client.post(path, json={"question": "年假几天？", "session_id": session_id})
    output = events(response)
    sources = next(data["items"] for kind, data in output if kind == "sources")
    answer = "".join(data["text"] for kind, data in output if kind == "delta")
    assert sources and "[1]" in answer
    assert output[-1][0] == "done"
    services = client.app.state.services
    assert len(services.sessions.get(kb, session_id)) == 2
    captured = []

    def rewrite(question, history):
        captured.extend(history)
        return "试用期能否申请年假？"

    monkeypatch.setattr(services.chat.llm, "rewrite", rewrite)
    response = client.post(path, json={"question": "试用期也可以吗？", "session_id": session_id})
    assert captured[0]["content"] == "年假几天？"
    assert dict(events(response))["done"]["session_id"] == session_id
    assert not services.sessions.get("another-kb", session_id)
    assert client.delete(f"/api/knowledge-bases/{kb}/sessions/{session_id}").status_code == 200
    assert not services.sessions.get(kb, session_id)


def test_model_failure_has_error_and_no_history(client, kb, monkeypatch):
    upload_ready(client, kb, "# 年假\n年假每年五天。")
    services = client.app.state.services

    def broken(*args):
        raise TimeoutError("do not leak provider details")

    monkeypatch.setattr(services.chat.llm, "stream", broken)
    response = client.post(f"/api/knowledge-bases/{kb}/chat", json={"question": "年假几天", "session_id": "b" * 32})
    output = dict(events(response))
    assert "error" in output and "done" not in output
    assert "do not leak" not in response.text
    assert not services.sessions.get(kb, "b" * 32)
