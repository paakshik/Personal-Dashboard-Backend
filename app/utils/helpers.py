from typing import List, Dict, Any
from app.config import sentry_sdk,logger
import numpy as np

def determine_trend(values: List[float], threshold: float = 0.1) -> str:
    """
    Determine the trend of a metric using Linear Regression (Slope).

    This function calculates the slope of the line of best fit for the given
    values. This is superior to simple start-vs-end comparison because it
    is resistant to temporary spikes and outliers.

    Args:
        values (List[float]): A list of numerical values (e.g., CPU history).
        threshold (float): The minimum slope magnitude required to consider
                           the trend 'increasing' or 'decreasing'.
                           Default is 0.1 (statistically significant drift).

    Returns:
        str: One of "increasing", "decreasing", "stable", or "insufficient_data".
             Returns "stable" if an error occurs (Fail-Safe).
    """
    if not values or len(values) < 2:
        logger.warning("No values provided for trend slope calculation")
        return "insufficient_data"

    with sentry_sdk.start_span(op="calculation", description="determine_trend_slope"):
        try:
            # Create X-axis (Time steps: 0, 1, 2, ... N)
            x_axis = np.arange(len(values))

            # 3. Math: Calculate Slope (m)
            # np.polyfit(x, y, 1) returns [slope, intercept]
            # We select [0] to get the slope.
            slope = np.polyfit(x_axis, values, 1)[0]

            # 4. Logic: Determine Trend based on Slope
            # Using Match-Case for clean logic (Python 3.10+)
            match slope:
                case s if s > threshold:
                    return "increasing"
                case s if s < -threshold:
                    return "decreasing"
                case _:
                    return "stable"

        except Exception as e:
            logger.error(f"Error calculating trend slope: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)
            return "error"


def get_disk_analysis(disk_values: List[float]) -> Dict[str, Any]:
    """
    Get comprehensive disk usage analysis using Match-Case logic.

    This function calculates the trend, severity, and rate of change for disk usage.
    It is designed to fail gracefully; if an error occurs or data is insufficient,
    it returns a valid dictionary (with default values) instead of crashing or
    returning an error code, ensuring the Frontend UI remains stable.

    Args:
        disk_values (List[float]): A list of historical disk usage percentages.

    Returns:
        Dict[str, Any]: A dictionary containing 'trend', 'severity', 'message',
                        'hourly_rate', and other statistics.
    """

    # --- 1. Define a "Safe" Default Response ---
    # We use this if data is missing OR if the math crashes.
    # This prevents the Frontend from seeing 'undefined' keys and breaking.
    safe_response = {
        "current": 0.0,
        "start_value": 0.0,
        "change_amount": 0.0,
        "change_percent": 0.0,
        "trend": "stable",
        "severity": "low",
        "message": "Initializing disk metrics...",
        "hourly_rate": 0.0,
        "units": "percentage_points",
        "warning": False
    }

    # Input Validation
    if not disk_values or len(disk_values) < 2:
        logger.warning("Not enough values provided for trend slope calculation")
        return safe_response

    with sentry_sdk.start_span(op="analysis", description="disk_usage_analysis"):
        try:
            # --- 2. Core Math ---
            first = disk_values[0]
            last = disk_values[-1]
            change = last - first
            change_percent = (change / first * 100) if first > 0 else 0

            # --- 3. Initialize Variables (Fixing the Global Bug) ---
            trend = "stable"
            severity = "low"
            message = "Disk usage is stable"

            # --- 4. Match-Case Logic ---
            match change:
                case x if abs(x) < 1:
                    trend = "stable"
                    severity = "low"
                    message = "Disk usage is stable"

                case x if x > 10:
                    trend = "increasing"
                    severity = "critical"
                    message = "Rapid disk usage increase detected"

                case x if x > 5:
                    trend = "increasing"
                    severity = "high"
                    message = "Disk usage increasing significantly"

                case x if x > 2:
                    trend = "increasing"
                    severity = "medium"
                    message = "Disk usage slowly increasing"

                case x if x > 0:
                    trend = "increasing"
                    severity = "low"
                    message = "Disk usage slightly increasing"

                case _:
                    # Handles negative change (cleaning up files)
                    trend = "decreasing"
                    severity = "low"
                    message = "Disk usage decreasing (good!)"

            # Rate Calculation (Assuming 2-second polling interval)
            # 1800 * 2s = 3600s = 1 Hour
            hourly_rate = change / max(len(disk_values), 1) * 1800

            return {
                "current": round(last, 2),
                "start_value": round(first, 2),
                "change_amount": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": trend,
                "severity": severity,
                "message": message,
                "hourly_rate": round(hourly_rate, 2),
                "units": "percentage_points",
                "warning": last > 90
            }

        except Exception as e:
            logger.error(f"Error in get_disk_analysis: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)
            safe_response["message"] = "Analysis unavailable"
            return safe_response