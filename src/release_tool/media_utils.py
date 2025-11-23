"""Media download and processing utilities for release notes."""

import re
import hashlib
from pathlib import Path
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse
import requests
from rich.console import Console

console = Console()


class MediaDownloader:
    """Download and manage media assets for release notes."""

    def __init__(self, assets_path: str, download_enabled: bool = True):
        """
        Initialize media downloader.

        Args:
            assets_path: Path template for downloaded assets
            download_enabled: Whether to download media or keep URLs
        """
        self.assets_path = assets_path
        self.download_enabled = download_enabled
        self.downloaded_files: Dict[str, str] = {}  # URL -> local path mapping

    def process_description(
        self,
        description: str,
        version: str,
        output_path: str
    ) -> str:
        """
        Process description text to download media and update references.

        Args:
            description: Markdown text with potential media URLs
            version: Version string for path substitution
            output_path: Path to the output release notes file

        Returns:
            Updated description with local media references
        """
        if not self.download_enabled or not description:
            return description

        # Find all image and video references in markdown
        # Matches: ![alt](url) and videos with .mp4, .webm, etc.
        media_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

        def replace_media(match):
            alt_text = match.group(1)
            url = match.group(2)

            # Skip if already a local path
            if not url.startswith(('http://', 'https://')):
                return match.group(0)

            # Download media and get local path
            local_path = self._download_media(url, version, output_path)
            if local_path:
                return f'![{alt_text}]({local_path})'

            # If download fails, keep original
            return match.group(0)

        return re.sub(media_pattern, replace_media, description)

    def _download_media(
        self,
        url: str,
        version: str,
        output_path: str
    ) -> Optional[str]:
        """
        Download media file and return relative path.

        Args:
            url: URL of media file to download
            version: Version string for path substitution
            output_path: Path to the output release notes file

        Returns:
            Relative path to downloaded file or None if failed
        """
        # Check if already downloaded
        if url in self.downloaded_files:
            return self.downloaded_files[url]

        try:
            # Parse version for path substitution
            version_parts = self._parse_version(version)

            # Create assets directory
            assets_dir = Path(self.assets_path.format(**version_parts))
            assets_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename from URL
            parsed_url = urlparse(url)
            original_filename = Path(parsed_url.path).name

            # Add hash to filename to avoid collisions
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"{url_hash}_{original_filename}"

            local_file = assets_dir / filename

            # Download file
            console.print(f"[blue]Downloading media: {url}[/blue]")
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()

            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Calculate relative path from output_path to media file
            output_dir = Path(output_path).parent
            try:
                relative_path = local_file.relative_to(output_dir)
            except ValueError:
                # If not relative, use absolute path
                relative_path = local_file

            relative_path_str = str(relative_path).replace('\\', '/')
            self.downloaded_files[url] = relative_path_str

            console.print(f"[green]Downloaded: {relative_path_str}[/green]")
            return relative_path_str

        except Exception as e:
            console.print(f"[yellow]Warning: Failed to download {url}: {e}[/yellow]")
            return None

    def _parse_version(self, version: str) -> Dict[str, str]:
        """
        Parse version string into components for path substitution.

        Args:
            version: Version string (e.g., "1.2.3" or "1.2.3-rc.1")

        Returns:
            Dictionary with version, major, minor, patch keys
        """
        # Remove 'v' prefix if present
        clean_version = version.lstrip('v')

        # Split by '-' to separate version from prerelease
        version_base = clean_version.split('-')[0]

        # Split version into parts
        parts = version_base.split('.')

        return {
            'version': version,
            'major': parts[0] if len(parts) > 0 else '0',
            'minor': parts[1] if len(parts) > 1 else '0',
            'patch': parts[2] if len(parts) > 2 else '0',
        }
