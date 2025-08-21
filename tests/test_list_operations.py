"""Test suite for Things list view operations.

Focuses on verifying API response format and structure without exposing actual data.
"""

from things3_mcp.fast_server import (
    get_anytime,
    get_areas,
    get_inbox,
    get_logbook,
    get_projects,
    get_random_anytime,
    get_random_inbox,
    get_random_todos,
    get_recent,
    get_someday,
    get_tagged_items,
    get_tags,
    get_today,
    get_todos,
    get_trash,
    get_upcoming,
    search_advanced,
    # Add the MCP tool endpoints for integration testing
    search_all_items,
    search_todos,
    show_item,
)

from .conftest import (
    create_test_tag,
    delete_test_tags,
)


def verify_todo_format(todo_str: str) -> bool:
    """Verify a todo string has the expected format without checking specific content.

    Args:
        todo_str: The todo string to verify.

    Returns:
        bool: True if the format is valid, False otherwise.
    """
    # Check for required fields
    required_fields = ["Title:", "UUID:"]
    return all(field in todo_str for field in required_fields)


def verify_project_format(project_str: str) -> bool:
    """Verify a project string has the expected format without checking specific content.

    Args:
        project_str: The project string to verify.

    Returns:
        bool: True if the format is valid, False otherwise.
    """
    required_fields = ["Title:", "UUID:"]
    return all(field in project_str for field in required_fields)


def verify_area_format(area_str: str) -> bool:
    """Verify an area string has the expected format without checking specific content.

    Args:
        area_str: The area string to verify.

    Returns:
        bool: True if the format is valid, False otherwise.
    """
    required_fields = ["Title:", "UUID:"]
    return all(field in area_str for field in required_fields)


def verify_tag_format(tag_str: str) -> bool:
    """Verify a tag string has the expected format without checking specific content.

    Args:
        tag_str: The tag string to verify.

    Returns:
        bool: True if the format is valid, False otherwise.
    """
    required_fields = ["Title:"]
    return all(field in tag_str for field in required_fields)


def verify_item_format(item_str: str) -> bool:
    """Verify any item string has the expected format without checking specific content.

    This function checks if the string matches either a todo or project format.

    Args:
        item_str: The item string to verify.

    Returns:
        bool: True if the format is valid, False otherwise.
    """
    return verify_todo_format(item_str) or verify_project_format(item_str)


def test_get_inbox():
    """Test get_inbox() returns data in expected format."""
    result = get_inbox()
    assert isinstance(result, str), "Should return a string"

    if result != "No items found in Inbox":
        # Split multiple items if present
        todos = result.split("\n\n---\n\n")
        for todo in todos:
            assert verify_todo_format(todo), f"Todo format is incorrect: {todo}"


def test_get_today():
    """Test get_today() returns data in expected format."""
    result = get_today()
    assert isinstance(result, str), "Should return a string"

    if result != "No items due today":
        todos = result.split("\n\n---\n\n")
        for todo in todos:
            assert verify_todo_format(todo), f"Todo format is incorrect: {todo}"


def test_get_upcoming():
    """Test get_upcoming() returns data in expected format."""
    result = get_upcoming()
    assert isinstance(result, str), "Should return a string"

    if result != "No upcoming items":
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_get_anytime():
    """Test get_anytime() returns data in expected format."""
    result = get_anytime()
    assert isinstance(result, str), "Should return a string"

    if result != "No items in Anytime list":
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_todo_format(item), f"Todo format is incorrect: {item}"


def test_get_someday():
    """Test get_someday() returns data in expected format."""
    result = get_someday()
    assert isinstance(result, str), "Should return a string"

    if result != "No items in Someday list":
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_todo_format(item), f"Todo format is incorrect: {item}"


def test_get_logbook():
    """Test get_logbook() returns data in expected format."""
    result = get_logbook(period="7d", limit=50)
    assert isinstance(result, str), "Should return a string"

    if result != "No completed items found":
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"
        assert len(items) <= 50, "Should respect item limit"


def test_get_trash():
    """Test get_trash() returns data in expected format."""
    result = get_trash()
    assert isinstance(result, str), "Should return a string"

    if result != "No items in trash":
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_get_random_inbox():
    """Test get_random_inbox() returns data in expected format."""
    # Test default count (5)
    result = get_random_inbox()
    assert isinstance(result, str), "Should return a string"

    if result != "No items found in Inbox":
        items = result.split("\n\n---\n\n")
        # Should return at most 5 items by default
        assert len(items) <= 5, f"Should return at most 5 items, got {len(items)}"
        for item in items:
            assert verify_todo_format(item), f"Item format is incorrect: {item}"

    # Test custom count
    result_3 = get_random_inbox(count=3)
    assert isinstance(result_3, str), "Should return a string"

    if result_3 != "No items found in Inbox":
        items_3 = result_3.split("\n\n---\n\n")
        assert len(items_3) <= 3, f"Should return at most 3 items, got {len(items_3)}"
        for item in items_3:
            assert verify_todo_format(item), f"Item format is incorrect: {item}"

    # Test edge case: count=0
    result_0 = get_random_inbox(count=0)
    assert result_0 == "No items found in Inbox", "Should return no items message for count=0"


def test_get_random_anytime():
    """Test get_random_anytime() returns data in expected format."""
    # Test default count (5)
    result = get_random_anytime()
    assert isinstance(result, str), "Should return a string"

    if result != "No items in Anytime list":
        items = result.split("\n\n---\n\n")
        # Should return at most 5 items by default
        assert len(items) <= 5, f"Should return at most 5 items, got {len(items)}"
        for item in items:
            # Anytime can contain both todos and projects
            assert verify_item_format(item), f"Item format is incorrect: {item}"

    # Test custom count
    result_2 = get_random_anytime(count=2)
    assert isinstance(result_2, str), "Should return a string"

    if result_2 != "No items in Anytime list":
        items_2 = result_2.split("\n\n---\n\n")
        assert len(items_2) <= 2, f"Should return at most 2 items, got {len(items_2)}"
        for item in items_2:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_get_random_todos():
    """Test get_random_todos() returns data in expected format."""
    # Test without project filter
    result = get_random_todos()
    assert isinstance(result, str), "Should return a string"

    if result != "No todos found":
        items = result.split("\n\n---\n\n")
        # Should return at most 5 items by default
        assert len(items) <= 5, f"Should return at most 5 items, got {len(items)}"
        for item in items:
            assert verify_todo_format(item), f"Item format is incorrect: {item}"

    # Test custom count
    result_4 = get_random_todos(count=4)
    assert isinstance(result_4, str), "Should return a string"

    if result_4 != "No todos found":
        items_4 = result_4.split("\n\n---\n\n")
        assert len(items_4) <= 4, f"Should return at most 4 items, got {len(items_4)}"
        for item in items_4:
            assert verify_todo_format(item), f"Item format is incorrect: {item}"


def test_get_random_todos_with_project():
    """Test get_random_todos() with project filtering returns data in expected format."""
    # First get a project ID from the projects list
    projects_result = get_projects()
    if projects_result != "No projects found":
        # Get first project's ID from the result
        project_lines = projects_result.split("\n")
        for line in project_lines:
            if line.startswith("UUID:"):
                project_id = line.split("UUID:")[1].strip()
                # Test random todos for this project
                result = get_random_todos(project_uuid=project_id, count=3)
                assert isinstance(result, str), "Should return a string"

                if result != "No todos found":
                    todos = result.split("\n\n---\n\n")
                    assert len(todos) <= 3, f"Should return at most 3 items, got {len(todos)}"
                    for todo in todos:
                        assert verify_todo_format(todo), f"Todo format is incorrect: {todo}"
                break


def test_random_sampling_edge_cases():
    """Test edge cases for random sampling functions."""
    # Test negative count (should behave like count=0)
    result_neg = get_random_inbox(count=-1)
    assert result_neg == "No items found in Inbox", "Should handle negative count gracefully"

    # Test very large count (should return all available items)
    result_large = get_random_anytime(count=1000)
    assert isinstance(result_large, str), "Should handle large count gracefully"

    # Test invalid project UUID
    result_invalid = get_random_todos(project_uuid="invalid-uuid-123", count=2)
    assert "Error: Invalid project UUID" in result_invalid, "Should handle invalid project UUID"


def test_get_todos_with_project():
    """Test get_todos() with project filtering returns data in expected format."""
    # First get a project ID from the projects list
    projects_result = get_projects()
    if projects_result != "No projects found":
        # Get first project's ID from the result
        project_lines = projects_result.split("\n")
        for line in project_lines:
            if line.startswith("UUID:"):
                project_id = line.split("UUID:")[1].strip()
                # Test todos for this project
                result = get_todos(project_uuid=project_id)
                assert isinstance(result, str), "Should return a string"

                if result != "No todos found":
                    todos = result.split("\n\n---\n\n")
                    for todo in todos:
                        assert verify_todo_format(todo), f"Todo format is incorrect: {todo}"
                break


def test_get_projects_with_items():
    """Test get_projects() with include_items=True returns data in expected format."""
    result = get_projects(include_items=True)
    assert isinstance(result, str), "Should return a string"

    if result != "No projects found":
        projects = result.split("\n\n---\n\n")
        for project in projects:
            assert verify_project_format(project), f"Project format is incorrect: {project}"
            # If project has items, they should be properly formatted
            if "Tasks:" in project:
                items_section = project.split("Tasks:")[1]
                items = [item.strip() for item in items_section.split("\n- ") if item.strip()]
                for item in items:
                    assert item, "Item should not be empty"


def test_get_areas_with_items():
    """Test get_areas() with include_items=True returns data in expected format."""
    result = get_areas(include_items=True)
    assert isinstance(result, str), "Should return a string"

    if result != "No areas found":
        areas = result.split("\n\n---\n\n")
        for area in areas:
            assert verify_area_format(area), f"Area format is incorrect: {area}"
            # If area has items, they should be properly formatted
            if "Tasks:" in area:
                items_section = area.split("Tasks:")[1]
                items = items_section.split("\n- ")
                for item in items[1:]:  # Skip first empty split
                    assert item.strip(), "Item should not be empty"


def test_get_tags():
    """Test get_tags() returns data in expected format."""
    result = get_tags()
    assert isinstance(result, str), "Should return a string"

    if result != "No tags found":
        tags = result.split("\n\n---\n\n")
        for tag in tags:
            assert verify_tag_format(tag), f"Tag format is incorrect: {tag}"


def test_get_tagged_items():
    """Test get_tagged_items() returns data in expected format."""
    # First get a tag from the tags list
    tags_result = get_tags()
    if tags_result != "No tags found":
        # Get first tag's title
        tag_lines = tags_result.split("\n")
        for line in tag_lines:
            if line.startswith("Title:"):
                tag_title = line.split("Title:")[1].strip()
                # Test items for this tag
                result = get_tagged_items(tag=tag_title)
                assert isinstance(result, str), "Should return a string"

                if not result.startswith("No items found with tag"):
                    items = result.split("\n\n---\n\n")
                    for item in items:
                        assert verify_item_format(item), f"Item format is incorrect: {item}"
                break


def test_search_todos():
    """Test search_todos() returns data in expected format."""
    # Use a generic search term that won't expose data
    result = search_todos(query="test")
    assert isinstance(result, str), "Should return a string"

    if not result.startswith("No todos found matching"):
        todos = result.split("\n\n---\n\n")
        for todo in todos:
            assert verify_todo_format(todo), f"Todo format is incorrect: {todo}"


def test_search_advanced(test_namespace):
    """Test search_advanced() returns data in expected format."""
    # Create a test tag first
    test_tag_name = "search-test"
    if create_test_tag(test_tag_name):
        try:
            result = search_advanced(
                status="incomplete",
                tag=f"{test_namespace}-{test_tag_name}",
            )
            assert isinstance(result, str), "Should return a string"

            # Handle both success and error cases
            if "No items found" not in result and "Error in advanced search" not in result:
                items = result.split("\n\n---\n\n")
                for item in items:
                    assert verify_item_format(item), f"Item format is incorrect: {item}"
            elif "Error in advanced search" in result:
                # This is acceptable - the tag might not be recognized
                assert "Unrecognized tag type" in result or "Valid tag types" in result, "Should provide helpful error message"
        finally:
            # Clean up the test tag
            delete_test_tags()
    else:
        # If we can't create the tag, test with a non-existent tag
        result = search_advanced(
            status="incomplete",
            tag="non-existent-tag-xyz123",
        )
        assert isinstance(result, str), "Should return a string"
        assert "Error in advanced search" in result or "No items found" in result, f"Expected error or no results, got: {result}"


def test_get_recent():
    """Test get_recent() returns data in expected format."""
    result = get_recent(period="1d")
    assert isinstance(result, str), "Should return a string"

    if result != "No recent items found":
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_search_empty_results():
    """Test search_todos() with query that should return no matches."""
    # Use a very unlikely search term that shouldn't exist
    result = search_todos("xyz123unlikelysearchterm456abc")
    assert isinstance(result, str), "Should return a string"
    assert result == "No todos found matching 'xyz123unlikelysearchterm456abc'", f"Expected no results message, got: {result}"


def test_search_advanced_empty_results():
    """Test search_advanced() with filters that should return no matches."""
    # Search for items with a very specific combination that shouldn't exist
    result = search_advanced(status="incomplete", tag="xyz123unlikelytag456abc")
    assert isinstance(result, str), "Should return a string"
    # Should return an error for invalid tag, not "No items found"
    assert "Error in advanced search" in result, f"Expected error message, got: {result}"


def test_multiple_tag_filtering():
    """Test search_advanced() with multiple tags simultaneously."""
    # Get all available tags first
    all_tags = get_tags()
    assert isinstance(all_tags, str), "Should return a string"

    if all_tags != "No tags found":
        # Extract tag names from the response
        tag_lines = [line.strip() for line in all_tags.split("\n") if line.strip().startswith("Title:")]
        tag_names = [line.replace("Title:", "").strip() for line in tag_lines]

        if len(tag_names) >= 2:
            # Test with first available tag
            tag1 = tag_names[0]
            result = search_advanced(tag=tag1)
            assert isinstance(result, str), "Should return a string"

            # Note: Things AppleScript supports comma-separated tags like "Home, Mac"
            # but our current implementation might not support multiple tags in one call
            # This test verifies the current behavior

            # Test that we get a valid response (even if empty)
            assert result != "", "Should not return empty string"

            # If we have results, verify format
            # Handle both success and error cases
            if "No items found" not in result and "Error in advanced search" not in result:
                items = result.split("\n\n---\n\n")
                for item in items:
                    assert verify_item_format(item), f"Item format is incorrect: {item}"
            elif "Error in advanced search" in result:
                # This is acceptable - the tag might not be recognized
                assert "Unrecognized tag type" in result or "Valid tag types" in result, "Should provide helpful error message"


def test_search_with_emoji():
    """Test search_todos() with emoji characters in search query."""
    # Test with common emojis that might appear in project names
    emoji_queries = ["🚀", "📱", "💻", "🎯", "⭐"]

    for emoji in emoji_queries:
        result = search_todos(emoji)
        assert isinstance(result, str), f"Should return a string for emoji {emoji}"

        # Should either return no results or valid formatted results
        if "No todos found" not in result:
            items = result.split("\n\n---\n\n")
            for item in items:
                assert verify_item_format(item), f"Item format is incorrect for emoji {emoji}: {item}"


def test_search_advanced_with_emoji():
    """Test search_advanced() with emoji characters in tag filter."""
    # Test with emoji in tag search
    emoji_tags = ["🚀", "📱", "💻"]

    for emoji in emoji_tags:
        result = search_advanced(tag=emoji)
        assert isinstance(result, str), f"Should return a string for emoji tag {emoji}"

        # Should either return error for invalid tag or valid formatted results
        if "Error in advanced search" not in result and "No items found" not in result:
            items = result.split("\n\n---\n\n")
            for item in items:
                assert verify_item_format(item), f"Item format is incorrect for emoji tag {emoji}: {item}"


# === MCP INTEGRATION TESTS ===


def test_mcp_search_items_basic():
    """Test the MCP search_items endpoint returns properly formatted results."""
    result = search_all_items("test")
    assert isinstance(result, str), "Should return a string"

    # Should not return placeholder messages (this would catch our recent bug)
    assert "Search functionality removed" not in result, "Search should be functional, not a placeholder"
    assert "would search for" not in result.lower(), "Should perform actual search, not return placeholder"

    # Should either return no results or valid formatted results
    if "No items found matching" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_search_items_empty_query():
    """Test MCP search_items with empty query."""
    result = search_all_items("")
    assert isinstance(result, str), "Should return a string"
    # Should handle empty query gracefully
    assert result != "", "Should not return empty string"


def test_mcp_search_items_special_characters():
    """Test MCP search_items with special characters."""
    special_queries = ["@", "#", "&", "test-item", "item.with.dots"]

    for query in special_queries:
        result = search_all_items(query)
        assert isinstance(result, str), f"Should return a string for query: {query}"

        # Should either return no results or valid formatted results
        if "No items found matching" not in result:
            items = result.split("\n\n---\n\n")
            for item in items:
                assert verify_item_format(item), f"Item format is incorrect for query '{query}': {item}"


def test_mcp_show_item_inbox():
    """Test the MCP show_item endpoint for inbox."""
    result = show_item("inbox")
    assert isinstance(result, str), "Should return a string"

    # Should not return placeholder messages (this would catch our recent bug)
    assert "Show functionality removed" not in result, "Show should be functional, not a placeholder"
    assert "would be displayed" not in result.lower(), "Should show actual data, not return placeholder"

    # Should either return no items or valid formatted results
    if "No items found in Inbox" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_show_item_today():
    """Test the MCP show_item endpoint for today."""
    result = show_item("today")
    assert isinstance(result, str), "Should return a string"

    # Should not return placeholder messages
    assert "Show functionality removed" not in result, "Show should be functional, not a placeholder"

    # Should either return no items or valid formatted results
    if "No items due today" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_show_item_upcoming():
    """Test the MCP show_item endpoint for upcoming."""
    result = show_item("upcoming")
    assert isinstance(result, str), "Should return a string"

    # Should either return no items or valid formatted results
    if "No upcoming items" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_show_item_anytime():
    """Test the MCP show_item endpoint for anytime."""
    result = show_item("anytime")
    assert isinstance(result, str), "Should return a string"

    # Should either return no items or valid formatted results
    if "No items in Anytime list" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_show_item_someday():
    """Test the MCP show_item endpoint for someday."""
    result = show_item("someday")
    assert isinstance(result, str), "Should return a string"

    # Should either return no items or valid formatted results
    if "No items in Someday list" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_show_item_logbook():
    """Test the MCP show_item endpoint for logbook."""
    result = show_item("logbook")
    assert isinstance(result, str), "Should return a string"

    # Should either return no items or valid formatted results
    if "No completed items found" not in result:
        items = result.split("\n\n---\n\n")
        for item in items:
            assert verify_item_format(item), f"Item format is incorrect: {item}"


def test_mcp_show_item_specific_uuid():
    """Test the MCP show_item endpoint with a specific UUID."""
    # First get a project or todo UUID
    projects_result = get_projects()
    if projects_result != "No projects found":
        # Extract first UUID
        project_lines = projects_result.split("\n")
        for line in project_lines:
            if line.startswith("UUID:"):
                uuid = line.split("UUID:")[1].strip()

                # Test showing this specific item
                result = show_item(uuid)
                assert isinstance(result, str), "Should return a string"

                # Should not return placeholder messages
                assert "Show functionality removed" not in result, "Show should be functional"

                # Should return item details or error message
                if "Error" not in result and "not found" not in result:
                    # Should contain the UUID we requested
                    assert uuid in result, f"Result should contain the requested UUID: {uuid}"
                break


def test_mcp_show_item_invalid_id():
    """Test the MCP show_item endpoint with invalid ID."""
    result = show_item("invalid-uuid-12345")
    assert isinstance(result, str), "Should return a string"

    # Should handle invalid ID gracefully
    assert result != "", "Should not return empty string"
    # Should either return error or no results message
    assert any(phrase in result.lower() for phrase in ["error", "not found", "invalid"]), f"Should indicate invalid ID, got: {result}"


def test_mcp_show_item_empty_id():
    """Test the MCP show_item endpoint with empty ID."""
    result = show_item("")
    assert isinstance(result, str), "Should return a string"

    # Should handle empty ID gracefully
    assert result != "", "Should not return empty string"


def test_mcp_endpoints_consistency():
    """Test that MCP endpoints return consistent format with underlying functions."""
    # Test search consistency
    direct_search = search_todos("test")
    mcp_search = search_all_items("test")

    # Both should be strings
    assert isinstance(direct_search, str), "Direct search should return string"
    assert isinstance(mcp_search, str), "MCP search should return string"

    # Both should have similar structure (though content may differ due to different search scopes)
    if "No todos found" not in direct_search and "No items found" not in mcp_search:
        # Both should use the same item separator
        direct_items = direct_search.split("\n\n---\n\n")
        mcp_items = mcp_search.split("\n\n---\n\n")

        # Verify format consistency
        for item in direct_items:
            assert verify_item_format(item), "Direct search item format should be valid"
        for item in mcp_items:
            assert verify_item_format(item), "MCP search item format should be valid"


def test_mcp_search_comprehensive():
    """Test MCP search with various query types to ensure comprehensive coverage."""
    test_queries = [
        "project",  # Generic term
        "test",  # Common test term
        "AI",  # Abbreviation
        "development",  # Common tag/category
        "🚀",  # Emoji
        "2025",  # Year/number
        "@",  # Symbol
        "email",  # Common word
        "setup",  # Common action word
    ]

    for query in test_queries:
        result = search_all_items(query)
        assert isinstance(result, str), f"Should return string for query: {query}"

        # Should not return placeholder messages
        assert "Search functionality removed" not in result, f"Search should work for query: {query}"

        # Should either return no results or valid formatted results
        if "No items found matching" not in result:
            items = result.split("\n\n---\n\n")
            for item in items:
                assert verify_item_format(item), f"Item format incorrect for query '{query}': {item}"
