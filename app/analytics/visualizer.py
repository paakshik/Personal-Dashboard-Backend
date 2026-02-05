import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.config import logger, sentry_sdk


def create_performance_plot(data: List[Dict[str, Any]],
                            metrics: List[str],
                            graph_type: str = "line") -> go.Figure:
    """
    Generate an interactive Plotly figure for system metrics.

    This function orchestrates the data transformation and visualization process.
    It includes error handling and performance tracing via Sentry to ensure
    dashboard stability during demos.

    Args:
        data (List[Dict[str, Any]]): A list of dictionary records containing raw metric data.
                                     Example: [{'timestamp': '...', 'cpu': {...}}, ...]
        metrics (List[str]): A list of specific metric keys to visualize.
                             Example: ['cpu.percent', 'memory.percent']
        graph_type (str, optional): The type of chart to render.
                                    Options: 'line' (default), 'bar', 'scatter', 'subplots'.

    Returns:
        go.Figure: A Plotly Graph Object ready for JSON serialization.
                   Returns a placeholder 'Empty Figure' if data is missing or errors occur.
    """

    if not data:
        logger.warning("create_performance_plot called with empty data.")
        return _get_empty_figure("Waiting for data stream...")

    with sentry_sdk.start_span(op="visualization",
                               description=f"generate_{graph_type}_plot"):
        try:
            logger.info(
                f"Generating {graph_type} plot for {len(metrics)} metrics over {len(data)} data points.")

            # 3. Data Preparation (Flatten JSON to DataFrame) using  Pandas
            df = _prepare_dataframe(data)

            # 4. Logic: Select the correct visualization strategy
            match graph_type:
                case "bar":
                    return _create_dynamic_bar_plot(df, metrics)
                case _:
                    # Default to line chart for time-series data
                    return _create_line_plot(df, metrics)

        except Exception as e:
            logger.error(f"Failed to generate {graph_type} plot: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)
            return _get_empty_figure("Error generating visualization")

def _prepare_dataframe(data: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Flatten nested JSON metrics into a Pandas DataFrame.

    This function iterates through raw API data, safely extracts nested keys
    (CPU, Memory, Disk), and indexes them by timestamp. It includes error
    handling to skip malformed records without crashing.

    Args:
        data (List[Dict[str, Any]]): List of raw metric dictionaries.
                                     e.g. [{'timestamp': '...', 'cpu': {...}}, ...]

    Returns:
        pd.DataFrame: A DataFrame indexed by timestamp with columns like
                      'cpu.percent', 'memory.percent', etc.
                      Returns an empty DataFrame if parsing fails.
    """
    with sentry_sdk.start_span(op="data_processing", description="prepare_dataframe"):
        rows = []

        # Log the start of processing
        logger.debug(f"Processing {len(data)} records for DataFrame conversion.")

        for entry in data:
            try:
                # 1. Parse Timestamp (Critical: Skip row if missing/invalid)
                if "timestamp" not in entry:
                    continue

                # Create base row
                row = {"timestamp": datetime.fromisoformat(entry["timestamp"])}

                # 2. Safe Extraction of Nested Values
                # We use .get() to prevent crashes if a specific metric is missing
                if "cpu" in entry:
                    row["cpu.percent"] = entry["cpu"].get("percent", 0.0)

                if "memory" in entry:
                    row["memory.percent"] = entry["memory"].get("percent", 0.0)

                if "disk" in entry:
                    row["disk.percent"] = entry["disk"].get("percent", 0.0)

                rows.append(row)

            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed data entry: {e}")
                continue

        # 3. Create DataFrame
        df = pd.DataFrame(rows)

        # 4. Final Setup
        if not df.empty:
            df.set_index("timestamp", inplace=True)
            df = df.sort_index()
        else:
            logger.warning("Data processing resulted in an empty DataFrame.")
            sentry_sdk.capture_message("Data processing resulted in an empty "
                                       "DataFrame for the system processing.",
                                       level="warning")
        return df


def _create_line_plot(df: pd.DataFrame, metrics: List[str]) -> go.Figure:
    """
    Create a Neon-style Line Chart with cyberpunk aesthetics.

    This function renders a high-contrast line chart suitable for dark-mode dashboards.
    It automatically calculates a transparent fill color based on the line color
    to create a glowing effect.

    Args:
        df (pd.DataFrame): Time-indexed DataFrame containing metric values.
        metrics (List[str]): List of column names to plot (e.g., ['cpu.percent']).

    Returns:
        go.Figure: A styled Plotly figure object.
    """
    fig = go.Figure()

    # Cyberpunk palette: Cyan, Magenta, Neon Green, Yellow
    colors = ["#00f2ff", "#ff00ff", "#39ff14", "#ffff00"]

    for i, metric in enumerate(metrics):
        if metric in df.columns:
            # Select color cyclically
            base_color = colors[i % len(colors)]

            # Convert Hex to RGBA for the fill (opacity 0.1) using helper
            fill_color = _hex_to_rgba(base_color, opacity=0.1)

            fig.add_trace(go.Scatter(
                x=df.index,
                y=df[metric],
                mode='lines',
                name=metric.upper(),
                line={"color": base_color, "width": 3},
                fill='tozeroy',  # Fills area under the line
                fillcolor=fill_color
            ))

    # Apply "Cyberpunk" Styling
    fig.update_layout(
        title="<b>REAL-TIME MONITOR</b>",
        template="plotly_dark",
        plot_bgcolor='rgba(0,0,0,1)',  # Transparent background
        paper_bgcolor='rgba(0,0,0,2)',  # Transparent container
        xaxis={"showgrid": False},  # Clean X-axis
        yaxis={"showgrid": True, "gridcolor": '#333'},  # Faint grid for readability
        height=450,
        margin={"l": 20, "r": 20, "t": 50, "b": 20}
    )
    return fig


def _hex_to_rgba(hex_color: str, opacity: float = 0.1) -> str:
    """
    Helper: Convert a Hex color string to an RGBA string.

    Args:
        hex_color (str): Hex color code (e.g., "#00f2ff" or "00f2ff").
        opacity (float): Opacity level between 0.0 (transparent) and 1.0 (solid).

    Returns:
        str: CSS-style rgba string (e.g., "rgba(0, 242, 255, 0.1)").
    """
    hex_color = hex_color.lstrip('#')

    # Parse hex into RGB tuple  of decimals
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {opacity})"


def _create_dynamic_bar_plot(df: pd.DataFrame, metrics: List[str]) -> go.Figure:
    """
    Create a Dynamic Bar Chart that adjusts resolution based on time range.

    This function intelligently resamples data (e.g., 10s, 1min, 1h) to prevent
    visual clutter or the "One Giant Bar" issue during short sessions.

    Args:
        df (pd.DataFrame): Time-indexed DataFrame containing metric values.
        metrics (List[str]): List of column names to plot.

    Returns:
        go.Figure: A styled Plotly figure object.
    """
    rule, label = "N/A", "N/A"
    if df.empty:
        logger.warning("Data processing resulted in an empty DataFrame for dynamic "
                       "bar plot.")
        sentry_sdk.capture_message("Data processing resulted in an empty DataFrame "
                                   "for the dynamic bar plot.",
                                   level="warning")
        return _get_empty_figure("No Data Available")

    # 2. for  getting the gap between 2 intervals from start to finish.
    try:
        duration = df.index[-1] - df.index[0]
    except IndexError:
        duration = timedelta(seconds=0)

    match duration:
        case d if d < timedelta(minutes=5):
            rule = '10s'
            label = "10s Interval"
        case d if  d > timedelta(hours=1):
            rule = '1min'
            label = "Minute Average"
        case _:
            rule = '1h'
            label = "Hours Average"

    logger.info(f"Generating Bar Plot: Duration={duration}, Rule={rule}")

    # 3. Initialize Figure
    fig = go.Figure()

    # Cyberpunk palette: Cyan, Magenta, Neon Green, Yellow
    colors = ["#00f2ff", "#ff00ff", "#39ff14", "#ffff00"]

    # 4. Add Traces
    for i, metric in enumerate(metrics):
        if metric in df.columns:
            # Resample safely to avoid messy graphs
            resampled = df[metric].resample(rule).mean()

            # Select color cyclically
            bar_color = colors[i % len(colors)]

            fig.add_trace(go.Bar(
                x=resampled.index,
                y=resampled.values,
                name=metric.upper(),
                marker={"color": bar_color}
            ))

    # 5. Apply "Cyberpunk" Styling
    fig.update_layout(
        title=f"<b>AVERAGE USAGE ({label})</b>",
        template="plotly_dark",
        plot_bgcolor='rgba(0,0,1,0)',  # Transparent background
        paper_bgcolor='rgba(0,0,1,0)',  # Transparent container
        barmode='group',
        # ✅ dict() -> {}
        xaxis={"showgrid": False},
        yaxis={"showgrid": True, "gridcolor": '#333'},
        height=450,
        margin={"l": 20, "r": 20, "t": 50, "b": 20}
    )

    return fig

def _get_empty_figure(text: str) -> go.Figure:
    """
    Create a clean, empty placeholder plot with a central text message.

    This is used as a fallback when data is missing or invalid, ensuring the
    dashboard UI remains stable rather than showing a broken image icon.

    Args:
        text (str): The message to display in the center (e.g., "No Data").

    Returns:
        go.Figure: A Plotly figure with no axes, displaying only the text.
    """
    fig = go.Figure()

    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
            "text": text,
            "xref": "paper",
            "yref": "paper",
            "showarrow": False,
            "font": {"size": 20, "color": "#666"}
        }],
        template="plotly_dark",
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)'
    )
    return fig