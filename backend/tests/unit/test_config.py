"""Tests for settings.

The single most important property is that the application configures itself with
nothing at all. If this file ever needs a credential to pass, the money-safe core
has been coupled to an external account.
"""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from recoup.config import Settings

CREDENTIAL_FIELDS = (
    "groq_api_key",
    "razorpay_key_id",
    "razorpay_key_secret",
    "razorpay_webhook_secret",
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_phone_number",
    "elevenlabs_api_key",
    "resend_api_key",
)

ALL_ENV_KEYS = (
    "RECOUP_MODE",
    "DATABASE_URL",
    "MAX_RETRIES",
    "MAX_AMOUNT_PAISE",
    "MIN_LLM_CONFIDENCE",
    *(name.upper() for name in CREDENTIAL_FIELDS),
)


@pytest.fixture
def empty_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every key Settings reads, so "empty environment" really is empty."""
    for key in ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def build(**overrides: object) -> Settings:
    """Construct Settings ignoring any developer .env sitting in the working tree."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# The empty-environment guarantee
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("empty_environment")
def test_settings_construct_with_a_completely_empty_environment() -> None:
    """No .env, no variables, no error. A missing key selects a mock, not a crash."""
    settings = build()

    assert settings.recoup_mode == "mock"
    assert settings.database_url == "sqlite:///./recoup.db"


@pytest.mark.usefixtures("empty_environment")
@pytest.mark.parametrize("field", CREDENTIAL_FIELDS)
def test_every_credential_defaults_to_none(field: str) -> None:
    """Not one external service may be a precondition for starting up."""
    assert getattr(build(), field) is None


@pytest.mark.usefixtures("empty_environment")
def test_cap_defaults_match_the_documented_policy() -> None:
    """PRD section 12.2: retry_count <= 3, amount <= Rs 50,000, confidence floor 0.7."""
    settings = build()

    assert settings.max_retries == 3
    assert settings.max_amount_paise == 5_000_000
    assert settings.min_llm_confidence == 0.7


@pytest.mark.usefixtures("empty_environment")
def test_the_default_mode_is_the_safe_one() -> None:
    """Reaching a real payment API must require a deliberate act, not an omission."""
    settings = build()

    assert settings.recoup_mode == "mock"
    assert settings.is_live is False


# --------------------------------------------------------------------------- #
# Environment overrides
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("empty_environment")
def test_an_environment_variable_override_is_picked_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOUP_MODE", "live")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_value")

    settings = build()

    assert settings.recoup_mode == "live"
    assert settings.is_live is True
    assert settings.groq_api_key == "gsk_test_value"


@pytest.mark.usefixtures("empty_environment")
def test_env_var_names_are_matched_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The .env template uses UPPER_CASE; the fields are lower_case."""
    monkeypatch.setenv("MAX_AMOUNT_PAISE", "7500000")

    assert build().max_amount_paise == 7_500_000


@pytest.mark.usefixtures("empty_environment")
def test_caps_are_overridable_because_they_are_policy_not_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_RETRIES", "1")
    monkeypatch.setenv("MIN_LLM_CONFIDENCE", "0.9")

    settings = build()

    assert settings.max_retries == 1
    assert settings.min_llm_confidence == 0.9


@pytest.mark.usefixtures("empty_environment")
def test_an_unknown_environment_variable_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared .env will carry keys belonging to other tools; they are not errors."""
    monkeypatch.setenv("SOME_UNRELATED_TOOL_TOKEN", "x")

    assert build().recoup_mode == "mock"


# --------------------------------------------------------------------------- #
# Validation of the caps
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("empty_environment")
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MAX_RETRIES", "-1"),
        ("MAX_AMOUNT_PAISE", "-1"),
        ("MIN_LLM_CONFIDENCE", "1.5"),
        ("MIN_LLM_CONFIDENCE", "-0.1"),
        ("RECOUP_MODE", "production"),
    ],
)
def test_an_invalid_cap_is_a_startup_error(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    """Credentials may be absent; a nonsensical cap may not be silently accepted."""
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError):
        build()


# --------------------------------------------------------------------------- #
# Honest reporting of what is mocked
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("empty_environment")
def test_missing_credentials_lists_everything_that_will_be_mocked() -> None:
    assert build().missing_credentials() == CREDENTIAL_FIELDS


@pytest.mark.usefixtures("empty_environment")
def test_a_set_credential_drops_out_of_the_missing_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_value")

    missing = build().missing_credentials()

    assert "groq_api_key" not in missing
    assert "razorpay_key_id" in missing


@pytest.mark.usefixtures("empty_environment")
def test_a_blank_credential_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The .env template ships every key present and empty; that is still unset."""
    monkeypatch.setenv("GROQ_API_KEY", "")

    assert "groq_api_key" in build().missing_credentials()


@pytest.mark.usefixtures("empty_environment")
def test_describe_mode_names_the_mocked_services() -> None:
    """PRD section 13.4: a mocked run must not be mistakable for a live one."""
    description = build().describe_mode()

    assert "mode=mock" in description
    assert "razorpay_key_id" in description


@pytest.mark.usefixtures("empty_environment")
def test_describe_mode_says_so_when_everything_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field in CREDENTIAL_FIELDS:
        monkeypatch.setenv(field.upper(), f"value_for_{field}")

    settings = build()

    assert settings.missing_credentials() == ()
    assert settings.describe_mode() == "mode=mock; all credentials present"
