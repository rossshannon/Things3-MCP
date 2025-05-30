#!/usr/bin/env python3
import subprocess
import logging
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger(__name__)

def run_applescript(script: str) -> Union[str, bool]:
    """Run an AppleScript command and return the result.
    
    Args:
        script: The AppleScript code to execute
        
    Returns:
        The result of the AppleScript execution, or False if it failed
    """
    try:
        result = subprocess.run(['osascript', '-e', script], 
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"AppleScript error: {result.stderr}")
            return False
        
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Error running AppleScript: {str(e)}")
        return False

def add_todo_direct(title: str, notes: Optional[str] = None, when: Optional[str] = None,
                   tags: Optional[List[str]] = None, list_title: Optional[str] = None) -> str:
    """Add a todo to Things directly using AppleScript.
    
    This bypasses URL schemes entirely to avoid encoding issues.
    
    Args:
        title: Title of the todo
        notes: Notes for the todo
        when: When to schedule the todo (today, tomorrow, evening, anytime, someday)
        tags: Tags to apply to the todo
        list_title: Name of project/area to add to
        
    Returns:
        ID of the created todo if successful, False otherwise
    """
    # Build the AppleScript command
    script_parts = ['tell application "Things3"']
    
    # Create the todo with properties
    properties = []
    properties.append(f'name:"{escape_applescript_string(title)}"')
    
    if notes:
        properties.append(f'notes:"{escape_applescript_string(notes)}"')
    
    # Create with properties in the right way
    script_parts.append(f'set newTodo to make new to do with properties {{{", ".join(properties)}}}')
    
    # Add scheduling
    if when:
        when_mapping = {
            'today': '',  # Default is today, no need to set
            'tomorrow': 'set activation date of newTodo to ((current date) + 1 * days)',
            'evening': '',  # Default is today, no need to set
            'anytime': '',  # Default
            'someday': 'set status of newTodo to someday'
        }
        
        if when in when_mapping:
            if when_mapping[when]:
                script_parts.append(when_mapping[when])
        else:
            # For date handling, it's safest to just log it and not try to set it
            # This avoids AppleScript date formatting issues
            logger.warning(f"Custom date format '{when}' not supported, defaulting to today")
    
    # Add tags if provided
    if tags and len(tags) > 0:
        for tag in tags:
            script_parts.append(f'tell newTodo to make new tag with properties {{name:"{escape_applescript_string(tag)}"}}')
    
    # Add to a specific project/area if specified
    if list_title:
        script_parts.append(f'set project_name to "{escape_applescript_string(list_title)}"')
        script_parts.append('try')
        script_parts.append('  set target_project to first project whose name is project_name')
        script_parts.append('  set project of newTodo to target_project')
        script_parts.append('on error')
        script_parts.append('  -- Project not found, try area')
        script_parts.append('  try')
        script_parts.append('    set target_area to first area whose name is project_name')
        script_parts.append('    set area of newTodo to target_area')
        script_parts.append('  on error')
        script_parts.append('    -- Neither project nor area found, todo will remain in inbox')
        script_parts.append('  end try')
        script_parts.append('end try')
    
    # Get the ID of the created todo
    script_parts.append('return id of newTodo')
    
    # Close the tell block
    script_parts.append('end tell')
    
    # Execute the script
    script = '\n'.join(script_parts)
    logger.debug(f"Executing AppleScript: {script}")
    
    result = run_applescript(script)
    if result:
        logger.info(f"Successfully created todo with ID: {result}")
        return result
    else:
        logger.error("Failed to create todo")
        return False

def escape_applescript_string(text: str) -> str:
    """Escape special characters in an AppleScript string.
    
    Args:
        text: The string to escape
        
    Returns:
        The escaped string
    """
    if not text:
        return ""
    
    # Replace any "+" with spaces first
    text = text.replace("+", " ")
    
    # Escape quotes by doubling them (AppleScript style)
    return text.replace('"', '""')

def update_todo_direct(id: str, title: Optional[str] = None, notes: Optional[str] = None,
                     when: Optional[str] = None, deadline: Optional[str] = None,
                     tags: Optional[Union[List[str], str]] = None, add_tags: Optional[Union[List[str], str]] = None,
                     checklist_items: Optional[List[str]] = None, completed: Optional[bool] = None, 
                     canceled: Optional[bool] = None) -> bool:
    """Update a todo directly using AppleScript.
    
    This bypasses URL schemes entirely to avoid authentication issues.
    
    Args:
        id: The ID of the todo to update
        title: New title for the todo
        notes: New notes for the todo
        when: New schedule for the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline for the todo (YYYY-MM-DD)
        tags: New tags for the todo (replaces existing tags)
        add_tags: Tags to add to the todo (preserves existing tags)
        checklist_items: Checklist items to set for the todo (replaces existing items)
        completed: Mark as completed
        canceled: Mark as canceled
    
    Returns:
        True if successful, False otherwise
    """
    import re
    
    # Build the AppleScript command to find and update the todo
    script_parts = ['tell application "Things3"']
    script_parts.append('try')
    script_parts.append(f'    set theTodo to to do id "{id}"')
    
    # Update properties one at a time
    if title:
        script_parts.append(f'    set name of theTodo to "{escape_applescript_string(title)}"')
    
    if notes:
        script_parts.append(f'    set notes of theTodo to "{escape_applescript_string(notes)}"')
    
    # Handle date-related properties
    if when:
        # Check if when is a date in YYYY-MM-DD format
        is_date_format = re.match(r'^\d{4}-\d{2}-\d{2}$', when)
        
        # Simple mapping of common 'when' values to AppleScript commands
        if when == 'today':
            script_parts.append('    move theTodo to list "Today"')
        elif when == 'tomorrow':
            script_parts.append('    set activation date of theTodo to ((current date) + (1 * days))')
            script_parts.append('    move theTodo to list "Upcoming"')
        elif when == 'evening':
            script_parts.append('    move theTodo to list "Evening"')
        elif when == 'anytime':
            script_parts.append('    move theTodo to list "Anytime"')
        elif when == 'someday':
            script_parts.append('    move theTodo to list "Someday"')
        elif is_date_format:
            # Handle YYYY-MM-DD format dates
            year, month, day = when.split('-')
            script_parts.append(f'''
    -- Set activation date with direct date string
    set dateString to "{when}"
    set newDate to date dateString
    set activation date of theTodo to newDate
    -- Move to the Upcoming list
    move theTodo to list "Upcoming"
''')
        else:
            # For other formats, just log a warning and don't try to set it
            logger.warning(f"Schedule format '{when}' not directly supported in this simplified version")
    
    if deadline:
        # Check if deadline is in YYYY-MM-DD format
        if re.match(r'^\d{4}-\d{2}-\d{2}$', deadline):
            year, month, day = deadline.split('-')
            script_parts.append(f'''
    -- Set deadline with direct date string
    set deadlineString to "{deadline}"
    set deadlineDate to date deadlineString
    set deadline of theTodo to deadlineDate
''')
        else:
            logger.warning(f"Invalid deadline format: {deadline}. Expected YYYY-MM-DD")
    
    # Handle tags (clearing and adding new ones)
    if tags is not None:
        # Convert string tags to list if needed
        if isinstance(tags, str):
            tags = [tags]
            
        if tags:
            # Clear existing tags first
            script_parts.append('    -- Clear existing tags')
            script_parts.append('    set tag_names of theTodo to {}')
            
            # Simplified tag handling
            import json
            tags_json = json.dumps(tags)
            script_parts.append(f'''
    -- Set tags using a list
    set tagNameList to {tags_json}
    -- Clear existing tags
    set oldTags to tags of theTodo
    repeat with t from (count of oldTags) to 1 by -1
        delete item t of oldTags
    end repeat
    -- Add new tags
    repeat with t from 1 to (count of tagNameList)
        set tagText to item t of tagNameList
        tell theTodo
            set newTag to make new tag
            set name of newTag to tagText
        end tell
    end repeat
''')
        else:
            # Clear all tags if empty list provided
            script_parts.append('    -- Clear all tags')
            script_parts.append('    set tag_names of theTodo to {}')
    
    # Handle adding tags without replacing existing ones
    if add_tags is not None:
        # Convert string to list if needed
        if isinstance(add_tags, str):
            add_tags = [add_tags]
            
        for tag in add_tags:
            tag_name = escape_applescript_string(tag)
            script_parts.append(f'''
            -- Add tag {tag_name} if it doesn't exist
            set tagFound to false
            repeat with t in tags of theTodo
                if name of t is "{tag_name}" then
                    set tagFound to true
                    exit repeat
                end if
            end repeat
            if not tagFound then
                tell theTodo to make new tag with properties {{name:"{tag_name}"}}
            end if
            ''')
            
    # Handle checklist items - simplified approach
    if checklist_items is not None:
        # Convert string to list if needed
        if isinstance(checklist_items, str):
            checklist_items = checklist_items.split('\n')
            
        if checklist_items:
            # For simplicity, we'll use JSON to pass checklist items
            import json
            items_json = json.dumps([item for item in checklist_items])
            script_parts.append(f'''
    -- Clear and set checklist items
    set oldItems to check list items of theTodo
    repeat with i from (count of oldItems) to 1 by -1
        delete item i of oldItems
    end repeat
    
    set itemList to {items_json}
    repeat with i from 1 to (count of itemList)
        set itemText to item i of itemList
        tell theTodo
            set newItem to make new check list item
            set name of newItem to itemText
        end tell
    end repeat
''')
    
    # Handle completion status - use completion date approach
    if completed is not None:
        if completed:
            script_parts.append('    set status of theTodo to completed')
        else:
            script_parts.append('    set status of theTodo to open')
    
    # Handle canceled status
    if canceled is not None:
        if canceled:
            script_parts.append('    set status of theTodo to canceled')
        else:
            script_parts.append('    set status of theTodo to open')
    
    # Return true on success
    script_parts.append('    return true')
    script_parts.append('on error errMsg')
    script_parts.append('    log "Error updating todo: " & errMsg')
    script_parts.append('    return false')
    script_parts.append('end try')
    script_parts.append('end tell')
    
    # Execute the script
    script = '\n'.join(script_parts)
    logger.info(f"Executing AppleScript for update_todo_direct: \n{script}")
    
    result = run_applescript(script)
    
    if result == "true":
        logger.info(f"Successfully updated todo with ID: {id}")
        return True
    else:
        logger.error(f"AppleScript update_todo_direct failed: {result}")
        return False