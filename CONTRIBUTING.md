# Contributing

First of all, thank you for considering contributing! We welcome contributions from everyone, including bug reports, feature requests, documentation improvements, and code enhancements.

This document outlines the process and guidelines to ensure smooth collaboration.

## How to Contribute

### 1. Fork the Repository
Create a personal fork of the repository and clone it to your local machine.

```bash
git clone https://github.com/your-username/your-repo.git
```

### 2. Create a Branch

Always create a new branch for your work. Use descriptive branch names:

```bash
git checkout -b feature/my-new-feature
git checkout -b bugfix/fix-issue-123
```

### 3. Follow the Code Style

We rely on the standard library and `pylint` to enforce consistency. Before committing, activate the project virtual environment and lint every tracked Python file:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pylint $(git ls-files '*.py')
```

Resolve every warning or error that `pylint` reports. Committers cannot push while lint fails in CI.

### 4. Write Clear Commits

- Follow the [Conventional Commits](https://www.conventionalcommits.org/) style so our semantic-release automation can produce changelogs (`feat:`, `fix:`, `docs:`, etc.).
- Keep the subject line concise (≤50 chars) and use the body for context when needed.

Example:
```
fix: surface CDN outages in job log

Adds a warning when file downloads retry across subdomains so operators can spot partial outages faster.
```

### 5. Testing

This repository does not yet ship a full automated test suite, so we lean on fast smoke checks:

- `python -m compileall src` ensures all Python sources are syntactically valid.
- `npm run build` compiles the web dashboard bundle.
- Run the CLI (`python3 downloader.py <url> --disable-ui`) or the web stack (`docker compose up --build`) when your changes touch runtime behaviour.

Please add targeted tests when you introduce new logic so we can build out coverage over time.

### 6. Pull Requests

1. Push your branch to your fork.
2. Open a pull request (PR) against the `main` branch of this repository.
3. Provide a clear description of what your PR changes and why, including manual verification steps.
4. Keep your branch rebased onto the latest `main` and respond quickly to review feedback.

### 7. Reporting Issues

If you find a bug or want to suggest a feature, please open an issue with a descriptive title and details about the problem.

## Thank You

Your contributions help make this project better and more useful for everyone. We appreciate your time and effort!
