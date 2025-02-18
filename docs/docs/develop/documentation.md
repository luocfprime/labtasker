# Documentation

## Installation

To install documentation dependencies:

```bash
pip install -e '.[doc]'
```

## Preview locally

To serve the documentation locally (for preview):

```bash
cd docs
# make sure you are at PROJECT_ROOT/docs

mike serve
```

or, you can use mkdocs to live-reload:

```bash
mkdocs serve
```

To check list of documentation versions:

```bash
make list
```

Check other utilities in `PROJECT_ROOT/docs/Makefile`.

## How to add a new document

Steps:

1. Create a new markdown file under `PROJECT_ROOT/docs/docs/` (e.g. `docs/docs/develop/foo.md`)
2. Add an entry in `docs/mkdocs-nav.yml`
