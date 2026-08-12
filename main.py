"""A thin AstrBot adapter for the HydroRoll-Team OneRoll engine."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import GreedyStr
from astrbot.api.star import PluginContext, Star

from .core import (
    OneRollMessages,
    OneRollSettings,
    OneRollUnavailableError,
    build_roller,
    format_dice_result,
    format_program_result,
    format_statistics,
    normalize_expression,
    settings_from_config,
)

_EMPTY_EXPRESSION: GreedyStr = ""


class OneRollPlugin(Star):
    """Expose OneRoll expressions through small, platform-neutral commands."""

    def __init__(self, context: PluginContext, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.settings: OneRollSettings = settings_from_config(
            config if isinstance(config, Mapping) else None
        )
        self._roller: Any | None = None

    async def initialize(self) -> None:
        """Load the optional Rust extension and apply bounded execution limits."""

        try:
            self._roller = self._load_roller()
        except OneRollUnavailableError as exc:
            self._roller = None
            logger.error("[oneroll] initialization failed: %s", type(exc).__name__)
        else:
            version = getattr(self._roller, "__version__", "unknown")
            logger.info("[oneroll] OneRoll adapter initialized (engine=%s)", version)

    async def terminate(self) -> None:
        """Release the extension reference during reload or shutdown."""

        self._roller = None

    def _load_roller(self) -> Any:
        try:
            module = importlib.import_module("oneroll")
        except ImportError as exc:
            raise OneRollUnavailableError("oneroll package is not installed") from exc
        return build_roller(module, self.settings)

    def _get_roller(self) -> Any:
        if self._roller is None:
            self._roller = self._load_roller()
        return self._roller

    def _evaluate(self, expression: str) -> tuple[Mapping[str, Any], bool]:
        roller = self._get_roller()
        if ";" in expression:
            result = roller.run(expression)
            return result, True
        result = roller.roll(expression)
        return result, False

    def _render_roll(self, expression: str) -> str:
        normalized = normalize_expression(
            expression,
            default_expression=self.settings.default_expression,
            max_input_length=self.settings.max_input_length,
            strict_syntax=self.settings.strict_syntax,
        )
        result, is_program = self._evaluate(normalized)
        if not isinstance(result, Mapping):
            raise TypeError("OneRoll returned a malformed result")
        if is_program:
            return format_program_result(
                result,
                show_details=self.settings.show_details,
                show_rolls=self.settings.show_rolls,
                max_message_length=self.settings.max_message_length,
                messages=self.settings.messages,
            )
        return format_dice_result(
            result,
            show_details=self.settings.show_details,
            show_rolls=self.settings.show_rolls,
            max_message_length=self.settings.max_message_length,
            messages=self.settings.messages,
        )

    def _safe_render_roll(self, expression: str) -> str:
        try:
            return self._render_roll(expression)
        except OneRollUnavailableError:
            return self.settings.messages.dependency_error
        except (
            AttributeError,
            IndexError,
            KeyError,
            OverflowError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.debug("[oneroll] roll failed: %s", type(exc).__name__)
            return self.settings.messages.roll_error

    @filter.command("roll", alias={"r"})
    async def roll(
        self, event: AstrMessageEvent, expression: GreedyStr = _EMPTY_EXPRESSION
    ):
        """Roll one OneRoll expression or a semicolon-separated program."""

        yield event.plain_result(self._safe_render_roll(expression))

    @filter.command("roll_stats", alias={"rs"})
    async def roll_stats(
        self,
        event: AstrMessageEvent,
        times: int,
        expression: GreedyStr,
    ):
        """Roll an expression repeatedly and show min/max/mean statistics."""

        if times < 1 or times > self.settings.max_batch_times:
            try:
                text = self.settings.messages.batch_range_error.format(
                    max_times=self.settings.max_batch_times
                )
            except IndexError, KeyError, ValueError:
                text = OneRollMessages().batch_range_error.format(
                    max_times=self.settings.max_batch_times
                )
            yield event.plain_result(text)
            return
        try:
            normalized = normalize_expression(
                expression,
                default_expression=self.settings.default_expression,
                max_input_length=self.settings.max_input_length,
                strict_syntax=self.settings.strict_syntax,
            )
            roller = self._get_roller()
            stats = roller.roll_statistics(normalized, times)
            if not isinstance(stats, Mapping):
                raise TypeError("OneRoll returned malformed statistics")
            text = format_statistics(
                stats,
                normalized,
                max_message_length=self.settings.max_message_length,
                messages=self.settings.messages,
            )
        except OneRollUnavailableError:
            text = self.settings.messages.dependency_error
        except (
            AttributeError,
            IndexError,
            KeyError,
            OverflowError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.debug("[oneroll] statistics failed: %s", type(exc).__name__)
            text = self.settings.messages.roll_error
        yield event.plain_result(text)

    @filter.command("roll_help", alias={"rhelp"})
    async def roll_help(self, event: AstrMessageEvent):
        """Show OneRoll adapter commands and examples."""

        yield event.plain_result(self.settings.messages.help)

    @filter.llm_tool(name="oneroll_roll")
    async def oneroll_roll(self, event: AstrMessageEvent, expression: str) -> str:
        """Roll a bounded OneRoll expression for a TRPG narration.

        Args:
            expression(string): OneRoll expression such as ``1d20+5`` or ``4d6kh3``.
        """

        return self._safe_render_roll(expression)
