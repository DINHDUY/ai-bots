"""Behave lifecycle for the Azure Blob ETL use cases."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "agentbot" / "src"))
sys.path.insert(0, str(ROOT))

from docs.usecases.tests.behavior import support


def before_all(context) -> None:
    support.boot(context)


def before_scenario(context, scenario) -> None:
    support.reset(context)


def before_step(context, step) -> None:
    context.step_kind = step.step_type


def after_scenario(context, scenario) -> None:
    support.cleanup_scenario(context)


def after_all(context) -> None:
    support.shutdown(context)
