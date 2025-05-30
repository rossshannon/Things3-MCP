#!/usr/bin/env python3
"""
Tag handler for Things MCP.
Ensures tags exist before applying them.
"""
import subprocess
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

def ensure_tags_exist(tags: List[str]) -> bool:
    """
    Ensure all tags exist in Things before using them.
    Creates missing tags using AppleScript.
    
    Args:
        tags: List of tag names to ensure exist
        
    Returns:
        bool: True if all tags exist or were created successfully
    """
    if not tags:
        return True
        
    try:
        # Build AppleScript to check and create tags
        script_lines = ['tell application "Things3"']
        
        for tag in tags:
            # Escape quotes in tag name
            escaped_tag = tag.replace('"', '\\"')
            
            # Check if tag exists, create if not
            script_lines.extend([
                f'  set tagName to "{escaped_tag}"',
                '  set tagExists to false',
                '  repeat with t in tags',
                '    if name of t is tagName then',
                '      set tagExists to true',
                '      exit repeat',
                '    end if',
                '  end repeat',
                '  if not tagExists then',
                '    try',
                '      make new tag with properties {name:tagName}',
                f'      log "Created tag: " & tagName',
                '    on error',
                f'      log "Failed to create tag: " & tagName',
                '    end try',
                '  end if'
            ])
        
        script_lines.append('end tell')
        script = '\n'.join(script_lines)
        
        # Execute the AppleScript
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            logger.error(f"Failed to ensure tags exist: {result.stderr}")
            return False
            
        logger.info(f"Ensured tags exist: {', '.join(tags)}")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("Timeout while ensuring tags exist")
        return False
    except Exception as e:
        logger.error(f"Error ensuring tags exist: {str(e)}")
        return False

def get_existing_tags() -> List[str]:
    """
    Get list of all existing tags in Things.
    
    Returns:
        List[str]: List of tag names
    """
    try:
        script = '''tell application "Things3"
            set tagList to {}
            repeat with t in tags
                set end of tagList to name of t
            end repeat
            return tagList
        end tell'''
        
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout:
            # Parse the output (comma-separated list)
            tags = [tag.strip() for tag in result.stdout.strip().split(',')]
            return tags
        
        return []
        
    except Exception as e:
        logger.error(f"Error getting existing tags: {str(e)}")
        return []