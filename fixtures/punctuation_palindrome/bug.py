def is_palindrome(text):
    """Return whether text reads the same forward and backward."""
    return text == text[::-1]
