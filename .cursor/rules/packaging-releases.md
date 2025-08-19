# Packaging Releases - Things3-MCP

## Version Bump and Release Process

### Prerequisites
- Ensure you're in the development virtual environment: `source .venv/bin/activate`
- Ensure all changes are committed and tests pass
- Ensure pre-commit hooks are installed and working

### Step 1: Bump Version Number
1. Update version numbers in ALL of these files:
   - `pyproject.toml` - Update the version in the `[project]` section:
     ```toml
     version = "2.0.2"  # Increment from previous version
     ```
   - `src/things_mcp/__init__.py` - Update the `__version__` variable:
     ```python
     __version__ = "2.0.2"
     ```
   - `smithery.yaml` - Update the version field:
     ```yaml
     version: 2.0.2
     ```
   - `README.md` - Update the installation command version:
     ```bash
     pip install Things3-MCP-server==2.0.2
     ```
   - `uv.lock` - Regenerate by running `uv lock` (auto-updates version)

2. Follow semantic versioning:
   - **Patch** (2.0.0 → 2.0.1): Bug fixes, API compatibility
   - **Minor** (2.0.0 → 2.1.0): New features, backward compatible
   - **Major** (2.0.0 → 3.0.0): Breaking changes

**Important**: After updating the first 4 files manually, run `uv lock` to regenerate the lock file with the new version.

### Step 2: Commit Changes
```bash
# Add all changes
git add .

# Commit with descriptive message
git commit -m "Bump version to X.Y.Z

- Brief description of changes
- Any breaking changes or important notes"
```

**Note**: Pre-commit hooks will run automatically and must pass before commit succeeds.

### Step 3: Build Package
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Build both wheel and source distribution
python -m build
```

This creates:
- `dist/things3_mcp_server-X.Y.Z-py3-none-any.whl` (wheel)
- `dist/things3_mcp_server-X.Y.Z.tar.gz` (source)

### Step 4: Publish to PyPI
```bash
# Upload to PyPI (requires authentication)
twine upload dist/things3_mcp_server-X.Y.Z*
```

**Note**: You'll be prompted for PyPI username and password/token, these are stored in the `~/.pypirc` file.

### Step 5: Push to GitHub
```bash
git push origin main
```

### Step 6: Create GitHub Release
```bash
# Create GitHub release with tag
gh release create vX.Y.Z --title "Release vX.Y.Z" --notes "$(cat <<'EOF'
## What's Changed

- Brief description of changes
- Any breaking changes or important notes

## Installation

```bash
pip install Things3-MCP-server==X.Y.Z
```

**Full Changelog**: https://github.com/rossshannon/Things3-MCP/compare/vPREVIOUS...vX.Y.Z
EOF
)"

# Upload package files to the release
gh release upload vX.Y.Z dist/things3_mcp_server-X.Y.Z-py3-none-any.whl dist/things3_mcp_server-X.Y.Z.tar.gz
```

### Step 7: Verify Release
1. Check PyPI: https://pypi.org/project/Things3-MCP-server/
2. Check GitHub Release: https://github.com/rossshannon/Things3-MCP/releases
   - Verify release notes are correct
   - Confirm both `.whl` and `.tar.gz` files are attached
3. Test installation:
   ```bash
   # Clear pip cache if needed
   python3 -m pip cache purge

   # Test installation
   python3 -m pip install Things3-MCP-server==X.Y.Z
   ```

## Common Issues and Solutions

### PyPI Indexing Delay
- Sometimes PyPI takes a few minutes to index new releases
- Use `python3 -m pip index versions Things3-MCP-server` to check available versions
- Clear pip cache: `python3 -m pip cache purge`

### Pre-commit Hook Failures
- Ensure virtual environment is activated: `source .venv/bin/activate`
- Install dev dependencies: `uv pip install -e ".[dev]"`
- Fix any linting/formatting issues before committing

### Build Failures
- Check `pyproject.toml` syntax
- Ensure all dependencies are correctly specified
- Verify package structure matches build configuration

### Upload Failures
- Check PyPI credentials
- Ensure version number is unique (not already published)
- Verify package name matches exactly

## Version History
- `2.0.4`: Enhanced error handling and test coverage, pytest timeout configuration
- `2.0.3`: Fixed area location logging and improved error detection
- `2.0.2`: Version bump release
- `2.0.1`: Fixed FastMCP API compatibility (description → instructions, removed version param)
- `2.0.0`: Initial release with FastMCP implementation

## Important Notes
- Always test the package installation after publishing
- Update this file with new version history
- **REQUIRED**: Create a GitHub release for every version published to PyPI
- The README installation instructions should reference the latest stable version
