"""Tests for DLPEngine."""
from __future__ import annotations

import pytest
from src.proxy.dlp import DLPEngine


@pytest.fixture
def engine():
    return DLPEngine()


# ---------------------------------------------------------------------------
# DLP detects secrets in dict values
# ---------------------------------------------------------------------------

def test_detects_api_key_in_params(engine):
    data = {"config": "api_key: sk-abcdefghijklmnopqrstuvwxyz1234567890"}
    violations = engine.scan(data)
    assert len(violations) > 0
    names = {v.pattern_name for v in violations}
    assert "API_KEY" in names


def test_detects_private_key(engine):
    data = {"key_material": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ..."}
    violations = engine.scan(data)
    assert len(violations) > 0
    names = {v.pattern_name for v in violations}
    assert "PRIVATE_KEY" in names


def test_detects_jwt_token(engine):
    # A syntactically valid JWT-like token (header.payload.signature all base64url)
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzNDU2Nzg5MCJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    data = {"token": jwt}
    violations = engine.scan(data)
    assert len(violations) > 0
    names = {v.pattern_name for v in violations}
    assert "JWT_TOKEN" in names


def test_detects_credit_card(engine):
    data = {"payment": "4111111111111111"}  # Visa test card number
    violations = engine.scan(data)
    assert len(violations) > 0
    names = {v.pattern_name for v in violations}
    assert "CREDIT_CARD" in names


# ---------------------------------------------------------------------------
# Redaction: detected values are masked in output
# ---------------------------------------------------------------------------

def test_redaction_masks_value(engine):
    data = {"key_material": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ..."}
    redacted, violations = engine.scan_and_redact(data)
    assert len(violations) > 0
    # The redacted value should differ from the original
    original = data["key_material"]
    redacted_val = redacted["key_material"]
    assert "*" in redacted_val
    assert redacted_val != original


# ---------------------------------------------------------------------------
# Clean data passes through
# ---------------------------------------------------------------------------

def test_clean_params_no_violations(engine):
    data = {"query": "python tutorials", "limit": 10, "page": 1}
    violations = engine.scan(data)
    assert violations == []


# ---------------------------------------------------------------------------
# Nested dict
# ---------------------------------------------------------------------------

def test_nested_dict_scanned(engine):
    data = {
        "outer": {
            "inner": "api_key: sk-verylongapikey1234567890abcdefghij"
        }
    }
    violations = engine.scan(data)
    assert len(violations) > 0
    # Field path should reflect nesting
    assert "outer" in violations[0].field_path
    assert "inner" in violations[0].field_path
