import os


def String(key: str, fallback: str) -> str:
    value = os.getenv(key)
    if value == "" or value is None:
        return fallback
    return value


def Int(key: str, fallback: int) -> int:
    value = os.getenv(key)
    if value == "" or value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def Float(key: str, fallback: float) -> float:
    value = os.getenv(key)
    if value == "" or value is None:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback
