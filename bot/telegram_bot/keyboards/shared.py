"""Shared keyboard helper functions."""

from collections.abc import Callable
from gettext import NullTranslations
from typing import Any, Protocol

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk

from bot.core.enums import UserListAction
from bot.models import MuteListMode
from bot.services.notification_service import is_muted  # Updated import
from bot.telegram_bot.callback_data import PaginateUsersCallback, ToggleMuteCallback

ttstr = pytalk.instance.sdk.ttstr


def _create_back_button_text(
    translator: NullTranslations, translated_destination: str
) -> str:
    """Creates a standardized 'Back to...' button text."""
    _ = translator.gettext
    return _("Back to {destination}").format(destination=translated_destination)


def create_back_button(
    translator: NullTranslations,
    translated_destination: str,
    callback_data: "PackableCallbackData",
) -> InlineKeyboardButton:
    """Creates a standardized 'Back' button."""
    return InlineKeyboardButton(
        text=_create_back_button_text(translator, translated_destination),
        callback_data=callback_data.pack(),
    )


def add_back_button(
    builder: InlineKeyboardBuilder,
    translator: NullTranslations,
    translated_destination: str,
    callback_data: "PackableCallbackData",
) -> None:
    """Adds a standardized 'Back' button to the keyboard builder."""
    builder.row(create_back_button(translator, translated_destination, callback_data))


class PackableCallbackData(Protocol):
    """A protocol for objects that have a .pack() method returning a string."""

    def pack(self) -> str:
        """Serializes the callback data into a string."""
        ...


def _create_option_selection_keyboard(
    translator: NullTranslations,
    options: list[tuple[str, str]],
    current_value: str | None,
    callback_data_factory: Callable[[str], PackableCallbackData],
    back_button_callback_data: PackableCallbackData,
    back_button_text_key: str,
    buttons_per_row: int = 1,
) -> InlineKeyboardMarkup:
    """Creates a generic keyboard for selecting one option from a list."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    active_marker = "✅ "

    for value, display_text in options:
        button_text = (
            f"{active_marker}{_(display_text)}"
            if value == current_value
            else _(display_text)
        )
        button_callback_data = callback_data_factory(value)
        builder.button(text=button_text, callback_data=button_callback_data.pack())

    if options:
        builder.adjust(buttons_per_row)

    add_back_button(
        builder, translator, back_button_text_key, back_button_callback_data
    )
    return builder.as_markup()


def _add_pagination_controls_generic(
    builder: InlineKeyboardBuilder,
    translator: NullTranslations,
    current_page: int,
    total_pages: int,
    pagination_callback_factory: "Callable[..., Any]",
    **factory_kwargs: Any,
) -> None:
    """Adds generic pagination controls (Previous/Next) to the keyboard builder."""
    _ = translator.gettext
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=pagination_callback_factory(
                    page=current_page - 1, **factory_kwargs
                ).pack(),
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=pagination_callback_factory(
                    page=current_page + 1, **factory_kwargs
                ).pack(),
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


def create_paginated_keyboard(
    translator: NullTranslations,
    page_items: list[Any],
    current_page: int,
    total_pages: int,
    item_button_former: "Callable[[Any, int, Callable[[str], str]], "
    "InlineKeyboardButton | list[InlineKeyboardButton]]",
    pagination_callback_factory: "Callable[..., Any]",
    pagination_factory_kwargs: dict[str, Any] | None = None,
    additional_buttons_top: list[list[InlineKeyboardButton]] | None = None,
    additional_buttons_bottom: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    """Generic helper to create a keyboard for a paginated list of items."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    if additional_buttons_top:
        for row_buttons in additional_buttons_top:
            builder.row(*row_buttons)

    for item in page_items:
        button_or_buttons = item_button_former(item, current_page, _)
        if isinstance(button_or_buttons, list):
            builder.row(*button_or_buttons)
        else:
            builder.row(button_or_buttons)

    if total_pages > 1:
        factory_kwargs_to_pass = (
            pagination_factory_kwargs if pagination_factory_kwargs is not None else {}
        )
        _add_pagination_controls_generic(
            builder,
            translator,
            current_page,
            total_pages,
            pagination_callback_factory,
            **factory_kwargs_to_pass,
        )

    if additional_buttons_bottom:
        for row_buttons in additional_buttons_bottom:
            builder.row(*row_buttons)

    return builder.as_markup()


def _add_pagination_controls(
    builder: InlineKeyboardBuilder,
    translator: NullTranslations,
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    callback_factory: type[PaginateUsersCallback],
) -> None:
    """Adds pagination controls (Previous/Next) to the keyboard builder."""
    _ = translator.gettext
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=callback_factory(
                    list_type=list_type, page=current_page - 1
                ).pack(),
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=callback_factory(
                    list_type=list_type, page=current_page + 1
                ).pack(),
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


def create_toggle_mute_keyboard(
    translator: NullTranslations,
    page_items: list[Any],
    current_page: int,
    total_pages: int,
    mute_list_mode: MuteListMode,
    muted_usernames: set[str],
    list_type_for_callback: UserListAction,
    item_username_extractor: "Callable[[Any], str]",
    item_display_name_extractor: "Callable[[Any], str]",
    back_button_callback_data: str,
    back_button_text_key: str,
) -> InlineKeyboardMarkup:
    """Generic helper for a paginated list of users with mute/unmute toggle buttons."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    for idx, item in enumerate(page_items):
        username_str = item_username_extractor(item)
        display_name_on_button = item_display_name_extractor(item)
        is_user_muted = is_muted(username_str, mute_list_mode, muted_usernames)
        if is_user_muted:
            button_text = _("{item_display_name} (Status: Muted)").format(
                item_display_name=display_name_on_button
            )
        else:
            button_text = _("{item_display_name} (Status: Not Muted)").format(
                item_display_name=display_name_on_button
            )
        callback_d = ToggleMuteCallback(
            user_idx=idx,
            current_page=current_page,
            list_type=list_type_for_callback,
        ).pack()
        builder.button(text=button_text, callback_data=callback_d)

    if page_items:
        builder.adjust(1)

    _add_pagination_controls(
        builder,
        translator,
        current_page,
        total_pages,
        list_type_for_callback,
        PaginateUsersCallback,
    )

    builder.row(
        InlineKeyboardButton(
            text=back_button_text_key, callback_data=back_button_callback_data
        )
    )
    return builder.as_markup()
