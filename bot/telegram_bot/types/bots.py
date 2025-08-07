"""Custom bot types for dependency injection."""

from typing import NewType

from aiogram import Bot

EventBot = NewType("EventBot", Bot)
MessageBot = NewType("MessageBot", Bot)
