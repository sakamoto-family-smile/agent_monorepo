from decimal import Decimal

import pytest

from utils.money import to_yen


class TestToYen:
    def test_int_input(self):
        assert to_yen(1000) == Decimal("1000")

    def test_negative_int(self):
        assert to_yen(-3500) == Decimal("-3500")

    def test_string_plain(self):
        assert to_yen("12345") == Decimal("12345")

    def test_string_with_comma(self):
        assert to_yen("1,234,567") == Decimal("1234567")

    def test_string_with_yen_sign(self):
        assert to_yen("￥5,000") == Decimal("5000")
        assert to_yen("¥5000") == Decimal("5000")

    def test_string_with_quotes(self):
        assert to_yen('"-3500"') == Decimal("-3500")

    def test_fullwidth_digits(self):
        assert to_yen("１２３") == Decimal("123")

    def test_float_truncated(self):
        # 1円未満は切り捨て
        assert to_yen(100.99) == Decimal("100")

    def test_decimal_passthrough(self):
        assert to_yen(Decimal("999.99")) == Decimal("999")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            to_yen("")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            to_yen("abc")

    def test_unsupported_type_raises(self):
        with pytest.raises(ValueError):
            to_yen([1000])  # type: ignore[arg-type]
