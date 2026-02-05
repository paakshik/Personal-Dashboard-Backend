from app.services.system_data_store import system_data_store
from app.analytics.analyzer import SystemAnalyzer
from app.analytics.visualizer import create_performance_plot
from typing import Any,Dict,List, Optional
from fastapi import  HTTPException,Query,APIRouter
from app.config import logger,sentry_sdk


router = APIRouter(prefix="/dashboard/system", tags=["System Monitoring"])


@router.get("/history")
async def get_historical_metrics(
        hours: int = Query(24, description="Time window to retrieve in hours", ge=1),
        metric: Optional[str] = Query(None,
                                      description="Specific metric path using dot notation (e.g., 'cpu.percent')")
) -> List[Dict[str, Any]]:
    """
    Retrieves historical system metrics for the specified time window.

    If a `metric` filter is provided, it traverses the nested data structure
    to return a simplified list of timestamp and value pairs.

    Args:
        hours (int): The number of hours to look back (default: 24).
        metric (Optional[str]): A dot-separated string representing the key path
                                (e.g., 'memory.used').

    Returns:
        List[Dict[str, Any]]: A list of dictionary objects containing the requested data.

    Raises:
        HTTPException: If the data store fails or processing encounters a critical error.
    """
    try:
        # Fetch raw data
        data: List[Dict[str, Any]] = system_data_store.get_historical_data(hours)

        if not metric:
            logger.info(f"Successfully retrieved {len(data)} raw records.")
            return data

        # Process specific metric filtering
        simplified_data: List[Dict[str, Any]] = []
        keys = metric.split(".")

        for entry in data:
            current_value = entry
            valid_path = True

            for key in keys:
                if isinstance(current_value, dict):
                    current_value = current_value.get(key)
                else:
                    # Path does not exist or structure is invalid
                    valid_path = False
                    break

            # If path was valid and result is a value (not another dict/None), add it
            if valid_path and current_value is not None and not isinstance(
                    current_value, dict):
                simplified_data.append({
                    "timestamp": entry.get("timestamp"),
                    "value": current_value
                })

        logger.info(
            f"Successfully extracted {len(simplified_data)} records for metric '{metric}'.")
        return simplified_data

    except Exception as e:
        # Log the full stack trace locally
        logger.error(f"Error processing historical metrics: {str(e)}", exc_info=True)

        # Send the exception to Sentry
        sentry_sdk.capture_exception(e)

        # Return a generic 500 to the client to avoid leaking internals
        raise HTTPException(status_code=500,
                            detail="Internal server error while retrieving historical data.")


@router.get("/data-insights")
async def get_system_insights(hours: int = 24) -> Dict[str, Any]:
    """
    Generate valuable insights from historical system data.

    Uses the SystemAnalyzer to process raw metrics and identify trends,
    anomalies, or resource bottlenecks over the specified time window.

    Args:
        hours (int): The lookback window in hours (default: 24).

    Returns:
        Dict[str, Any]: A structured report containing analysis results.
                        Returns a status message if no data is available.

    Raises:
        HTTPException: 500 - If the analysis engine encounters a critical error.
    """
    try:
        analyzer = SystemAnalyzer()
        data = system_data_store.get_historical_data(hours)

        if not data:
            logger.warning(
                f"Analysis skipped: No data found for the last {hours} hours")
            sentry_sdk.capture_message(f"Analysis skipped: No data found for the last {hours} hours",level='warning')
            return {
                "status": "empty",
                "message": "No data available for analysis"
            }

        insights = analyzer.generate_insights(data)
        return insights

    except Exception as e:
        logger.error(f"Insight Analysis Failed: {e}", exc_info=True)
        sentry_sdk.capture_exception(e, extra={"hours_requested": hours})
        raise HTTPException(
            status_code=500,
            detail="Internal server error during data analysis")


# ✅ 4. Get Performance Graph (Returns Plotly HTML/JSON)
@router.get("/graph")
async def get_performance_graph(
        hours: int = 24,
        metrics: str = "cpu.percent,memory.percent,disk.percent",
        graph_type: str = "line"
) -> Dict[str, Any]:
    """
    Generates a system performance graph for frontend rendering on the dashboard.

    Fetches historical data and converts it into a Plotly-compatible JSON structure.
    This allows the frontend to render interactive graphs without needing raw data processing.

    Args:
        hours (int): Time window in hours (default: 24).
        metrics (str): Comma-separated list of metric paths (e.g., "cpu.percent,memory.used").
        graph_type (str): Type of visualization ("line", "bar", "scatter").

    Returns:
        Dict[str, Any]: A Plotly figure dictionary (JSON) ready for the client-side Plotly library.
                        Returns an error dictionary if no data is found.

    Raises:
        HTTPException: 500 - If the plotting engine fails to generate the graph.
    """
    try:
        data = system_data_store.get_historical_data(hours)

        if not data:
            logger.warning(f"Graph generation skipped: No data for last {hours}h")
            sentry_sdk.capture_message(f"Graph generation skipped: No data for last "
                                       f"{hours}h",level='warning')
            return {"error": "No data available for the selected time range"}


        metric_list: List[str] = [m.strip() for m in metrics.split(",")]

        fig = create_performance_plot(data, metric_list, graph_type)

        return fig.to_dict()

    except Exception as e:
        logger.error(f"Graph Generation Failed: {e}", exc_info=True)
        sentry_sdk.capture_exception(
            e,
            extra={
                "graph_type": graph_type,
                "metrics": metrics,
                "hours": hours
            }
        )
        raise HTTPException(status_code=500, detail="Failed to generate system graph")
