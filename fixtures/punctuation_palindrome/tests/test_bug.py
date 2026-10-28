from bug import is_palindrome


def test_simple_palindrome():
    assert is_palindrome("level") is True


def test_ignores_case_and_punctuation():
    assert is_palindrome("A man, a plan, a canal: Panama!") is True


def test_non_palindrome():
    assert is_palindrome("python") is False
