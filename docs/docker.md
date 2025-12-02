# Docker Image & Registry

The `release-tool` is available as a Docker image stored in the GitHub Container Registry (GHCR). This allows other tools (like `release-bot`) or CI pipelines to use the tool without installing Python dependencies manually.

## Public Registry Access

The Docker image is published to:
`ghcr.io/sequentech/release-tool`

### Enabling Public Access

To ensure the image is publicly pullable (so `release-bot` or other users can use it without authentication):

1. **Ensure the repository is public**: Go to the repository settings and verify that the repository visibility is set to "Public".
2. **Configure organization package settings**: In the organization settings (Settings -> Packages), ensure that packages are configured to inherit the repository's visibility. This allows packages from public repositories to be automatically public.
3. **Verify package visibility**: Navigate to the repository's **Packages** section (right sidebar on the main page), click on the `release-tool` package, and confirm it shows as "Public".

## GitHub Action Workflow

The image is automatically built and published via a GitHub Action defined in `.github/workflows/docker-publish.yml`.

### Triggers
- **Push to `main`**: Updates the `main` tag.
- **Tags (`v*`)**: Pushes a semantic version tag (e.g., `v1.0.0`).
- **Pull Requests**: Builds the image to ensure validity but does **not** push to the registry.

### Configuration
The workflow uses the standard `GITHUB_TOKEN` to authenticate with GHCR. No additional secrets are required for the repository itself, provided "Read and write permissions" are enabled for workflows in the repository settings (Settings -> Actions -> General -> Workflow permissions).

## Local Development

### Building Locally
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
