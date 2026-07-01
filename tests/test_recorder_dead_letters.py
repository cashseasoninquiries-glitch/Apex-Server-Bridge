"""
Tests for recorder/recorder.py — write_dead_letter() (Master Task Order 15.12).
"""
import json

import pytest

import recorder


class _StubCursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, query, params):
        self.sink.append((query, params))


class _StubConn:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def cursor(self):
        return _StubCursor(self.sink)


@pytest.fixture
def db_sink(monkeypatch):
    sink = []
    monkeypatch.setattr(recorder, "get_db_conn", lambda: _StubConn(sink))
    return sink


def test_write_dead_letter_inserts_with_recorder_source(db_sink):
    recorder.write_dead_letter({"ticker": "AAPL"}, "boom")
    assert len(db_sink) == 1
    query, params = db_sink[0]
    assert "INSERT INTO dead_letters" in query
    source, raw_payload, error_message = params
    assert source == "recorder"
    assert error_message == "boom"


def test_write_dead_letter_json_encodes_dict_payloads(db_sink):
    recorder.write_dead_letter({"ticker": "AAPL", "action": "LONG"}, "err")
    _, (_, raw_payload, _) = db_sink[0]
    assert json.loads(raw_payload) == {"ticker": "AAPL", "action": "LONG"}


def test_write_dead_letter_stringifies_bytes_payload_without_crashing(db_sink):
    recorder.write_dead_letter(b'{"not": "valid json', "json decode error")
    _, (_, raw_payload, _) = db_sink[0]
    assert isinstance(raw_payload, str)
    assert "not" in raw_payload


def test_write_dead_letter_handles_none_payload(db_sink):
    recorder.write_dead_letter(None, "no payload at all")
    _, (_, raw_payload, _) = db_sink[0]
    assert raw_payload == "None"


def test_write_dead_letter_swallows_db_outage_without_raising(monkeypatch):
    monkeypatch.setattr(
        recorder,
        "get_db_conn",
        lambda: (_ for _ in ()).throw(ConnectionError("db unreachable")),
    )
    recorder.write_dead_letter({"ticker": "AAPL"}, "original error")
