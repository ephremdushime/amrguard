from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = 'AMRGuard API'
    app_env: str = 'development'
    database_url: str = 'sqlite:///./amrguard.db'
    postgres_password: str = ''
    integration_api_key: str = ''
    credential_hmac_secret: str = ''
    allowed_origins: str = 'http://localhost:5173'

    # Human authentication mode (ADR-001 Decision 1: Option B)
    # Resolved default: 'oidc' in production, 'hybrid_pilot' in sandbox/funder_demo, 'local_dev' in development/demo/test.
    auth_mode: Literal['oidc', 'hybrid_pilot', 'local_dev'] | None = None
    allow_local_auth: bool | None = None
    local_auth_production_approval_ref: str = ''

    # OIDC / OAuth2 JWT validation settings
    oidc_issuer: str = ''
    oidc_audience: str = ''
    oidc_jwks_url: str = ''
    oidc_jwks_json: str = ''
    oidc_algorithms: str = 'RS256,ES256'
    oidc_leeway_seconds: int = 30

    # Local pilot session & cookie settings
    session_idle_ttl_minutes: int = 30
    session_absolute_ttl_hours: int = 8
    session_cookie_name: str = 'amrguard_session'
    csrf_cookie_name: str = 'amrguard_csrf'
    session_cookie_secure: bool | None = None
    session_cookie_samesite: Literal['strict', 'lax'] = 'strict'

    # Brute-force & rate-limiting controls
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    login_rate_limit_attempts: int = 20
    login_rate_limit_window_seconds: int = 300
    credential_verify_rate_limit: int = 10
    credential_verify_window_seconds: int = 300
    credential_issue_rate_limit: int = 15
    credential_issue_window_seconds: int = 300

    # Cross-facility dispensing policy (ADR-001 Decision 2: disabled by default)
    cross_facility_dispensing_enabled: bool = False

    # P1 Catalogue & Quarantine policy
    quarantine_unmapped_codes: bool | None = None

    # OpenAPI docs visibility (disabled by default in production)
    enable_api_docs: bool | None = None

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @property
    def is_hosted_env(self) -> bool:
        return self.app_env.lower() in {'production', 'sandbox', 'funder_demo'}

    @property
    def effective_quarantine_unmapped_codes(self) -> bool:
        if self.quarantine_unmapped_codes is not None:
            return self.quarantine_unmapped_codes
        return self.is_hosted_env

    @property
    def effective_auth_mode(self) -> str:
        if self.auth_mode is not None:
            return self.auth_mode
        env = self.app_env.lower()
        if env == 'production':
            return 'oidc'
        if env in {'sandbox', 'funder_demo'}:
            return 'hybrid_pilot'
        return 'local_dev'

    @property
    def local_auth_enabled(self) -> bool:
        if self.allow_local_auth is not None:
            return self.allow_local_auth
        return self.effective_auth_mode in {'hybrid_pilot', 'local_dev'}

    @property
    def effective_session_cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_hosted_env

    @property
    def effective_enable_api_docs(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return self.app_env.lower() != 'production'

    @property
    def effective_hmac_secret(self) -> str:
        if self.credential_hmac_secret.strip():
            return self.credential_hmac_secret.strip()
        if self.is_hosted_env:
            raise RuntimeError('CREDENTIAL_HMAC_SECRET is required in hosted environments')
        return 'amrguard-local-dev-only-non-production-hmac-secret-0001'

    @model_validator(mode='after')
    def validate_production_settings(self):
        env = self.app_env.lower()
        if env not in {'production', 'sandbox', 'funder_demo'}:
            return self

        origins = [origin.strip() for origin in self.allowed_origins.split(',') if origin.strip()]
        if self.database_url.startswith('sqlite'):
            raise ValueError('DATABASE_URL must use PostgreSQL in sandbox/funder_demo/production')
        if len(self.postgres_password.strip()) < 32 or 'CHANGE_ME' in self.postgres_password:
            raise ValueError('POSTGRES_PASSWORD must be a generated secret of at least 32 characters in sandbox/funder_demo/production')
        if len(self.integration_api_key.strip()) < 32 or 'CHANGE_ME' in self.integration_api_key:
            raise ValueError('INTEGRATION_API_KEY must be a generated secret of at least 32 characters in sandbox/funder_demo/production')
        if len(self.credential_hmac_secret.strip()) < 32 or 'CHANGE_ME' in self.credential_hmac_secret:
            raise ValueError('CREDENTIAL_HMAC_SECRET must be a generated secret of at least 32 characters in sandbox/funder_demo/production')
        if self.credential_hmac_secret.strip() == self.integration_api_key.strip():
            raise ValueError('CREDENTIAL_HMAC_SECRET must be distinct from INTEGRATION_API_KEY')
        if not origins or '*' in origins:
            raise ValueError('ALLOWED_ORIGINS must list explicit HTTPS browser origins in sandbox/funder_demo/production')
        if any(not origin.startswith('https://') for origin in origins):
            raise ValueError('ALLOWED_ORIGINS must use HTTPS origins in sandbox/production')
        if self.session_cookie_secure is False:
            raise ValueError('SESSION_COOKIE_SECURE cannot be disabled in sandbox/funder_demo/production')

        if env == 'production':
            if self.effective_auth_mode == 'local_dev':
                raise ValueError('AUTH_MODE=local_dev is prohibited in production')
            if self.local_auth_enabled:
                ref = self.local_auth_production_approval_ref.strip()
                if len(ref) < 8 or 'CHANGE_ME' in ref:
                    raise ValueError(
                        'Local authentication is disabled by default in production and requires an explicit LOCAL_AUTH_PRODUCTION_APPROVAL_REF'
                    )
        return self


settings = Settings()
