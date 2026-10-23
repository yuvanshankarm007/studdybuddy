#!/bin/bash
# StudyBuddy Setup Script
# Sets up development environment for Amazon Build Ship Shape 2026

set -e

echo "🧠 StudyBuddy Setup Script"
echo "=========================="
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "📋 Python version: $PYTHON_VERSION"

if ! python3 -c "import sys; assert sys.version_info >= (3, 10)"; then
    echo "❌ Python 3.10+ required"
    exit 1
fi

# Create virtual environment
echo ""
echo "🔧 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Setup environment
echo ""
echo "⚙️  Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file from template"
else
    echo "⚠️  .env file already exists"
fi

# Setup DynamoDB Local
echo ""
echo "🗄️  Setting up DynamoDB Local..."
mkdir -p docker/dynamodb

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker not found. Please install Docker for local development."
else
    echo "✅ Docker found"
fi

# Run tests
echo ""
echo "🧪 Running tests..."
pytest tests/ -v --tb=short || echo "⚠️  Some tests failed (expected without AWS credentials)"

# Create directories
echo ""
echo "📁 Creating directories..."
mkdir -p logs
mkdir -p data

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your AWS credentials"
echo "  2. Start services: docker-compose up -d"
echo "  3. Run dashboard: streamlit run dashboard/app.py"
echo "  4. Open browser: http://localhost:8501"
echo ""
echo "🏆 Good luck with Amazon Build Ship Shape 2026!"
