# Things MCP Server

This [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) server lets you use Claude Desktop to interact with your task management data in [Things app](https://culturedcode.com/things). You can ask Claude to create tasks, analyze projects, help manage priorities, and more.

This server leverages the [Things.py](https://github.com/thingsapi/things.py) library and the [Things URL Scheme](https://culturedcode.com/things/help/url-scheme/), with additional reliability features including:

- **Robust error handling** with exponential backoff and retry mechanisms
- **Circuit breaker pattern** to prevent cascading failures
- **Dead letter queue** for failed operations
- **Intelligent caching** for improved performance
- **Comprehensive logging** with structured JSON output
- **AppleScript bridge** for operations that fail with URL schemes
- **Rate limiting** to prevent overwhelming the Things app
- **Extensive test suite** for reliability 

## Why Things MCP?

This MCP server unlocks the power of AI for your task management:

- **Natural Language Task Creation**: Ask Claude to create tasks with all details in natural language
- **Smart Task Analysis**: Get insights into your projects and productivity patterns
- **GTD & Productivity Workflows**: Let Claude help you implement productivity systems
- **Seamless Integration**: Works directly with your existing Things 3 data

## Features

- Access to all major Things lists (Inbox, Today, Upcoming, etc.)
- Project and area management
- Tag operations
- Advanced search capabilities
- Recent items tracking
- Detailed item information including checklists
- Support for nested data (projects within areas, todos within projects)

## Installation Options

There are multiple ways to install and use the Things MCP server:

### Option 1: Install from PyPI (Recommended)

#### Prerequisites
* Python 3.12+
* Claude Desktop
* Things 3 ("Enable Things URLs" must be turned on in Settings -> General)
* Things Authentication Token (required for URL scheme operations)

#### Installation

```bash
pip install things-mcp
```

Or using uv (recommended):

```bash
uv pip install things-mcp
```

#### Running

After installation, you can run the server directly:

```bash
things-mcp
```

### Option 2: Manual Installation

#### Prerequisites
* Python 3.12+
* Claude Desktop
* Things 3 ("Enable Things URLs" must be turned on in Settings -> General)

#### Step 1: Install uv
Install uv if you haven't already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Restart your terminal afterwards.

#### Step 2: Clone this repository
```bash
git clone https://github.com/hald/things-mcp
cd things-mcp
```

#### Step 3: Set up Python environment and dependencies
```bash
uv venv
uv pip install -r pyproject.toml
```

### Step 4: Configure Things authentication token
Run the configuration tool to set up your Things authentication token:
```bash
python configure_token.py
```
This will guide you through the process of configuring your Things authentication token, which is required for the MCP server to interact with your Things app.

### Step 5: Configure Claude Desktop
Edit the Claude Desktop configuration file:
```bash
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Add the Things server to the mcpServers key in the configuration file (be sure to update the path to the folder where you installed these files):
```json
{
    "mcpServers": {
        "things": {
            "command": "uv",
            "args": [
                "--directory",
                "/ABSOLUTE/PATH/TO/PARENT/FOLDER/things-mcp",
                "run",
                "things_server.py"
            ]
        }
    }
}
```

### Step 6: Configure Authentication Token
The Things URL scheme requires an authentication token. You can find it in Things → Settings → General.

Option 1: Set via configuration script
```bash
python configure_token.py
```

Option 2: Set via environment variable
```bash
export THINGS_AUTH_TOKEN="your-token-here"
```

Option 3: Manually create config file
```bash
mkdir -p ~/.things-mcp
echo '{"things_auth_token": "your-token-here"}' > ~/.things-mcp/config.json
```

### Step 7: Restart Claude Desktop
Restart the Claude Desktop app to apply the changes.

### Sample Usage with Claude Desktop
* "What's on my todo list today?"
* "Create a todo to pack for my beach vacation next week, include a packling checklist."
* "Evaluate my current todos using the Eisenhower matrix."
* "Help me conduct a GTD-style weekly review using Things."

#### Tips
* Create a project in Claude with custom instructions that explains how you use Things and organize areas, projects, tags, etc. Tell Claude what information you want included when it creates a new task (eg asking it to include relevant details in the task description might be helpful).
* Try adding another MCP server that gives Claude access to your calendar. This will let you ask Claude to block time on your calendar for specific tasks, create todos from upcoming calendar events (eg prep for a meeting), etc.


### Available Tools

#### List Views
- `get-inbox` - Get todos from Inbox
- `get-today` - Get todos due today
- `get-upcoming` - Get upcoming todos
- `get-anytime` - Get todos from Anytime list
- `get-someday` - Get todos from Someday list
- `get-logbook` - Get completed todos
- `get-trash` - Get trashed todos

#### Basic Operations
- `get-todos` - Get todos, optionally filtered by project
- `get-projects` - Get all projects
- `get-areas` - Get all areas

#### Tag Operations
- `get-tags` - Get all tags
- `get-tagged-items` - Get items with a specific tag

#### Search Operations
- `search-todos` - Simple search by title/notes
- `search-advanced` - Advanced search with multiple filters

#### Time-based Operations
- `get-recent` - Get recently created items

#### Modification Operations
- `add-todo` - Create a new todo with full parameter support
- `add-project` - Create a new project with tags and todos
- `update-todo` - Update an existing todo
- `update-project` - Update an existing project
- `delete-todo` - Delete a todo (moves to trash)
- `delete-project` - Delete a project (moves to trash)
- `show-item` - Show a specific item or list in Things
- `search-items` - Search for items in Things

## Tool Parameters

### get-todos
- `project_uuid` (optional) - Filter todos by project
- `include_items` (optional, default: true) - Include checklist items

### get-projects / get-areas / get-tags
- `include_items` (optional, default: false) - Include contained items

### search-advanced
- `status` - Filter by status (incomplete/completed/canceled)
- `start_date` - Filter by start date (YYYY-MM-DD)
- `deadline` - Filter by deadline (YYYY-MM-DD)
- `tag` - Filter by tag
- `area` - Filter by area UUID
- `type` - Filter by item type (to-do/project/heading)

### get-recent
- `period` - Time period (e.g., '3d', '1w', '2m', '1y')

### add-todo
- `title` - Title of the todo
- `notes` (optional) - Notes for the todo
- `when` (optional) - When to schedule the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
- `deadline` (optional) - Deadline for the todo (YYYY-MM-DD)
- `tags` (optional) - Tags to apply to the todo
- `list_title` or `list_id` (optional) - Title or ID of project/area to add to
- `heading` (optional) - Heading to add under
- `checklist_items` (optional) - Checklist items to add

### update-todo
- `id` - ID of the todo to update
- `title` (optional) - New title
- `notes` (optional) - New notes
- `when` (optional) - New schedule
- `deadline` (optional) - New deadline
- `tags` (optional) - New tags
- `completed` (optional) - Mark as completed
- `canceled` (optional) - Mark as canceled

### add-project
- `title` - Title of the project
- `notes` (optional) - Notes for the project
- `when` (optional) - When to schedule the project
- `deadline` (optional) - Deadline for the project
- `tags` (optional) - Tags to apply to the project
- `area_title` or `area_id` (optional) - Title or ID of area to add to
- `todos` (optional) - Initial todos to create in the project

### update-project
- `id` - ID of the project to update
- `title` (optional) - New title
- `notes` (optional) - New notes
- `when` (optional) - New schedule
- `deadline` (optional) - New deadline
- `tags` (optional) - New tags
- `completed` (optional) - Mark as completed
- `canceled` (optional) - Mark as canceled

### delete-todo
- `id` - ID of the todo to delete (moves to trash)

### delete-project
- `id` - ID of the project to delete (moves to trash)

### show-item
- `id` - ID of item to show, or one of: inbox, today, upcoming, anytime, someday, logbook
- `query` (optional) - Optional query to filter by
- `filter_tags` (optional) - Optional tags to filter by

## Important Limitations

### Tags
- Tags must exist in Things before they can be applied to todos or projects
- The MCP server will automatically create missing tags when you try to use them
- If tag creation fails, the todo/project will still be created but without tags

### Authentication Token
- Required for all URL scheme operations (create, update, delete)
- Without a token, Things will prompt for authentication on each operation

## Authentication Token Configuration

The Things MCP server requires an authentication token to interact with the Things app. This token is used to authorize URL scheme commands.

### How to get your Things authentication token

1. Open Things app on your Mac
2. Go to Things → Preferences (⌘,)
3. Select the General tab
4. Make sure "Enable Things URLs" is checked
5. Look for the authentication token displayed in the preferences window

### Configuring the token

Run the included configuration tool to set up your token:

```bash
python configure_token.py
```

This interactive script will prompt you for your token and save it securely in your local configuration.

## Development

This project uses `pyproject.toml` to manage dependencies and build configuration. It's built using the [Model Context Protocol](https://modelcontextprotocol.io), which allows Claude to securely access tools and data.

### Implementation Options

This project provides two different implementation approaches:

1. **Standard MCP Server** (`things_server.py`) - The original implementation that uses the basic MCP server pattern.

2. **FastMCP Server** (`things_fast_server.py`) - A modern implementation using the FastMCP pattern for cleaner, more maintainable code with decorator-based tool registration.

### Development Workflow

#### Setting up a development environment

```bash
# Clone the repository
git clone https://github.com/hald/things-mcp
cd things-mcp

# Set up a virtual environment with development dependencies
uv venv
uv pip install -e ".[dev]"  # Install in development mode with extra dependencies
```

#### Testing changes during development

Use the MCP development server to test changes:

```bash
# Test the FastMCP implementation
mcp dev things_fast_server.py

# Or test the traditional implementation
mcp dev things_server.py
```

#### Building the package for PyPI

```bash
python -m build
```

#### Publishing to PyPI

```bash
twine upload dist/*
```

Requires Python 3.12+.

## Reliability Features

### Error Handling & Recovery
- **Retry Logic**: Automatic retries with exponential backoff for transient failures
- **Circuit Breaker**: Prevents repeated failures from overwhelming the system
- **Dead Letter Queue**: Failed operations are stored for later retry or analysis
- **AppleScript Fallback**: When URL scheme operations fail, falls back to direct AppleScript

### Performance Optimization
- **Smart Caching**: Frequently accessed data is cached with appropriate TTLs
- **Rate Limiting**: Prevents overwhelming Things app with too many requests
- **Cache Invalidation**: Automatic cache clearing when data is modified

### Monitoring & Debugging
- **Structured Logging**: JSON-formatted logs for better analysis
- **Operation Tracking**: Each operation is logged with timing and status
- **Cache Statistics**: Monitor cache performance with `get-cache-stats` tool
- **Log Locations**: 
  - Main logs: `~/.things-mcp/logs/things_mcp.log`
  - Structured logs: `~/.things-mcp/logs/things_mcp_structured.json`
  - Error logs: `~/.things-mcp/logs/things_mcp_errors.log`

## Troubleshooting

The server includes error handling for:
- Invalid UUIDs
- Missing required parameters
- Things database access errors
- Data formatting errors
- Authentication token issues
- Network timeouts
- AppleScript execution failures

### Common Issues

1. **Missing or invalid token**: Run `python configure_token.py` to set up your token
2. **Things app not running**: The server will attempt to launch Things automatically
3. **URL scheme not enabled**: Check that "Enable Things URLs" is enabled in Things → Preferences → General
4. **Operations failing**: Check the circuit breaker status and dead letter queue
5. **Performance issues**: Monitor cache statistics with the `get-cache-stats` tool

### Checking Logs

All errors are logged and returned with descriptive messages. To review the MCP logs:

```bash
# Follow main logs in real-time
tail -f ~/.things-mcp/logs/things_mcp.log

# Check error logs
tail -f ~/.things-mcp/logs/things_mcp_errors.log

# View structured logs for analysis
cat ~/.things-mcp/logs/things_mcp_structured.json | jq

# Claude Desktop MCP logs
tail -n 20 -f ~/Library/Logs/Claude/mcp*.log
```

### Advanced Debugging

1. **Check Dead Letter Queue**: Failed operations are stored in `things_dlq.json`
2. **Monitor Circuit Breaker**: Look for "Circuit breaker" messages in logs
3. **Cache Performance**: Use `get-cache-stats` tool to check hit rates
4. **Enable Debug Logging**: Set console level to DEBUG in `logging_config.py`
