from __future__ import annotations

import pytest

from core import (
    OneRollMessages,
    format_dice_result,
    format_program_result,
    format_statistics,
    normalize_expression,
    settings_from_config,
)


def test_normalize_expression_uses_default_and_supports_bare_dice() -> None:
    assert (
        normalize_expression("", default_expression="1d20", max_input_length=64)
        == "1d20"
    )
    assert (
        normalize_expression(
            "d20 + d6",
            default_expression="1d20",
            max_input_length=64,
            strict_syntax=False,
        )
        == "1d20 + 1d6"
    )
    assert (
        normalize_expression("d20", default_expression="1d20", max_input_length=64)
        == "d20"
    )


def test_normalize_expression_rejects_nul_and_oversized_input() -> None:
    with pytest.raises(ValueError):
        normalize_expression("1d6\x00", default_expression="1d20", max_input_length=64)
    with pytest.raises(ValueError):
        normalize_expression("1d6", default_expression="1d20", max_input_length=2)


def test_settings_clamp_untrusted_values() -> None:
    settings = settings_from_config(
        {
            "max_input_length": -1,
            "max_batch_times": 999,
            "show_details": "off",
            "max_message_length": "bad",
            "strict_syntax": False,
            "messages": {"result_total": "结果={total}"},
        }
    )
    assert settings.max_input_length == 256
    assert settings.max_batch_times == 20
    assert settings.show_details is False
    assert settings.max_message_length == 4_000
    assert settings.strict_syntax is False
    assert settings.messages.result_total == "结果={total}"


def test_format_dice_result_respects_display_flags() -> None:
    result = {
        "expression": "4d6kh3",
        "total": 12,
        "details": "4d6kh3 = 12",
        "rolls": [[6, 4, 2, 1]],
        "comment": "属性",
    }
    text = format_dice_result(
        result,
        show_details=False,
        show_rolls=False,
        max_message_length=100,
    )
    assert "总点数：12" in text
    assert "详情" not in text
    assert "骰面" not in text
    assert "注释：属性" in text


def test_format_dice_result_uses_configured_copy_and_falls_back_bad_templates() -> None:
    text = format_dice_result(
        {"expression": "1d1", "total": 1, "details": "1", "rolls": []},
        show_details=False,
        show_rolls=False,
        max_message_length=200,
        messages=OneRollMessages(result_total="broken {missing}"),
    )
    assert "总点数：1" in text


def test_format_program_and_statistics() -> None:
    program = {
        "results": [{"expression": "1d1", "total": 1, "details": "1", "rolls": []}],
        "comment": "encounter",
    }
    assert "程序注释：encounter" in format_program_result(
        program,
        show_details=True,
        show_rolls=True,
        max_message_length=500,
    )
    stats = format_statistics(
        {"min": 1, "max": 6, "mean": 3.5, "total": 21, "count": 6},
        "1d6",
        max_message_length=500,
    )
    assert "平均值：3.50" in stats
