def clamp(value, lower, upper):
    """Constrain value to the inclusive interval [lower, upper]."""
    return min(value, upper)
