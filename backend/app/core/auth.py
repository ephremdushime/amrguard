from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import json
import secrets
from typing import Literal

from fastapi import Depends, HTTPException, Request, Response
import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKSet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.core import (
    Role,
    ServiceClient,
    ServiceClientCredential,
    ServiceClientScope,
    User,
    UserRoleScope,
    UserSession,
)
from app.services.audit import record_audit
from app.services.security import keyed_digest

LOCAL_ISSUER = 'urn:amrguard:local'
STATE_CHANGING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass(frozen=True)
class RoleScopeGrant:
    role_code: str
    scope_type: str
    organization_id: int | None = None
    facility_id: int | None = None
    pharmacy_id: int | None = None


@dataclass(frozen=True)
class ServiceScopeGrant:
    scope: str
    facility_id: int | None = None
    pharmacy_id: int | None = None


@dataclass(frozen=True)
class Principal:
    actor_type: Literal['HUMAN', 'SERVICE_CLIENT']
    actor_id: str
    auth_method: str
    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    roles: frozenset[str] = frozenset()
    role_scopes: tuple[RoleScopeGrant, ...] = ()
    session_id: int | None = None
    service_client_id: int | None = None
    service_client_code: str | None = None
    service_scopes: tuple[ServiceScopeGrant, ...] = ()


def _truncate_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    if '.' in ip:
        parts = ip.split('.')
        if len(parts) == 4:
            return '.'.join(parts[:3] + ['0'])
    if ':' in ip:
        parts = ip.split(':')
        return ':'.join(parts[:4]) + '::'
    return ip[:64]


def _load_human_principal(
    db: Session,
    user: User,
    *,
    auth_method: str,
    session_id: int | None = None,
) -> Principal:
    rows = db.execute(
        select(Role.code, UserRoleScope)
        .join(Role, Role.id == UserRoleScope.role_id)
        .where(
            UserRoleScope.user_id == user.id,
            UserRoleScope.active.is_(True),
            UserRoleScope.revoked_at.is_(None),
        )
    ).all()
    grants = tuple(
        RoleScopeGrant(
            role_code=role_code,
            scope_type=scope.scope_type,
            organization_id=scope.organization_id,
            facility_id=scope.facility_id,
            pharmacy_id=scope.pharmacy_id,
        )
        for role_code, scope in rows
    )
    roles = frozenset(g.role_code for g in grants)
    return Principal(
        actor_type='HUMAN',
        actor_id=f'user:{user.id}',
        auth_method=auth_method,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=roles,
        role_scopes=grants,
        session_id=session_id,
    )


class OIDCJWTAuthenticator:
    """Validates institutional OIDC/OAuth2 Bearer JWT tokens via JWKS."""

    def __init__(self) -> None:
        self._jwks_client_url: str = ''
        self._jwks_client: PyJWKClient | None = None

    def _get_signing_key(self, token: str):
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')

        if settings.oidc_jwks_json.strip():
            jwk_set = PyJWKSet.from_json(settings.oidc_jwks_json)
            if kid:
                for key in jwk_set.keys:
                    if key.key_id == kid:
                        return key.key
                raise InvalidTokenError('Unknown signing key ID')
            if len(jwk_set.keys) == 1:
                return jwk_set.keys[0].key
            raise InvalidTokenError('Missing signing key ID')

        if settings.oidc_jwks_url.strip():
            if self._jwks_client is None or self._jwks_client_url != settings.oidc_jwks_url.strip():
                self._jwks_client_url = settings.oidc_jwks_url.strip()
                self._jwks_client = PyJWKClient(self._jwks_client_url, cache_keys=True)
            return self._jwks_client.get_signing_key_from_jwt(token).key

        raise HTTPException(status_code=503, detail='OIDC authentication is not configured')

    def authenticate(self, token: str, db: Session) -> Principal:
        if not settings.oidc_issuer.strip() or not settings.oidc_audience.strip():
            raise HTTPException(status_code=503, detail='OIDC issuer and audience must be configured')

        algorithms = [alg.strip() for alg in settings.oidc_algorithms.split(',') if alg.strip()]
        try:
            signing_key = self._get_signing_key(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=algorithms,
                audience=settings.oidc_audience.strip(),
                issuer=settings.oidc_issuer.strip(),
                leeway=settings.oidc_leeway_seconds,
                options={'require': ['exp', 'sub', 'iss', 'aud']},
            )
        except HTTPException:
            raise
        except InvalidTokenError as exc:
            record_audit(
                db,
                'AUTH_OIDC_FAILED',
                'Authentication',
                'oidc',
                'AMRGuard',
                actor_type='ANONYMOUS',
                outcome='DENIED',
                details={'reason': type(exc).__name__},
            )
            db.commit()
            raise HTTPException(status_code=401, detail='Invalid or expired OIDC token') from exc

        issuer = str(claims['iss'])
        subject = str(claims['sub'])
        user = db.scalar(
            select(User).where(User.identity_issuer == issuer, User.identity_subject == subject)
        )
        if not user or not user.active:
            record_audit(
                db,
                'AUTH_OIDC_USER_DENIED',
                'User',
                subject,
                'AMRGuard',
                actor_type='ANONYMOUS',
                outcome='DENIED',
                details={'issuer': issuer, 'reason': 'inactive_or_unprovisioned'},
            )
            db.commit()
            raise HTTPException(status_code=401, detail='Account is not provisioned or is disabled')

        locked_until = _as_utc(user.locked_until)
        if locked_until and locked_until > utcnow():
            record_audit(
                db,
                'AUTH_ACCOUNT_LOCKED',
                'User',
                user.id,
                'AMRGuard',
                actor_type='HUMAN',
                actor_id=f'user:{user.id}',
                outcome='DENIED',
                details={'auth_method': 'oidc_jwt'},
            )
            db.commit()
            raise HTTPException(status_code=403, detail='Account is temporarily locked')

        return _load_human_principal(db, user, auth_method='oidc_jwt')


oidc_authenticator = OIDCJWTAuthenticator()


def create_local_session(user: User, request: Request, response: Response, db: Session) -> tuple[UserSession, str]:
    now = utcnow()
    raw_session_token = secrets.token_urlsafe(32)
    raw_csrf_token = secrets.token_urlsafe(32)
    idle_expires = now + timedelta(minutes=settings.session_idle_ttl_minutes)
    abs_expires = now + timedelta(hours=settings.session_absolute_ttl_hours)

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get('user-agent', '')
    session_row = UserSession(
        user_id=user.id,
        token_hash=keyed_digest(raw_session_token, purpose='user_session'),
        csrf_token_hash=keyed_digest(raw_csrf_token, purpose='session_csrf'),
        created_at=now,
        last_seen_at=now,
        expires_at=min(idle_expires, abs_expires),
        absolute_expires_at=abs_expires,
        ip_address_truncated=_truncate_ip(client_ip),
        user_agent_hash=keyed_digest(user_agent, purpose='user_agent') if user_agent else None,
    )
    db.add(session_row)
    db.flush()

    max_age = settings.session_absolute_ttl_hours * 3600
    secure_cookie = settings.effective_session_cookie_secure
    samesite = settings.session_cookie_samesite

    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_session_token,
        httponly=True,
        secure=secure_cookie,
        samesite=samesite,
        max_age=max_age,
        path='/',
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=raw_csrf_token,
        httponly=False,
        secure=secure_cookie,
        samesite=samesite,
        max_age=max_age,
        path='/',
    )
    return session_row, raw_csrf_token


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path='/')
    response.delete_cookie(key=settings.csrf_cookie_name, path='/')


def authenticate_local_session(request: Request, db: Session) -> Principal:
    if not settings.local_auth_enabled:
        raise HTTPException(status_code=401, detail='Local session authentication is disabled')

    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail='Authentication required')

    token_hash = keyed_digest(raw_token, purpose='user_session')
    session_row = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    now = utcnow()
    if not session_row or session_row.revoked_at is not None:
        raise HTTPException(status_code=401, detail='Invalid or revoked session')

    expires_at = _as_utc(session_row.expires_at)
    abs_expires = _as_utc(session_row.absolute_expires_at)
    if (expires_at and expires_at <= now) or (abs_expires and abs_expires <= now):
        raise HTTPException(status_code=401, detail='Session expired')

    user = db.get(User, session_row.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail='Account is disabled')

    locked_until = _as_utc(user.locked_until)
    if locked_until and locked_until > now:
        raise HTTPException(status_code=403, detail='Account is temporarily locked')

    # Enforce double-submit CSRF protection on all state-changing cookie-authenticated requests
    if request.method.upper() in STATE_CHANGING_METHODS:
        csrf_header = request.headers.get('x-csrf-token', '')
        csrf_cookie = request.cookies.get(settings.csrf_cookie_name, '')
        expected_hash = session_row.csrf_token_hash
        if (
            not csrf_header
            or not csrf_cookie
            or not hmac.compare_digest(csrf_header, csrf_cookie)
            or not hmac.compare_digest(keyed_digest(csrf_header, purpose='session_csrf'), expected_hash)
        ):
            record_audit(
                db,
                'AUTH_CSRF_FAILED',
                'UserSession',
                session_row.id,
                'AMRGuard',
                actor_type='HUMAN',
                actor_id=f'user:{user.id}',
                outcome='DENIED',
                details={'method': request.method, 'path': request.url.path},
            )
            db.commit()
            raise HTTPException(status_code=403, detail='CSRF validation failed')

    # Slide idle expiration bounded by absolute expiry
    session_row.last_seen_at = now
    new_idle = now + timedelta(minutes=settings.session_idle_ttl_minutes)
    session_row.expires_at = min(new_idle, abs_expires) if abs_expires else new_idle
    db.flush()

    return _load_human_principal(db, user, auth_method='local_session', session_id=session_row.id)


def authenticate_service_client_key(raw_key: str, db: Session) -> Principal:
    """Authenticate a partner service client via '<key_prefix>.<secret>' credential."""
    if '.' not in raw_key:
        record_audit(
            db,
            'AUTH_SERVICE_FAILED',
            'ServiceClient',
            'unknown',
            'AMRGuard',
            actor_type='SERVICE_CLIENT',
            outcome='DENIED',
            details={'reason': 'malformed_key'},
        )
        db.commit()
        raise HTTPException(status_code=403, detail='Invalid service client credential')

    prefix, secret = raw_key.split('.', 1)
    if not prefix or not secret:
        raise HTTPException(status_code=403, detail='Invalid service client credential')

    cred = db.scalar(select(ServiceClientCredential).where(ServiceClientCredential.key_prefix == prefix))
    now = utcnow()
    if not cred or cred.revoked_at is not None:
        record_audit(
            db,
            'AUTH_SERVICE_FAILED',
            'ServiceClientCredential',
            prefix,
            'AMRGuard',
            actor_type='SERVICE_CLIENT',
            outcome='DENIED',
            details={'reason': 'unknown_or_revoked'},
        )
        db.commit()
        raise HTTPException(status_code=403, detail='Invalid or revoked service client credential')

    expires_at = _as_utc(cred.expires_at)
    if expires_at and expires_at <= now:
        record_audit(
            db,
            'AUTH_SERVICE_FAILED',
            'ServiceClientCredential',
            prefix,
            'AMRGuard',
            actor_type='SERVICE_CLIENT',
            outcome='DENIED',
            details={'reason': 'expired'},
        )
        db.commit()
        raise HTTPException(status_code=401, detail='Expired service client credential')

    expected_digest = keyed_digest(secret, purpose='service_client_key', salt=prefix)
    if not hmac.compare_digest(expected_digest, cred.secret_hash):
        record_audit(
            db,
            'AUTH_SERVICE_FAILED',
            'ServiceClientCredential',
            prefix,
            'AMRGuard',
            actor_type='SERVICE_CLIENT',
            outcome='DENIED',
            details={'reason': 'secret_mismatch'},
        )
        db.commit()
        raise HTTPException(status_code=403, detail='Invalid service client credential')

    client = db.get(ServiceClient, cred.service_client_id)
    if not client or not client.active:
        record_audit(
            db,
            'AUTH_SERVICE_FAILED',
            'ServiceClient',
            cred.service_client_id,
            'AMRGuard',
            actor_type='SERVICE_CLIENT',
            outcome='DENIED',
            details={'reason': 'client_disabled'},
        )
        db.commit()
        raise HTTPException(status_code=403, detail='Service client is disabled')

    scope_rows = db.scalars(
        select(ServiceClientScope).where(
            ServiceClientScope.service_client_id == client.id,
            ServiceClientScope.active.is_(True),
        )
    ).all()
    scopes = tuple(
        ServiceScopeGrant(scope=row.scope, facility_id=row.facility_id, pharmacy_id=row.pharmacy_id)
        for row in scope_rows
    )
    return Principal(
        actor_type='SERVICE_CLIENT',
        actor_id=f'service:{client.client_code}',
        auth_method='service_key',
        service_client_id=client.id,
        service_client_code=client.client_code,
        service_scopes=scopes,
    )


def require_human_user(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Strictly authenticate a human user via OIDC Bearer JWT or local pilot session cookie.

    Service-client credentials (x-amrguard-integration-key) are never accepted here.
    """
    auth_header = request.headers.get('authorization', '')
    if auth_header.lower().startswith('bearer '):
        token = auth_header[7:].strip()
        if not token:
            raise HTTPException(status_code=401, detail='Empty bearer token')
        return oidc_authenticator.authenticate(token, db)

    if request.cookies.get(settings.session_cookie_name):
        return authenticate_local_session(request, db)

    if request.headers.get('x-amrguard-integration-key'):
        record_audit(
            db,
            'AUTH_PATH_VIOLATION',
            'Authentication',
            request.url.path,
            'AMRGuard',
            actor_type='SERVICE_CLIENT',
            outcome='DENIED',
            details={'reason': 'service_credential_used_on_human_endpoint'},
        )
        db.commit()
        raise HTTPException(status_code=403, detail='Human user authentication required; service credentials are not accepted')

    raise HTTPException(status_code=401, detail='Authentication required')


def require_service_client(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Strictly authenticate a partner integration service client.

    Human sessions and OIDC user tokens are never accepted here.
    """
    raw_key = request.headers.get('x-amrguard-integration-key')
    if not raw_key:
        if request.headers.get('authorization') or request.cookies.get(settings.session_cookie_name):
            record_audit(
                db,
                'AUTH_PATH_VIOLATION',
                'Authentication',
                request.url.path,
                'AMRGuard',
                actor_type='HUMAN',
                outcome='DENIED',
                details={'reason': 'human_credential_used_on_service_endpoint'},
            )
            db.commit()
            raise HTTPException(status_code=403, detail='Service client authentication required')
        raise HTTPException(status_code=401, detail='Service client credential required')
    return authenticate_service_client_key(raw_key, db)


def require_authenticated_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Authenticate either a human user OR a scoped service client, preserving strict actor_type separation."""
    auth_header = request.headers.get('authorization', '')
    has_bearer = auth_header.lower().startswith('bearer ')
    has_session = bool(request.cookies.get(settings.session_cookie_name))
    has_service_key = bool(request.headers.get('x-amrguard-integration-key'))

    if (has_bearer or has_session) and has_service_key:
        raise HTTPException(status_code=400, detail='Do not combine human and service-client credentials')

    if has_bearer:
        token = auth_header[7:].strip()
        if not token:
            raise HTTPException(status_code=401, detail='Empty bearer token')
        return oidc_authenticator.authenticate(token, db)

    if has_session:
        return authenticate_local_session(request, db)

    if has_service_key:
        return authenticate_service_client_key(request.headers['x-amrguard-integration-key'], db)

    raise HTTPException(status_code=401, detail='Authentication required')
