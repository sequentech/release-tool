# Claude Code Rules for Release Tool Project

## Testing and Documentation Requirements

**CRITICAL:** When making ANY code changes to this project, you MUST:

### 1. Update Tests

- **Always update tests** when modifying code that has test coverage
- **Add new tests** for new features or bug fixes
- **Run tests before considering work complete**: `poetry run pytest tests/ --ignore=tests/test_docker.py -v`
- **All tests must pass** - do not mark work as complete if tests are failing
- **Never skip test updates** - tests are not optional

### 2. Update Documentation

- **Update config_template.toml** when adding or changing configuration options
- **Update docstrings** when changing function signatures or behavior
- **Update README.md** if user-facing functionality changes
- **Update migration guides** if configuration format changes

### 3. Security Best Practices

- **Never store secrets in configuration files** - always use environment variables
- **Never commit tokens, passwords, or API keys** to the repository
- **Use environment variables** for sensitive data (e.g., GITHUB_TOKEN)
- **Validate and sanitize** all user inputs
- **Fail gracefully** with clear error messages when required environment variables are missing

### 3. Configuration Version Migrations

**CRITICAL:** When modifying the configuration format (`.toml` files), you MUST:

- **Bump the config version** in `config_version` field (e.g., from `"1.7"` to `"1.8"`)
- **Update ALL configuration files** with the new version:
  - `src/release_tool/config_template.toml`
  - `examples/example_output_template.toml`
  - `.release_tool.toml`
  - `release-bot/.release_tool.toml`
- **Create or update migration** in `src/release_tool/migrations.py` if needed
- **Test the migration** to ensure old configs can be upgraded automatically
- **Document breaking changes** in migration descriptions

**When to bump version:**
- Adding new required fields
- Removing fields
- Changing field names or structure
- Changing default values that affect behavior
- Changing validation rules

**When NOT to bump version:**
- Adding optional fields with defaults
- Updating documentation/comments only
- Bug fixes that don't change the schema

## Code Quality Standards

### Testing
- Maintain at least 80% test coverage for new code
- Use fixtures from `conftest.py` to avoid duplication
- Use `monkeypatch` for environment variable testing
- Test both success and failure cases
- Test edge cases and error handling

### Code Organization
- Follow existing project structure
- Use type hints for all function parameters and return values
- Keep functions focused and single-purpose
- Use descriptive variable and function names

### Error Handling
- Provide clear, actionable error messages
- Use appropriate exception types
- Log errors with sufficient context
- Fail fast and loudly rather than silently

### Documentation
- Write docstrings for all public functions and classes
- Include parameter descriptions and return value documentation
- Provide usage examples in docstrings where helpful
- Keep comments up-to-date with code changes

## Development Workflow

1. **Before making changes:**
   - Read relevant existing code and tests
   - Understand the current behavior
   - Plan changes with tests in mind

2. **While making changes:**
   - Update code and tests together
   - Run tests frequently during development
   - Update documentation as you go

3. **Before completing work:**
   - Run full test suite: `poetry run pytest tests/ --ignore=tests/test_docker.py -v`
   - Verify all tests pass
   - Check that documentation is updated
   - Review security implications

4. **Never:**
   - Skip running tests
   - Leave failing tests
   - Commit broken code
   - Leave documentation outdated

## Testing Commands

```bash
# Run all tests (excluding Docker tests)
poetry run pytest tests/ --ignore=tests/test_docker.py -v

# Run specific test file
poetry run pytest tests/test_config.py -v

# Run tests with coverage
poetry run pytest tests/ --ignore=tests/test_docker.py --cov=src/release_tool --cov-report=html

# Run specific test
poetry run pytest tests/test_config.py::test_missing_github_token_raises_error -v
```

## Configuration Security

**IMPORTANT:** GitHub tokens and other secrets MUST only be provided via environment variables:

```bash
export GITHUB_TOKEN="your_token_here"
```

**NEVER:**
- Add `token = "..."` to any `.toml` configuration file
- Commit files containing secrets
- Store secrets in code or configuration files

The `GitHubConfig.token` property will automatically read from the `GITHUB_TOKEN` environment variable and raise a clear error if it's not set.
