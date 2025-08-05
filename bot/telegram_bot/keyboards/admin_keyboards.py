"""Keyboards for admin-facing functions."""

from collections.abc import Callable
import gettext
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk

from bot.core.enums import (
    AdminAction,
    ManageTTAccountAction,
    SubscriberAction,
    SubscriberListAction,
)
from bot.core.languages import LanguageInfo
from bot.models import MuteListMode, NotificationSetting
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.callback_data import (
    AdminActionCallback,
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    MenuCallback,
    PaginateLinkableAccountsCallback,
    PaginateMuteListCallback,
    SubscriberActionCallback,
    SubscriberListCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.models import SubscriberInfo

from .shared import (
    _add_pagination_controls_generic,
    _create_back_button_text,
    _create_generic_paginated_list_keyboard,
    _create_option_selection_keyboard,
)

ttstr = pytalk.instance.sdk.ttstr


async def create_banned_user_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[SubscriberInfo],
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the banned user list."""
    _ = translator.gettext

    def banned_user_button_former(
        user: SubscriberInfo, page_num: int, _translate: "Callable[[str], str]"
    ) -> list[InlineKeyboardButton]:
        user_info_parts = [user.display_name]
        if user.teamtalk_username:
            user_info_parts.append(f"TT: {user.teamtalk_username}")
        button_text = ", ".join(user_info_parts)
        return [
            InlineKeyboardButton(
                text=button_text,
                callback_data=ViewSubscriberCallback(telegram_id=user.telegram_id, page=page_num).pack(),
            ),
            InlineKeyboardButton(
                text=_("✅ Unban"),
                callback_data=SubscriberActionCallback(
                    action=SubscriberAction.UNBAN,
                    target_telegram_id=user.telegram_id,
                    page=page_num,
                ).pack(),
            ),
        ]

    pagination_kwargs = {"action": SubscriberListAction.PAGE}

    return await _create_generic_paginated_list_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        item_button_former=banned_user_button_former,
        pagination_callback_factory=SubscriberListCallback,
        pagination_factory_kwargs=pagination_kwargs,
    )


async def create_subscriber_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[SubscriberInfo],
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the subscriber list."""
    _ = translator.gettext

    def subscriber_button_former(
        subscriber: SubscriberInfo, page_num: int, _translate: "Callable[[str], str]"
    ) -> InlineKeyboardButton:
        user_info_parts = [subscriber.display_name]
        if subscriber.teamtalk_username:
            user_info_parts.append(f"TT: {subscriber.teamtalk_username}")
        button_text = ", ".join(user_info_parts)
        return InlineKeyboardButton(
            text=button_text,
            callback_data=ViewSubscriberCallback(telegram_id=subscriber.telegram_id, page=page_num).pack(),
        )

    pagination_kwargs = {"action": SubscriberListAction.PAGE}

    return await _create_generic_paginated_list_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        item_button_former=subscriber_button_former,
        pagination_callback_factory=SubscriberListCallback,
        pagination_factory_kwargs=pagination_kwargs,
    )


async def create_user_selection_keyboard(
    translator: gettext.GNUTranslations,
    users_to_display: list[pytalk.user.User],
    command_type: AdminAction,
) -> InlineKeyboardBuilder:
    """Creates a keyboard with buttons for each user in the provided list."""
    builder = InlineKeyboardBuilder()
    for user_obj in users_to_display:
        if not user_obj:
            continue
        user_nickname = get_tt_user_display_name(user_obj, translator)
        if not hasattr(user_obj, "id"):
            continue
        user_id = user_obj.id
        callback_data = AdminActionCallback(action=command_type, user_id=user_id).pack()
        builder.button(text=user_nickname, callback_data=callback_data)
    builder.adjust(2)
    return builder


async def create_main_menu_keyboard(translator: gettext.GNUTranslations, *, is_admin: bool) -> InlineKeyboardBuilder:
    """Creates the main menu keyboard with commands."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    builder.button(text=_("ℹ️ Who is online?"), callback_data=MenuCallback(command="who").pack())
    builder.button(text=_("⚙️ Settings"), callback_data=MenuCallback(command="settings").pack())
    builder.button(text=_("❓ Help"), callback_data=MenuCallback(command="help").pack())
    if is_admin:
        builder.button(text=_("👢 Kick User"), callback_data=MenuCallback(command="kick").pack())
        builder.button(text=_("🚫 Ban User"), callback_data=MenuCallback(command="ban").pack())
        builder.button(text=_("✅ Unban User"), callback_data=MenuCallback(command="unban").pack())
        builder.button(
            text=_("👥 Subscribers"),
            callback_data=MenuCallback(command="subscribers").pack(),
        )
    builder.adjust(1)
    return builder


async def create_subscriber_action_menu_keyboard(
    translator: gettext.GNUTranslations, target_telegram_id: int, page: int
) -> InlineKeyboardMarkup:
    """Creates the action menu for a specific subscriber."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("🗑️ Delete Subscriber"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.DELETE,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_("🚫 Ban User (TG & TT)"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.BAN, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("🔗 Manage TeamTalk Account"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.MANAGE_TT_ACCOUNT,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_("🗣️ Change Language"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_SET_LANGUAGE,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_("🌞 Toggle NOON"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_TOGGLE_NOON,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_("🔔 Set Notification Prefs"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_SET_NOTIF_PREF,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_("🔇 Set Mute Mode"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_SET_MUTE_MODE,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_("📜 View Mute List"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_VIEW_MUTE_LIST,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_create_back_button_text(translator, "Subscribers List"),
        callback_data=SubscriberListCallback(action=SubscriberListAction.PAGE, page=page).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def create_manage_tt_account_keyboard(
    translator: gettext.GNUTranslations,
    target_telegram_id: int,
    current_tt_username: str | None,
    page: int,
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing a subscriber's TeamTalk account link."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    if current_tt_username:
        builder.button(
            text=_("➖ Unlink {current_tt_username}").format(current_tt_username=current_tt_username),
            callback_data=ManageTTAccountCallback(
                action=ManageTTAccountAction.UNLINK,
                target_telegram_id=target_telegram_id,
                page=page,
            ).pack(),
        )

    builder.button(
        text=_("➕ Link/Change TeamTalk Account"),
        callback_data=ManageTTAccountCallback(
            action=ManageTTAccountAction.LINK_NEW,
            target_telegram_id=target_telegram_id,
            page=page,
        ).pack(),
    )
    builder.button(
        text=_create_back_button_text(translator, "User Actions"),
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=page).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def create_view_mute_list_keyboard(
    translator: gettext.GNUTranslations,
    _page_items: list[Any],
    current_page: int,
    total_pages: int,
    target_telegram_id: int,
    subscriber_context_page: int,
) -> InlineKeyboardMarkup:
    """Creates the keyboard for viewing a paginated mute list for a specific subscriber."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    if total_pages > 1:

        def mute_list_pagination_factory_adapter(**kwargs: dict[str, Any]) -> PaginateMuteListCallback:
            page_num = kwargs.pop("page")
            return PaginateMuteListCallback(mute_list_page=page_num, **kwargs)

        _add_pagination_controls_generic(
            builder=builder,
            translator=translator,
            current_page=current_page,
            total_pages=total_pages,
            pagination_callback_factory=mute_list_pagination_factory_adapter,
            target_telegram_id=target_telegram_id,
            subscriber_context_page=subscriber_context_page,
        )

    builder.row(
        InlineKeyboardButton(
            text=_create_back_button_text(translator, "User Actions"),
            callback_data=ViewSubscriberCallback(
                telegram_id=target_telegram_id,
                page=subscriber_context_page,
            ).pack(),
        )
    )
    return builder.as_markup()


async def create_admin_subscriber_mute_mode_keyboard(
    translator: gettext.GNUTranslations,
    current_mode: MuteListMode,
    target_telegram_id: int,
    subscriber_page_context: int,
) -> InlineKeyboardMarkup:
    """Creates the mute mode selection keyboard for an admin."""
    _ = translator.gettext
    options = [
        (MuteListMode.blacklist.value, _("Blacklist Mode")),
        (MuteListMode.whitelist.value, _("Whitelist Mode")),
    ]

    def mute_mode_callback_factory(
        mode_value_str: str,
    ) -> AdminSetSubscriberMuteModeCallback:
        mode_enum = MuteListMode(mode_value_str)
        return AdminSetSubscriberMuteModeCallback(
            target_telegram_id=target_telegram_id,
            mode=mode_enum,
            subscriber_page_context=subscriber_page_context,
        )

    back_button_cb_data = ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=current_mode.value,
        callback_data_factory=mute_mode_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key=_create_back_button_text(translator, "User Actions"),
        buttons_per_row=1,
    )


async def create_linkable_tt_account_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[pytalk.UserAccount],
    current_page: int,
    total_pages: int,
    target_telegram_id: int,
    subscriber_list_page: int,
) -> InlineKeyboardMarkup:
    """Creates keyboard for selecting a TeamTalk account to link to a subscriber."""
    _ = translator.gettext

    def tt_account_button_former(
        account_obj: pytalk.UserAccount,
        _page_num: int,
        _translate: "Callable[[str], str]",
    ) -> InlineKeyboardButton:
        username_str = ttstr(account_obj.username)
        return InlineKeyboardButton(
            text=username_str,
            callback_data=LinkTTAccountChosenCallback(
                tt_username=username_str,
                target_telegram_id=target_telegram_id,
                page=subscriber_list_page,
            ).pack(),
        )

    back_button = InlineKeyboardButton(
        text=_create_back_button_text(translator, "Manage Account"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.MANAGE_TT_ACCOUNT,
            target_telegram_id=target_telegram_id,
            page=subscriber_list_page,
        ).pack(),
    )
    bottom_buttons = [[back_button]]

    pagination_factory_kwargs = {
        "subscriber_context_page": subscriber_list_page,
        "target_telegram_id": target_telegram_id,
    }

    return await _create_generic_paginated_list_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        item_button_former=tt_account_button_former,
        pagination_callback_factory=PaginateLinkableAccountsCallback,
        pagination_factory_kwargs=pagination_factory_kwargs,
        additional_buttons_bottom=bottom_buttons,
    )


async def create_admin_subscriber_lang_keyboard(
    translator: gettext.GNUTranslations,
    available_languages: list[LanguageInfo],
    target_telegram_id: int,
    subscriber_page_context: int,
) -> InlineKeyboardMarkup:
    """Creates the language selection keyboard for an admin."""
    _ = translator.gettext
    options = [(lang["code"], lang["native_name"]) for lang in available_languages]

    if not available_languages:
        builder = InlineKeyboardBuilder()
        builder.button(text=_("No languages available"), callback_data="noop_admin_lang_sel")
        builder.row(
            InlineKeyboardButton(
                text=_create_back_button_text(translator, "User Actions"),
                callback_data=ViewSubscriberCallback(
                    telegram_id=target_telegram_id, page=subscriber_page_context
                ).pack(),
            )
        )
        return builder.as_markup()

    def lang_callback_factory(
        lang_code_value: str,
    ) -> AdminSetSubscriberLanguageCallback:
        return AdminSetSubscriberLanguageCallback(
            target_telegram_id=target_telegram_id,
            lang_code=lang_code_value,
            subscriber_page_context=subscriber_page_context,
        )

    back_button_cb_data = ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=None,
        callback_data_factory=lang_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key="⬅️ Back to User Actions",
        buttons_per_row=1,
    )


async def create_admin_subscriber_notification_pref_keyboard(
    translator: gettext.GNUTranslations,
    current_setting: NotificationSetting,
    target_telegram_id: int,
    subscriber_page_context: int,
) -> InlineKeyboardMarkup:
    """Creates the notification preference selection keyboard for an admin."""
    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", NotificationSetting.ALL.value),
        NotificationSetting.LEAVE_OFF: ("Join Only", NotificationSetting.LEAVE_OFF.value),
        NotificationSetting.JOIN_OFF: ("Leave Only", NotificationSetting.JOIN_OFF.value),
        NotificationSetting.NONE: ("None", NotificationSetting.NONE.value),
    }
    options = [(val_str, text_source) for _setting_enum, (text_source, val_str) in settings_map_source.items()]

    def notif_pref_callback_factory(
        setting_value_str: str,
    ) -> AdminSetSubscriberNotificationPrefCallback:
        return AdminSetSubscriberNotificationPrefCallback(
            target_telegram_id=target_telegram_id,
            setting_value=setting_value_str,
            subscriber_page_context=subscriber_page_context,
        )

    back_button_cb_data = ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=current_setting.value,
        callback_data_factory=notif_pref_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key=_create_back_button_text(translator, "User Actions"),
        buttons_per_row=1,
    )
