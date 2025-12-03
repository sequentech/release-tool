<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
description: Run linters and auto-fix code quality issues
---

Automatically fix code formatting and style issues using black, isort, and check types with mypy.

Steps:
1. Run black formatter on all Python files:
   ```bash
   poetry run black src/ tests/
   ```
   - Reports files reformatted
   - Auto-fixes formatting issues

2. Run isort to organize imports:
   ```bash
   poetry run isort src/ tests/
   ```
   - Sorts imports alphabetically
   - Groups imports by standard lib, third-party, local

3. Run mypy type checker:
   ```bash
   poetry run mypy src/
   ```
   - Reports type errors (does NOT auto-fix)
   - Show any type violations that need manual fixing

4. Summary report:
   - Files formatted: X
   - Imports organized: Y
   - Type errors: Z (if any)

5. If type errors exist:
   - Show the specific errors
   - Offer to explain how to fix common type issues
   - Suggest adding type hints where missing

6. If changes were made, offer to:
   - Show git diff of changes
   - Commit the formatting changes
   - Run tests to ensure nothing broke

Example output:
```
✓ Formatted 5 files with black
✓ Organized imports in 3 files with isort
✓ Type checking passed with 0 errors
```
