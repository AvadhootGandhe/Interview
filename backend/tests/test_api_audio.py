from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import audio


@pytest.fixture
def client(tmp_path, monkeypatch):
    audio_dir = tmp_path / "cache"
    audio_dir.mkdir()
    monkeypatch.setattr(audio, "AUDIO_DIR", audio_dir)
    (audio_dir / "abc123.wav").write_bytes(b"RIFFdata")
    (tmp_path / "secret.wav").write_bytes(b"secret")
    app = FastAPI()
    app.include_router(audio.router)
    return TestClient(app)


def test_serves_wav(client):
    r = client.get("/audio/abc123.wav")
    assert r.status_code == 200 and r.content == b"RIFFdata"
    assert r.headers["content-type"].startswith("audio/")


@pytest.mark.parametrize(
    "name",
    ["../secret.wav", "..%2Fsecret.wav", "%2e%2e/secret.wav", "a/b.wav", "abc123.txt", "missing.wav", ".hidden.wav"],
)
def test_rejects_traversal_and_bad_names(client, name):
    r = client.get(f"/audio/{name}")
    assert r.status_code in (400, 404)
    assert b"secret" not in r.content


def test_main_app_registers_audio_route():
    from app.main import app

    assert "/audio/{file}" in app.openapi()["paths"]
