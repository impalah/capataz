"""Smoke test for the ASGI entry point: main.py is a thin wrapper around create_app()."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

import capataz_api.main as main_module
from capataz_api.main import app


def test_app_is_a_fastapi_instance_with_expected_title() -> None:
    assert isinstance(app, FastAPI)
    assert app.title == "Capataz API"
    assert app.openapi_url == "/api/v1/openapi.json"


def test_run_starts_uvicorn_with_settings_derived_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_uvicorn = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)
    fake_settings = MagicMock(api_host="0.0.0.0", api_port=8000, env="production")
    monkeypatch.setattr(main_module, "get_settings", lambda: fake_settings)

    main_module.run()

    fake_uvicorn.run.assert_called_once_with(
        "capataz_api.main:app", host="0.0.0.0", port=8000, reload=False
    )
