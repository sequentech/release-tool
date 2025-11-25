"""Config migration system for release-tool.

Handles upgrading config files between versions when format changes.
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable
import importlib.util
from packaging import version


class MigrationError(Exception):
    """Raised when a migration fails."""
    pass


class MigrationManager:
    """Manages config file migrations."""

    CURRENT_VERSION = "1.2"  # Latest config version

    def __init__(self):
        # Since manager.py is in the migrations/ directory, parent IS the migrations dir
        self.migrations_dir = Path(__file__).parent
        self._loaded_migrations: Dict[Tuple[str, str], Callable] = {}

    def compare_versions(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.

        Returns:
            -1 if v1 < v2
            0 if v1 == v2
            1 if v1 > v2
        """
        ver1 = version.parse(v1)
        ver2 = version.parse(v2)

        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0

    def needs_upgrade(self, current_version: str) -> bool:
        """Check if config needs upgrade."""
        return self.compare_versions(current_version, self.CURRENT_VERSION) < 0

    def get_migration_path(self, from_version: str, to_version: str) -> List[Tuple[str, str]]:
        """
        Get ordered list of migrations needed to go from one version to another.

        Returns:
            List of (from_version, to_version) tuples representing migration steps
        """
        # For now, we support direct migrations
        # In future, could support chained migrations (1.0 -> 1.1 -> 1.2)
        available_migrations = self._discover_migrations()

        if (from_version, to_version) in available_migrations:
            return [(from_version, to_version)]

        # Try to find a path through intermediate versions
        # Simple implementation: try common version chain
        path = []
        current = from_version

        while self.compare_versions(current, to_version) < 0:
            # Find next migration
            found = False
            for (from_v, to_v) in available_migrations:
                if from_v == current:
                    path.append((from_v, to_v))
                    current = to_v
                    found = True
                    break

            if not found:
                # No migration path found
                raise MigrationError(
                    f"No migration path found from {from_version} to {to_version}"
                )

        return path

    def _discover_migrations(self) -> List[Tuple[str, str]]:
        """Discover available migration scripts."""
        migrations = []

        if not self.migrations_dir.exists():
            return migrations

        for file in self.migrations_dir.glob("v*_to_v*.py"):
            # Parse filename: v1_0_to_v1_1.py -> ("1.0", "1.1")
            name = file.stem
            parts = name.split("_to_")
            if len(parts) != 2:
                continue

            from_part = parts[0].replace("v", "").replace("_", ".")
            to_part = parts[1].replace("v", "").replace("_", ".")

            migrations.append((from_part, to_part))

        return migrations

    def load_migration(self, from_version: str, to_version: str) -> Callable:
        """Load a migration function from file."""
        key = (from_version, to_version)

        if key in self._loaded_migrations:
            return self._loaded_migrations[key]

        # Build filename: v1_0_to_v1_1.py
        from_part = "v" + from_version.replace(".", "_")
        to_part = "v" + to_version.replace(".", "_")
        filename = f"{from_part}_to_{to_part}.py"

        migration_file = self.migrations_dir / filename

        if not migration_file.exists():
            raise MigrationError(
                f"Migration file not found: {migration_file}"
            )

        # Dynamically load the migration module
        spec = importlib.util.spec_from_file_location(
            f"migration_{from_part}_to_{to_part}",
            migration_file
        )
        if not spec or not spec.loader:
            raise MigrationError(f"Failed to load migration: {migration_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, 'migrate'):
            raise MigrationError(
                f"Migration {filename} must have a 'migrate' function"
            )

        self._loaded_migrations[key] = module.migrate
        return module.migrate

    def apply_migration(
        self,
        config_dict: Dict,
        from_version: str,
        to_version: str
    ) -> Dict:
        """Apply a single migration to config dict."""
        migrate_func = self.load_migration(from_version, to_version)

        try:
            updated_config = migrate_func(config_dict)
            # Ensure version is updated
            updated_config['config_version'] = to_version
            return updated_config
        except Exception as e:
            raise MigrationError(
                f"Migration from {from_version} to {to_version} failed: {e}"
            ) from e

    def upgrade_config(
        self,
        config_dict: Dict,
        target_version: Optional[str] = None
    ) -> Dict:
        """
        Upgrade config dict to target version (or latest if not specified).

        Args:
            config_dict: Config dictionary (from TOML)
            target_version: Target version (defaults to latest)

        Returns:
            Upgraded config dictionary
        """
        if target_version is None:
            target_version = self.CURRENT_VERSION

        current_version = config_dict.get('config_version', '1.0')

        if self.compare_versions(current_version, target_version) >= 0:
            # Already at target version or newer
            return config_dict

        # Get migration path
        path = self.get_migration_path(current_version, target_version)

        # Apply migrations in sequence
        updated_config = config_dict.copy()
        for from_v, to_v in path:
            updated_config = self.apply_migration(updated_config, from_v, to_v)

        return updated_config

    def get_changes_description(self, from_version: str, to_version: str) -> str:
        """Get human-readable description of changes between versions."""
        descriptions = {
            ("1.0", "1.1"): (
                "Version 1.1 adds:\n"
                "  • New template variables: ticket_url, pr_url for more flexible URL handling\n"
                "  • Improved output_template formatting with better spacing\n"
                "  • url field now intelligently uses ticket_url if available, else pr_url"
            ),
            ("1.1", "1.2"): (
                "Version 1.2 adds:\n"
                "  • New partial_ticket_action policy (ignore/warn/error)\n"
                "  • Handles tickets extracted but not found in database\n"
                "  • Handles tickets found in different repositories\n"
                "  • Provides diagnostics with potential reasons and links"
            ),
        }

        key = (from_version, to_version)
        return descriptions.get(key, "No description available")
