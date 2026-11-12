# Contributing to MCP Agent Bridge

Thank you for your interest in contributing!

## Development Setup

1. Clone the repository:
   ```cmd
   git clone git@github.com:Wolrym/mcp-agent-bridge.git
   cd mcp-agent-bridge
   ```

2. Install dependencies:
   ```cmd
   pip install -r requirements.txt
   ```

3. Run the test suite:
   ```cmd
   python tests/smoke_test.py
   python tests/tools_test.py
   ```

## Pull Requests & Guidelines

- Keep pull requests focused on a single change or feature.
- Ensure all tests pass before submitting.
- Avoid committing secrets or personal settings (`config/settings.json`, token keys).
- Respect the security model: tools should never circumvent active project bounds or safety guards unintentionally.
