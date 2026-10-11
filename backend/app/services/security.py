import hashlib, hmac

def digest(value:str)->str: return hashlib.sha256(value.encode()).hexdigest()
def matches(value:str, stored:str)->bool: return hmac.compare_digest(digest(value),stored)
