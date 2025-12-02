"""Tests for Docker image build and functionality."""

import subprocess
import pytest


@pytest.fixture(scope="module")
def docker_image_name():
    """Return the Docker image name to use for tests."""
    return "release-tool-test"


@pytest.fixture(scope="module")
def build_docker_image(docker_image_name):
    """Build the Docker image before running tests."""
    # Build the Docker image
    result = subprocess.run(
        ["docker", "build", "-t", docker_image_name, "."],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        pytest.fail(f"Failed to build Docker image: {result.stderr}")
    
    yield docker_image_name
    
    # Cleanup: Remove the Docker image after tests
    subprocess.run(
        ["docker", "rmi", "-f", docker_image_name],
        capture_output=True,
    )


def test_docker_image_builds_successfully(docker_image_name):
    """Test that the Docker image can be built successfully from the Dockerfile."""
    # Build the Docker image
    result = subprocess.run(
        ["docker", "build", "-t", docker_image_name, "."],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, f"Docker build failed: {result.stderr}"
    # Modern Docker output may show success in stdout or stderr
    output = result.stdout + result.stderr
    assert (
        "Successfully built" in output
        or "Successfully tagged" in output
        or f"naming to docker.io/library/{docker_image_name}" in output
    )


def test_release_tool_executable_available(build_docker_image):
    """Test that the release-tool executable is available in the Docker image."""
    # Check if release-tool command exists in the image
    result = subprocess.run(
        ["docker", "run", "--rm", build_docker_image, "which", "release-tool"],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, "release-tool executable not found in PATH"
    assert "release-tool" in result.stdout


def test_release_tool_help_returns_success(build_docker_image):
    """Test that running release-tool -h inside the Docker container returns a successful exit code."""
    # Run release-tool -h in the container
    result = subprocess.run(
        ["docker", "run", "--rm", build_docker_image, "release-tool", "-h"],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, f"release-tool -h failed with exit code {result.returncode}"
    assert "Usage:" in result.stdout or "usage:" in result.stdout.lower()


def test_docker_image_default_command(build_docker_image):
    """Test that the Docker image runs release-tool as its default command."""
    # Run the container without specifying a command
    # This should execute the default CMD from the Dockerfile
    result = subprocess.run(
        ["docker", "run", "--rm", build_docker_image],
        capture_output=True,
        text=True,
        timeout=5,
    )
    
    # The default command should run release-tool, which without arguments
    # should either show help or an error message from release-tool
    # We're checking that it's release-tool that runs, not bash or another shell
    assert result.returncode in [0, 1, 2], f"Unexpected exit code: {result.returncode}"
    
    # Verify the output contains release-tool-specific content
    output = result.stdout + result.stderr
    assert any(
        keyword in output.lower()
        for keyword in ["release-tool", "usage", "command"]
    ), "Default command does not appear to be release-tool"
