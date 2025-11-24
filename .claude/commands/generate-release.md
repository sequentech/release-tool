---
description: Interactive release notes generation workflow
---

Generate release notes for a version with automatic comparison detection and preview.

Steps:
1. Ask user for:
   - Version number (e.g., "2.0.0", "1.5.0-rc.1")
   - Path to local git repository (default: current directory)
   - Output preference: console, file, GitHub release, or PR

2. Validate version format using SemanticVersion model

3. Check if database has necessary data:
   ```bash
   poetry run release-tool list-releases
   ```

4. Run generate command:
   ```bash
   poetry run release-tool generate VERSION \
     --repo-path ~/path/to/repo \
     [--output docs/releases/VERSION.md] \
     [--upload] \
     [--create-pr]
   ```

5. Show preview of generated notes:
   - Title and version
   - Number of changes per category
   - Breaking changes (if any)
   - Migration notes (if any)

6. If creating PR or release, confirm with user before proceeding

7. Report success with links to:
   - Output file (if --output)
   - GitHub release URL (if --upload)
   - Pull request URL (if --create-pr)

Notes:
- Comparison version is auto-detected based on semantic versioning rules
- RCs compare to previous RC of same version, or previous final
- Finals compare to previous final version
- Use `--from-version` to override automatic comparison
