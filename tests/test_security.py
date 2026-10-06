"""Mots de passe et tokens JWT (shared/security.py)."""

import time

import jwt
import pytest

from shared import security
from shared.config import settings


def test_le_mot_de_passe_est_hashe_puis_verifie():
    stored = security.hash_password("s3cret-pass")
    assert "s3cret-pass" not in stored
    assert security.verify_password("s3cret-pass", stored)


def test_un_mauvais_mot_de_passe_est_refuse():
    stored = security.hash_password("s3cret-pass")
    assert not security.verify_password("other-pass", stored)


def test_le_token_contient_le_compte():
    payload = security.decode_token(security.create_token("camille@vendor.fr", 3))
    assert payload["account_id"] == 3
    assert payload["sub"] == "camille@vendor.fr"


def test_un_token_expire_est_refuse():
    token = jwt.encode({"sub": "a@b.fr", "account_id": 1, "exp": int(time.time()) - 10},
                       settings.jwt_secret, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)


def test_un_token_signe_avec_un_autre_secret_est_refuse():
    token = jwt.encode({"sub": "a@b.fr", "account_id": 1, "exp": int(time.time()) + 60},
                       "another-secret-that-is-also-long-enough-123", algorithm="HS256")
    with pytest.raises(jwt.InvalidSignatureError):
        security.decode_token(token)


def test_un_secret_trop_court_est_refuse(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "too-short")
    with pytest.raises(RuntimeError):
        security.create_token("a@b.fr", 1)
