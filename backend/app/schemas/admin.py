from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrganizationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    active: bool = True


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    active: bool
    created_at: datetime


class FacilityCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    district: str = Field(min_length=2, max_length=100)
    organization_id: int | None = None
    active: bool = True


class FacilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    district: str | None = Field(default=None, min_length=2, max_length=100)
    organization_id: int | None = None
    active: bool | None = None


class FacilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    district: str
    organization_id: int | None = None
    active: bool


class PharmacyCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    district: str = Field(min_length=2, max_length=100)
    organization_id: int | None = None
    facility_id: int | None = None
    pharmacy_type: Literal['FACILITY_PHARMACY', 'COMMUNITY_RETAIL', 'NETWORK_PARTNER'] = 'FACILITY_PHARMACY'
    active: bool = True


class PharmacyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    district: str | None = Field(default=None, min_length=2, max_length=100)
    pharmacy_type: Literal['FACILITY_PHARMACY', 'COMMUNITY_RETAIL', 'NETWORK_PARTNER'] | None = None
    active: bool | None = None


class PharmacyAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    district: str
    organization_id: int | None = None
    facility_id: int | None = None
    pharmacy_type: str
    active: bool


class PharmacyNetworkCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    active: bool = True


class PharmacyNetworkMemberUpsert(BaseModel):
    facility_id: int | None = None
    pharmacy_id: int | None = None
    allow_all_medicines: bool = False
    antibiotic_codes: list[str] = Field(default_factory=list)
    active: bool = True

    @model_validator(mode='after')
    def check_member_present(self) -> 'PharmacyNetworkMemberUpsert':
        if self.facility_id is None and self.pharmacy_id is None:
            raise ValueError('Provide at least one of facility_id or pharmacy_id')
        return self


class PharmacyNetworkPharmacyItem(BaseModel):
    pharmacy_id: int
    pharmacy_code: str
    pharmacy_name: str
    allow_all_medicines: bool
    active: bool
    permitted_antibiotic_codes: list[str] = []


class PharmacyNetworkFacilityItem(BaseModel):
    facility_id: int
    facility_code: str
    facility_name: str
    active: bool


class PharmacyNetworkResponse(BaseModel):
    id: int
    code: str
    name: str
    active: bool
    created_at: datetime
    facilities: list[PharmacyNetworkFacilityItem] = []
    pharmacies: list[PharmacyNetworkPharmacyItem] = []


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    description: str


class RoleScopeCreate(BaseModel):
    role_code: Literal[
        'prescriber',
        'pharmacist',
        'pharmacy_assistant',
        'stewardship_officer',
        'facility_admin',
        'national_analyst',
        'platform_operator',
    ]
    scope_type: Literal['PHARMACY', 'FACILITY', 'ORGANIZATION', 'NATIONAL_AGGREGATE', 'PLATFORM']
    organization_id: int | None = None
    facility_id: int | None = None
    pharmacy_id: int | None = None

    @model_validator(mode='after')
    def validate_explicit_scope(self) -> 'RoleScopeCreate':
        if self.scope_type == 'PHARMACY':
            if self.pharmacy_id is None or self.facility_id is not None or self.organization_id is not None:
                raise ValueError('PHARMACY scope requires pharmacy_id only')
        elif self.scope_type == 'FACILITY':
            if self.facility_id is None or self.pharmacy_id is not None or self.organization_id is not None:
                raise ValueError('FACILITY scope requires facility_id only')
        elif self.scope_type == 'ORGANIZATION':
            if self.organization_id is None or self.facility_id is not None or self.pharmacy_id is not None:
                raise ValueError('ORGANIZATION scope requires organization_id only')
        elif self.scope_type in {'NATIONAL_AGGREGATE', 'PLATFORM'}:
            if self.organization_id is not None or self.facility_id is not None or self.pharmacy_id is not None:
                raise ValueError(f'{self.scope_type} scope must not specify organization_id, facility_id, or pharmacy_id')
        return self


class RoleScopeResponse(BaseModel):
    id: int
    role_code: str
    scope_type: str
    organization_id: int | None = None
    facility_id: int | None = None
    pharmacy_id: int | None = None
    active: bool
    granted_by_user_id: int | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    display_name: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    auth_provider: Literal['local', 'oidc'] = 'local'
    password: str | None = Field(default=None, min_length=12, max_length=200)
    identity_issuer: str | None = Field(default=None, max_length=255)
    identity_subject: str | None = Field(default=None, max_length=255)
    initial_scope: RoleScopeCreate | None = None

    @model_validator(mode='after')
    def validate_provider_fields(self) -> 'UserCreate':
        if self.auth_provider == 'local' and not self.password:
            raise ValueError('password (min 12 chars) is required when auth_provider is local')
        if self.auth_provider == 'oidc' and (not self.identity_issuer or not self.identity_subject):
            raise ValueError('identity_issuer and identity_subject are required when auth_provider is oidc')
        return self


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    active: bool | None = None
    unlock: bool = False


class UserAdminResponse(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None = None
    identity_issuer: str
    active: bool
    failed_login_attempts: int
    locked_until: datetime | None = None
    created_at: datetime
    scopes: list[RoleScopeResponse] = []


class ServiceClientScopeIn(BaseModel):
    scope: str = Field(min_length=3, max_length=100)
    facility_id: int | None = None
    pharmacy_id: int | None = None


class ServiceClientCreate(BaseModel):
    client_code: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=2, max_length=200)
    partner_type: Literal['EMR', 'SUPPLY_CHAIN', 'INTEGRATION_GATEWAY', 'SYSTEM_WORKER'] = 'EMR'
    scopes: list[ServiceClientScopeIn] = Field(min_length=1)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class ServiceClientKeyRotateRequest(BaseModel):
    revoke_previous: bool = True
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class ServiceClientScopeResponse(BaseModel):
    id: int
    scope: str
    facility_id: int | None = None
    pharmacy_id: int | None = None
    active: bool


class ServiceClientCredentialResponse(BaseModel):
    id: int
    key_prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    active: bool


class ServiceClientResponse(BaseModel):
    id: int
    client_code: str
    name: str
    partner_type: str
    active: bool
    created_at: datetime
    scopes: list[ServiceClientScopeResponse] = []
    credentials: list[ServiceClientCredentialResponse] = []


class ServiceClientKeyIssuedResponse(BaseModel):
    client_id: int
    client_code: str
    credential_id: int
    key_prefix: str
    api_key: str
    expires_at: datetime | None = None
    revoked_previous_count: int = 0
    disclosure_notice: str = 'Store this key securely now. The raw secret cannot be retrieved again.'
