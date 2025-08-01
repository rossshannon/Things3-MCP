# Things FastMCP Test Suite Todo List


## Critical Requirement
> **⚠️ IMPORTANT**: The test suite MUST be fully self-contained with no dependency on existing Projects, Areas or Tags, and MUST NOT have any side-effects on existing data.

## Core Requirements
- [x] Ensure test suite is fully self-contained
  - [x] Create all required test data within tests
  - [x] No dependencies on existing Projects
  - [x] No dependencies on existing Areas
  - [x] No dependencies on existing Tags
- [x] Prevent side-effects on existing data
  - [x] Verify no modifications to existing items
  - [x] Clean up all test data after tests
  - [x] Handle test failures without leaving artifacts

## List View Operations
- [x] Test `get_inbox()`
- [x] Test `get_today()`
- [x] Test `get_upcoming()`
- [x] Test `get_anytime()`
- [x] Test `get_someday()`
- [x] Test `get_logbook()`
- [x] Test `get_trash()`
- [x] Test `get_todos()` with project filtering
- [x] Test `get_projects()` with `include_items=True`
- [x] Test `get_areas()` with `include_items=True`
- [x] Test `get_tags()` and `get_tagged_items()`
- [x] Test `search_todos()` and `search_advanced()`
- [x] Test `get_recent()` functionality
- [x] Test empty search results
- [x] Test multiple tag filtering
- [x] Test searching by emoji

## Task Operations
- [x] Test task completion states
- [x] Test moving tasks between different types of lists
- [x] Test deadline parameter in `add_todo()`
- [x] Test deadline parameter in `update_todo()`
- [x] Test scheduling scenarios (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
- [x] Test tag operations (adding/removing multiple tags)
- [x] Test task completion
- [x] Test moving tasks between projects
- [x] Test moving tasks between areas
- [x] Allow tasks to be created directly in an existing Area.

## Project Operations
- [x] Test deadline parameter in `add_project()`
- [x] Test deadline parameter in `update_project()`
- [x] Test scheduling scenarios (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
- [x] Test tag operations (adding/removing multiple tags)
- [x] Test project completion
- [x] Test moving projects between areas
- [x] Allow projects to be created directly in an existing Area.

## AppleScript Bridge Functionality
- [x] Test AppleScript error message parsing
- [x] Test special character handling in AppleScript strings

## Edge Cases and Error Handling
- [x] Test invalid date formats
- [x] Test invalid list names
- [x] Test nonexistent projects/areas
- [x] Test concurrent operations limits
- [x] Test Things app not running scenarios
- [x] Test large data set handling

## Documentation and Maintenance
- [x] Document test setup requirements
- [x] Document known limitations
- [x] Create test data generators
- [x] Create test helper functions
- [x] Document test coverage metrics
- [x] Create test run automation scripts
- [x] Create test run automation scripts

## Data Integrity Verification
- [x] Verify no unintended tag creation
- [x] Verify no unintended project/area creation
- [x] Verify no modification of existing items
