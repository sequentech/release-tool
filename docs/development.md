# Development Guide

This guide covers development workflows, testing, Docker image management, and CI/CD for the `release-tool` project.

## Table of Contents
- [Testing](#testing)
- [GitHub Actions](#github-actions)
- [Docker Image & Registry](#docker-image--registry)
- [Local Development](#local-development)

## Testing

### Running Tests

The project uses pytest for testing. All tests can be run using Poetry:

```bash
# Run all tests
poetry run pytest

# Run with verbose output
poetry run pytest -v

# Run specific test file
poetry run pytest tests/test_models.py -v

# Run with coverage report
poetry run pytest --cov=release_tool --cov-report=html
```

### Test Categories

#### Unit Tests
Standard unit tests covering:
- Models and data structures (`test_models.py`)
- Configuration management (`test_config.py`)
- Database operations (`test_db.py`)
- Git operations (`test_git_ops.py`)
- Policies and business logic (`test_policies.py`)
- Template rendering (`test_output_template.py`, `test_default_template.py`)
- Ticket management (`test_query_tickets.py`, `test_partial_tickets.py`)
- Publishing and syncing (`test_publish.py`, `test_sync.py`)

```bash
# Run all unit tests except Docker tests
poetry run pytest tests/ --ignore=tests/test_docker.py
```

#### Docker Tests
Docker integration tests verify:
- Docker image builds successfully from the Dockerfile
- `release-tool` executable is available in the image
- `release-tool -h` returns a successful exit code
- Docker image runs `release-tool` as its default command

```bash
# Run Docker tests (requires Docker to be running)
poetry run pytest tests/test_docker.py -v
```

**Note**: Docker tests take longer (~20-30 seconds) as they build the actual Docker image.

## GitHub Actions

The project uses GitHub Actions for continuous integration and delivery. All workflows are defined in `.github/workflows/`.

### Test Workflow

File: `.github/workflows/test.yml`

**Triggers**:
- Push to `main` branch
- Pull requests to `main` branch

**What it does**:
1. Sets up a test matrix for Python 3.10, 3.11, and 3.12
2. Installs Poetry and project dependencies
3. Runs all unit tests (excluding Docker tests)
4. Runs Docker tests separately

**Running locally with act**:

[act](https://github.com/nektos/act) allows you to test GitHub Actions workflows locally:

```bash
# Install act (macOS)
brew install act

# List available workflows
act -l

# Run the test workflow
act -j test --container-architecture linux/amd64

# Run with a specific runner image
act -j test --container-architecture linux/amd64 -P ubuntu-latest=catthehacker/ubuntu:act-latest

# Run and show verbose output
act -j test --container-architecture linux/amd64 -v
```

**Note**: On Apple M-series chips, use `--container-architecture linux/amd64` to avoid compatibility issues.

### Documentation Deployment Workflow

File: `.github/workflows/deploy-docs.yml`

**Triggers**:
- Push to `main` branch (only when files in `docs/` change)

**What it does**:
1. Sets up Node.js environment
2. Installs dependencies in `docs/` directory
3. Builds the Docusaurus static site
4. Deploys the `docs/build` directory to the `gh-pages` branch

**Running locally with act**:

```bash
# Run the deploy-docs workflow
act -j deploy --container-architecture linux/amd64
```

## Docker Image & Registry

The `release-tool` is available as a Docker image stored in the GitHub Container Registry (GHCR). This allows other tools (like `release-bot`) or CI pipelines to use the tool without installing Python dependencies manually.

## Public Registry Access

The Docker image is published to:
`ghcr.io/sequentech/release-tool`

### Enabling Public Access

To ensure the image is publicly pullable (so `release-bot` or other users can use it without authentication):

1. **Ensure the repository is public**: Go to the repository settings and verify that the repository visibility is set to "Public".
2. **Configure organization package settings**: In the organization settings (Settings -> Packages), ensure that packages are configured to inherit the repository's visibility. This allows packages from public repositories to be automatically public.
3. **Verify package visibility**: Navigate to the repository's **Packages** section (right sidebar on the main page), click on the `release-tool` package, and confirm it shows as "Public".

### Configuration
The workflow uses the standard `GITHUB_TOKEN` to authenticate with GHCR. No additional secrets are required for the repository itself, provided "Read and write permissions" are enabled for workflows in the repository settings (Settings -> Actions -> General -> Workflow permissions).

## Local Development

### Building the Docker Image Locally
You can build the image locally for testing purposes:

```bash
docker build -t release-tool:local .
```

### VS Code Task
For convenience, a VS Code task is included. Open the Command Palette (`Cmd+Shift+P`) and run **Tasks: Run Build Task** (or select "Docker: Build Image") to build the image directly from the editor.

## Usage

### Pulling the image
```bash
docker pull ghcr.io/sequentech/release-tool:latest
```

### Running the tool
```bash
docker run --rm -v $(pwd):/workspace -w /workspace ghcr.io/sequentech/release-tool release-tool --help
```

### Extending the image (e.g., for Release Bot)
```dockerfile
FROM ghcr.io/sequentech/release-tool:latest

# Add your wrapper scripts
COPY main.py /app/

ENTRYPOINT ["python", "/app/main.py"]
```
