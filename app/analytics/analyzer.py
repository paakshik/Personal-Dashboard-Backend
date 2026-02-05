import numpy as np
from datetime import datetime
from app.utils.helpers import (
    determine_trend,
    get_disk_analysis,
)
from typing import Dict, Any ,List
from app.config import logger, sentry_sdk
from collections import  defaultdict

class SystemAnalyzer:
    """
        Analyze system metrics and generate valuable insights.

        This class acts as a facade (Black Box) that orchestrates
        various internal analysis methods.
        """

    def generate_insights(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Orchestrates the generation of all system insights.

        This method validates the input data and calls internal helper methods
        to produce a comprehensive report. Catches and reports unexpected
        errors to Sentry.

        Args:
            data (Dict[str, Any]): Raw system metrics data (e.g., CPU, memory, requests).
                                   Can be None.

        Returns:
            Dict[str, Any]: A dictionary containing the analysis results (summary,
                            anomalies, trends, etc.) or an error object if generation fails.
        """
        # VALIDATION: Early exit if data is missing
        if not data:
            logger.warning("Insight generation aborted: No input data provided.")
            return {"error": "Insight generation aborted: No input data provided.", "status": "failed"}

        try:
            logger.debug(f"Processing data payload with keys: {list(data.keys())}")

            insights = {
                "summary": self._generate_summary([data]),
                "anomalies": self._detect_anomalies([data]),
                "trends": self._analyze_trends([data]),
                "recommendations": self._generate_recommendations([data]),
                "performance_score": self._calculate_performance_score([data])
            }

            return insights

        except Exception as e:
            sentry_sdk.capture_exception(e)
            logger.error(f"Critical failure in generate_insights: {str(e)}",
                         exc_info=True)
            return {
                "error": "Internal processing error",
                "status": "error"
            }

    @staticmethod
    def _generate_summary(data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate statistical summary of system metrics using NumPy.

        Calculates aggregates (mean, max, std dev) for CPU, Memory, and Disk usage
        over the provided time period.

        Args:
            data [dict[str, Any]]: A list of time-series data points.
                                         Expected keys: 'timestamp', 'cpu', 'memory', 'disk'.

        Returns:
            dict[str, Any]: A nested dictionary containing statistical summaries.
                            Returns an empty dict if input data is empty or malformed.
        """
        # VALIDATION: Quick exit for empty data
        if not data:
            logger.debug("Skipping summary generation: No data provided.")
            return {}

        # SENTRY: Start a performance span to track how long this math takes
        with sentry_sdk.start_span(op="data_processing",
                                   description="generate_summary_stats"):
            try:
                logger.debug(f"Generating summary for {len(data)} data points.")

                # EXTRACT: Pulling raw lists for Vectorized operations
                # Note: We assume the data structure is validated before reaching here,
                # but a KeyError here would be caught by the block below.
                timestamps = [datetime.fromisoformat(d["timestamp"]) for d in data]
                cpu_values = [d["cpu"]["percent"] for d in data]
                memory_values = [d["memory"]["percent"] for d in data]
                disk_values: list[float] = [d["disk"]["percent"] for d in data]

                # LOGIC: Calculate detailed stats
                summary = {
                    "time_period": {
                        "start": timestamps[0].isoformat(),
                        "end": timestamps[-1].isoformat(),
                        "duration_hours": round(
                            (timestamps[-1] - timestamps[0]).total_seconds() / 3600, 2
                        )
                    },
                    "cpu": {
                        "mean": round(float(np.mean(cpu_values)), 2),
                        "max": round(float(np.max(cpu_values)), 2),
                        "min": round(float(np.min(cpu_values)), 2),
                        "std": round(float(np.std(cpu_values)), 2),
                        "high_usage_percentage": round(
                            sum(1 for v in cpu_values if v > 80) / len(
                                cpu_values) * 100, 1
                        )
                    },
                    "memory": {
                        "mean": round(float(np.mean(memory_values)), 2),
                        "max": round(float(np.max(memory_values)), 2),
                        "min": round(float(np.min(memory_values)), 2),
                        "high_usage_percentage": round(
                            sum(1 for v in memory_values if v > 85) / len(
                                memory_values) * 100, 1
                        )
                    },
                    "disk": {
                        "current": disk_values[-1],
                        "first_value": disk_values[0],
                        "change": round(disk_values[-1] - disk_values[0], 2),
                        # Assuming these helper functions exist in your scope
                        "trend": determine_trend(disk_values),
                        "analysis": get_disk_analysis(disk_values)
                    }
                }

                logger.info("Summary statistics generated successfully.")
                return summary

            except KeyError as e:
                sentry_sdk.add_breadcrumb(
                    category="data_error",
                    message=f"Missing key in data stream: {str(e)}",
                    level="error"
                )
                logger.error(f"Malformed data structure in _generate_summary: {e}")
                # Return empty dict so the main process continues without this specific section
                return {}

            except Exception as e:
                logger.error(f"Calculation error in _generate_summary: {e}",
                             exc_info=True)
                raise e

    @staticmethod
    def _detect_anomalies(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Detect unusual patterns or spikes in system metrics.

        Uses statistical thresholds (Mean + 2 Standard Deviations) to identify
        outliers in CPU usage, and fixed thresholds for Memory pressure.

        Args:
            data (list[dict[str, Any]]): List of metric data points.

        Returns:
            list[dict[str, Any]]: A list of detected anomaly objects. Returns empty list
                                  if no anomalies are found or data is insufficient.
        """
        if not data:
            logger.debug("Skipping anomaly detection: No data provided.")
            return []

        anomalies = []

        # SENTRY: Start a span to track the performance of this specific algorithm
        with sentry_sdk.start_span(op="analysis", description="detect_anomalies_logic"):
            try:
                # Extract vectors for analysis
                cpu_values = [d["cpu"]["percent"] for d in data]
                memory_values = [d["memory"]["percent"] for d in data]

                # 1. Detect CPU Spikes (Dynamic Thresholding)
                # Logic: Anything above (Mean + 2 * StdDev) is considered an anomaly
                cpu_mean = np.mean(cpu_values)
                cpu_std = np.std(cpu_values)
                cpu_threshold = cpu_mean + (2 * cpu_std)

                logger.debug(
                    f"Anomaly Detection: Calculated CPU threshold at {cpu_threshold:.2f}%")

                for i, value in enumerate(cpu_values):
                    if value > cpu_threshold:
                        anomalies.append({
                            "type": "cpu_spike",
                            "timestamp": data[i]["timestamp"],
                            "value": value,
                            "details": f"Value {value}% exceeded threshold {cpu_threshold:.1f}%",
                            "severity": "high" if value > 90 else "medium"
                        })

                # 2. Detect Memory Pressure (Static Thresholding)
                for i, value in enumerate(memory_values):
                    if value > 90:
                        anomalies.append({
                            "type": "memory_pressure",
                            "timestamp": data[i]["timestamp"],
                            "value": value,
                            "severity": "high"
                        })

                # LOGGING & SENTRY: Report findings
                if anomalies:
                    logger.warning(f"Detected {len(anomalies)} system anomalies.")

                    # BREADCRUMB: Leave a trail that we found issues here
                    sentry_sdk.add_breadcrumb(
                        category="analysis",
                        message=f"Found {len(anomalies)} anomalies (CPU/Mem)",
                        level="warning",
                        data={"first_anomaly_type": anomalies[0]["type"]}
                    )
                else:
                    logger.info("No anomalies detected.")

                return anomalies

            except KeyError as e:
                logger.error(f"Data structure mismatch in anomaly detection: {e}")
                sentry_sdk.capture_exception(e)
                return []

            except Exception as e:
                logger.error(f"Unexpected error in anomaly detection: {e}",
                             exc_info=True)
                sentry_sdk.capture_exception(e)
                return []

    @staticmethod
    def _analyze_trends(data: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Analyze trends over time using Linear Regression.

        Calculates the slope of CPU usage to determine if usage is increasing,
        decreasing, or stable. Identifies peak usage hours.

        Args:
            data (list[dict[str, Any]]): Time-series data list.

        Returns:
            dict[str, Any]: Trend analysis results. Returns specific 'unknown'
                            states if data is insufficient (< 10 records).
        """
        if not data or len(data) < 10:
            logger.info(
                f"Trend analysis skipped: Insufficient data ({len(data)} records).")

            return {
            "cpu_trend": "insufficient_data",
            "peak_usage_hour": None,
            "slope_value": 0.0,
            "avg_hourly_usage": {},
            "status": "skipped"
        }

        # SENTRY: Track performance of regression math
        with sentry_sdk.start_span(op="analysis",
                                   description="analyze_trends_linear_regression"):
            try:
                # 1. Prepare vectors
                cpu_values = [d["cpu"]["percent"] for d in data]
                x_axis = np.arange(len(cpu_values))

                # 2. Linear Regression (Calculate Slope)
                # polyfit(x, y, 1) fits a line (y = mx + b). We want 'm' (slope).
                slope = np.polyfit(x_axis, cpu_values, 1)[0]

                # Determine direction based on slope steepness
                match slope:
                    case x if x > 0.1:
                        trend = "increasing"
                    case x if x < -0.1:
                        trend = "decreasing"
                    case _:
                        trend = "stable"

                logger.debug(f"Trend Analysis: Slope={slope:.4f}, Verdict={trend}")

                # 3. Calculate Peak Usage Hours
                # Using defaultdict to group values by hour: {10: [50, 55], 11: [60, ...]}
                hourly_usage = defaultdict(list)
                for d in data:
                    try:
                        dt = datetime.fromisoformat(d["timestamp"])
                        hourly_usage[dt.hour].append(d["cpu"]["percent"])
                    except ValueError:
                        continue  # Skip malformed timestamps

                # Average the buckets
                avg_hourly_usage = {
                    hour: round(float(np.mean(vals)), 2)
                    for hour, vals in hourly_usage.items() if vals
                }

                # Find the hour with the highest average
                peak_hour = max(avg_hourly_usage,
                                key=avg_hourly_usage.get) if avg_hourly_usage else None

                return {
                    "cpu_trend": trend,
                    "peak_usage_hour": peak_hour,
                    "slope_value": round(float(slope), 4),
                    "avg_hourly_usage": avg_hourly_usage,
                    "status": "success",
                    # "periodic_patterns": self._detect_periodic_patterns(cpu_values) # keeping your placeholder
                }

            except Exception as e:
                logger.error(f"Math error in trend analysis: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)
                return {
                    "cpu_trend": trend,
                    "peak_usage_hour": peak_hour,
                    "slope_value": round(float(slope), 4),
                    "avg_hourly_usage": avg_hourly_usage,
                    "status": "error",
                    # "periodic_patterns": self._detect_periodic_patterns(cpu_values) # keeping your placeholder
                }

    @staticmethod
    def _detect_periodic_patterns(values):
    # change the code as  this  is just placeholder
        if len(values) < 50:
            return "insufficient_data"

        # Check for daily patterns (assuming data is ~2 second intervals)
        daily_period = 12 * 60 * 60 / 2  # 12 hours in data points

        return {
            "has_daily_pattern": len(values) > daily_period,
            "suggestion": "More data needed for accurate period detection"
        }

    @staticmethod
    def _generate_recommendations(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Generate actionable recommendations based on resource usage.

        Analyzes CPU, Memory, and Disk usage trends to suggest optimizations
        or warnings using static thresholds.

        Args:
            data (list[dict[str, Any]]): Time-series data list.

        Returns:
            list[dict[str, Any]]: List of recommendation dictionaries.
        """

        if not data:
            logger.warning("Recommendation generation skipped: No data available.")
            return [{
                "category": "system",
                "priority": "info",
                "message": "Collecting data... No recommendations yet.",
                "status": "initializing"
            }]

        recommendations = []

        with sentry_sdk.start_span(op="analysis",
                                   description="generate_recommendations_logic"):
            try:
                cpu_values = [d["cpu"]["percent"] for d in data]
                memory_values = [d["memory"]["percent"] for d in data]

                # --- 1. CPU Analysis ---
                avg_cpu = np.mean(cpu_values)

                match avg_cpu:
                    case x if x > 80:
                        recommendations.append({
                            "category": "cpu",
                            "priority": "high",
                            "message": "Critical CPU usage detected. Review active processes.",
                            "avg_usage": f"{x:.1f}%"
                        })
                    case x if x > 50:
                        recommendations.append({
                            "category": "cpu",
                            "priority": "medium",
                            "message": "CPU is running warm. Monitor for heavier loads.",
                            "avg_usage": f"{x:.1f}%"
                        })


                # --- 2. Memory Analysis (Match Case) ---
                max_mem = max(memory_values)

                match max_mem:
                    case x if x > 90:
                        recommendations.append({
                            "category": "memory",
                            "priority": "high",
                            "message": "Memory reached critical levels. Risk of OOM crash.",
                            "max_usage": f"{x:.1f}%"
                        })


                # If no above condition is detected
                if not recommendations:
                    recommendations.append({
                        "category": "general",
                        "priority": "low",
                        "message": "System performance is optimal.",
                        "status": "healthy"
                    })

                logger.debug(f"Generated {len(recommendations)} recommendations.")
                return recommendations

            except Exception as e:
                logger.error(f"Error generating recommendations: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)
                return [{
                    "category": "system",
                    "priority": "error",
                    "message": "Could not analyze system health.",
                    "status": "error"
                }]

    @staticmethod
    def _calculate_performance_score(data: list[dict[str, Any]]) -> float:
        """
        Calculate a composite System Health Score (0-100).

        Uses a weighted average of CPU and Memory usage:
        - Higher Score = Better Health (Lower Usage)
        - CPU is weighted higher (60%) as it impacts responsiveness more.

        Args:
            data (list[dict[str, Any]]): Time-series data list.

        Returns:
            float: A score between 0.0 (Critical) and 100.0 (Perfect).
        """

        if not data:
            logger.warning("No data provided.")
            return 100.0  # Default to perfect health if just starting

        with sentry_sdk.start_span(op="analysis", description="calculate_health_score"):
            try:
                # Look at recent history only (last 50 data points)
                recent_data = data[-50:]

                cpu_values = [d["cpu"]["percent"] for d in recent_data]
                memory_values = [d["memory"]["percent"] for d in recent_data]

                if not cpu_values or not memory_values:
                    return 100.0

                # 1. Calculate Averages
                avg_cpu = np.mean(cpu_values)
                avg_memory = np.mean(memory_values)

                # 2. Invert the logic (High Usage = Low Score)
                # The '0.8' factor ensures even 100% usage doesn't drop score to 0 immediately
                # (100 - 100*0.8 = 20 score). This prevents panic at full load.
                cpu_score = max(0, 100 - int(avg_cpu * 0.8))
                memory_score = max(0, 100 - int(avg_memory * 0.8))

                # 3. Weighted Average
                final_score = (cpu_score * 0.6) + (memory_score * 0.4)
                logger.debug(f"Health Score Calculated: {final_score:.1f}")
                return round(final_score, 1)

            except Exception as e:
                logger.error(f"Error calculating score: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)
                return 0.0