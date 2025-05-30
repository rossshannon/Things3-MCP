#!/usr/bin/env python3
"""
Configuration tool for setting up the Things authentication token.
"""
import sys
import logging
from src.things_mcp import config

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_auth_token():
    """Interactive setup for the Things authentication token."""
    print("\n=== Things MCP Configuration ===")
    print("\nThis tool helps you set up the authentication token required for Things URL commands.")
    print("You can find your token in Things → Settings → General.")
    print("\nThe token is saved in your configuration file and used for all URL scheme operations.")
    
    # Display current token if any
    current_token = config.get_things_auth_token()
    if current_token:
        print(f"\nCurrent token: {current_token}")
    else:
        print("\nNo token currently configured.")
    
    # Prompt for new token
    print("\nEnter your Things authentication token (leave empty to keep current token):")
    new_token = input("> ").strip()
    
    if not new_token:
        if current_token:
            print("\nKeeping current token.")
            return True
        else:
            print("\nError: No token provided and no existing token found.")
            return False
    
    # Save the new token
    success = config.set_things_auth_token(new_token)
    
    if success:
        print(f"\nAuthentication token saved successfully to {config.CONFIG_FILE}")
        return True
    else:
        print("\nError: Failed to save authentication token.")
        return False

if __name__ == "__main__":
    print("Things MCP Token Configuration Tool")
    setup_auth_token()
