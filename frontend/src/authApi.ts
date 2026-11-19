export type AuthScope = {
  role: string;
  scope_type: string;
  organization_id: number | null;
  facility_id: number | null;
  pharmacy_id: number | null;
};

export type AuthUser = {
  actor_type: string;
  actor_id: string;
  auth_method: string;
  user_id: number | null;
  username: string | null;
  display_name: string | null;
  roles: string[];
  scopes: AuthScope[];
  csrf_token?: string;
};

let cachedCsrfToken = '';

export function setCsrfToken(token: string) {
  cachedCsrfToken = token;
}

export function getCsrfToken(): string {
  if (typeof document !== 'undefined') {
    const match = document.cookie
      .split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('amrguard_csrf='));
    if (match) {
      return decodeURIComponent(match.slice('amrguard_csrf='.length));
    }
  }
  return cachedCsrfToken;
}

export function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers || {});
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) {
      headers.set('X-CSRF-Token', csrf);
    }
  }
  return fetch(input, {
    ...init,
    credentials: 'include',
    headers,
  });
}
