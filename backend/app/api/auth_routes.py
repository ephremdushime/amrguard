from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    LOCAL_ISSUER,
    Principal,
    _as_utc,
    clear_session_cookies,
    create_local_session,
    require_human_user,
    utcnow,
)
from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.db.session import get_db
from app.models.core import User, UserSession
from app.services.audit import record_audit
from app.services.security import hash_password, password_needs_rehash, verify_password

router = APIRouter(prefix='/api/v1/auth', tags=['authentication'])


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=1, max_length=200)


def _principal_payload(principal: Principal, csrf_token: str | None = None) -> dict:
    body = {
        'actor_type': principal.actor_type,
        'actor_id': principal.actor_id,
        'auth_method': principal.auth_method,
        'user_id': principal.user_id,
        'username': principal.username,
        'display_name': principal.display_name,
        'roles': sorted(principal.roles),
        'scopes': [
            {
                'role': g.role_code,
                'scope_type': g.scope_type,
                'organization_id': g.organization_id,
                'facility_id': g.facility_id,
                'pharmacy_id': g.pharmacy_id,
            }
            for g in principal.role_scopes
        ],
    }
    if csrf_token is not None:
        body['csrf_token'] = csrf_token
    return body


@router.post('/login')
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate a human user using controlled local Argon2id sessions.

    Disabled by default in production (ADR-001 Decision 1).
    """
    if not settings.local_auth_enabled:
        raise HTTPException(status_code=403, detail='Local authentication is disabled in this environment')

    username = payload.username.strip()
    client_ip = request.client.host if request.client else 'unknown'
    rate_key = f'login:{client_ip}:{username.lower()}'
    if not rate_limiter.check_and_record(
        rate_key,
        max_attempts=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    ):
        record_audit(
            db,
            'AUTH_LOGIN_RATE_LIMITED',
            'Authentication',
            username,
            'AMRGuard',
            actor_type='ANONYMOUS',
            outcome='DENIED',
            details={'username': username},
        )
        db.commit()
        raise HTTPException(status_code=429, detail='Too many login attempts; please try again later')

    user = db.scalar(select(User).where(User.username == username))
    now = utcnow()
    if not user or user.identity_issuer != LOCAL_ISSUER or not user.password_hash:
        record_audit(
            db,
            'AUTH_LOGIN_FAILED',
            'Authentication',
            username,
            'AMRGuard',
            actor_type='ANONYMOUS',
            outcome='DENIED',
            details={'username': username, 'reason': 'invalid_credentials'},
        )
        db.commit()
        raise HTTPException(status_code=401, detail='Invalid username or password')

    if not user.active:
        record_audit(
            db,
            'AUTH_LOGIN_FAILED',
            'User',
            user.id,
            'AMRGuard',
            actor_type='HUMAN',
            actor_id=f'user:{user.id}',
            outcome='DENIED',
            details={'reason': 'account_disabled'},
        )
        db.commit()
        raise HTTPException(status_code=403, detail='Account is disabled')

    locked_until = _as_utc(user.locked_until)
    if locked_until and locked_until > now:
        record_audit(
            db,
            'AUTH_LOGIN_LOCKED',
            'User',
            user.id,
            'AMRGuard',
            actor_type='HUMAN',
            actor_id=f'user:{user.id}',
            outcome='DENIED',
            details={'locked_until': locked_until.isoformat()},
        )
        db.commit()
        raise HTTPException(status_code=423, detail='Account is temporarily locked due to repeated failed logins')

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_attempts += 1
        outcome_event = 'AUTH_LOGIN_FAILED'
        if user.failed_login_attempts >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            outcome_event = 'AUTH_ACCOUNT_LOCKED'
        record_audit(
            db,
            outcome_event,
            'User',
            user.id,
            'AMRGuard',
            actor_type='HUMAN',
            actor_id=f'user:{user.id}',
            outcome='DENIED',
            details={'failed_attempts': user.failed_login_attempts},
        )
        db.commit()
        if outcome_event == 'AUTH_ACCOUNT_LOCKED':
            raise HTTPException(status_code=423, detail='Account is temporarily locked due to repeated failed logins')
        raise HTTPException(status_code=401, detail='Invalid username or password')

    # Successful authentication: reset lockout counters and upgrade password hash if parameters changed
    user.failed_login_attempts = 0
    user.locked_until = None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    session_row, csrf_token = create_local_session(user, request, response, db)
    from app.core.auth import _load_human_principal

    principal = _load_human_principal(db, user, auth_method='local_session', session_id=session_row.id)
    record_audit(
        db,
        'AUTH_LOGIN_SUCCESS',
        'User',
        user.id,
        'AMRGuard',
        actor_type='HUMAN',
        actor_id=principal.actor_id,
        outcome='SUCCESS',
        details={'auth_method': 'local_session', 'session_id': session_row.id},
    )
    db.commit()
    return _principal_payload(principal, csrf_token=csrf_token)


@router.post('/logout')
def logout(
    response: Response,
    principal: Principal = Depends(require_human_user),
    db: Session = Depends(get_db),
):
    if principal.session_id is not None:
        session_row = db.get(UserSession, principal.session_id)
        if session_row and session_row.revoked_at is None:
            session_row.revoked_at = utcnow()
    clear_session_cookies(response)
    record_audit(
        db,
        'AUTH_LOGOUT',
        'User',
        principal.user_id or principal.actor_id,
        'AMRGuard',
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
        outcome='SUCCESS',
        details={'session_id': principal.session_id},
    )
    db.commit()
    return {'logged_out': True}


@router.post('/sessions/revoke-all')
def revoke_all_sessions(
    response: Response,
    principal: Principal = Depends(require_human_user),
    db: Session = Depends(get_db),
):
    now = utcnow()
    revoked_count = 0
    if principal.user_id is not None:
        active_sessions = db.scalars(
            select(UserSession).where(
                UserSession.user_id == principal.user_id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        for session_row in active_sessions:
            session_row.revoked_at = now
            revoked_count += 1
    clear_session_cookies(response)
    record_audit(
        db,
        'AUTH_SESSIONS_REVOKED',
        'User',
        principal.user_id or principal.actor_id,
        'AMRGuard',
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
        outcome='SUCCESS',
        details={'revoked_sessions': revoked_count},
    )
    db.commit()
    return {'revoked_sessions': revoked_count}


@router.get('/me')
def auth_me(principal: Principal = Depends(require_human_user)):
    return _principal_payload(principal)
