#!/usr/bin/env python3
"""
Simplified URL scheme implementation for Things.
Based on https://culturedcode.com/things/support/articles/2803573/
"""
import urllib.parse
import webbrowser
import subprocess
import time
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

def launch_things() -> bool:
    """Launch Things app if not already running."""
    try:
        # Check if running
        result = subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to (name of processes) contains "Things3"'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.stdout.strip().lower() == 'true':
            return True
            
        # Launch Things
        subprocess.run(['open', '-a', 'Things3'], capture_output=True, check=False)
        time.sleep(2)  # Give it time to start
        return True
    except Exception as e:
        logger.error(f"Error launching Things: {str(e)}")
        return False

def execute_url(url: str) -> bool:
    """Execute a Things URL."""
    try:
        logger.debug(f"Executing URL: {url}")
        
        # Ensure Things is running
        launch_things()
        
        # Execute the URL
        result = webbrowser.open(url)
        
        # Small delay to let Things process
        time.sleep(0.5)
        
        return result
    except Exception as e:
        logger.error(f"Failed to execute URL: {str(e)}")
        return False

def construct_url(command: str, params: Dict[str, Any]) -> str:
    """Construct a Things URL from command and parameters."""
    # Start with base URL
    url = f"things:///{command}"
    
    # Get authentication token if available
    try:
        from . import config
        token = config.get_things_auth_token()
        if token:
            params['auth-token'] = token
            logger.debug(f"Added authentication token to {command} URL")
        else:
            logger.warning(f"No authentication token configured for {command} URL")
    except Exception as e:
        logger.error(f"Failed to get authentication token: {str(e)}")
        # Try environment variable as fallback
        import os
        token = os.environ.get('THINGS_AUTH_TOKEN')
        if token:
            params['auth-token'] = token
            logger.debug(f"Using authentication token from environment variable")
    
    # Filter out None values
    params = {k: v for k, v in params.items() if v is not None}
    
    if params:
        encoded_params = []
        for key, value in params.items():
            if isinstance(value, bool):
                value = str(value).lower()
            elif isinstance(value, list):
                if key == 'tags':
                    # Tags should be comma-separated
                    value = ','.join(str(v) for v in value)
                elif key == 'checklist-items':
                    # Checklist items should be newline-separated
                    value = '\n'.join(str(v) for v in value)
                else:
                    value = ','.join(str(v) for v in value)
            
            # URL encode the value
            encoded_value = urllib.parse.quote(str(value), safe='')
            encoded_params.append(f"{key}={encoded_value}")
        
        url += "?" + "&".join(encoded_params)
    
    return url

# URL scheme functions based on Things documentation

def add_todo(
    title: str,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    checklist_items: Optional[List[str]] = None,
    list_id: Optional[str] = None,
    list: Optional[str] = None,  # Project/Area name
    heading: Optional[str] = None,
    completed: Optional[bool] = None
) -> bool:
    """Add a new todo using Things URL scheme."""
    params = {
        'title': title,
        'notes': notes,
        'when': when,
        'deadline': deadline,
        'tags': tags,
        'checklist-items': checklist_items,
        'list-id': list_id,
        'list': list,  # This is the project/area name
        'heading': heading,
        'completed': completed
    }
    
    url = construct_url('add', params)
    return execute_url(url)

def add_project(
    title: str,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    area_id: Optional[str] = None,
    area: Optional[str] = None,  # Area name
    todos: Optional[List[str]] = None
) -> bool:
    """Add a new project using Things URL scheme."""
    params = {
        'title': title,
        'notes': notes,
        'when': when,
        'deadline': deadline,
        'tags': tags,
        'area-id': area_id,
        'area': area,
        'to-dos': todos  # List of todo titles
    }
    
    url = construct_url('add-project', params)
    return execute_url(url)

def update_todo(
    id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    add_tags: Optional[List[str]] = None,
    completed: Optional[bool] = None,
    canceled: Optional[bool] = None
) -> bool:
    """Update an existing todo."""
    params = {
        'id': id,
        'title': title,
        'notes': notes,
        'when': when,
        'deadline': deadline,
        'tags': tags,
        'add-tags': add_tags,
        'completed': completed,
        'canceled': canceled
    }
    
    url = construct_url('update', params)
    return execute_url(url)

def update_project(
    id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    completed: Optional[bool] = None,
    canceled: Optional[bool] = None
) -> bool:
    """Update an existing project."""
    params = {
        'id': id,
        'title': title,
        'notes': notes,
        'when': when,
        'deadline': deadline,
        'tags': tags,
        'completed': completed,
        'canceled': canceled
    }
    
    url = construct_url('update-project', params)
    return execute_url(url)

def show(
    id: str,
    query: Optional[str] = None,
    filter: Optional[List[str]] = None
) -> bool:
    """Show a specific item or list in Things."""
    params = {
        'id': id,
        'query': query,
        'filter': filter
    }
    
    url = construct_url('show', params)
    return execute_url(url)

def search(query: str) -> bool:
    """Search for items in Things."""
    return show(id='search', query=query)