from __future__ import annotations

from datetime import date

import pytest

from ontology_core.errors import TemporalIntentError
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain
from ontology_core.temporal import (
    TemporalIntentSource,
    TemporalTarget,
    parse_system_date,
    parse_temporal_intents,
)

XSD = "http://www.w3.org/2001/XMLSchema#"
SYSTEM_DATE = date(2026, 8, 24)


def _partition_target() -> TemporalTarget:
    return TemporalTarget(
        property_uri="https://example.invalid/ontology/AccountingMonth",
        aliases=("账期", "数据月份", "时间分区"),
        datatype_uri=f"{XSD}string",
    )


def _parse_month(query: str):
    return parse_temporal_intents(
        query,
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        partition_target=_partition_target(),
    )


def test_parse_system_date_is_strict() -> None:
    assert parse_system_date("2026-08-24") == SYSTEM_DATE
    assert parse_system_date(None, today=SYSTEM_DATE) == SYSTEM_DATE
    with pytest.raises(TemporalIntentError, match="系统时间格式无效"):
        parse_system_date("2026/08/24")


@pytest.mark.parametrize("query", ["查询账期20260820", "P_DAY=20260820"])
def test_compact_day_overrides_default(query: str) -> None:
    parsed = parse_temporal_intents(
        query,
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        partition_target=_partition_target(),
    )
    assert parsed.partition.start == "20260820"
    assert parsed.partition.source == TemporalIntentSource.EXPLICIT_ABSOLUTE


@pytest.mark.parametrize(
    "today,day,month",
    [
        (date(2026, 1, 1), "20251230", "202512"),
        (date(2024, 3, 1), "20240228", "202402"),
        (date(2024, 3, 2), "20240229", "202402"),
    ],
)
def test_default_periods_use_calendar_arithmetic(today, day, month) -> None:
    for grain, strategy, expected in (
        (TemporalGrain.DAY, TemporalDefaultStrategy.T_MINUS_2, day),
        (TemporalGrain.MONTH, TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH, month),
    ):
        result = parse_temporal_intents(
            "查询客户编码",
            system_date=today,
            grain=grain,
            default_strategy=strategy,
            partition_target=_partition_target(),
        )
        assert result.partition.start == expected


def test_default_period_comes_from_the_ontology_strategy() -> None:
    monthly = _parse_month("查询客户编码")
    daily = parse_temporal_intents(
        "查询客户编码",
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        partition_target=TemporalTarget(
            property_uri="https://example.invalid/ontology/PartitionDay",
            aliases=("日期分区",),
            datatype_uri=f"{XSD}string",
        ),
    )

    assert (monthly.partition.start, monthly.partition.end) == ("202607", "202607")
    assert monthly.partition.source is TemporalIntentSource.ONTOLOGY_DEFAULT
    assert (daily.partition.start, daily.partition.end) == ("20260822", "20260822")
    with pytest.raises(TemporalIntentError, match="时间分区粒度与默认策略不匹配"):
        parse_temporal_intents(
            "查询客户编码",
            system_date=SYSTEM_DATE,
            grain=TemporalGrain.MONTH,
            default_strategy=TemporalDefaultStrategy.T_MINUS_2,
            partition_target=_partition_target(),
        )


@pytest.mark.parametrize(
    ("query", "start", "end", "source"),
    [
        ("查询2026年6月数据", "202606", "202606", "explicit_absolute"),
        ("查询202606账期", "202606", "202606", "explicit_absolute"),
        ("查询2026-06数据", "202606", "202606", "explicit_absolute"),
        ("查询6月用户", "202606", "202606", "explicit_absolute"),
        ("查询2026年4月至6月数据", "202604", "202606", "explicit_absolute"),
        ("查询本月数据", "202608", "202608", "explicit_relative"),
        ("查询上月数据", "202607", "202607", "explicit_relative"),
        ("查询最近3个账期", "202605", "202607", "explicit_relative"),
    ],
)
def test_parse_month_intents(query: str, start: str, end: str, source: str) -> None:
    intent = _parse_month(query).partition

    assert (intent.start, intent.end, intent.source.value) == (start, end, source)


@pytest.mark.parametrize(
    ("query", "start", "end"),
    [
        ("查询2026年8月20日数据", "20260820", "20260820"),
        ("查询2026-08-20数据", "20260820", "20260820"),
        ("查询2026-08-20至2026-08-22数据", "20260820", "20260822"),
        ("查询今天数据", "20260824", "20260824"),
        ("查询昨天数据", "20260823", "20260823"),
        ("查询前天数据", "20260822", "20260822"),
    ],
)
def test_parse_day_intents(query: str, start: str, end: str) -> None:
    result = parse_temporal_intents(
        query,
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        partition_target=TemporalTarget(
            property_uri="https://example.invalid/ontology/PartitionDay",
            aliases=("日期分区",),
            datatype_uri=f"{XSD}string",
        ),
    )

    assert (result.partition.start, result.partition.end) == (start, end)


def test_day_partition_expands_one_natural_month_to_full_day_range() -> None:
    result = parse_temporal_intents(
        "查询2026年6月数据",
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        partition_target=TemporalTarget(
            property_uri="https://example.invalid/ontology/PartitionDay",
            aliases=("日期分区",),
            datatype_uri=f"{XSD}string",
        ),
    )

    assert (result.partition.start, result.partition.end) == ("20260601", "20260630")


def test_conflicting_and_unbounded_partition_time_fail_closed() -> None:
    with pytest.raises(TemporalIntentError) as conflict:
        _parse_month("查询2026年5月用户，账期按202606")
    assert conflict.value.details["reason"] == "conflicting_partition_time"

    with pytest.raises(TemporalIntentError) as unbounded:
        _parse_month("查询全部历史用户，不限时间")
    assert unbounded.value.details["reason"] == "unbounded_time"


def test_business_date_and_partition_date_bind_to_different_properties() -> None:
    joined_at = TemporalTarget(
        property_uri="https://example.invalid/ontology/JoinedAt",
        aliases=("入网日期",),
        datatype_uri=f"{XSD}date",
    )

    result = parse_temporal_intents(
        "查询入网日期为2026年6月、账期为202607的用户",
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        partition_target=_partition_target(),
        other_targets=(joined_at,),
    )

    assert (result.partition.start, result.partition.end) == ("202607", "202607")
    assert len(result.property_intents) == 1
    assert result.property_intents[0].target_property_uri == joined_at.property_uri
    assert (result.property_intents[0].start, result.property_intents[0].end) == (
        "2026-06-01",
        "2026-06-30",
    )


def test_unknown_business_date_encoding_is_not_silently_guessed() -> None:
    joined_at = TemporalTarget(
        property_uri="https://example.invalid/ontology/JoinedAt",
        aliases=("入网日期",),
        datatype_uri=f"{XSD}string",
    )

    with pytest.raises(TemporalIntentError) as caught:
        parse_temporal_intents(
            "查询入网日期为2026年6月的用户",
            system_date=SYSTEM_DATE,
            grain=TemporalGrain.MONTH,
            default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
            partition_target=_partition_target(),
            other_targets=(joined_at,),
        )

    assert caught.value.details["reason"] == "unsupported_business_date_type"
