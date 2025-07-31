# Things FastMCP Test Suite Todo List

- [ ] Allow tasks and projects to be created directly in an existing Area.

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

## Project Operations
- [ ] Test deadline parameter in `add_project()`
- [ ] Test deadline parameter in `update_project()`
- [ ] Test complex tag operations (adding/removing multiple tags)
- [ ] Test project completion with subtasks
- [ ] Test project scheduling with specific dates

## Task Operations
- [ ] Test deadline parameter in `add_todo()`
- [ ] Test deadline parameter in `update_todo()`
- [ ] Test complex scheduling scenarios (specific dates)
- [ ] Test task completion with checklist items
- [ ] Test task relationships (dependencies)
- [ ] Test moving tasks between different types of lists
- [ ] Test task completion states
- [ ] Test task priority levels

## AppleScript Bridge Functionality
- [ ] Test rate limiting functionality
- [ ] Test circuit breaker functionality
- [ ] Test cache invalidation scenarios
- [ ] Test complex error recovery scenarios
- [ ] Test date conversion edge cases
- [ ] Test AppleScript timeout handling
- [ ] Test AppleScript error message parsing
- [ ] Test special character handling in AppleScript strings

## Edge Cases and Error Handling
- [ ] Test invalid date formats
- [ ] Test invalid list names
- [ ] Test nonexistent projects/areas
- [ ] Test concurrent operations limits
- [ ] Test network timeout scenarios
- [ ] Test Things app not running scenarios
- [ ] Test recovery from Things app crashes
- [ ] Test large data set handling

## Performance and Reliability
- [ ] Test concurrent operation handling
- [ ] Test long-running operation stability

## Documentation and Maintenance
- [ ] Document test setup requirements
- [ ] Document test cleanup procedures
- [ ] Document known limitations
- [ ] Document performance characteristics
- [ ] Create test data generators
- [ ] Create test helper functions
- [ ] Document test coverage metrics
- [ ] Create test run automation scripts

## Data Integrity Verification
- [ ] Verify no unintended tag creation
- [ ] Verify no unintended project/area creation
- [ ] Verify no modification of existing items
