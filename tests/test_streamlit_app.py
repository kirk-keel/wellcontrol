"""Run the Streamlit app headlessly and check it renders without exceptions.

Uses Streamlit's own ``AppTest`` harness, which executes the script the same way
the server does. Skipped when streamlit is not installed, so the core test suite
stays dependency-free.
"""

from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

_APP_DIR = Path(__file__).resolve().parent.parent / "app"
APP = _APP_DIR / "streamlit_app.py"
PLANNER = _APP_DIR / "views" / "planner.py"
LEARN = _APP_DIR / "views" / "learn.py"

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
    """Run the planner page directly.

    The pages are separate scripts, so each can be exercised on its own
    rather than only through whichever one navigation happens to open.
    """
    app = AppTest.from_file(str(PLANNER), default_timeout=90)
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


def test_navigation_entry_renders():
    """The entry script wires the two pages together and opens the planner."""
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.run()
    assert not app.exception, f"entry script raised: {app.exception}"
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


def test_every_method_offers_a_link_to_its_chapter():
    """Each plan should carry a button through to the theory."""
    from wellcontrol.methods import METHODS

    for method in METHODS:
        app = _run(method=method.name)
        labels = [b.label for b in app.button]
        assert any("Read the theory" in label for label in labels), (
            f"{method.name} has no chapter link"
        )


def test_chapter_link_names_the_right_chapter():
    from wellcontrol import content
    from wellcontrol.methods import get_method

    app = _run(method="Stripping to Bottom")
    expected = content.chapter_title(get_method("stripping").chapter)
    assert any(expected in b.label for b in app.button)


@pytest.mark.parametrize("method_name,expected_chapter", [
    ("Wait and Weight", "06-circulation-methods.md"),
    ("Driller's Method", "06-circulation-methods.md"),
    ("Stripping to Bottom", "13-stripping.md"),
    ("Bullheading", "12-choosing-a-kill-method.md"),
])
def test_clicking_the_link_selects_that_chapter(method_name, expected_chapter):
    """Regression: the link was wired to an on_click callback, and
    st.switch_page is a rerun, which Streamlit makes a no-op inside callbacks.
    Clicking silently did nothing. Asserting the button merely *exists* did
    not catch it -- this clicks it.
    """
    app = _run(method=method_name)
    link = next(b for b in app.button if "Read the theory" in b.label)
    link.click().run()
    assert not app.exception
    assert app.session_state["learn_chapter"] == expected_chapter


class TestScheduleSection:
    def test_segment_table_shown_for_circulating_methods(self):
        app = _run(method="Wait and Weight")
        headers = " ".join(str(s.value) for s in app.subheader)
        assert "by section" in headers

    def test_lateral_reversal_is_warned_about(self):
        """On a horizontal well the schedule reverses in the lateral; the app
        must say so rather than leaving it in a table to be noticed."""
        app = _run(config="Surface BOP - Horizontal", method="Wait and Weight")
        warnings = " ".join(str(w.value) for w in app.warning)
        assert "TAKE UP" in warnings or "taken UP" in warnings

    def test_no_reversal_warning_on_a_vertical_well(self):
        app = _run(config="Surface BOP - Vertical", method="Wait and Weight")
        warnings = " ".join(str(w.value) for w in app.warning)
        assert "taken UP" not in warnings

    def test_not_shown_for_non_circulating_methods(self):
        app = _run(method="Bullheading")
        headers = " ".join(str(s.value) for s in app.subheader)
        assert "by section" not in headers


class TestStripThenKillSection:
    def _off_bottom(self, method="Stripping to Bottom"):
        app = AppTest.from_file(str(PLANNER), default_timeout=90)
        app.run()
        app.selectbox[1].set_value(method)
        bit = next(w for w in app.number_input if "Bit depth" in w.label)
        bit.set_value(8500.0)
        app.run()
        return app

    def test_follow_on_section_appears_when_stripping_is_usable(self):
        app = self._off_bottom()
        assert not app.exception
        headers = " ".join(str(s.value) for s in app.subheader)
        assert "Then kill the well" in headers

    def test_offers_both_circulating_methods(self):
        app = self._off_bottom()
        follow_on = next(
            r for r in app.radio if "once on bottom" in r.label
        )
        # AppTest reports the formatted labels rather than the underlying keys.
        assert list(follow_on.options) == ["Driller's Method", "Wait and Weight"]

    def test_totals_cover_both_phases(self):
        app = self._off_bottom()
        labels = " ".join(str(m.label) for m in app.metric)
        assert "Total time, both phases" in labels
        assert "Worst phase" in labels

    def test_absent_when_stripping_is_blocked(self):
        """Bit on bottom means nothing to strip, so no follow-on either."""
        app = _run(method="Stripping to Bottom")
        headers = " ".join(str(s.value) for s in app.subheader)
        assert "Then kill the well" not in headers

    def test_absent_for_other_methods(self):
        app = _run(method="Driller's Method")
        headers = " ".join(str(s.value) for s in app.subheader)
        assert "Then kill the well" not in headers


# --------------------------------------------------------------------------
# Learn page
# --------------------------------------------------------------------------

class TestLearnPage:
    def _learn(self, chapter: str | None = None):
        app = AppTest.from_file(str(LEARN), default_timeout=90)
        if chapter is not None:
            app.session_state["learn_chapter"] = chapter
        app.run()
        return app

    def test_renders(self):
        app = self._learn()
        assert not app.exception, f"learn page raised: {app.exception}"
        assert any("theory" in str(t.value).lower() for t in app.title)

    def test_lists_every_chapter(self):
        from wellcontrol import content

        app = self._learn()
        assert len(app.sidebar.radio[0].options) == len(content.chapter_files())

    @pytest.mark.parametrize("chapter", __import__(
        "wellcontrol.content", fromlist=["content"]).chapter_files())
    def test_every_chapter_renders(self, chapter):
        app = self._learn(chapter)
        assert not app.exception, f"{chapter} raised: {app.exception}"
        assert app.markdown, f"{chapter} rendered nothing"

    def test_opens_at_the_requested_chapter(self):
        from wellcontrol import content

        app = self._learn("13-stripping.md")
        expected = content.chapter_title("13-stripping.md")
        assert any(expected in str(s.value) for s in app.subheader)

    def test_unknown_chapter_falls_back_to_the_first(self):
        app = self._learn("99-does-not-exist.md")
        assert not app.exception
        assert app.session_state["learn_chapter"].startswith("01-")

    def test_navigation_buttons_present(self):
        from wellcontrol import content

        files = content.chapter_files()
        first = self._learn(files[0])
        assert len(first.button) == 1          # next only

        middle = self._learn(files[5])
        assert len(middle.button) == 2         # previous and next

        last = self._learn(files[-1])
        assert len(last.button) == 1           # previous only

    def test_rendered_body_has_no_dead_relative_links(self):
        app = self._learn("06-circulation-methods.md")
        body = " ".join(str(m.value) for m in app.markdown)
        assert ".md)" not in body


def test_impossible_geometry_is_reported_not_raised():
    """A shoe deeper than total depth must produce a message, not a traceback."""
    app = AppTest.from_file(str(PLANNER), default_timeout=90)
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
