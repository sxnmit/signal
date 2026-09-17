"""Renderers: email, plaintext, terminal, markdown, and the static site."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from signal_agent.archive import Archive
from signal_agent.models import Digest, RunStats, Section, Story
from signal_agent.render.email import render_email, render_plaintext
from signal_agent.render.markdown import render_markdown
from signal_agent.render.site import build_site
from signal_agent.render.terminal import render_terminal
from signal_agent.render.util import headline_stat, plural, time_ago


@pytest.fixture
def digest() -> Digest:
    now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    return Digest(
        generated_at=now,
        title="Signal",
        stats=RunStats(fetched=240, published=2, summarizer="extractive"),
        sections=[
            Section(
                topic="Chips & Hardware",
                slug="chips",
                icon="🔩",
                stories=[
                    Story(
                        headline="Nvidia unveils Rubin",
                        summary="Nvidia announced Rubin today.",
                        url="https://ars.example.com/rubin",
                        source="Ars Technica",
                        published=now - timedelta(hours=3),
                        corroboration=3,
                        also_covered_by=[
                            ("The Verge", "https://verge.example.com/rubin"),
                            ("WIRED", "https://wired.example.com/rubin"),
                        ],
                    )
                ],
            ),
            Section(
                topic="World",
                slug="world",
                icon="🌍",
                stories=[
                    Story(
                        headline='Talks stall over "final" terms',
                        summary="Negotiators <adjourned> without agreement.",
                        url="https://bbc.example.com/talks",
                        source="BBC World",
                        published=now - timedelta(hours=9),
                    )
                ],
            ),
        ],
    )


@pytest.fixture
def empty_digest() -> Digest:
    return Digest(generated_at=datetime(2026, 9, 17, tzinfo=UTC), sections=[])


class TestTimeAgo:
    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [(0, "just now"), (1, "just now"), (30, "30m ago"), (180, "3h ago"), (60 * 30, "1d ago")],
    )
    def test_formats(self, minutes, expected):
        now = datetime(2026, 9, 17, 12, tzinfo=UTC)
        assert time_ago(now - timedelta(minutes=minutes), now=now) == expected

    def test_missing_timestamp(self):
        assert time_ago(None) == ""

    def test_future_timestamps(self):
        now = datetime(2026, 9, 17, 12, tzinfo=UTC)
        assert time_ago(now + timedelta(hours=1), now=now) == "just now"


def test_plural():
    assert plural(1, "story", "stories") == "1 story"
    assert plural(3, "story", "stories") == "3 stories"
    assert plural(2, "topic") == "2 topics"


class TestHeadlineStat:
    def test_mentions_corroboration(self, digest):
        assert "4 outlets" not in headline_stat(digest)
        assert "3 outlets" in headline_stat(digest)

    def test_empty(self, empty_digest):
        assert headline_stat(empty_digest) == "No new stories today."


class TestEmail:
    def test_contains_the_content(self, digest):
        html = render_email(digest)
        assert "Nvidia unveils Rubin" in html
        assert "https://ars.example.com/rubin" in html
        assert "3 outlets" in html

    def test_escapes_user_content(self, digest):
        html = render_email(digest)
        # The summary contains <adjourned>; it must not become a tag.
        assert "<adjourned>" not in html
        assert "&lt;adjourned&gt;" in html

    def test_declares_dark_mode_support(self, digest):
        html = render_email(digest)
        assert 'name="color-scheme"' in html
        assert "prefers-color-scheme: dark" in html

    def test_includes_a_permalink_when_configured(self, digest):
        html = render_email(digest, base_url="https://example.github.io/signal")
        assert "https://example.github.io/signal/2026-09-17.html" in html

    def test_omits_the_permalink_otherwise(self, digest):
        assert "Read this edition on the web" not in render_email(digest)

    def test_empty_digest_renders(self, empty_digest):
        assert "Nothing new cleared the bar" in render_email(empty_digest)

    def test_is_a_complete_document(self, digest):
        html = render_email(digest)
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")


class TestPlaintext:
    def test_contains_headlines_and_links(self, digest):
        text = render_plaintext(digest)
        assert "Nvidia unveils Rubin" in text
        assert "https://ars.example.com/rubin" in text

    def test_has_no_markup(self, digest):
        assert "<" not in render_plaintext(digest).replace("<", "")

    def test_notes_corroboration(self, digest):
        assert "3 outlets" in render_plaintext(digest)


class TestTerminal:
    def test_plain_output_has_no_escape_codes(self, digest):
        out = render_terminal(digest, color=False, width=80)
        assert "\033" not in out
        assert "Nvidia unveils Rubin" in out

    def test_colour_output_has_escape_codes(self, digest):
        assert "\033" in render_terminal(digest, color=True, width=80)

    def test_wraps_to_width(self, digest):
        for line in render_terminal(digest, color=False, width=60).splitlines():
            assert len(line) <= 70

    def test_empty(self, empty_digest):
        assert "Nothing new" in render_terminal(empty_digest, color=False, width=80)


class TestMarkdown:
    def test_links_and_headings(self, digest):
        md = render_markdown(digest)
        assert "# Signal" in md
        assert "[Nvidia unveils Rubin](https://ars.example.com/rubin)" in md
        assert "Also covered by" in md

    def test_escapes_link_labels(self):
        digest = Digest(
            generated_at=datetime(2026, 9, 17, tzinfo=UTC),
            sections=[
                Section(
                    topic="T",
                    slug="t",
                    icon="x",
                    stories=[
                        Story(
                            headline="Brackets [here] break links",
                            summary="s",
                            url="https://e.com/a",
                            source="E",
                        )
                    ],
                )
            ],
        )
        assert "\\[here\\]" in render_markdown(digest)

    def test_heading_level(self, digest):
        assert render_markdown(digest, heading_level=2).startswith("## ")


class TestSite:
    def test_builds_every_expected_file(self, digest, tmp_path):
        root = build_site([digest], tmp_path / "site")

        for name in ("index.html", "style.css", "app.js", "search.json", ".nojekyll"):
            assert (root / name).is_file(), name
        assert (root / "2026-09-17.html").is_file()

    def test_index_mirrors_the_newest_edition(self, digest, tmp_path):
        older = Digest(
            generated_at=datetime(2026, 9, 10, tzinfo=UTC),
            sections=[
                Section(
                    topic="Old",
                    slug="old",
                    icon="x",
                    stories=[
                        Story(
                            headline="Older story",
                            summary="s",
                            url="https://e.com/o",
                            source="E",
                        )
                    ],
                )
            ],
        )
        root = build_site([older, digest], tmp_path / "site")

        index = (root / "index.html").read_text()
        assert "Nvidia unveils Rubin" in index
        assert "Older story" not in index

    def test_search_index_covers_every_edition(self, digest, tmp_path):
        root = build_site([digest], tmp_path / "site")
        entries = json.loads((root / "search.json").read_text())

        assert len(entries) == 2
        assert {e["h"] for e in entries} == {
            "Nvidia unveils Rubin",
            'Talks stall over "final" terms',
        }

    def test_escapes_content(self, digest, tmp_path):
        root = build_site([digest], tmp_path / "site")
        assert "<adjourned>" not in (root / "index.html").read_text()

    def test_empty_archive_still_builds(self, tmp_path):
        root = build_site([], tmp_path / "site")
        assert "No editions yet" in (root / "index.html").read_text()

    def test_canonical_link_when_base_url_is_set(self, digest, tmp_path):
        root = build_site([digest], tmp_path / "site", base_url="https://example.com/signal")
        assert 'rel="canonical"' in (root / "2026-09-17.html").read_text()


class TestArchive:
    def test_round_trip(self, digest, tmp_path):
        archive = Archive(tmp_path / "archive")
        archive.write(digest)

        restored = archive.read("2026-09-17")
        assert restored is not None
        assert restored.story_count == digest.story_count

    def test_latest_picks_the_newest(self, digest, tmp_path):
        archive = Archive(tmp_path / "archive")
        archive.write(digest)
        archive.write(Digest(generated_at=datetime(2026, 9, 10, tzinfo=UTC), sections=[]))

        assert archive.latest().date_slug == "2026-09-17"

    def test_rerun_replaces_the_day(self, digest, tmp_path):
        archive = Archive(tmp_path / "archive")
        archive.write(digest)
        archive.write(digest)
        assert archive.dates() == ["2026-09-17"]

    def test_sent_urls_includes_corroborating_links(self, digest, tmp_path):
        archive = Archive(tmp_path / "archive")
        archive.write(digest)

        urls = archive.sent_urls()
        assert "https://ars.example.com/rubin" in urls
        assert "https://verge.example.com/rubin" in urls

    def test_missing_and_corrupt_files(self, tmp_path):
        archive = Archive(tmp_path / "archive")
        assert archive.read("2026-01-01") is None
        assert archive.latest() is None
        assert archive.dates() == []

        archive.directory.mkdir(parents=True)
        (archive.directory / "2026-01-01.json").write_text("{ broken")
        assert archive.read("2026-01-01") is None
