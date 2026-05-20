"""Test suite for Things area operations.

This module tests the add_area and update_area functionality.
"""

import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import things  # noqa: E402

from things3_mcp.applescript_bridge import (  # noqa: E402
    add_area,
    update_area,
)

from .conftest import (  # noqa: E402
    generate_random_string,
)

# ============================================================================
# ADD_AREA TESTS
# ============================================================================


def test_add_area_basic(test_namespace, cleanup_tracker):
    """Create a bare area and verify it appears in Things."""
    title = f"{test_namespace}-Area-{generate_random_string(5)}"
    area_id = add_area(title=title)
    assert area_id, f"add_area returned falsy value: {area_id!r}"
    cleanup_tracker.add_area(area_id)

    area = things.areas(uuid=area_id)
    assert area, f"Area not found via things.areas() with uuid={area_id}"
    assert area["title"] == title


def test_add_area_with_tags(test_namespace, cleanup_tracker):
    """Create an area with tags and verify the tags are applied."""
    title = f"{test_namespace}-Area-Tagged-{generate_random_string(5)}"
    tag_a = f"{test_namespace}-tag-{generate_random_string(4)}"
    tag_b = f"{test_namespace}-tag-{generate_random_string(4)}"

    area_id = add_area(title=title, tags=[tag_a, tag_b])
    assert area_id, "add_area with tags returned falsy"
    cleanup_tracker.add_area(area_id)
    cleanup_tracker.add_tag(tag_a)
    cleanup_tracker.add_tag(tag_b)

    area = things.areas(uuid=area_id, include_items=False)
    assert area, "Tagged area not found"
    applied_tags = {t["title"] if isinstance(t, dict) else str(t) for t in area.get("tags", [])}
    assert tag_a in applied_tags, f"Tag {tag_a} missing from {applied_tags}"
    assert tag_b in applied_tags, f"Tag {tag_b} missing from {applied_tags}"


def test_add_area_empty_title_returns_false():
    """Empty/whitespace title is rejected before AppleScript is invoked."""
    assert add_area(title="") is False
    assert add_area(title="   ") is False


# ============================================================================
# UPDATE_AREA TESTS
# ============================================================================


def test_update_area_rename(test_namespace, cleanup_tracker):
    """Rename an existing area via update_area."""
    original = f"{test_namespace}-Area-Original-{generate_random_string(5)}"
    renamed = f"{test_namespace}-Area-Renamed-{generate_random_string(5)}"

    area_id = add_area(title=original)
    assert area_id, "Setup: failed to create area"
    cleanup_tracker.add_area(area_id)

    result = update_area(id=area_id, title=renamed)
    assert "true" in str(result).lower(), f"update_area did not succeed: {result!r}"

    area = things.areas(uuid=area_id)
    assert area["title"] == renamed, f"Title not updated: got {area['title']!r}"


def test_update_area_replace_tags(test_namespace, cleanup_tracker):
    """Replace area tags via update_area, then clear them with an empty list."""
    title = f"{test_namespace}-Area-Retag-{generate_random_string(5)}"
    initial_tag = f"{test_namespace}-tag-{generate_random_string(4)}"
    replacement_tag = f"{test_namespace}-tag-{generate_random_string(4)}"

    area_id = add_area(title=title, tags=[initial_tag])
    assert area_id, "Setup: failed to create area with initial tag"
    cleanup_tracker.add_area(area_id)
    cleanup_tracker.add_tag(initial_tag)
    cleanup_tracker.add_tag(replacement_tag)

    # Replace the tags
    result = update_area(id=area_id, tags=[replacement_tag])
    assert "true" in str(result).lower(), f"update_area replace failed: {result!r}"
    area = things.areas(uuid=area_id)
    applied = {t["title"] if isinstance(t, dict) else str(t) for t in area.get("tags", [])}
    assert replacement_tag in applied, f"Replacement tag missing: {applied}"
    assert initial_tag not in applied, f"Initial tag should have been replaced: {applied}"

    # Clear all tags
    result = update_area(id=area_id, tags=[])
    assert "true" in str(result).lower(), f"update_area clear failed: {result!r}"
    area = things.areas(uuid=area_id)
    assert not area.get("tags"), f"Tags should be empty, got: {area.get('tags')}"


def test_update_area_invalid_id_returns_error():
    """Calling update_area with a non-existent id returns an Error: string."""
    result = update_area(id="this-id-does-not-exist-xyz-12345", title="ignored")
    assert "Error" in str(result), f"Expected error string, got: {result!r}"
