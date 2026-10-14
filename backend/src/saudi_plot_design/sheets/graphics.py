"""Shared deterministic SVG and PDF renderers for M6.3 sheet primitives."""

from __future__ import annotations

import math
from html import escape
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from saudi_plot_design.sheets.models import GraphicProfile, Primitive, SheetPage


def _number(value: float) -> str:
    value = 0.0 if abs(value) < 5e-8 else value
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _attrs(primitive: Primitive) -> str:
    values = {
        "data-role": primitive.role,
        "data-source-id": primitive.source_id,
    }
    return " ".join(
        f'{name}="{escape(value, quote=True)}"' for name, value in values.items() if value
    )


def render_sheet_svg(page: SheetPage, profile: GraphicProfile) -> str:
    """Serialize a sheet page as standalone deterministic SVG."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{_number(profile.paper_width_mm)}mm" '
            f'height="{_number(profile.paper_height_mm)}mm" '
            f'viewBox="0 0 {_number(profile.paper_width_mm)} '
            f'{_number(profile.paper_height_mm)}">'
        ),
        (
            f"<metadata>profile={profile.profile_id};sheet={escape(page.number)};"
            f"candidate={escape(page.candidate_id)};"
            f"geometry={escape(page.geometry_fingerprint)}</metadata>"
        ),
        '<rect x="0" y="0" width="420" height="297" fill="#ffffff"/>',
    ]
    for primitive in page.primitives:
        lines.append(_svg_primitive(primitive, profile))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _svg_style(p: Primitive) -> str:
    dash = ""
    if p.dash_mm:
        dash = f' stroke-dasharray="{" ".join(_number(v) for v in p.dash_mm)}"'
    return (
        f'stroke="{p.stroke}" fill="{p.fill}" '
        f'stroke-width="{_number(p.stroke_width_mm)}" opacity="{_number(p.opacity)}"'
        f"{dash}"
    )


def _svg_primitive(p: Primitive, profile: GraphicProfile) -> str:
    attrs = _attrs(p)
    style = _svg_style(p)
    if p.kind == "line":
        (x1, y1), (x2, y2) = p.points
        return (
            f'<line x1="{_number(x1)}" y1="{_number(y1)}" '
            f'x2="{_number(x2)}" y2="{_number(y2)}" {style} {attrs}/>'
        )
    if p.kind in {"polyline", "polygon"}:
        points = " ".join(f"{_number(x)},{_number(y)}" for x, y in p.points)
        return f'<{p.kind} points="{points}" {style} {attrs}/>'
    if p.kind == "rect":
        return (
            f'<rect x="{_number(p.x)}" y="{_number(p.y)}" '
            f'width="{_number(p.width)}" height="{_number(p.height)}" '
            f"{style} {attrs}/>"
        )
    if p.kind == "circle":
        return (
            f'<circle cx="{_number(p.x)}" cy="{_number(p.y)}" '
            f'r="{_number(p.radius)}" {style} {attrs}/>'
        )
    if p.kind == "text":
        font_size_mm = p.font_size_pt * 25.4 / 72.0
        svg_font = "Arial, Helvetica, sans-serif"
        transform = ""
        if p.rotation_deg:
            transform = (
                f' transform="rotate({_number(p.rotation_deg)} {_number(p.x)} {_number(p.y)})"'
            )
        return (
            f'<text x="{_number(p.x)}" y="{_number(p.y)}" '
            f'font-family="{svg_font}" font-size="{_number(font_size_mm)}" '
            f'font-weight="{"bold" if p.bold else "normal"}" '
            f'text-anchor="{p.anchor}" fill="{p.fill if p.fill != "none" else p.stroke}" '
            f'opacity="{_number(p.opacity)}"{transform} {attrs}>'
            f"{escape(p.text)}</text>"
        )
    raise ValueError(f"unsupported sheet primitive kind: {p.kind}")


def write_sheet_svg(path: str | Path, page: SheetPage, profile: GraphicProfile) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sheet_svg(page, profile), encoding="utf-8", newline="\n")
    return path


def write_sheet_pdf(
    path: str | Path,
    pages: tuple[SheetPage, ...],
    profile: GraphicProfile,
    *,
    title: str,
    candidate_id: str,
    geometry_fingerprint: str,
) -> Path:
    """Render vector PDF pages from the exact primitives used by SVG."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(
        str(path),
        pagesize=(profile.paper_width_mm * mm, profile.paper_height_mm * mm),
        invariant=1,
        pageCompression=1,
    )
    c.setTitle(title)
    c.setAuthor("Saudi Plot Design Studio")
    c.setCreator("saudi-plot-design M6.3 deterministic sheet engine")
    c.setSubject("DEMO architectural concept sheets - NOT FOR CONSTRUCTION")
    c.setKeywords(
        f"DEMO,{profile.profile_id},{candidate_id},{geometry_fingerprint},NOT FOR CONSTRUCTION"
    )
    for page in pages:
        for primitive in page.primitives:
            _pdf_primitive(c, primitive, profile)
        c.showPage()
    c.save()
    return path


def _pdf_point(profile: GraphicProfile, x: float, y: float) -> tuple[float, float]:
    return x * mm, (profile.paper_height_mm - y) * mm


def _set_pdf_style(c, p: Primitive) -> None:
    c.setStrokeColor(HexColor(p.stroke))
    c.setFillColor(HexColor(p.fill if p.fill != "none" else p.stroke))
    c.setLineWidth(p.stroke_width_mm * mm)
    c.setDash([v * mm for v in p.dash_mm] if p.dash_mm else [])
    if hasattr(c, "setFillAlpha"):
        c.setFillAlpha(p.opacity)
        c.setStrokeAlpha(p.opacity)


def _pdf_primitive(c, p: Primitive, profile: GraphicProfile) -> None:
    c.saveState()
    _set_pdf_style(c, p)
    if p.kind == "line":
        (x1, y1), (x2, y2) = p.points
        c.line(*_pdf_point(profile, x1, y1), *_pdf_point(profile, x2, y2))
    elif p.kind in {"polyline", "polygon"}:
        path = c.beginPath()
        x0, y0 = _pdf_point(profile, *p.points[0])
        path.moveTo(x0, y0)
        for point in p.points[1:]:
            path.lineTo(*_pdf_point(profile, *point))
        if p.kind == "polygon":
            path.close()
        c.drawPath(path, stroke=1, fill=int(p.fill != "none"))
    elif p.kind == "rect":
        x = p.x * mm
        y = (profile.paper_height_mm - p.y - p.height) * mm
        c.rect(x, y, p.width * mm, p.height * mm, stroke=1, fill=int(p.fill != "none"))
    elif p.kind == "circle":
        x, y = _pdf_point(profile, p.x, p.y)
        c.circle(x, y, p.radius * mm, stroke=1, fill=int(p.fill != "none"))
    elif p.kind == "text":
        font = profile.font_bold if p.bold else profile.font_regular
        c.setFont(font, p.font_size_pt)
        x, y = _pdf_point(profile, p.x, p.y)
        c.translate(x, y)
        c.rotate(-p.rotation_deg)
        text_width = c.stringWidth(p.text, font, p.font_size_pt)
        offset = 0.0
        if p.anchor == "middle":
            offset = -text_width / 2
        elif p.anchor == "end":
            offset = -text_width
        c.drawString(offset, 0, p.text)
    else:
        raise ValueError(f"unsupported sheet primitive kind: {p.kind}")
    c.restoreState()


def polyline_arc(
    center: tuple[float, float],
    radius: float,
    start_deg: float,
    end_deg: float,
    *,
    segments: int = 12,
) -> tuple[tuple[float, float], ...]:
    """Return a deterministic polyline arc in the page's Y-down system."""
    return tuple(
        (
            center[0]
            + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * i / segments)),
            center[1]
            + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * i / segments)),
        )
        for i in range(segments + 1)
    )
