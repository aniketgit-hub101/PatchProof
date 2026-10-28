import pytest

from bug import average


def test_average_of_values():
    assert average([2, 4, 6]) == 4


def test_empty_average_is_zero():
    assert average([]) == 0.0
