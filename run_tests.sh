#!/bin/bash

# FileFolio test runner script
# This script runs the test suite and generates a coverage report

set -e  # Exit on error

echo "🧪 FileFolio test suite"
echo "======================"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Warning: No virtual environment detected"
    echo "   Consider activating your venv first:"
    echo "   source venv/bin/activate"
    echo ""
fi

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not found. Installing test dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Run tests
echo "▶️  Running tests..."
echo ""

if [ "$1" = "--coverage" ] || [ "$1" = "-c" ]; then
    echo "📊 Running with coverage report..."
    pytest --cov=backend --cov-report=term --cov-report=html
    echo ""
    echo "✅ Coverage report generated in htmlcov/index.html"
    echo "   Open it with: open htmlcov/index.html"
elif [ "$1" = "--verbose" ] || [ "$1" = "-v" ]; then
    pytest -v
elif [ "$1" = "--fast" ] || [ "$1" = "-f" ]; then
    echo "⚡ Running in fast mode (skipping slow tests)..."
    pytest -m "not slow"
else
    pytest
fi

echo ""
echo "✅ Test suite completed!"
