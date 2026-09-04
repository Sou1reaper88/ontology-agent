from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from ontology_core.errors import TemporalIntentError
from ontology_core.models import FrozenModel
from ontology_core.normalization import normalize_text
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain

_XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"
_UNBOUNDED = ("全部历史", "不限时间", "不限制账期", "全量数据")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_COMPACT_DAY = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
_MONTH_RANGE = re.compile(
    r"(?P<sy>\d{4})年(?P<sm>1[0-2]|0?[1-9])月(?:至|到)"
    r"(?:(?P<ey>\d{4})年)?(?P<em>1[0-2]|0?[1-9])月"
)
_DAY_RANGE = re.compile(r"(?P<start>\d{4}-\d{2}-\d{2})(?:至|到)(?P<end>\d{4}-\d{2}-\d{2})")
_FULL_MONTH = re.compile(r"(?P<year>\d{4})年(?P<month>1[0-2]|0?[1-9])月")
_COMPACT_MONTH = re.compile(r"(?<!\d)(?P<year>\d{4})(?P<month>0[1-9]|1[0-2])(?!\d)")
_DASHED_MONTH = re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])(?!-?\d)")
_YEARLESS_MONTH = re.compile(r"(?<![\d年])(?P<month>1[0-2]|0?[1-9])月")
_CHINESE_DAY = re.compile(
    r"(?P<year>\d{4})年(?P<month>1[0-2]|0?[1-9])月(?P<day>3[01]|[12]\d|0?[1-9])日"
)
_RECENT = re.compile(r"最近(?P<count>[1-9]\d*)个?(?:月|账期)")
_ADJACENT_FILLER = re.compile(r"^[，,、\s]*(?:为|在|是|按)?[，,、\s]*$")


class TemporalIntentSource(StrEnum):
    EXPLICIT_ABSOLUTE = "explicit_absolute"
    EXPLICIT_RELATIVE = "explicit_relative"
    ONTOLOGY_DEFAULT = "ontology_default"


class TemporalTarget(FrozenModel):
    property_uri: str
    aliases: tuple[str, ...]
    datatype_uri: str


class TemporalIntent(FrozenModel):
    target_property_uri: str
    start: str
    end: str
    source: TemporalIntentSource
    matched_text: str | None = None
    explanation: str


class TemporalParseResult(FrozenModel):
    partition: TemporalIntent
    property_intents: tuple[TemporalIntent, ...] = ()


@dataclass(frozen=True)
class _Token:
    start_index: int
    end_index: int
    start: str
    end: str
    source: TemporalIntentSource
    matched_text: str


def _error(message: str, reason: str) -> TemporalIntentError:
    return TemporalIntentError(message, details={"reason": reason})


def parse_system_date(value: str | None, *, today: date | None = None) -> date:
    if value is None:
        return today or date.today()
    if not _ISO_DATE.fullmatch(value):
        raise _error("系统时间格式无效", "invalid_system_time")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _error("系统时间格式无效", "invalid_system_time") from exc


def _month_value(year: int, month: int) -> str:
    date(year, month, 1)
    return f"{year:04d}{month:02d}"


def _shift_month(base: date, offset: int) -> tuple[int, int]:
    index = base.year * 12 + base.month - 1 + offset
    return divmod(index, 12)[0], divmod(index, 12)[1] + 1


def _month_from_value(value: str) -> tuple[int, int]:
    return int(value[:4]), int(value[4:6])


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and span[1] > start for start, end in occupied)


def _add_token(
    tokens: list[_Token],
    occupied: list[tuple[int, int]],
    match: re.Match[str],
    start: str,
    end: str,
    source: TemporalIntentSource,
) -> None:
    if _overlaps(match.span(), occupied):
        return
    occupied.append(match.span())
    tokens.append(_Token(*match.span(), start, end, source, match.group(0)))


def _month_tokens(query: str, system_date: date) -> list[_Token]:
    tokens: list[_Token] = []
    occupied: list[tuple[int, int]] = []
    for match in _MONTH_RANGE.finditer(query):
        start = _month_value(int(match["sy"]), int(match["sm"]))
        end = _month_value(int(match["ey"] or match["sy"]), int(match["em"]))
        if start > end:
            raise _error("时间范围起止顺序无效", "invalid_time_range")
        _add_token(tokens, occupied, match, start, end, TemporalIntentSource.EXPLICIT_ABSOLUTE)
    for match in _RECENT.finditer(query):
        count = int(match["count"])
        end_year, end_month = _shift_month(system_date.replace(day=1), -1)
        start_year, start_month = _shift_month(date(end_year, end_month, 1), -(count - 1))
        _add_token(
            tokens,
            occupied,
            match,
            _month_value(start_year, start_month),
            _month_value(end_year, end_month),
            TemporalIntentSource.EXPLICIT_RELATIVE,
        )
    relative = {
        "本月": (system_date.year, system_date.month),
        "上月": _shift_month(system_date.replace(day=1), -1),
    }
    for text, (year, month) in relative.items():
        for match in re.finditer(text, query):
            value = _month_value(year, month)
            _add_token(
                tokens,
                occupied,
                match,
                value,
                value,
                TemporalIntentSource.EXPLICIT_RELATIVE,
            )
    for pattern in (_FULL_MONTH, _COMPACT_MONTH, _DASHED_MONTH):
        for match in pattern.finditer(query):
            value = _month_value(int(match["year"]), int(match["month"]))
            _add_token(
                tokens,
                occupied,
                match,
                value,
                value,
                TemporalIntentSource.EXPLICIT_ABSOLUTE,
            )
    for match in _YEARLESS_MONTH.finditer(query):
        value = _month_value(system_date.year, int(match["month"]))
        _add_token(
            tokens,
            occupied,
            match,
            value,
            value,
            TemporalIntentSource.EXPLICIT_ABSOLUTE,
        )
    return sorted(tokens, key=lambda item: item.start_index)


def _day_tokens(query: str, system_date: date) -> list[_Token]:
    tokens: list[_Token] = []
    occupied: list[tuple[int, int]] = []
    for match in _COMPACT_DAY.finditer(query):
        try:
            value_date = date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError as exc:
            raise _error("日账期格式无效", "invalid_day_period") from exc
        value = value_date.strftime("%Y%m%d")
        _add_token(tokens, occupied, match, value, value, TemporalIntentSource.EXPLICIT_ABSOLUTE)
    for match in _DAY_RANGE.finditer(query):
        start_date = parse_system_date(match["start"])
        end_date = parse_system_date(match["end"])
        if start_date > end_date:
            raise _error("时间范围起止顺序无效", "invalid_time_range")
        _add_token(
            tokens,
            occupied,
            match,
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            TemporalIntentSource.EXPLICIT_ABSOLUTE,
        )
    relative = {
        "今天": system_date,
        "昨天": system_date - timedelta(days=1),
        "前天": system_date - timedelta(days=2),
    }
    for text, value_date in relative.items():
        for match in re.finditer(text, query):
            value = value_date.strftime("%Y%m%d")
            _add_token(
                tokens,
                occupied,
                match,
                value,
                value,
                TemporalIntentSource.EXPLICIT_RELATIVE,
            )
    for match in _CHINESE_DAY.finditer(query):
        value_date = date(int(match["year"]), int(match["month"]), int(match["day"]))
        value = value_date.strftime("%Y%m%d")
        _add_token(
            tokens,
            occupied,
            match,
            value,
            value,
            TemporalIntentSource.EXPLICIT_ABSOLUTE,
        )
    for match in _ISO_DATE.finditer(query):
        value_date = parse_system_date(match.group(0))
        value = value_date.strftime("%Y%m%d")
        _add_token(
            tokens,
            occupied,
            match,
            value,
            value,
            TemporalIntentSource.EXPLICIT_ABSOLUTE,
        )
    return sorted(tokens, key=lambda item: item.start_index)


def _adjacent_target(
    query: str, token: _Token, targets: tuple[TemporalTarget, ...]
) -> TemporalTarget | None:
    normalized_query = normalize_text(query)
    for target in targets:
        for alias in target.aliases:
            normalized_alias = normalize_text(alias)
            if not normalized_alias:
                continue
            for match in re.finditer(re.escape(normalized_alias), normalized_query):
                if match.end() <= token.start_index:
                    gap = normalized_query[match.end() : token.start_index]
                elif token.end_index <= match.start():
                    gap = normalized_query[token.end_index : match.start()]
                else:
                    return target
                if _ADJACENT_FILLER.fullmatch(gap):
                    return target
    return None


def _business_intent(token: _Token, target: TemporalTarget) -> TemporalIntent:
    if target.datatype_uri != _XSD_DATE:
        raise _error("业务日期字段格式未确认", "unsupported_business_date_type")
    if len(token.start) != 6 or len(token.end) != 6:
        raise _error("业务日期粒度暂不支持", "unsupported_business_date_type")
    start_year, start_month = _month_from_value(token.start)
    end_year, end_month = _month_from_value(token.end)
    end_day = calendar.monthrange(end_year, end_month)[1]
    return TemporalIntent(
        target_property_uri=target.property_uri,
        start=f"{start_year:04d}-{start_month:02d}-01",
        end=f"{end_year:04d}-{end_month:02d}-{end_day:02d}",
        source=token.source,
        matched_text=token.matched_text,
        explanation=f"用户指定业务日期 {token.matched_text}",
    )


def _default_partition(
    system_date: date,
    strategy: TemporalDefaultStrategy,
    partition_target: TemporalTarget,
) -> TemporalIntent:
    if strategy is TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH:
        year, month = _shift_month(system_date.replace(day=1), -1)
        value = _month_value(year, month)
        explanation = "用户未指定账期，按本体策略取上一个完整自然月"
    else:
        value = (system_date - timedelta(days=2)).strftime("%Y%m%d")
        explanation = "用户未指定日期，按本体策略取 T-2"
    return TemporalIntent(
        target_property_uri=partition_target.property_uri,
        start=value,
        end=value,
        source=TemporalIntentSource.ONTOLOGY_DEFAULT,
        explanation=explanation,
    )


def parse_temporal_intents(
    query: str,
    *,
    system_date: date,
    grain: TemporalGrain,
    default_strategy: TemporalDefaultStrategy,
    partition_target: TemporalTarget,
    other_targets: tuple[TemporalTarget, ...] = (),
) -> TemporalParseResult:
    normalized_query = normalize_text(query)
    if any(normalize_text(marker) in normalized_query for marker in _UNBOUNDED):
        raise _error("需求未限定时间范围，请明确账期", "unbounded_time")
    expected = {
        TemporalGrain.DAY: TemporalDefaultStrategy.T_MINUS_2,
        TemporalGrain.MONTH: TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
    }
    if expected[grain] is not default_strategy:
        raise _error("时间分区粒度与默认策略不匹配", "invalid_temporal_strategy")

    tokens = (
        _month_tokens(query, system_date)
        if grain is TemporalGrain.MONTH
        else _day_tokens(query, system_date)
    )
    partition_tokens: list[_Token] = []
    property_intents: list[TemporalIntent] = []
    for token in tokens:
        target = _adjacent_target(query, token, other_targets)
        if target is None:
            partition_tokens.append(token)
        else:
            property_intents.append(_business_intent(token, target))

    distinct = {(item.start, item.end) for item in partition_tokens}
    if len(distinct) > 1:
        raise _error("需求中出现多个冲突账期，请确认最终账期", "conflicting_partition_time")
    if partition_tokens:
        token = partition_tokens[0]
        partition = TemporalIntent(
            target_property_uri=partition_target.property_uri,
            start=token.start,
            end=token.end,
            source=token.source,
            matched_text=token.matched_text,
            explanation=f"用户指定时间 {token.matched_text}",
        )
    else:
        partition = _default_partition(system_date, default_strategy, partition_target)
    return TemporalParseResult(
        partition=partition,
        property_intents=tuple(property_intents),
    )
