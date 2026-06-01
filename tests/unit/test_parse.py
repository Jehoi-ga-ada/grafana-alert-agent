"""Tests for pure Prometheus/Loki response parsers."""

from __future__ import annotations

import pytest

from gaa.clients.parse import QueryParseError, parse_instant, parse_loki


class TestParseInstant:
    def test_parses_vector_result(self):
        payload = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"job": "url-shortener", "instance": "a"}, "value": [1700000000, "1"]},
                    {"metric": {"job": "url-shortener", "instance": "b"}, "value": [1700000000, "0"]},
                ],
            },
        }
        result = parse_instant(payload)
        assert len(result.samples) == 2
        assert {s.value for s in result.samples} == {0.0, 1.0}

    def test_parses_scalar_result(self):
        payload = {"status": "success", "data": {"resultType": "scalar", "result": [1700000000, "42"]}}
        result = parse_instant(payload)
        assert result.samples[0].value == 42.0

    def test_skips_unparsable_values(self):
        payload = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {}, "value": [1, "NaN"]},
                    {"metric": {}, "value": [1, "3"]},
                ],
            },
        }
        result = parse_instant(payload)
        assert len(result.samples) == 1
        assert result.samples[0].value == 3.0

    def test_raises_on_error_status(self):
        with pytest.raises(QueryParseError):
            parse_instant({"status": "error", "error": "boom"})


class TestParseLoki:
    def test_returns_newest_first_limited(self):
        payload = {
            "status": "success",
            "data": {
                "result": [
                    {"stream": {"app": "x"}, "values": [["100", "old"], ["300", "new"]]},
                    {"stream": {"app": "y"}, "values": [["200", "mid"]]},
                ]
            },
        }
        lines = parse_loki(payload, limit=2)
        assert lines == ("new", "mid")

    def test_empty_on_failure(self):
        assert parse_loki({"status": "error"}) == ()
