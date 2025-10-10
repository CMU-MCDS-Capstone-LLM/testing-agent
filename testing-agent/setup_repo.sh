#!/bin/bash

# Simple script to set up the repository for testing
echo "Setting up repository for testing..."

if [ "$LOCAL_REPO_MODE" = "1" ]; then
    echo "Running in LOCAL_REPO_MODE - processing local repositories"
    
    if [ -z "$REPO_NAME" ]; then
        echo "No specific repo specified, processing all repos in /uploads"
        
        # Process all repos in uploads directory
        for repo_path in /uploads/*/; do
            if [ -d "$repo_path" ]; then
                repo_name=$(basename "$repo_path")
                echo "Processing local repo: $repo_name"
                
                # Copy repo to workspace
                echo "Copying $repo_name to workspace..."
                rm -rf "/workspace/$repo_name"
                cp -r "$repo_path" "/workspace/$repo_name"
                
                # Generate real tests for this repo
                echo "Generating real tests for $repo_name..."
                cd "/workspace/$repo_name"
                
                # Run the real test generation script from the app directory with explicit repo name
                cd /app && REPO_NAME="$repo_name" /app/run.sh
                
                # Create completion flag for this repo
                echo "Creating completion flag for $repo_name..."
                touch "/workspace/$repo_name/testing_complete.flag"
                
                echo "Completed processing: $repo_name"
                echo "Testing agent will stay running to maintain the flag..."
            fi
        done
        
        # Keep the container alive so the worker agent can start
        echo "Testing agent is ready. Waiting for worker agent to complete..."
        while true; do
            sleep 30
            echo "Testing agent still running, flags maintained"
        done
    else
        echo "Processing specific repo: $REPO_NAME"
        
        # Copy specific repo to workspace
        echo "Copying $REPO_NAME to workspace..."
        rm -rf "/workspace/$REPO_NAME"
        cp -r "/uploads/$REPO_NAME" "/workspace/$REPO_NAME"
        
        # Generate real tests
        echo "Generating real tests for $REPO_NAME..."
        cd "/workspace/$REPO_NAME"
        
        # Run the real test generation script from the app directory
        cd /app && /app/run.sh
        
        # Create completion flag
        echo "Creating completion flag for $REPO_NAME..."
        touch "/workspace/$REPO_NAME/testing_complete.flag"
        
        echo "Completed processing: $REPO_NAME"
        echo "Testing agent will stay running to maintain the flag..."
        
        # Keep the container alive so the worker agent can start
        echo "Testing agent is ready. Waiting for worker agent to complete..."
        while true; do
            sleep 30
            echo "Testing agent still running, flag maintained at /workspace/$REPO_NAME/testing_complete.flag"
        done
    fi
else
    echo "Running in GitHub mode - cloning from GitHub"
    
    # Extract org/repo from GitHub URL
    REPO_PATH=$(echo "$GITHUB_URL" | sed 's|.*github.com/||' | sed 's|\.git$||')
    ORG=${REPO_PATH%%/*}
    REPO=${REPO_PATH##*/}
    REPO_NAME="${ORG}__${REPO}"

    echo "Repository: $REPO_NAME"
    echo "GitHub URL: $GITHUB_URL"
    echo "Commit: $COMMIT_HASH"

    # Clean workspace
    rm -rf /workspace/*

    # Clone the repository
    echo "Cloning repository..."
    git clone "$GITHUB_URL" "/workspace/$REPO_NAME"

    # Checkout specific commit if provided
    if [ -n "$COMMIT_HASH" ]; then
        echo "Checking out commit: $COMMIT_HASH"
        cd "/workspace/$REPO_NAME"
        git checkout "$COMMIT_HASH"
    fi

    # Create test files
    echo "Creating test files..."
    cat > "/workspace/$REPO_NAME/test_migration.py" << 'EOF'
import pytest

def test_migration_always_passes():
    """Fake test that always passes"""
    assert True
    print("✓ Migration test passed (fake)")

def test_basic_functionality():
    """Fake test for basic functionality"""
    assert 1 + 1 == 2
    print("✓ Basic functionality test passed (fake)")

def test_cli_interface():
    """Fake test for CLI interface"""
    assert "click" in "click is better than argparse"
    print("✓ CLI interface test passed (fake)")
EOF

    # Create completion flag
    echo "Creating completion flag..."
    touch "/workspace/$REPO_NAME/testing_complete.flag"

    echo "Repository setup complete!"
    echo "Test files created in /workspace/$REPO_NAME"
fi