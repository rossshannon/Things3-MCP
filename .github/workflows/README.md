# GitHub Actions Workflows

## Automated PyPI Publishing

This repository includes GitHub Actions workflows for automated package building and publishing.

### Package vs Repository Names
- **GitHub Repository**: `rossshannon/Things3-MCP`
- **PyPI Package**: `Things3-MCP-server` (https://pypi.org/project/Things3-MCP-server/)
- **Python Import**: `import things3_mcp`

### Current Workflows

- **`lint.yml`** - Runs linting and code quality checks on PRs and pushes
- **`publish-trusted.yml`** - Automated PyPI publishing with trusted publishing

### Setting Up Automated Publishing

#### Trusted Publishing Setup

1. **Configure PyPI Trusted Publisher**:
   - Go to https://pypi.org/manage/account/publishing/
   - Add a new trusted publisher for the **Things3-MCP-server** package:
     - **Owner**: `rossshannon`
     - **Repository**: `Things3-MCP` (GitHub repository name)
     - **Workflow**: `publish-trusted.yml`
     - **Environment**: `pypi`

2. **Enable the workflow**:
   - The `publish-trusted.yml` workflow is ready to use
   - Create a GitHub environment called `pypi` in repository settings
   - No API tokens needed!

### How It Works

#### Current Manual Process:
```bash
# 1. Update versions manually
# 2. Commit and tag
git commit -m "Bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags

# 3. Build manually
python -m build

# 4. Upload manually
twine upload dist/*

# 5. Create GitHub release manually
gh release create vX.Y.Z --generate-notes
gh release upload vX.Y.Z dist/*
```

#### With Automation:
```bash
# 1. Update versions and commit
git commit -m "Bump version to X.Y.Z"
git push origin main

# 2. Create GitHub release (triggers everything automatically)
gh release create vX.Y.Z --generate-notes

# ✅ Done! GitHub Actions handles:
# - Building packages
# - Testing installation
# - Publishing to PyPI
# - Uploading artifacts to GitHub release
```

### Benefits of Automation

- **Consistency**: Same build process every time
- **Security**: No local API tokens needed with trusted publishing
- **Testing**: Automated installation testing before publishing
- **Reliability**: Reduces human error in release process
- **Audit Trail**: All releases tracked in GitHub Actions logs
- **Rollback**: Easy to see exactly what was published and when

### Workflow Triggers

- **`on: release: types: [published]`** - Triggers when you create a GitHub release
- **`on: push: tags: ['v*']`** - Alternative: triggers on version tags
- **Manual trigger**: Can add `workflow_dispatch` for manual runs

### Environment Protection

The `pypi` environment can be configured with:
- **Required reviewers**: Require approval before publishing
- **Branch restrictions**: Only allow publishing from main branch
- **Wait timer**: Add delay before publishing

This gives you an extra safety net for important releases.
