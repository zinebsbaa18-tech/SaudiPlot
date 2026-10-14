"""Renderers over the canonical geometry model (never compute geometry here).

Public export API: ``export_project`` (export/pipeline.py) - the ONLY entry
point that enforces the complete export safety gate. The raw PDF/DXF writer
functions are private (underscore-prefixed) and must not be called outside
the pipeline and unit tests: they perform no gating by design.
"""

from saudi_plot_design.export.pipeline import export_project

__all__ = ["export_project"]
