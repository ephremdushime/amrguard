from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = 'AMRGuard API'
    app_env: str = 'development'
    database_url: str = 'sqlite:///./amrguard.db'
    postgres_password: str = ''
    integration_api_key: str = ''
    allowed_origins: str = 'http://localhost:5173'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @model_validator(mode='after')
    def validate_production_settings(self):
        if self.app_env.lower() not in {'production','sandbox','funder_demo'}:
            return self

        origins = [origin.strip() for origin in self.allowed_origins.split(',') if origin.strip()]
        if self.database_url.startswith('sqlite'):
            raise ValueError('DATABASE_URL must use PostgreSQL in sandbox/funder_demo/production')
        if len(self.postgres_password.strip()) < 32 or 'CHANGE_ME' in self.postgres_password:
            raise ValueError('POSTGRES_PASSWORD must be a generated secret of at least 32 characters in sandbox/funder_demo/production')
        if len(self.integration_api_key.strip()) < 32 or 'CHANGE_ME' in self.integration_api_key:
            raise ValueError('INTEGRATION_API_KEY must be a generated secret of at least 32 characters in sandbox/funder_demo/production')
        if not origins or '*' in origins:
            raise ValueError('ALLOWED_ORIGINS must list explicit HTTPS browser origins in sandbox/funder_demo/production')
        if any(not origin.startswith('https://') for origin in origins):
            raise ValueError('ALLOWED_ORIGINS must use HTTPS origins in sandbox/production')
        return self


settings = Settings()
