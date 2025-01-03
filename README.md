## Development Setup

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Install development dependencies
pip install -r requirements-dev.txt

# Format code
make format

# Run linters
make lint

# Run tests
make test
