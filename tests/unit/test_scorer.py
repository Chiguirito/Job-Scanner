from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import HardRequirements, Job, SearchConfig, SoftRequirements
from src.scorer import JobScorer, _parse_json_response


def _make_job(**kwargs) -> Job:
    defaults = dict(
        title="Engineering Manager",
        url="https://example.com/jobs/1",
        company="Acme",
        ats_job_id="job-1",
        location="Munich, Germany",
        department="Engineering",
        description="Lead a team of engineers building backend systems.",
    )
    return Job(**{**defaults, **kwargs})


def _make_search(tmp_path: Path, **kwargs) -> SearchConfig:
    profile_file = tmp_path / "profile.md"
    if not profile_file.exists():
        profile_file.write_text("Experienced engineering manager with 8 years in backend.")
    defaults = dict(
        name="EM Germany",
        regions=["Germany"],
        profile_path=str(profile_file),
        hard=HardRequirements(salary_min=150_000, title_keywords=["engineering manager"]),
        soft=SoftRequirements(prefers_remote=True),
    )
    defaults.update(kwargs)
    return SearchConfig(**defaults)


def _mock_llm(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content[0].text = text
    return msg


class TestParseJsonResponse:
    def test_parses_valid_json(self) -> None:
        result = _parse_json_response('{"fit_score": 80, "hard_fail": false}')
        assert result["fit_score"] == 80
        assert result["hard_fail"] is False

    def test_extracts_json_from_surrounding_text(self) -> None:
        text = 'Here is the result:\n{"fit_score": 75}\nDone.'
        assert _parse_json_response(text)["fit_score"] == 75

    def test_returns_empty_dict_on_invalid_json(self) -> None:
        assert _parse_json_response("not json at all") == {}

    def test_returns_empty_dict_on_empty_string(self) -> None:
        assert _parse_json_response("") == {}


class TestJobScorerStage1:
    def test_title_mismatch_is_hard_fail(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path)
        job = _make_job(title="Software Engineer")  # doesn't match "engineering manager"
        scorer = JobScorer()

        result = scorer.score(job, search)

        assert result.hard_fail is True
        assert result.fit_score == 0
        assert result.desirability_score == 0
        assert result.stage_reached == 1

    def test_title_match_passes_stage1(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path)
        job = _make_job(title="Senior Engineering Manager")

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm(
                '{"fit_score": 85, "fit_reasoning": "Good.", '
                '"desirability_score": 70, "desirability_reasoning": "OK.", '
                '"hard_fail": false, "hard_fail_reason": ""}'
            )
            result = JobScorer().score(job, search)

        assert result.hard_fail is False
        assert result.stage_reached == 3

    def test_no_title_keywords_skips_stage1(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, hard=HardRequirements())  # no keywords
        job = _make_job(title="Janitor")  # would fail keyword check if configured

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm(
                '{"fit_score": 5, "fit_reasoning": "No match.", '
                '"desirability_score": 5, "desirability_reasoning": "No.", '
                '"hard_fail": false, "hard_fail_reason": ""}'
            )
            result = JobScorer().score(job, search)

        assert result.stage_reached == 3


class TestJobScorerStage3:
    def test_returns_both_scores(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, hard=HardRequirements())
        job = _make_job()

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm(
                '{"fit_score": 82, "fit_reasoning": "Strong match.", '
                '"desirability_score": 68, "desirability_reasoning": "Salary OK.", '
                '"hard_fail": false, "hard_fail_reason": ""}'
            )
            result = JobScorer().score(job, search)

        assert result.fit_score == 82
        assert result.desirability_score == 68
        assert result.hard_fail is False
        assert result.score_detail["fit_reasoning"] == "Strong match."

    def test_llm_hard_fail_propagates(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, hard=HardRequirements())
        job = _make_job()

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm(
                '{"fit_score": 70, "fit_reasoning": "Good skills.", '
                '"desirability_score": 20, "desirability_reasoning": "Salary too low.", '
                '"hard_fail": true, "hard_fail_reason": "Salary below 150k threshold."}'
            )
            result = JobScorer().score(job, search)

        assert result.hard_fail is True
        assert result.hard_fail_reason == "Salary below 150k threshold."

    def test_malformed_llm_response_gives_zero_scores(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, hard=HardRequirements())
        job = _make_job()

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm("oops")
            result = JobScorer().score(job, search)

        assert result.fit_score == 0
        assert result.desirability_score == 0

    def test_profile_included_in_prompt(self, tmp_path: Path) -> None:
        profile_file = tmp_path / "profile.md"
        profile_file.write_text("UNIQUE_PROFILE_TOKEN")
        search = _make_search(tmp_path, profile_path=str(profile_file), hard=HardRequirements())

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm(
                '{"fit_score": 50, "fit_reasoning": ".", '
                '"desirability_score": 50, "desirability_reasoning": ".", '
                '"hard_fail": false, "hard_fail_reason": ""}'
            )
            JobScorer().score(job=_make_job(), search=search)
            prompt = mock_cls.return_value.messages.create.call_args[1]["messages"][0]["content"]

        assert "UNIQUE_PROFILE_TOKEN" in prompt

    def test_profile_cached_across_calls(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, hard=HardRequirements())
        scorer = JobScorer()

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_llm(
                '{"fit_score": 50, "fit_reasoning": ".", '
                '"desirability_score": 50, "desirability_reasoning": ".", '
                '"hard_fail": false, "hard_fail_reason": ""}'
            )
            scorer.score(_make_job(ats_job_id="1"), search)
            scorer.score(_make_job(ats_job_id="2"), search)

        # Profile file should be read once and cached
        assert len(scorer._profile_cache) == 1

    def test_missing_profile_raises(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, profile_path=str(tmp_path / "missing.md"), hard=HardRequirements())
        with pytest.raises(FileNotFoundError):
            JobScorer().score(_make_job(), search)


class TestHashing:
    def test_profile_hash_changes_when_content_changes(self, tmp_path: Path) -> None:
        search = _make_search(tmp_path, hard=HardRequirements())
        scorer = JobScorer()
        h1 = scorer.profile_hash(search)

        profile = Path(search.profile_path)
        profile.write_text("Completely different profile content.")
        scorer._profile_cache.clear()

        assert scorer.profile_hash(search) != h1

    def test_requirements_hash_changes_when_salary_changes(self, tmp_path: Path) -> None:
        scorer = JobScorer()
        s1 = _make_search(tmp_path, hard=HardRequirements(salary_min=150_000))
        s2 = _make_search(tmp_path, hard=HardRequirements(salary_min=200_000))
        assert scorer.requirements_hash(s1) != scorer.requirements_hash(s2)

    def test_requirements_hash_stable_for_same_config(self, tmp_path: Path) -> None:
        scorer = JobScorer()
        s = _make_search(tmp_path)
        assert scorer.requirements_hash(s) == scorer.requirements_hash(s)
