
"""
Generate bar, line, and pie charts from a pandas DataFrame.

Outputs:
- Interactive HTML chart using Plotly.
- Static PNG chart using Matplotlib.

Matplotlib is used for PNG generation to avoid depending on
Kaleido or a browser installation.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.config import get_settings


_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")
ALLOWED_CHART_TYPES = {"bar", "line", "pie"}


@dataclass
class ChartArtifact:
    ok: bool
    png_path: str | None = None
    html_path: str | None = None
    error: str | None = None


def _slug(text: str, fallback: str = "chart") -> str:
    """Convert a title into a safe filename component."""
    text = (text or "").strip()
    text = _SLUG_RE.sub("_", text)[:60].strip("_.-")
    return text or fallback


def _outputs_dir() -> Path:
    """Create and return the configured output directory."""
    path = Path(get_settings().outputs_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_chart(
    df: pd.DataFrame,
    chart_type: str,
    x: str,
    y: str,
    title: str,
) -> ChartArtifact:
    """
    Build an interactive HTML chart and a static PNG chart.

    Returns a ChartArtifact describing the generated files or any error.
    """

    # 1. Validate chart type.
    if chart_type not in ALLOWED_CHART_TYPES:
        return ChartArtifact(
            ok=False,
            error=f"Unsupported chart_type: {chart_type}",
        )

    # 2. Validate input data.
    if df is None or df.empty:
        return ChartArtifact(
            ok=False,
            error="Cannot create a chart from an empty result.",
        )

    if x not in df.columns:
        return ChartArtifact(
            ok=False,
            error=f"Column '{x}' not found. Available columns: {list(df.columns)}",
        )

    if y not in df.columns:
        return ChartArtifact(
            ok=False,
            error=f"Column '{y}' not found. Available columns: {list(df.columns)}",
        )

    # 3. Validate numeric values required for the y-axis.
    if chart_type in {"bar", "line", "pie"}:
        if not pd.api.types.is_numeric_dtype(df[y]):
            return ChartArtifact(
                ok=False,
                error=f"Column '{y}' must contain numeric values.",
            )

    if chart_type == "pie":
        if (df[y].dropna() < 0).any():
            return ChartArtifact(
                ok=False,
                error="Pie charts cannot contain negative values.",
            )

        if df[y].fillna(0).sum() <= 0:
            return ChartArtifact(
                ok=False,
                error="Pie charts require a positive total value.",
            )

    # 4. Build the Plotly figure.
    try:
        plotly_fig = _make_figure(df, chart_type, x, y, title)
    except Exception as exc:
        return ChartArtifact(
            ok=False,
            error=f"Chart build failed: {exc}",
        )

    # 5. Create unique output filenames.
    filename = f"{_slug(title)}-{uuid.uuid4().hex[:8]}"
    output_dir = _outputs_dir()

    html_path = output_dir / f"{filename}.html"
    png_path = output_dir / f"{filename}.png"

    # 6. Save both chart formats.
    try:
        # Interactive chart.
        plotly_fig.write_html(
            str(html_path),
            include_plotlyjs="cdn",
        )

        # Static image; does not use Kaleido.
        _save_png(
            df=df,
            chart_type=chart_type,
            x=x,
            y=y,
            title=title,
            png_path=png_path,
        )

    except Exception as exc:
        # Remove incomplete outputs if either export fails.
        html_path.unlink(missing_ok=True)
        png_path.unlink(missing_ok=True)

        return ChartArtifact(
            ok=False,
            error=f"Chart rendering failed: {exc}",
        )

    finally:
        plt.close("all")

    return ChartArtifact(
        ok=True,
        png_path=str(png_path),
        html_path=str(html_path),
    )


def _make_figure(
    df: pd.DataFrame,
    chart_type: str,
    x: str,
    y: str,
    title: str,
) -> go.Figure:
    """Create the interactive Plotly chart."""

    if chart_type == "bar":
        return px.bar(
            df,
            x=x,
            y=y,
            title=title,
        )

    if chart_type == "line":
        return px.line(
            df,
            x=x,
            y=y,
            title=title,
            markers=True,
        )

    return px.pie(
        df,
        names=x,
        values=y,
        title=title,
    )


def _save_png(
    df: pd.DataFrame,
    chart_type: str,
    x: str,
    y: str,
    title: str,
    png_path: Path,
) -> None:
    """Generate a PNG chart using Matplotlib."""

    fig, ax = plt.subplots(figsize=(9, 5.2))

    if chart_type == "bar":
        ax.bar(
            df[x].astype(str),
            df[y],
        )
        ax.set_xlabel(x)
        ax.set_ylabel(y)

    elif chart_type == "line":
        ax.plot(
            df[x].astype(str),
            df[y],
            marker="o",
        )
        ax.set_xlabel(x)
        ax.set_ylabel(y)

    elif chart_type == "pie":
        ax.pie(
            df[y],
            labels=df[x].astype(str),
            autopct="%1.1f%%",
        )

    ax.set_title(title)

    if chart_type != "pie":
        ax.tick_params(
            axis="x",
            labelrotation=30,
        )

    fig.tight_layout()
    fig.savefig(
        png_path,
        dpi=120,
        bbox_inches="tight",
    )

