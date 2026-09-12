def decide(x: int, limit: int) -> str:
    # Deliberate seed bug: equality is incorrectly allowed.
    return "ALLOW" if x <= limit else "DENY"
