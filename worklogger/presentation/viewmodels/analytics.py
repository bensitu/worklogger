"""Analytics presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from worklogger.app.queries.analytics_queries import GetAnalyticsBundleQuery
from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class AnalyticsBundleHandlerProtocol(Protocol):
    def handle(self, query: GetAnalyticsBundleQuery) -> Result[ChartDataBundle]:
        ...


class AnalyticsCsvExporterProtocol(Protocol):
    def export_bundle(self, destination: Path, bundle: ChartDataBundle) -> Result[Path]:
        ...


class AnalyticsPdfExporterProtocol(Protocol):
    def export_bundle(
        self,
        destination: Path,
        bundle: ChartDataBundle,
        *,
        title: str = "Analytics",
    ) -> Result[Path]:
        ...


@dataclass(frozen=True)
class AnalyticsState:
    user_id: int
    year: int
    month: int
    scope: str
    metric: str
    chart_mode: str
    include_leaves: bool
    bundle: ChartDataBundle


class AnalyticsViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        bundle_handler: AnalyticsBundleHandlerProtocol,
        csv_exporter: AnalyticsCsvExporterProtocol,
        pdf_exporter: AnalyticsPdfExporterProtocol,
        standard_leave_hours: float = 8.0,
    ) -> None:
        self._user_id = user_id
        self._bundle_handler = bundle_handler
        self._csv_exporter = csv_exporter
        self._pdf_exporter = pdf_exporter
        self._standard_leave_hours = standard_leave_hours

    def load(
        self,
        *,
        year: int,
        month: int,
        scope: str = "monthly",
        metric: str = "hours",
        chart_mode: str = "bar",
        include_leaves: bool = True,
    ) -> Result[AnalyticsState]:
        try:
            normalized_scope = _normalize_choice(scope, {"monthly", "quarterly", "annual"}, "scope")
            normalized_metric = _normalize_choice(metric, {"hours", "average"}, "metric")
            normalized_mode = _normalize_choice(chart_mode, {"bar", "line"}, "chart_mode")
            normalized_month = max(1, min(int(month), 12))
            normalized_year = int(year)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        bundle = self._bundle_handler.handle(
            GetAnalyticsBundleQuery(
                user_id=self._user_id,
                year=normalized_year,
                month=normalized_month if normalized_scope == "monthly" else None,
                metric=normalized_metric,
                include_leaves=include_leaves,
                scope=normalized_scope,
                standard_leave_hours=self._standard_leave_hours,
            )
        )
        if not bundle.ok or bundle.value is None:
            return Result.failure(bundle.error or _validation("analytics_load_failed"))
        return Result.success(
            AnalyticsState(
                user_id=self._user_id,
                year=normalized_year,
                month=normalized_month,
                scope=normalized_scope,
                metric=normalized_metric,
                chart_mode=normalized_mode,
                include_leaves=include_leaves,
                bundle=bundle.value,
            )
        )

    def export_csv(self, destination: Path, state: AnalyticsState) -> Result[Path]:
        return self._csv_exporter.export_bundle(destination, state.bundle)

    def export_pdf(self, destination: Path, state: AnalyticsState) -> Result[Path]:
        return self._pdf_exporter.export_bundle(
            destination,
            state.bundle,
            title=_title(state),
        )


def _normalize_choice(value: str, allowed: set[str], name: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"analytics_{name}_invalid")
    return normalized


def _title(state: AnalyticsState) -> str:
    if state.scope == "monthly":
        return f"Analytics {state.year}-{state.month:02d}"
    return f"Analytics {state.year} {state.scope}"


def _validation(code: str) -> ValidationError:
    return ValidationError(code, code)

