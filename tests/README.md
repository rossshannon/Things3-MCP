# Things AppleScript Bridge Test Suite

This test suite validates the core AppleScript bridge functions for the Things MCP integration:

- `add_todo` (add_task)
- `update_todo` (update_task)
- `add_project` (add_new_project)
- `update_project` (update_existing_project)

## Prerequisites

- **Things 3** must be installed and running
- **Python 3.8+**
- **pytest**
- **things.py library**

## Running Tests

### Quick Start

From the project root directory:

```bash
python3 run_tests.py
```

### With HTML Report

```bash
python3 run_tests.py --html
```

This generates a detailed HTML test report at `test_report.html`.

### Manual pytest Execution

If you prefer to run pytest directly:

```bash
# Install dependencies first
pip install -r tests/requirements.txt

# Run the test suite
pytest tests/test_applescript_bridge.py -v
```

## Test Coverage

### Todo Operations (`TestTodoOperations`)

- ✅ **Basic Creation**: Title, notes, verification
- ✅ **Tag Assignment**: Multiple tags, verification
- ✅ **Scheduling**: Today, tomorrow, anytime, someday, custom dates (YYYY-MM-DD)
- ✅ **Special Characters**: Emojis, Unicode, quotes
- ✅ **Title/Notes Updates**: Content modification
- ✅ **Tag Updates**: Replacing existing tags
- ✅ **Completion Status**: Marking as done
- ✅ **Moving Between Lists**: Today ↔ Anytime ↔ Someday

### Project Operations (`TestProjectOperations`)

- ✅ **Basic Creation**: Title, notes, verification
- ✅ **Complex Creation**: Tags + initial todos
- ✅ **Area Assignment**: Organizing projects
- ✅ **Scheduling**: Today, tomorrow, anytime, someday, custom dates (YYYY-MM-DD)
- ✅ **Title/Notes Updates**: Content modification
- ✅ **Tag Updates**: Replacing existing tags
- ✅ **Completion Status**: Marking as done

### Edge Cases (`TestEdgeCases`)

- ✅ **Empty Titles**: Boundary condition testing
- ✅ **Invalid IDs**: Error handling verification
- ✅ **Long Content**: Stress testing with large data

### Integration Testing

- ✅ **End-to-End Workflow**: Complete create → update → verify cycle
- ✅ **Cross-Operation Consistency**: Todo and project interoperability

## Test Features

### 🧹 Automatic Cleanup Tracking

The test suite tracks all created items and reports what needs manual cleanup:

```
⚠️  Manual cleanup needed:
   Todo: ABC123XYZ
   Project: DEF456UVW
```

### 🎯 Smart Assertions

Tests verify:
- Successful creation (returns valid IDs)
- Content accuracy (titles, notes preserved)
- Tag assignment (all tags applied correctly)
- Status changes (completion, cancellation)
- Error conditions (invalid IDs fail gracefully)

### 📊 Detailed Reporting

- Verbose test output shows each step
- Timing information for performance monitoring
- HTML reports with full details and screenshots
- Color-coded pass/fail indicators

## Test Structure

```
tests/
├── __init__.py                    # Package marker
├── test_applescript_bridge.py     # Main test suite
├── requirements.txt               # Test dependencies
└── README.md                      # This file

run_tests.py                       # Test runner script
```

## Sample Output

```
🧪 Things AppleScript Bridge Test Suite
==================================================
✅ Things app is accessible

🚀 Running tests...

tests/test_applescript_bridge.py::TestTodoOperations::test_add_todo_basic PASSED
tests/test_applescript_bridge.py::TestTodoOperations::test_add_todo_with_tags PASSED
tests/test_applescript_bridge.py::TestTodoOperations::test_update_todo_tags PASSED
tests/test_applescript_bridge.py::TestProjectOperations::test_add_project_basic PASSED
tests/test_applescript_bridge.py::test_integration_workflow PASSED

✅ All tests passed!
```

## Important Notes

### Manual Cleanup Required

Since Things doesn't provide programmatic deletion via AppleScript, test items need manual cleanup. The test suite tracks all created items and reports their IDs for easy removal.

### Test Data Isolation

Tests use recognizable naming patterns:
- **Todos**: "Test Todo 🧪", "Tagged Todo ✨"
- **Projects**: "Test Project 🏗️", "Integration Test Project 🔄"

### Real Things App

Tests run against your actual Things app, not a mock. This provides authentic validation but means:
- Test items appear in your real Things database
- Tests may fail if Things is not running
- Network/sync delays may affect timing-sensitive tests

## Troubleshooting

### "Things app may not be accessible"

Ensure Things 3 is running and responsive. Try:
1. Launch Things manually
2. Wait for sync to complete
3. Re-run tests

### "AssertionError: Todo should exist in Things"

This usually indicates:
1. AppleScript execution failed
2. Things is unresponsive
3. Timing issues with item creation

Check the detailed error output and ensure Things is running properly.

### Tests Pass but Items Not Visible

Things may be syncing in the background. Wait a moment and refresh your Things view.

## Contributing

To add new tests:

1. Add test methods to the appropriate class
2. Use the `cleanup_tracker` fixture for item tracking
3. Follow the naming convention for test items
4. Include both positive and negative test cases
5. Verify cleanup reporting works correctly

## Integration with CI/CD

For automated testing environments:

```bash
# Headless testing (if Things supports it)
python3 run_tests.py --quiet --tb=line

# Generate machine-readable results
pytest tests/test_applescript_bridge.py --junitxml=test_results.xml
```

Note: Automated testing requires a macOS environment with Things 3 installed and configured.
