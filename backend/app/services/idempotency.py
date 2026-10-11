from hashlib import sha256

def event_fingerprint(source_system: str, external_id: str) -> str:
    return sha256(f"{source_system}:{external_id}".encode()).hexdigest()
