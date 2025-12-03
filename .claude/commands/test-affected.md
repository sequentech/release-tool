<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
description: Run tests for recently modified modules
---

Smart test execution that focuses on modules affected by recent changes.

Steps:
1. Check git status to find modified files:
   ```bash
   git status --short
   ```

2. Identify modified Python modules in `src/release_tool/`

3. Map modules to their corresponding test files:
   - `models.py` → `tests/test_models.py`
   - `config.py` → `tests/test_config.py`
   - `db.py` → `tests/test_db.py`
   - `git_ops.py` → `tests/test_git_ops.py`
   - `policies.py` → `tests/test_policies.py`
   - `sync.py` → `tests/test_sync.py`

4. Run affected tests with verbose output:
   ```bash
   poetry run pytest tests/test_MODULE.py -v --tb=short
   ```

5. If multiple modules changed, run all affected tests together:
   ```bash
   poetry run pytest tests/test_file1.py tests/test_file2.py -v
   ```

6. Show summary:
   - Tests run: X
   - Passed: Y
   - Failed: Z
   - Duration: T seconds

7. If tests fail, offer to:
   - Show detailed failure output
   - Run just the failed test
   - Run with debugger (--pdb)

Optional: Run with coverage for changed modules:
```bash
poetry run pytest tests/test_MODULE.py --cov=release_tool.MODULE --cov-report=term-missing
```
