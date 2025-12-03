# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Config migration system.

This package manages configuration file migrations between versions.
Individual migration scripts live in this directory (e.g., v1_0_to_v1_1.py).
The MigrationManager is defined in manager.py.
"""

from .manager import MigrationManager, MigrationError

__all__ = ['MigrationManager', 'MigrationError']
