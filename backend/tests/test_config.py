import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production_settings(**overrides):
    values = {
        'app_env': 'production',
        'database_url': 'postgresql+psycopg://amrguard:secret@localhost/amrguard',
        'postgres_password': 'p' * 32,
        'integration_api_key': 'k' * 32,
        'allowed_origins': 'https://amrguard.example.org',
    }
    values.update(overrides)
    return Settings(**values)


def test_production_settings_accept_explicit_database_and_origin():
    settings = production_settings()
    assert settings.app_env == 'production'


@pytest.mark.parametrize('overrides', [
    {'database_url': 'sqlite:///./amrguard.db'},
    {'postgres_password': 'CHANGE_ME_USE_OPENSSL_RAND_HEX_32'},
    {'integration_api_key': 'CHANGE_ME_USE_A_DIFFERENT_OPENSSL_RAND_HEX_32'},
    {'allowed_origins': '*'},
])
def test_production_settings_reject_unsafe_values(overrides):
    with pytest.raises(ValidationError):
        production_settings(**overrides)