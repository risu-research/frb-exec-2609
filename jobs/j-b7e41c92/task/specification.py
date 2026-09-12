def accepts(x: int, limit: int, output: str) -> bool:
    expected = "ALLOW" if x < limit else "DENY"
    return output == expected
