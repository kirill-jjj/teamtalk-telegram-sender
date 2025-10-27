"""Utility functions for pagination."""

from collections.abc import Callable
from typing import Any, TypeVar

from bot.core.constants import USERS_PER_PAGE

T = TypeVar("T")


def paginate_list(
    full_list: list[T], page: int, page_size: int = USERS_PER_PAGE
) -> tuple[list[T], int, int]:
    """Paginates a given list.

    Args:
        full_list: The full list of items to paginate.
        page: The requested page number (0-indexed).
        page_size: The number of items per page.

    Returns:
        A tuple containing:
            - page_slice: The slice of the list for the current page.
            - total_pages: The total number of pages.
            - current_page_idx: The validated current page index.
    """
    total_items = len(full_list)
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    current_page_idx = max(0, min(page, total_pages - 1))

    start_index = current_page_idx * page_size
    end_index = start_index + page_size
    page_slice: list[T] = full_list[start_index:end_index]

    return page_slice, total_pages, current_page_idx


def get_item_from_paginated_list(
    items: list[T],
    sort_key_extractor: Callable[[T], Any],
    page: int,
    idx_on_page: int,
    page_size: int = USERS_PER_PAGE,
) -> T | None:
    """Gets a specific item from a paginated list."""
    sorted_items = sorted(items, key=sort_key_extractor)
    page_items, _, _ = paginate_list(sorted_items, page, page_size)
    if 0 <= idx_on_page < len(page_items):
        return page_items[idx_on_page]
    return None
