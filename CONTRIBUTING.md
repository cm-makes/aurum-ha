# Contributing to AURUM

Thanks for your interest in improving AURUM! Here's how to get started.

## Reporting Bugs

1. Check [existing issues](https://github.com/Chris0479/aurum-ha/issues) first
2. Open a new issue using the **Bug Report** template
3. Include your HA version, AURUM version, and relevant logs

## Suggesting Features

Open an issue using the **Feature Request** template. Describe the use case, not just the solution.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/Chris0479/aurum-ha.git
cd aurum-ha

# Copy into your HA dev environment
cp -r custom_components/aurum /path/to/ha/config/custom_components/
```

## Code Guidelines

- Follow existing code style (no linter enforced, but keep it consistent)
- Add docstrings to new functions
- Test changes with the simulation suite in `tests/`
- Update `strings.json` AND `translations/de.json` + `translations/en.json` for any UI changes

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit with clear messages
4. Open a PR against `main`
5. Describe what changed and why

## Translation

AURUM ships with English and German translations. If you'd like to add another language:

1. Copy `custom_components/aurum/translations/en.json`
2. Rename to your language code (e.g. `fr.json`)
3. Translate all values (keep keys unchanged)
4. Open a PR

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
