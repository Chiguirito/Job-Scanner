from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import Job
from src.scorer import JobScorer, _parse_response


def _make_job(**kwargs) -> Job:
    defaults = dict(
        title="Software Engineer",
        url="https://example.com/jobs/1",
        company="Acme",
        ats_job_id="job-1",
        location="Munich, Germany",
        department="Engineering",
        description="Build cool things with Python.",
    )
    return Job(**{**defaults, **kwargs})


def _mock_api_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content[0].text = text
    return msg


class TestParseResponse:
    def test_parses_score_and_reason(self) -> None:
        score, reason = _parse_response("SCORE: 85\nREASON: Strong backend match.")
        assert score == 85
        assert reason == "Strong backend match."

    def test_handles_extra_whitespace(self) -> None:
        score, reason = _parse_response("  SCORE:  72  \n  REASON:  Partial match.  ")
        assert score == 72
        assert reason == "Partial match."

    def test_returns_defaults_on_empty(self) -> None:
        score, reason = _parse_response("")
        assert score == 0
        assert reason == ""


class TestJobScorer:
    def test_score_returns_int_and_str(self, tmp_path: Path) -> None:
        profile_file = tmp_path / "profile.md"
        profile_file.write_text("Experienced Python engineer.")

        with (
            patch.dict("os.environ", {"CANDIDATE_PROFILE_PATH": str(profile_file)}),
            patch("anthropic.Anthropic") as mock_cls,
        ):
            mock_cls.return_value.messages.create.return_value = _mock_api_response(
                "SCORE: 90\nREASON: Excellent match."
            )
            score, reason = JobScorer().score(_make_job())

        assert score == 90
        assert reason == "Excellent match."

    def test_passes_job_fields_to_prompt(self, tmp_path: Path) -> None:
        profile_file = tmp_path / "profile.md"
        profile_file.write_text("Profile content.")
        job = _make_job(title="Data Engineer", company="BigCorp", location="Berlin")

        with (
            patch.dict("os.environ", {"CANDIDATE_PROFILE_PATH": str(profile_file)}),
            patch("anthropic.Anthropic") as mock_cls,
        ):
            mock_cls.return_value.messages.create.return_value = _mock_api_response(
                "SCORE: 70\nREASON: Good fit."
            )
            JobScorer().score(job)
            call_kwargs = mock_cls.return_value.messages.create.call_args
            prompt = call_kwargs[1]["messages"][0]["content"]

        assert "Data Engineer" in prompt
        assert "BigCorp" in prompt
        assert "Berlin" in prompt

    def test_raises_if_profile_path_not_set(self) -> None:
        with patch.dict("os.environ", {"CANDIDATE_PROFILE_PATH": ""}):
            with pytest.raises(RuntimeError, match="CANDIDATE_PROFILE_PATH"):
                JobScorer().score(_make_job())

    def test_raises_if_profile_file_missing(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"CANDIDATE_PROFILE_PATH": str(tmp_path / "missing.md")}):
            with pytest.raises(FileNotFoundError):
                JobScorer().score(_make_job())
