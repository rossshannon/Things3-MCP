#!/usr/bin/env python3
"""
Test runner for Things AppleScript Bridge Test Suite.

This script provides an easy way to run the test suite with proper setup.
"""

import sys
import os
import subprocess
from pathlib import Path

def main():
    """Run the test suite"""

    # Get the project root directory
    project_root = Path(__file__).parent
    tests_dir = project_root / "tests"

    print("🧪 Things AppleScript Bridge Test Suite")
    print("=" * 50)

    # Check if pytest is available
    try:
        import pytest
    except ImportError:
        print("❌ pytest not found. Installing test dependencies...")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                "-r", str(tests_dir / "requirements.txt")
            ])
            import pytest
            print("✅ Test dependencies installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install test dependencies: {e}")
            return 1

    # Check if Things app is running
    try:
        import things
        # Try to access Things to make sure it's available
        things.inbox()
        print("✅ Things app is accessible")
    except Exception as e:
        print(f"⚠️  Warning: Things app may not be accessible: {e}")
                print("   Make sure Things is running before running tests")

    # Set up the Python path to include src directory
    src_dir = project_root / "src"
    if src_dir.exists():
        original_path = os.environ.get('PYTHONPATH', '')
        new_path = str(src_dir) + (f":{original_path}" if original_path else "")
        os.environ['PYTHONPATH'] = new_path
        print(f"✅ PYTHONPATH set to include: {src_dir}")

    # Run the tests
    print("\n🚀 Running tests...")
    test_file = tests_dir / "test_applescript_bridge.py"

    # Pytest arguments for nice output
    pytest_args = [
        str(test_file),
        "-v",                    # verbose output
        "--tb=short",           # shorter traceback format
        "--color=yes",          # colored output
        "-x",                   # stop on first failure
        "--durations=10",       # show 10 slowest tests
    ]

    # Add HTML report if requested
    if "--html" in sys.argv:
        html_report = project_root / "test_report.html"
        pytest_args.extend(["--html", str(html_report), "--self-contained-html"])
        print(f"📊 HTML report will be generated at: {html_report}")

    # Run pytest
    exit_code = pytest.main(pytest_args)

    if exit_code == 0:
        print("\n✅ All tests passed!")
    else:
        print(f"\n❌ Tests failed with exit code: {exit_code}")
        print("\n⚠️  Note: Test items may need manual cleanup in Things app")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
