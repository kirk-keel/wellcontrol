"""Run the Streamlit app headlessly and check it renders without exceptions.

Uses Streamlit's own ``AppTest`` harness, which executes the script the same way
the server does. Skipped when streamlit is not installed, so the core test suite
stays dependency-free.
"""

from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

APP = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"

CONFIG_LABELS = [
    "Surface BOP - Vertical",
    "Surface BOP - Horizontal",
    "Subsea BOP - Vertical",
    "Subsea BOP - Horizontal",
]

METHOD_LABELS = [
    "Driller's Method",
    "Wait and Weight",
    "Volumetric Method",
    "Stripping to Bottom",
    "Lube and Bleed",
    "Reverse Circulation",
    "Bullheading",
]


def _run(config: str | None = None, method: str | None = None):
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.run()
    assert not app.exception, f"initial render raised: {app.exception}"
    if config is not None:
        app.selectbox[0].set_value(config)
    if method is not None:
        app.selectbox[1].set_value(method)
    if config is not None or method is not None:
        app.run()
    return app


def test_app_renders():
    app = _run()
    assert not app.exception
    assert any("Well Control Kill Planner" in str(t.value) for t in app.title)


@pytest.mark.parametrize("config", CONFIG_LABELS)
def test_every_configuration_renders(config):
    app = _run(config=config)
    assert not app.exception, f"{config} raised: {app.exception}"


@pytest.mark.parametrize("method", METHOD_LABELS)
def test_every_method_renders(method):
    app = _run(method=method)
    assert not app.exception, f"{method} raised: {app.exception}"


@pytest.mark.parametrize("config", CONFIG_LABELS)
@pytest.mark.parametrize("method", METHOD_LABELS)
def test_full_matrix_renders(config, method):
    """All 24 combinations of well type and kill method."""
    app = _run(config=config, method=method)
    assert not app.exception, f"{config} / {method} raised: {app.exception}"


def test_blocked_combination_shows_an_error():
    """Volumetric on a horizontal well must be reported as unusable."""
    app = _run(config="Surface BOP - Horizontal", method="Volumetric Method")
    assert not app.exception
    errors = " ".join(str(e.value) for e in app.error)
    assert "not usable" in errors.lower()


def test_workable_combination_shows_no_error():
    app = _run(config="Surface BOP - Vertical", method="Wait and Weight")
    assert not app.exception
    assert len(app.error) == 0


def test_impossible_geometry_is_reported_not_raised():
    """A shoe deeper than total depth must produce a message, not a traceback."""
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.run()
    # Casing shoe below total depth.
    shoe = next(
        widget for widget in app.number_input
        if "Casing shoe" in widget.label
    )
    shoe.set_value(20000.0)
    app.run()
    assert not app.exception, "bad geometry should be caught, not raised"
    assert len(app.error) > 0
