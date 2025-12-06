# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for media download and processing utilities."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from release_tool.media_utils import MediaDownloader


@pytest.fixture
def media_downloader(tmp_path):
    """Create a MediaDownloader instance for testing."""
    assets_path = str(tmp_path / "assets" / "v{{ major }}.{{ minor }}")
    return MediaDownloader(assets_path, download_enabled=True)


def test_process_markdown_images(media_downloader, tmp_path):
    """Test processing of Markdown image syntax."""
    output_path = tmp_path / "release-notes.md"
    
    description = """
Some text here.
![Example Image](https://github.com/user-attachments/assets/test-image.png)
More text.
"""
    
    with patch.object(media_downloader, '_download_media') as mock_download:
        mock_download.return_value = "assets/v1.0/abc123_test-image.png"
        
        result = media_downloader.process_description(
            description, "1.0.0", str(output_path)
        )
        
        # Check that download was called with correct URL
        mock_download.assert_called_once()
        assert "https://github.com/user-attachments/assets/test-image.png" in mock_download.call_args[0]
        
        # Check that Markdown image was replaced with local path
        assert "![Example Image](assets/v1.0/abc123_test-image.png)" in result


def test_process_html_images_conversion(media_downloader, tmp_path):
    """Test processing of HTML img tags with conversion to Markdown."""
    output_path = tmp_path / "release-notes.md"
    
    description = """
Some text here.
<img width="1014" height="835" alt="Screenshot" src="https://github.com/user-attachments/assets/8184a4b2-25f5-42d9-85c3-296e81ddd4d3" />
More text.
"""
    
    with patch.object(media_downloader, '_download_media') as mock_download:
        mock_download.return_value = "assets/v1.0/abc123_screenshot.png"
        
        result = media_downloader.process_description(
            description, "1.0.0", str(output_path), convert_html_to_markdown=True
        )
        
        # Check that download was called
        mock_download.assert_called_once()
        assert "https://github.com/user-attachments/assets/8184a4b2-25f5-42d9-85c3-296e81ddd4d3" in mock_download.call_args[0]
        
        # Check that HTML img was converted to Markdown with local path
        assert "![Screenshot](assets/v1.0/abc123_screenshot.png)" in result
        # Original HTML should be gone
        assert "<img" not in result


def test_process_html_images_without_conversion(media_downloader, tmp_path):
    """Test that HTML img tags are NOT converted when convert_html_to_markdown=False."""
    output_path = tmp_path / "release-notes.md"
    
    description = """
Some text here.
<img width="1014" height="835" alt="Screenshot" src="https://github.com/user-attachments/assets/8184a4b2-25f5-42d9-85c3-296e81ddd4d3" />
More text.
"""
    
    with patch.object(media_downloader, '_download_media') as mock_download:
        mock_download.return_value = "assets/v1.0/abc123_screenshot.png"
        
        result = media_downloader.process_description(
            description, "1.0.0", str(output_path), convert_html_to_markdown=False
        )
        
        # Check that download was NOT called (HTML imgs ignored without conversion)
        mock_download.assert_not_called()
        
        # Original HTML should still be there
        assert "<img" in result
        assert "https://github.com/user-attachments/assets/8184a4b2-25f5-42d9-85c3-296e81ddd4d3" in result


def test_process_html_images_with_default_alt(media_downloader, tmp_path):
    """Test HTML img tag without alt attribute gets default alt text."""
    output_path = tmp_path / "release-notes.md"
    
    description = '<img src="https://example.com/image.png" width="100" />'
    
    with patch.object(media_downloader, '_download_media') as mock_download:
        mock_download.return_value = "assets/v1.0/abc123_image.png"
        
        result = media_downloader.process_description(
            description, "1.0.0", str(output_path), convert_html_to_markdown=True
        )
        
        # Check that default alt text "Image" was used
        assert "![Image](assets/v1.0/abc123_image.png)" in result


def test_process_mixed_markdown_and_html_images(media_downloader, tmp_path):
    """Test processing document with both Markdown and HTML images."""
    output_path = tmp_path / "release-notes.md"
    
    description = """
# Title

Here's a Markdown image:
![Markdown Image](https://example.com/markdown.png)

And an HTML image:
<img alt="HTML Image" src="https://example.com/html.png" width="500" />

End of document.
"""
    
    with patch.object(media_downloader, '_download_media') as mock_download:
        mock_download.side_effect = [
            "assets/v1.0/md_markdown.png",  # First call for HTML img
            "assets/v1.0/md2_markdown.png"  # Second call for Markdown img
        ]
        
        result = media_downloader.process_description(
            description, "1.0.0", str(output_path), convert_html_to_markdown=True
        )
        
        # Both images should be processed
        assert mock_download.call_count == 2
        
        # Both should be in Markdown format with local paths
        assert "![Markdown Image](assets/v1.0/md2_markdown.png)" in result
        assert "![HTML Image](assets/v1.0/md_markdown.png)" in result
        assert "<img" not in result


def test_skip_local_paths(media_downloader, tmp_path):
    """Test that local paths are not downloaded."""
    output_path = tmp_path / "release-notes.md"
    
    description = """
![Local Image](./local/path/image.png)
<img src="assets/another.png" alt="Another Local" />
"""
    
    with patch.object(media_downloader, '_download_media') as mock_download:
        result = media_downloader.process_description(
            description, "1.0.0", str(output_path), convert_html_to_markdown=True
        )
        
        # No downloads should happen for local paths
        mock_download.assert_not_called()
        
        # Local paths should remain unchanged
        assert "./local/path/image.png" in result
        assert "assets/another.png" in result


def test_disabled_media_downloader(tmp_path):
    """Test that disabled MediaDownloader doesn't process anything."""
    assets_path = str(tmp_path / "assets")
    downloader = MediaDownloader(assets_path, download_enabled=False)
    output_path = tmp_path / "release-notes.md"
    
    description = """
![Image](https://example.com/image.png)
<img src="https://example.com/html.png" alt="HTML" />
"""
    
    result = downloader.process_description(
        description, "1.0.0", str(output_path), convert_html_to_markdown=True
    )
    
    # Nothing should be changed
    assert result == description
