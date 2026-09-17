"""The command line surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signal_agent.cli import main


@pytest.fixture(autouse=True)
def in_tmp_dir(tmp_path, monkeypatch):
    """Run every CLI test inside a scratch directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _isolated_config(tmp_path: Path) -> Path:
    """A config that writes only inside the scratch directory."""
    path = tmp_path / "signal.toml"
    path.write_text(
        f"""
[store]
path = "{(tmp_path / "signal.db").as_posix()}"

[archive]
directory = "{(tmp_path / "archive").as_posix()}"

[site]
directory = "{(tmp_path / "site").as_posix()}"

[email]
enabled = false

[newsapi]
enabled = false

[hackernews]
enabled = false
""",
        encoding="utf-8",
    )
    return path


class TestHelpAndVersion:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert "signal" in capsys.readouterr().out

    def test_no_command_exits_with_usage(self):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code != 0


class TestDemo:
    def test_prints_a_digest(self, capsys):
        assert main(["demo", "-q"]) == 0
        assert "SIGNAL" in capsys.readouterr().out

    def test_touches_nothing(self, in_tmp_dir, capsys):
        main(["demo", "-q"])
        capsys.readouterr()
        assert list(in_tmp_dir.iterdir()) == []

    def test_markdown_format(self, capsys):
        assert main(["demo", "-q", "--format", "markdown"]) == 0
        assert "# Signal" in capsys.readouterr().out

    def test_html_format_writes_a_file(self, in_tmp_dir, capsys):
        main(["demo", "-q", "--format", "html", "--output", "out.html"])
        capsys.readouterr()
        assert (in_tmp_dir / "out.html").read_text().startswith("<!DOCTYPE html>")


class TestInit:
    def test_writes_config_and_env_example(self, in_tmp_dir, capsys):
        assert main(["init", "-q"]) == 0
        capsys.readouterr()

        assert (in_tmp_dir / "signal.toml").is_file()
        assert (in_tmp_dir / ".env.example").is_file()
        assert "[[topics]]" in (in_tmp_dir / "signal.toml").read_text()

    def test_refuses_to_clobber(self, in_tmp_dir, capsys):
        main(["init", "-q"])
        capsys.readouterr()
        assert main(["init", "-q"]) == 1

    def test_force_overwrites(self, in_tmp_dir, capsys):
        main(["init", "-q"])
        (in_tmp_dir / "signal.toml").write_text("title = 'clobbered'")
        assert main(["init", "-q", "--force"]) == 0
        capsys.readouterr()
        assert "clobbered" not in (in_tmp_dir / "signal.toml").read_text()

    def test_written_config_loads(self, in_tmp_dir, capsys):
        main(["init", "-q"])
        capsys.readouterr()
        from signal_agent.config import Config

        assert Config.load(in_tmp_dir / "signal.toml").topics


class TestRunAndPreview:
    def test_dry_run_with_no_sources_succeeds(self, in_tmp_dir, capsys):
        config = _isolated_config(in_tmp_dir)
        # Every provider is disabled, so this fetches nothing and delivers nothing.
        assert main(["run", "-q", "--dry-run", "-c", str(config)]) == 0

    def test_preview_without_an_archive_fails_cleanly(self, in_tmp_dir):
        config = _isolated_config(in_tmp_dir)
        assert main(["preview", "-q", "-c", str(config)]) == 1

    def test_preview_renders_an_archived_edition(self, in_tmp_dir, capsys):
        config = _isolated_config(in_tmp_dir)
        _seed_archive(in_tmp_dir / "archive")

        assert main(["preview", "-q", "-c", str(config)]) == 0
        assert "Seeded story" in capsys.readouterr().out

    def test_preview_accepts_a_date(self, in_tmp_dir, capsys):
        config = _isolated_config(in_tmp_dir)
        _seed_archive(in_tmp_dir / "archive")

        assert main(["preview", "-q", "2026-09-17", "-c", str(config)]) == 0
        assert "Seeded story" in capsys.readouterr().out

    def test_preview_rejects_a_missing_date(self, in_tmp_dir):
        config = _isolated_config(in_tmp_dir)
        _seed_archive(in_tmp_dir / "archive")
        assert main(["preview", "-q", "1999-01-01", "-c", str(config)]) == 1


class TestSite:
    def test_builds_from_the_archive(self, in_tmp_dir, capsys):
        config = _isolated_config(in_tmp_dir)
        _seed_archive(in_tmp_dir / "archive")

        assert main(["site", "-q", "-c", str(config)]) == 0
        capsys.readouterr()
        assert (in_tmp_dir / "site" / "index.html").is_file()
        assert "Seeded story" in (in_tmp_dir / "site" / "index.html").read_text()


class TestStats:
    def test_reports_an_empty_database(self, in_tmp_dir, capsys):
        config = _isolated_config(in_tmp_dir)
        assert main(["stats", "-q", "-c", str(config)]) == 0
        assert "Articles" in capsys.readouterr().out


def test_bad_config_path_exits_two(in_tmp_dir):
    assert main(["stats", "-q", "-c", str(in_tmp_dir / "missing.toml")]) == 2


def _seed_archive(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "title": "Signal",
        "generated_at": "2026-09-17T12:00:00+00:00",
        "date": "2026-09-17",
        "stats": {"fetched": 10, "published": 1},
        "sections": [
            {
                "topic": "World",
                "slug": "world",
                "icon": "🌍",
                "stories": [
                    {
                        "headline": "Seeded story",
                        "summary": "It happened.",
                        "url": "https://example.com/a",
                        "source": "BBC",
                        "corroboration": 1,
                        "also_covered_by": [],
                    }
                ],
            }
        ],
    }
    (directory / "2026-09-17.json").write_text(json.dumps(payload), encoding="utf-8")
