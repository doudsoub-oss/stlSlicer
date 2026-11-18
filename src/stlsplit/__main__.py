"""Entry point for ``python -m stlsplit``; delegates to :func:`stlsplit.cli.main`."""

from stlsplit.cli import main

raise SystemExit(main())
