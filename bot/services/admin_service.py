"""Service layer for administrator-related operations."""

import gettext  # Added
import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError  # Added
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database import crud
from bot.models import UserSettings
from bot.services import user_service  # For updating bot commands

if TYPE_CHECKING:
    import pytalk  # Added

    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection  # Added

logger = logging.getLogger(__name__)


async def add_admin_full(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    services: "Services",
) -> bool:
    """Adds an admin to the DB, updates cache, and refreshes bot commands."""
    try:
        if await crud.add_admin(session, telegram_id):  # crud.add_admin handles its own commit
            logger.info("Admin %s added to DB.", telegram_id)
            services.cache.add_admin(telegram_id)
            logger.info("Admin %s added to cache.", telegram_id)

            if user_settings:  # Should always have user_settings if adding admin
                commands_updated = await user_service.update_user_bot_commands(
                    telegram_id, user_settings.language_code, services
                )
                if commands_updated:
                    logger.info("Bot commands updated for new admin %s.", telegram_id)
                else:
                    logger.warning("Failed to update bot commands for new admin %s.", telegram_id)
            else:
                logger.warning("User settings not available for new admin %s, commands not updated.", telegram_id)
            return True
        logger.warning("Failed to add admin %s to DB (possibly already admin or DB error).", telegram_id)
    except Exception:
        logger.exception("Error in add_admin_full for telegram_id %s.", telegram_id)
        # crud.add_admin should manage its own session rollback on error.
        return False
    else:
        return False  # This path is reached if crud.add_admin returns False


async def remove_admin_full(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    services: "Services",
) -> bool:
    """Removes an admin from the DB, updates cache, and refreshes bot commands."""
    try:
        if await crud.remove_admin_db(session, telegram_id):  # crud.remove_admin_db handles its own commit
            logger.info("Admin %s removed from DB.", telegram_id)
            services.cache.remove_admin(telegram_id)
            logger.info("Admin %s removed from cache.", telegram_id)

            if user_settings:  # Should always have user_settings
                commands_updated = await user_service.update_user_bot_commands(
                    telegram_id, user_settings.language_code, services
                )
                if commands_updated:
                    logger.info("Bot commands updated for former admin %s.", telegram_id)
                else:
                    logger.warning("Failed to update bot commands for former admin %s.", telegram_id)
            else:
                logger.warning("User settings not available for former admin %s, commands not updated.", telegram_id)
            return True
        logger.warning("Failed to remove admin %s from DB (possibly not an admin or DB error).", telegram_id)
    except Exception:
        logger.exception("Error in remove_admin_full for telegram_id %s.", telegram_id)
        # crud.remove_admin_db should manage its own session rollback on error.
        return False
    else:
        return False  # This path is reached if crud.remove_admin_db returns False


# ruff: noqa: PLR0912, PLR0915
async def ban_and_delete_subscriber(
    session: AsyncSession,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
    target_telegram_id: int,
    translator: "gettext.GNUTranslations",
) -> tuple[bool, list[str]]:
    """Bans a subscriber by TG ID and TT username (if linked), then deletes their profile."""
    _ = translator.gettext
    ban_messages: list[str] = []
    overall_success = True

    try:
        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

        # Ban Telegram ID
        banned_tg = await crud.add_to_ban_list(
            session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu"
        )
        if banned_tg:
            ban_messages.append(_("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id))
        else:
            # If already banned, it's not a "failure" of this operation, but good to note.
            # If DB error, it's a failure. crud.add_to_ban_list should ideally signal this.
            # Assuming it returns False on actual error or if already banned.
            logger.info("Telegram ID %s might already be banned or DB error occurred.", target_telegram_id)

        # Ban TeamTalk username
        if tt_username_to_ban:
            banned_tt = await crud.add_to_ban_list(
                session,
                teamtalk_username=tt_username_to_ban,
                reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
            )
            if banned_tt:
                ban_messages.append(_("TeamTalk username {tt_username} banned.").format(tt_username=tt_username_to_ban))
            else:
                logger.info("TeamTalk username %s might already be banned or DB error occurred.", tt_username_to_ban)

            # Conceptual TeamTalk server ban (current logic is mostly logging)
            if tt_connection and tt_connection.instance and tt_connection.is_ready:
                try:
                    # Placeholder for actual ban logic if/when implemented in pytalk SDK
                    logger.info(
                        "Conceptual TT ban for %s on %s (not in SDK by username).", # Shortened
                        tt_username_to_ban,
                        tt_connection.server_info.host,
                    )
                except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
                    logger.exception(
                        "Error during conceptual TeamTalk ban for %s on %s.",
                        tt_username_to_ban,
                        tt_connection.server_info.host,
                    )
                except Exception: # pylint: disable=broad-except
                    logger.exception(
                        "Unexpected error during conceptual TeamTalk ban for %s on %s.",
                        tt_username_to_ban,
                        tt_connection.server_info.host,
                    )
            elif tt_username_to_ban:  # Ensure username exists before logging skip
                logger.warning(
                    "Skipping conceptual TeamTalk server ban for %s as tt_connection or instance is"
                    " None/invalid/not ready.",
                    tt_username_to_ban,
                )
        # If any ban step failed in a way crud.add_to_ban_list indicates (e.g. returns False on True error)
        # we might set overall_success = False here. For now, assuming add_to_ban_list is idempotent.

        # Delete user profile
        # session commit for bans should happen before delete, or delete_full_user_profile should handle it.
        # delete_full_user_profile handles its own commit for deletions.
        # Let's commit ban list changes before calling delete.
        await session.commit()
        logger.debug("Committed ban list changes for user %s before profile deletion.", target_telegram_id)

        deleted_profile = await user_service.delete_full_user_profile(session, target_telegram_id, services=services)
        if deleted_profile:
            if ban_messages:  # Only add "data deleted" if there were preceding ban messages
                ban_messages.append(_("Subscriber data also deleted."))
            else:  # If no specific ban messages (e.g. user was already banned), but data was deleted.
                ban_messages.append(_("Subscriber data deleted."))
        else:
            ban_messages.append(_("Error deleting subscriber data."))
            overall_success = False  # Deletion failure is a significant issue

        if not ban_messages:  # If nothing happened (e.g. already banned, and delete failed or no data)
            ban_messages.append(_("User already banned or error occurred during processing."))

    except SQLAlchemyError:
        await session.rollback()
        logger.exception("SQLAlchemyError in ban_and_delete_subscriber for %s.", target_telegram_id)
        ban_messages.append(_("Database error during ban operation."))
        overall_success = False
    except Exception:  # pylint: disable=broad-except
        await session.rollback()
        logger.exception("Unexpected error in ban_and_delete_subscriber for %s.", target_telegram_id)
        ban_messages.append(_("An unexpected error occurred."))
        overall_success = False

    return overall_success, ban_messages
