"""Teaching content tests.

Two jobs: check the chapters are structurally sound, and check that every kill
method points at a chapter that actually exists. The second is the one that
matters -- a method whose `chapter` attribute names a missing file would give
the reader a dead button.
"""

import pytest

from wellcontrol import content
from wellcontrol.methods import METHODS

CHAPTERS = content.chapter_files()


class TestChapterDiscovery:
    def test_chapters_are_found(self):
        assert CHAPTERS, f"no chapters found in {content.DEFAULT_CONTENT_DIR}"

    def test_thirteen_chapters(self):
        assert len(CHAPTERS) == 13

    def test_returned_in_reading_order(self):
        assert CHAPTERS == sorted(CHAPTERS)
        assert CHAPTERS[0].startswith("01-")
        assert CHAPTERS[-1].startswith("13-")

    def test_missing_directory_returns_empty(self, tmp_path):
        assert content.chapter_files(tmp_path / "nope") == []

    def test_readme_index_is_excluded(self):
        """It is a table of links, which is what does not survive rendering."""
        assert "README.md" not in CHAPTERS


@pytest.mark.parametrize("filename", CHAPTERS)
class TestEveryChapter:
    def test_has_a_title(self, filename):
        title = content.chapter_title(filename)
        assert title
        assert not title.startswith("#")

    def test_body_is_substantial(self, filename):
        assert len(content.chapter_body(filename)) > 500

    def test_body_drops_the_h1(self, filename):
        assert not content.chapter_body(filename).startswith("# ")

    def test_body_drops_the_footer_navigation(self, filename):
        body = content.chapter_body(filename)
        tail = body[-400:]
        assert "Previous:" not in tail
        assert "Next:" not in tail

    def test_body_has_no_relative_links_left(self, filename):
        """Relative links would 404 when rendered outside GitHub."""
        import re

        leftover = re.findall(r"\[[^\]]+\]\((?!https?://)[^)]*\)",
                              content.chapter_body(filename))
        assert leftover == [], f"unrewritten local links: {leftover}"


class TestLinkRewriting:
    def test_relative_link_reduced_to_text(self):
        assert content.strip_local_links(
            "see [Hydrostatics](02-hydrostatics.md) for more"
        ) == "see Hydrostatics for more"

    def test_absolute_links_are_kept(self):
        original = "see [the docs](https://example.com/page) for more"
        assert content.strip_local_links(original) == original

    def test_parent_relative_link_reduced(self):
        assert content.strip_local_links("[index](../README.md)") == "index"

    def test_multiple_links_on_one_line(self):
        assert content.strip_local_links(
            "[A](01-a.md) and [B](02-b.md)"
        ) == "A and B"

    def test_text_without_links_is_unchanged(self):
        assert content.strip_local_links("plain text") == "plain text"


class TestMissingFiles:
    def test_title_falls_back_to_the_filename(self):
        assert content.chapter_title("99-not-here.md") == "99 not here"

    def test_body_reports_rather_than_raises(self):
        body = content.chapter_body("99-not-here.md")
        assert "Could not read" in body

    def test_chapter_exists(self):
        assert content.chapter_exists(CHAPTERS[0])
        assert not content.chapter_exists("99-not-here.md")


class TestMethodChapterLinks:
    """Every method must point at a chapter that exists."""

    @pytest.mark.parametrize("method", METHODS, ids=[m.key for m in METHODS])
    def test_chapter_is_set(self, method):
        assert method.chapter

    @pytest.mark.parametrize("method", METHODS, ids=[m.key for m in METHODS])
    def test_chapter_file_exists(self, method):
        assert content.chapter_exists(method.chapter), (
            f"{method.name} points at {method.chapter}, which is not in "
            f"{content.DEFAULT_CONTENT_DIR}"
        )

    @pytest.mark.parametrize("method", METHODS, ids=[m.key for m in METHODS])
    def test_chapter_depth_is_honest(self, method):
        assert method.chapter_depth in ("in depth", "in context")

    def test_circulating_methods_point_at_the_circulation_chapter(self):
        from wellcontrol.methods import get_method

        for key in ("drillers", "wait_and_weight"):
            method = get_method(key)
            assert method.chapter == "06-circulation-methods.md"
            assert method.chapter_depth == "in depth"

    def test_stripping_points_at_its_own_chapter(self):
        from wellcontrol.methods import get_method

        assert get_method("stripping").chapter == "13-stripping.md"
        assert get_method("stripping").chapter_depth == "in depth"

    def test_methods_without_a_dedicated_chapter_say_in_context(self):
        """Lube and Bleed, Reverse and Bullhead are covered comparatively in
        the 'choosing a method' chapter, not in depth. The link should not
        over-promise."""
        from wellcontrol.methods import get_method

        for key in ("lube_and_bleed", "reverse", "bullhead"):
            method = get_method(key)
            assert method.chapter == "12-choosing-a-kill-method.md"
            assert method.chapter_depth == "in context"

    def test_every_method_name_appears_in_its_chapter(self):
        """A weak but useful check: the chapter should at least mention the
        method it claims to explain."""
        for method in METHODS:
            body = content.chapter_body(method.chapter)
            # Match on the distinctive first word to survive minor rewording.
            keyword = method.name.split()[0].rstrip("'s")
            assert keyword.lower() in body.lower(), (
                f"{method.chapter} never mentions '{keyword}'"
            )
