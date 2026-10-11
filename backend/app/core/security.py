import secrets
from fastapi import Header, HTTPException
from app.core.config import settings

def require_integration_key(x_amrguard_integration_key: str | None = Header(default=None)):
    """Protect integration endpoints when a key is configured.

    Local demo environments may leave INTEGRATION_API_KEY empty. Sandbox/production deployments
    should configure a secret and preferably replace this with OAuth2/client-credentials
    or the institution's approved service-to-service mechanism.
    """
    expected = settings.integration_api_key
    if settings.app_env.lower() in {'sandbox','funder_demo','production'} and not expected:
        raise HTTPException(status_code=503, detail="Integration authentication is not configured")
    if expected and not x_amrguard_integration_key:
        raise HTTPException(status_code=401, detail="Integration credential required")
    if expected and x_amrguard_integration_key and not secrets.compare_digest(x_amrguard_integration_key, expected):
        raise HTTPException(status_code=403, detail="Invalid integration credential")
    return True


def require_funder_demo_ui_or_integration_key(x_amrguard_integration_key: str | None = Header(default=None)):
    """Allow the Basic-Auth-gated funder UI while keeping partner APIs key protected."""
    if settings.app_env.lower() == 'funder_demo':
        return True
    return require_integration_key(x_amrguard_integration_key)
