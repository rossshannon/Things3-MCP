# Things FastMCP Test Suite Todo List

## Critical Requirement
> **⚠️ IMPORTANT**: The test suite MUST be fully self-contained with no dependency on existing Projects, Areas or Tags, and MUST NOT have any side-effects on existing data.

## Core Requirements
- [ ] Ensure test suite is fully self-contained
  - [ ] Create all required test data within tests
  - [ ] No dependencies on existing Projects
  - [ ] No dependencies on existing Areas
  - [ ] No dependencies on existing Tags
- [ ] Prevent side-effects on existing data
  - [ ] Verify no modifications to existing items
  - [ ] Clean up all test data after tests
  - [ ] Handle test failures without leaving artifacts
  - [ ] Implement proper rollback mechanisms

## List View Operations
- [ ] Test `get_inbox()`
- [ ] Test `get_today()`
- [ ] Test `get_upcoming()`
- [ ] Test `get_anytime()`
- [ ] Test `get_someday()`
- [ ] Test `get_logbook()`
- [ ] Test `get_trash()`
- [ ] Test `get_todos()` with project filtering
- [ ] Test `get_projects()` with `include_items=True`
- [ ] Test `get_areas()` with `include_items=True`
- [ ] Test `get_tags()` and `get_tagged_items()`
- [ ] Test `search_todos()` and `search_advanced()`
- [ ] Test `get_recent()` functionality

## Project Operations
- [ ] Test deadline parameter in `add_project_direct()`
- [ ] Test deadline parameter in `update_project_direct()`
- [ ] Test complex tag operations (adding/removing multiple tags)
- [ ] Test project completion with subtasks
- [ ] Test project cancellation scenarios
- [ ] Test project scheduling with specific dates
- [ ] Test project completion states
- [ ] Test project dependencies

## Task Operations
- [ ] Test deadline parameter in `add_todo_direct()`
- [ ] Test deadline parameter in `update_todo_direct()`
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
- [ ] Test cache hit rates
- [ ] Test operation timing thresholds
- [ ] Test memory usage patterns
- [ ] Test concurrent operation handling
- [ ] Test rate limiting effectiveness
- [ ] Test circuit breaker triggering
- [ ] Test recovery after circuit breaker trips
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
- [ ] Create snapshots of Things database before tests
- [ ] Verify database integrity after tests
- [ ] Implement rollback mechanisms for failed tests
- [ ] Verify no unintended tag creation
- [ ] Verify no unintended project/area creation
- [ ] Verify no modification of existing items
