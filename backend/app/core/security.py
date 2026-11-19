"""Legacy compatibility exports for security dependencies.

Human and service-client authentication are strictly separated in `app.core.auth` and `app.core.authz`.
"""
from app.core.auth import (
    Principal,
    require_authenticated_principal,
    require_human_user,
    require_service_client,
)
from app.core.authz import require_human_roles, require_service_scope

__all__ = [
    'Principal',
    'require_authenticated_principal',
    'require_human_user',
    'require_service_client',
    'require_human_roles',
    'require_service_scope',
]
