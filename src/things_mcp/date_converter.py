"""Functions for converting between ISO datetime and AppleScript date formats.

Based on the official Things AppleScript Commands documentation.
"""

import datetime
import logging
import re

logger = logging.getLogger(__name__)


def update_applescript_with_due_date(script_parts: list, deadline: str, item_var: str = "theProject") -> None:
    """Update an AppleScript command list with the correct due date syntax.

    Uses the safe step-by-step date construction method to avoid edge cases:
    set deadlineDate to current date
    set month of deadlineDate to 1      -- Reset to January first
    set day of deadlineDate to 1        -- Reset to 1st first
    set year of deadlineDate to 2025
    set month of deadlineDate to 3      -- Then set actual month
    set day of deadlineDate to 15       -- Then set actual day
    set time of deadlineDate to 0
    set due date of itemVar to deadlineDate

    Args:
    ----
        script_parts: List of AppleScript commands being built
        deadline: Deadline in YYYY-MM-DD format
        item_var: The AppleScript variable name to set the due date on
    """
    if not deadline:
        logger.warning("No deadline provided")
        return

    # Step 1: Accept an ISO string, validate it in Python
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", deadline):
        logger.error(f"Invalid deadline format: {deadline}. Expected YYYY-MM-DD")
        return

    try:
        # Parse and validate the ISO date
        target_date = datetime.datetime.strptime(deadline, "%Y-%m-%d")

        # Step 2: Convert to AppleScript using the official arithmetic format
        # Calculate days difference from today
        today = datetime.datetime.now().date()
        target_date_only = target_date.date()
        days_diff = (target_date_only - today).days

        script_parts.append(f"    -- Setting due date to {deadline} ({days_diff:+d} days from today)")

        if days_diff == 0:
            script_parts.append(f"    set due date of {item_var} to current date")
        elif days_diff > 0:
            script_parts.append(f"    set due date of {item_var} to (current date) + {days_diff} * days")
        else:
            # Negative days for past dates
            script_parts.append(f"    set due date of {item_var} to (current date) - {abs(days_diff)} * days")

        logger.debug(f"Generated arithmetic AppleScript date construction for {deadline} ({days_diff:+d} days)")

    except ValueError:
        logger.error(f"Invalid date: {deadline}")
    except Exception as e:
        logger.error(f"Error setting deadline: {e!s}")
