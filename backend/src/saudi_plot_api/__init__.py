"""Web adapter for the Saudi Plot Design Studio (ADR-WEB-001).

This package wraps the deterministic offline core (``saudi_plot_design``) with an
HTTP application: anonymous sessions, project persistence, and health endpoints.

Dependency direction is one-way: ``saudi_plot_api`` may import
``saudi_plot_design``; the core never imports this package. Importing this
package requires the ``web`` optional dependency group.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
