#!/usr/bin/env python3
"""
Simplified Things MCP Server with essential reliability features.
Focuses on practicality over enterprise patterns.
"""
import logging
import time
import things
from typing import Dict, Any, Optional, List
from functools import lru_cache
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP
import mcp.types as types

# Import our minimal supporting modules
from .formatters import format_todo, format_project, format_area, format_tag
from .applescript_bridge import add_todo_direct, update_todo_direct
from .simple_url_scheme import add_todo, add_project, update_todo, update_project, show, search, launch_things
from .config import get_things_auth_token
from .tag_handler import ensure_tags_exist

# Simple logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create the FastMCP server
mcp = FastMCP(
    "Things", 
    description="Interact with the Things task management app",
    version="0.2.0"
)

# Simple retry decorator
def retry(max_attempts=3, delay=1.0):
    """Simple retry decorator with fixed delay."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying...")
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_attempts} attempts failed: {str(e)}")
            raise last_error
        return wrapper
    return decorator

# Simple cache with TTL
class SimpleCache:
    def __init__(self):
        self.cache = {}
        self.timestamps = {}
    
    def get(self, key, ttl_seconds=300):
        """Get value from cache if not expired."""
        if key in self.cache:
            if datetime.now() - self.timestamps[key] < timedelta(seconds=ttl_seconds):
                return self.cache[key]
            else:
                # Expired, remove it
                del self.cache[key]
                del self.timestamps[key]
        return None
    
    def set(self, key, value):
        """Set value in cache."""
        self.cache[key] = value
        self.timestamps[key] = datetime.now()
    
    def invalidate(self, pattern=None):
        """Clear cache entries matching pattern or all if pattern is None."""
        if pattern is None:
            self.cache.clear()
            self.timestamps.clear()
        else:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.cache[key]
                del self.timestamps[key]

# Global cache instance
cache = SimpleCache()

# Helper function to ensure Things is running
def ensure_things_running():
    """Make sure Things app is running."""
    try:
        # Quick check if Things is responsive
        things.inbox()
        return True
    except:
        logger.info("Things not responding, attempting to launch...")
        if launch_things():
            time.sleep(2)  # Give it time to start
            return True
        return False

# LIST VIEWS

@mcp.tool(name="get-inbox")
def get_inbox() -> str:
    """Get todos from Inbox"""
    # Check cache first
    cached_result = cache.get("inbox", ttl_seconds=30)
    if cached_result is not None:
        return cached_result
    
    todos = things.inbox()
    
    if not todos:
        result = "No items found in Inbox"
    else:
        formatted_todos = [format_todo(todo) for todo in todos]
        result = "\n\n---\n\n".join(formatted_todos)
    
    cache.set("inbox", result)
    return result

@mcp.tool(name="get-today")
def get_today() -> str:
    """Get todos due today"""
    cached_result = cache.get("today", ttl_seconds=30)
    if cached_result is not None:
        return cached_result
    
    todos = things.today()
    
    if not todos:
        result = "No items due today"
    else:
        formatted_todos = [format_todo(todo) for todo in todos]
        result = "\n\n---\n\n".join(formatted_todos)
    
    cache.set("today", result)
    return result

@mcp.tool(name="get-upcoming")
def get_upcoming() -> str:
    """Get upcoming todos"""
    cached_result = cache.get("upcoming", ttl_seconds=60)
    if cached_result is not None:
        return cached_result
    
    todos = things.upcoming()
    
    if not todos:
        result = "No upcoming items"
    else:
        formatted_todos = [format_todo(todo) for todo in todos]
        result = "\n\n---\n\n".join(formatted_todos)
    
    cache.set("upcoming", result)
    return result

@mcp.tool(name="get-anytime")
def get_anytime() -> str:
    """Get todos from Anytime list"""
    cached_result = cache.get("anytime", ttl_seconds=300)
    if cached_result is not None:
        return cached_result
    
    todos = things.anytime()
    
    if not todos:
        result = "No items in Anytime list"
    else:
        formatted_todos = [format_todo(todo) for todo in todos]
        result = "\n\n---\n\n".join(formatted_todos)
    
    cache.set("anytime", result)
    return result

@mcp.tool(name="get-someday")
def get_someday() -> str:
    """Get todos from Someday list"""
    cached_result = cache.get("someday", ttl_seconds=300)
    if cached_result is not None:
        return cached_result
    
    todos = things.someday()
    
    if not todos:
        result = "No items in Someday list"
    else:
        formatted_todos = [format_todo(todo) for todo in todos]
        result = "\n\n---\n\n".join(formatted_todos)
    
    cache.set("someday", result)
    return result

@mcp.tool(name="get-logbook")
def get_logbook(period: str = "7d", limit: int = 50) -> str:
    """Get completed todos from Logbook"""
    cache_key = f"logbook_{period}_{limit}"
    cached_result = cache.get(cache_key, ttl_seconds=300)
    if cached_result is not None:
        return cached_result
    
    todos = things.last(period, status='completed')
    
    if not todos:
        result = "No completed items found"
    else:
        if len(todos) > limit:
            todos = todos[:limit]
        formatted_todos = [format_todo(todo) for todo in todos]
        result = "\n\n---\n\n".join(formatted_todos)
    
    cache.set(cache_key, result)
    return result

@mcp.tool(name="get-trash")
def get_trash() -> str:
    """Get trashed todos"""
    todos = things.trash()
    
    if not todos:
        return "No items in trash"
    
    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

# BASIC TODO OPERATIONS

@mcp.tool(name="get-todos")
def get_todos(project_uuid: Optional[str] = None, include_items: bool = True) -> str:
    """Get todos, optionally filtered by project"""
    if project_uuid:
        project = things.get(project_uuid)
        if not project or project.get('type') != 'project':
            return f"Error: Invalid project UUID '{project_uuid}'"

    todos = things.todos(project=project_uuid, start=None)
    
    if not todos:
        return "No todos found"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="get-projects")
def get_projects(include_items: bool = False) -> str:
    """Get all projects from Things"""
    cached_result = cache.get(f"projects_{include_items}", ttl_seconds=300)
    if cached_result is not None:
        return cached_result
    
    projects = things.projects()

    if not projects:
        result = "No projects found"
    else:
        formatted_projects = [format_project(project, include_items) for project in projects]
        result = "\n\n---\n\n".join(formatted_projects)
    
    cache.set(f"projects_{include_items}", result)
    return result

@mcp.tool(name="get-areas")
def get_areas(include_items: bool = False) -> str:
    """Get all areas from Things"""
    cached_result = cache.get(f"areas_{include_items}", ttl_seconds=600)
    if cached_result is not None:
        return cached_result
    
    areas = things.areas()

    if not areas:
        result = "No areas found"
    else:
        formatted_areas = [format_area(area, include_items) for area in areas]
        result = "\n\n---\n\n".join(formatted_areas)
    
    cache.set(f"areas_{include_items}", result)
    return result

# TAG OPERATIONS

@mcp.tool(name="get-tags")
def get_tags(include_items: bool = False) -> str:
    """Get all tags"""
    cached_result = cache.get(f"tags_{include_items}", ttl_seconds=600)
    if cached_result is not None:
        return cached_result
    
    tags = things.tags()

    if not tags:
        result = "No tags found"
    else:
        formatted_tags = [format_tag(tag, include_items) for tag in tags]
        result = "\n\n---\n\n".join(formatted_tags)
    
    cache.set(f"tags_{include_items}", result)
    return result

@mcp.tool(name="get-tagged-items")
def get_tagged_items(tag: str) -> str:
    """Get items with a specific tag"""
    todos = things.todos(tag=tag)

    if not todos:
        return f"No items found with tag '{tag}'"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

# SEARCH OPERATIONS

@mcp.tool(name="search-todos")
def search_todos(query: str) -> str:
    """Search todos by title or notes"""
    todos = things.search(query)

    if not todos:
        return f"No todos found matching '{query}'"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="search-advanced")
def search_advanced(
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    deadline: Optional[str] = None,
    tag: Optional[str] = None,
    area: Optional[str] = None,
    type: Optional[str] = None
) -> str:
    """Advanced todo search with multiple filters"""
    kwargs = {}
    if status:
        kwargs['status'] = status
    if deadline:
        kwargs['deadline'] = deadline
    if start_date:
        kwargs['start'] = start_date
    if tag:
        kwargs['tag'] = tag
    if area:
        kwargs['area'] = area
    if type:
        kwargs['type'] = type
        
    try:
        todos = things.todos(**kwargs)
        
        if not todos:
            return "No items found matching your search criteria"
            
        formatted_todos = [format_todo(todo) for todo in todos]
        return "\n\n---\n\n".join(formatted_todos)
    except Exception as e:
        return f"Error in advanced search: {str(e)}"

# MODIFICATION OPERATIONS

@mcp.tool(name="add-todo")
@retry(max_attempts=3)
def add_task(
    title: str,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    checklist_items: Optional[List[str]] = None,
    list_id: Optional[str] = None,
    list_title: Optional[str] = None,
    heading: Optional[str] = None
) -> str:
    """Create a new todo in Things"""
    # Ensure Things is running
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
    
    # Ensure tags exist before using them
    if tags:
        logger.info(f"Ensuring tags exist: {tags}")
        if not ensure_tags_exist(tags):
            logger.warning("Failed to ensure all tags exist, but continuing anyway")
    
    # Use URL scheme for creation as it supports more parameters
    # According to Things URL scheme docs, some features only work via URL scheme
    try:
        # The URL scheme uses 'list' parameter for project/area name
        result = add_todo(
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            tags=tags,
            checklist_items=checklist_items,
            list_id=list_id,
            list=list_title,  # This is the correct parameter name for project/area
            heading=heading
        )
        
        if result:
            # Invalidate relevant caches
            cache.invalidate("inbox")
            cache.invalidate("today")
            cache.invalidate("upcoming")
            
            return f"✅ Created todo: {title}"
        else:
            return f"❌ Failed to create todo: {title}"
    except Exception as e:
        logger.error(f"Error creating todo: {str(e)}")
        return f"❌ Error creating todo: {str(e)}"

@mcp.tool(name="add-project")
@retry(max_attempts=3)
def add_new_project(
    title: str,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    area_id: Optional[str] = None,
    area_title: Optional[str] = None,
    todos: Optional[List[str]] = None
) -> str:
    """Create a new project in Things"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
    
    # Ensure tags exist before using them
    if tags:
        logger.info(f"Ensuring tags exist for project: {tags}")
        if not ensure_tags_exist(tags):
            logger.warning("Failed to ensure all tags exist, but continuing anyway")
        
    try:
        result = add_project(
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            tags=tags,
            area_id=area_id,
            area=area_title,  # Correct parameter name for area
            todos=todos
        )
        
        if result:
            cache.invalidate("projects")
            return f"✅ Created project: {title}"
        else:
            return f"❌ Failed to create project: {title}"
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        return f"❌ Error creating project: {str(e)}"

@mcp.tool(name="update-todo")
@retry(max_attempts=3)
def update_task(
    id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    completed: Optional[bool] = None,
    canceled: Optional[bool] = None
) -> str:
    """Update an existing todo in Things"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
    
    # Ensure tags exist before using them
    if tags:
        logger.info(f"Ensuring tags exist for update: {tags}")
        if not ensure_tags_exist(tags):
            logger.warning("Failed to ensure all tags exist, but continuing anyway")
    
    # Use URL scheme for updates as per Things documentation
    try:
        result = update_todo(
            id=id,
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            tags=tags,
            completed=completed,
            canceled=canceled
        )
        
        if result:
            cache.invalidate(None)  # Clear all caches
            return f"✅ Updated todo: {id}"
        else:
            return f"❌ Failed to update todo: {id}"
    except Exception as e:
        logger.error(f"Error updating todo: {str(e)}")
        return f"❌ Error updating todo: {str(e)}"

@mcp.tool(name="delete-todo")
@retry(max_attempts=3)
def delete_todo(id: str) -> str:
    """Delete a todo by moving it to trash"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
    
    try:
        # In Things, "deleting" means canceling
        result = update_todo(
            id=id,
            canceled=True
        )
        
        if result:
            cache.invalidate(None)  # Clear all caches
            return f"✅ Deleted todo (moved to trash): {id}"
        else:
            return f"❌ Failed to delete todo: {id}"
    except Exception as e:
        logger.error(f"Error deleting todo: {str(e)}")
        return f"❌ Error deleting todo: {str(e)}"

@mcp.tool(name="update-project")
@retry(max_attempts=3)
def update_existing_project(
    id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    completed: Optional[bool] = None,
    canceled: Optional[bool] = None
) -> str:
    """Update an existing project in Things"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
    
    # Ensure tags exist before using them
    if tags:
        logger.info(f"Ensuring tags exist for project update: {tags}")
        if not ensure_tags_exist(tags):
            logger.warning("Failed to ensure all tags exist, but continuing anyway")
        
    try:
        result = update_project(
            id=id,
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            tags=tags,
            completed=completed,
            canceled=canceled
        )
        
        if result:
            cache.invalidate("projects")
            return f"✅ Updated project: {id}"
        else:
            return f"❌ Failed to update project: {id}"
    except Exception as e:
        logger.error(f"Error updating project: {str(e)}")
        return f"❌ Error updating project: {str(e)}"

@mcp.tool(name="delete-project")
@retry(max_attempts=3)
def delete_project(id: str) -> str:
    """Delete a project by moving it to trash"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
    
    try:
        # In Things, "deleting" means canceling and moving to trash
        # First cancel the project
        result = update_project(
            id=id,
            canceled=True
        )
        
        if result:
            cache.invalidate("projects")
            cache.invalidate("trash")
            return f"✅ Deleted project (moved to trash): {id}"
        else:
            return f"❌ Failed to delete project: {id}"
    except Exception as e:
        logger.error(f"Error deleting project: {str(e)}")
        return f"❌ Error deleting project: {str(e)}"

@mcp.tool(name="show-item")
def show_item(
    id: str,
    query: Optional[str] = None,
    filter_tags: Optional[List[str]] = None
) -> str:
    """Show a specific item or list in Things"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
        
    try:
        result = show(
            id=id,
            query=query,
            filter_tags=filter_tags
        )
        
        if result:
            return f"✅ Opened '{id}' in Things"
        else:
            return f"❌ Failed to show item: {id}"
    except Exception as e:
        logger.error(f"Error showing item: {str(e)}")
        return f"❌ Error showing item: {str(e)}"

@mcp.tool(name="search-items")
def search_all_items(query: str) -> str:
    """Search for items in Things"""
    if not ensure_things_running():
        return "Error: Unable to connect to Things app"
        
    try:
        result = search(query=query)
        
        if result:
            return f"✅ Searching for '{query}' in Things"
        else:
            return f"❌ Failed to search for: {query}"
    except Exception as e:
        logger.error(f"Error searching: {str(e)}")
        return f"❌ Error searching: {str(e)}"

@mcp.tool(name="get-recent")
def get_recent(period: str) -> str:
    """Get recently created items"""
    if not period or not any(period.endswith(unit) for unit in ['d', 'w', 'm', 'y']):
        return "Error: Period must be in format '3d', '1w', '2m', '1y'"
        
    try:
        items = things.last(period)
        
        if not items:
            return f"No items found in the last {period}"
            
        formatted_items = []
        for item in items:
            if item.get('type') == 'to-do':
                formatted_items.append(format_todo(item))
            elif item.get('type') == 'project':
                formatted_items.append(format_project(item, include_items=False))
                
        return "\n\n---\n\n".join(formatted_items)
    except Exception as e:
        logger.error(f"Error getting recent items: {str(e)}")
        return f"Error getting recent items: {str(e)}"

# Main entry point
def run_simple_things_server():
    """Run the simplified Things MCP server"""
    logger.info("Starting simplified Things MCP server...")
    
    # Check if Things is available at startup
    if ensure_things_running():
        logger.info("Things app is ready")
    else:
        logger.warning("Things app is not available - will retry when needed")
    
    # Check for auth token
    token = get_things_auth_token()
    if not token:
        logger.warning("No Things auth token configured. Run 'python configure_token.py' to set it up.")
    
    # Run the server
    mcp.run()

# Make mcp available as 'server' for MCP dev command
server = mcp

if __name__ == "__main__":
    run_simple_things_server()