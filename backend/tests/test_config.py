import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production_settings(**overrides):
    values = {
        'app_env': 'production',
        'database_url': 'postgresql+psycopg://amrguard:secret@localhost/amrguard',
        'postgres_password': 'p' * 32,
        'integration_api_key': 'k' * 32,
        'credential_hmac_secret': 'h' * 32,
        'allowed_origins': 'https://amrguard.example.org',
    }
    values.update(overrides)
    return Settings(**values)


def test_production_settings_accept_explicit_database_and_origin():
    cfg = production_settings()
    assert cfg.app_env == 'production'
    assert cfg.effective_auth_mode == 'oidc'
    assert cfg.local_auth_enabled is False
    assert cfg.cross_facility_dispensing_enabled is False
    assert cfg.effective_enable_api_docs is False
    assert cfg.effective_session_cookie_secure is True


def test_production_settings_allow_hybrid_pilot_only_with_explicit_approval_ref():
    cfg = production_settings(
        auth_mode='hybrid_pilot',
        allow_local_auth=True,
        local_auth_production_approval_ref='GOV-PILOT-AUTH-2026-001',
    )
    assert cfg.local_auth_enabled is True


@pytest.mark.parametrize(
    'overrides',
    [
        {'database_url': 'sqlite:///./amrguard.db'},
        {'postgres_password': 'CHANGE_ME_USE_OPENSSL_RAND_HEX_32'},
        {'integration_api_key': 'CHANGE_ME_USE_A_DIFFERENT_OPENSSL_RAND_HEX_32'},
        {'credential_hmac_secret': 'CHANGE_ME_USE_A_THIRD_OPENSSL_RAND_HEX_32'},
        {'credential_hmac_secret': 'short'},
        {'credential_hmac_secret': 'k' * 32},  # must be distinct from integration_api_key
        {'allowed_origins': '*'},
        {'allowed_origins': 'http://amrguard.example.org'},
        {'session_cookie_secure': False},
        {'auth_mode': 'local_dev'},
        {'allow_local_auth': True},  # missing explicit approval ref
        {'auth_mode': 'hybrid_pilot'},  # local auth implicitly enabled without approval ref
        {'auth_mode': 'hybrid_pilot', 'local_auth_production_approval_ref': 'CHANGE_ME_REF'},
    ],
)
def test_production_settings_reject_unsafe_values(overrides):
    with pytest.raises(ValidationError):
        production_settings(**overrides)
