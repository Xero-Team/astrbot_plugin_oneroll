"""Pure helpers for the OneRoll AstrBot adapter.

The Rust package remains responsible for parsing and evaluating expressions. This
module only validates the adapter boundary, builds a bounded policy, and renders
the structured result returned by OneRoll.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_BARE_DICE_RE = re.compile(r"(?<![0-9A-Za-z_])d(?=[0-9])")

_DEFAULT_HELP = """OneRoll 插件

/roll [表达式]（别名 /r）
  例如：/r 1d20+5、/r 4d6kh3
  OneRoll 注释和多指令请使用引号：/r '1d20; 2d6 # encounter'

/roll_stats <次数> <表达式>（别名 /rs）
  例如：/rs 20 4d6

/roll_help（别名 /rhelp）
"""


class OneRollUnavailableError(RuntimeError):
    """Raised when the optional ``oneroll`` package cannot be initialized."""


@dataclass(frozen=True, slots=True)
class OneRollMessages:
    """User-facing templates; every field can be overridden in plugin config."""

    help: str = _DEFAULT_HELP
    dependency_error: str = "OneRoll 依赖未就绪，请先安装 requirements.txt 后重载插件。"
    roll_error: str = "掷骰失败：表达式无效，或计算超出 OneRoll 的安全限制。"
    batch_range_error: str = "投掷次数必须在 1 到 {max_times} 之间。"
    result_header: str = "结果：{expression}"
    result_total: str = "总点数：{total}"
    result_details: str = "详情：{details}"
    result_rolls: str = "骰面：{rolls}"
    result_comment: str = "注释：{comment}"
    program_comment: str = "程序注释：{comment}"
    stats_header: str = "统计：{expression}"
    stats_count: str = "投掷次数：{count}"
    stats_minimum: str = "最小值：{minimum}"
    stats_maximum: str = "最大值：{maximum}"
    stats_mean: str = "平均值：{mean:.2f}"
    stats_total: str = "总和：{total}"


_DEFAULT_MESSAGES = OneRollMessages()


@dataclass(frozen=True, slots=True)
class OneRollSettings:
    """Validated settings used by the plugin at runtime."""

    default_expression: str = "1d20"
    strict_syntax: bool = True
    max_input_length: int = 256
    max_batch_times: int = 20
    show_details: bool = True
    show_rolls: bool = True
    max_generated_values: int = 10_000
    max_work_units: int = 1_000_000
    max_output_bytes: int = 1_048_576
    max_message_length: int = 4_000
    messages: OneRollMessages = _DEFAULT_MESSAGES


def safe_int(
    value: object,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Convert a configuration value while enforcing a closed interval."""

    try:
        converted = int(value)
    except TypeError, ValueError, OverflowError:
        return default
    if not minimum <= converted <= maximum:
        return default
    return converted


def safe_bool(value: object, default: bool) -> bool:
    """Convert values commonly produced by JSON/WebUI configuration."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        return default
    return bool(value)


def safe_text(value: object, default: str, *, maximum: int) -> str:
    """Accept bounded configurable copy and fall back for malformed values."""

    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text or "\x00" in text or len(text) > maximum:
        return default
    return text


def _messages_from_config(config: Mapping[str, Any]) -> OneRollMessages:
    raw = config.get("messages")
    if not isinstance(raw, Mapping):
        return _DEFAULT_MESSAGES
    defaults = _DEFAULT_MESSAGES
    values: dict[str, str] = {}
    for field_name in defaults.__dataclass_fields__:
        default = getattr(defaults, field_name)
        values[field_name] = safe_text(
            raw.get(field_name), default, maximum=4_096 if field_name == "help" else 512
        )
    return OneRollMessages(**values)


def settings_from_config(config: Mapping[str, Any] | None) -> OneRollSettings:
    """Read and clamp plugin configuration without trusting WebUI constraints."""

    raw = config if isinstance(config, Mapping) else {}
    default_expression = str(raw.get("default_expression") or "1d20").strip()
    if not default_expression:
        default_expression = "1d20"
    if "\x00" in default_expression or len(default_expression.encode()) > 256:
        default_expression = "1d20"

    return OneRollSettings(
        default_expression=default_expression,
        strict_syntax=safe_bool(raw.get("strict_syntax"), True),
        max_input_length=safe_int(
            raw.get("max_input_length"), 256, minimum=32, maximum=4_096
        ),
        max_batch_times=safe_int(
            raw.get("max_batch_times"), 20, minimum=1, maximum=100
        ),
        show_details=safe_bool(raw.get("show_details"), True),
        show_rolls=safe_bool(raw.get("show_rolls"), True),
        max_generated_values=safe_int(
            raw.get("max_generated_values"),
            10_000,
            minimum=1,
            maximum=1_000_000,
        ),
        max_work_units=safe_int(
            raw.get("max_work_units"),
            1_000_000,
            minimum=100,
            maximum=50_000_000,
        ),
        max_output_bytes=safe_int(
            raw.get("max_output_bytes"),
            1_048_576,
            minimum=1_024,
            maximum=67_108_864,
        ),
        max_message_length=safe_int(
            raw.get("max_message_length"),
            4_000,
            minimum=512,
            maximum=10_000,
        ),
        messages=_messages_from_config(raw),
    )


def normalize_expression(
    expression: str | None,
    *,
    default_expression: str,
    max_input_length: int,
    strict_syntax: bool = True,
) -> str:
    """Normalize an incoming expression without implementing a second parser.

    OneRoll's grammar uses an explicit dice count. In non-strict mode only, the
    small ``d20`` → ``1d20`` convenience mirrors the reference dice plugins;
    strict mode leaves every token untouched for OneRoll to validate.
    """

    text = str(expression or "").strip()
    if not text:
        text = default_expression
    if "\x00" in text:
        raise ValueError("expression contains a NUL byte")
    if not strict_syntax:
        text = _BARE_DICE_RE.sub("1d", text)
    if len(text.encode()) > max_input_length:
        raise ValueError("expression is too long")
    return text


def build_roller(oneroll_module: Any, settings: OneRollSettings) -> Any:
    """Create OneRoll with adapter-owned resource limits."""

    try:
        policy = oneroll_module.ResourcePolicy()
        for name, limit in (
            ("generated_values", settings.max_generated_values),
            ("work_units", settings.max_work_units),
            ("output_bytes", settings.max_output_bytes),
            ("batch_samples", settings.max_batch_times),
        ):
            policy = policy.with_limit(name, limit)
        return oneroll_module.OneRoll(policy)
    except (AttributeError, TypeError, ValueError) as exc:
        raise OneRollUnavailableError(
            "OneRoll policy could not be initialized"
        ) from exc


def _truncate(text: str, maximum: int) -> str:
    if len(text) <= maximum:
        return text
    return f"{text[: maximum - 16].rstrip()} …（内容已截断）"


def _render_template(template: str, default: str, **values: Any) -> str:
    """Render editable copy without allowing a malformed template to break rolls."""

    try:
        return template.format(**values)
    except IndexError, KeyError, ValueError:
        return default.format(**values)


def format_dice_result(
    result: Mapping[str, Any],
    *,
    show_details: bool,
    show_rolls: bool,
    max_message_length: int,
    messages: OneRollMessages | None = None,
) -> str:
    """Render one structured OneRoll result for a chat message."""

    messages = messages or _DEFAULT_MESSAGES
    expression = str(result.get("expression") or "?")
    total = result.get("total", "?")
    lines = [
        _render_template(
            messages.result_header,
            _DEFAULT_MESSAGES.result_header,
            expression=expression,
        ),
        _render_template(
            messages.result_total,
            _DEFAULT_MESSAGES.result_total,
            total=total,
        ),
    ]

    if show_details:
        details = str(result.get("details") or "").strip()
        if details:
            lines.append(
                _render_template(
                    messages.result_details,
                    _DEFAULT_MESSAGES.result_details,
                    details=details,
                )
            )
    if show_rolls:
        rolls = result.get("rolls")
        if rolls:
            lines.append(
                _render_template(
                    messages.result_rolls,
                    _DEFAULT_MESSAGES.result_rolls,
                    rolls=rolls,
                )
            )
    comment = str(result.get("comment") or "").strip()
    if comment:
        lines.append(
            _render_template(
                messages.result_comment,
                _DEFAULT_MESSAGES.result_comment,
                comment=comment,
            )
        )

    return _truncate("\n".join(lines), max_message_length)


def format_program_result(
    result: Mapping[str, Any],
    *,
    show_details: bool,
    show_rolls: bool,
    max_message_length: int,
    messages: OneRollMessages | None = None,
) -> str:
    """Render a semicolon-separated OneRoll program result."""

    messages = messages or _DEFAULT_MESSAGES
    raw_results = result.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        raise ValueError("OneRoll returned no program results")
    blocks = [
        format_dice_result(
            item,
            show_details=show_details,
            show_rolls=show_rolls,
            max_message_length=max_message_length,
            messages=messages,
        )
        for item in raw_results
        if isinstance(item, Mapping)
    ]
    if not blocks:
        raise ValueError("OneRoll returned malformed program results")
    comment = str(result.get("comment") or "").strip()
    if comment:
        blocks.append(
            _render_template(
                messages.program_comment,
                _DEFAULT_MESSAGES.program_comment,
                comment=comment,
            )
        )
    return _truncate("\n\n".join(blocks), max_message_length)


def format_statistics(
    stats: Mapping[str, Any],
    expression: str,
    *,
    max_message_length: int,
    messages: OneRollMessages | None = None,
) -> str:
    """Render OneRoll's batch statistics result."""

    messages = messages or _DEFAULT_MESSAGES
    try:
        mean = float(stats["mean"])
        minimum = stats["min"]
        maximum = stats["max"]
        total = stats["total"]
        count = stats["count"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("OneRoll returned malformed statistics") from exc
    text = "\n".join(
        (
            _render_template(
                messages.stats_header,
                _DEFAULT_MESSAGES.stats_header,
                expression=expression,
            ),
            _render_template(
                messages.stats_count,
                _DEFAULT_MESSAGES.stats_count,
                count=count,
            ),
            _render_template(
                messages.stats_minimum,
                _DEFAULT_MESSAGES.stats_minimum,
                minimum=minimum,
            ),
            _render_template(
                messages.stats_maximum,
                _DEFAULT_MESSAGES.stats_maximum,
                maximum=maximum,
            ),
            _render_template(
                messages.stats_mean,
                _DEFAULT_MESSAGES.stats_mean,
                mean=mean,
            ),
            _render_template(
                messages.stats_total,
                _DEFAULT_MESSAGES.stats_total,
                total=total,
            ),
        )
    )
    return _truncate(text, max_message_length)
