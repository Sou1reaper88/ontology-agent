from __future__ import annotations

import zipfile
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

import ontology_core.management.parsers as parsers
from ontology_core.management.models import UploadLimits
from ontology_core.management.parsers import UnsafeUploadError, parse_metadata_upload

LIMITS = UploadLimits(max_upload_bytes=1_000_000, max_xlsx_uncompressed_bytes=100_000)
THREE_OBJECTS_TSV = (
    "对象英文名称\t对象中文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述\t是否主键\t是否标题\n"
    "DEMO_ACCOUNT_M\t账户月表\t账户快照\tACCOUNT_ID\t账户编码\tbigint\t账户稳定编码\t是\t是\n"
    "DEMO_CUSTOMER_M\t客户月表\t客户快照\tCUSTOMER_ID\t客户编码\tbigint\t客户稳定编码\t是\t是\n"
    "DEMO_ORDER_D\t订单日表\t订单流水\tORDER_ID\t订单编码\tbigint\t订单稳定编码\t是\t是\n"
    "demo_account_m\t\t\tOPEN_DATE\t开户日期\tdate\t开户日期\t\t\n"
    "DEMO_CUSTOMER_M\t\t\tCUSTOMER_NAME\t客户名称\tstring\t客户显示名称\t\t是\n"
    "DEMO_ORDER_D\t\t\tCUSTOMER_ID\t客户编码\tbigint\t下单客户编码\t\t\n"
    "DEMO_ACCOUNT_M\t\t\tBALANCE\t账户余额\tdecimal\t日终余额\t\t\n"
    "DEMO_ORDER_D\t\t\tORDER_AMOUNT\t订单金额\tdecimal\t订单金额\t\t\n"
)


def synthetic_xlsx(*sheets: tuple[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets:
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    return content.getvalue()


def synthetic_xlsx_with_member(name: str, data: bytes) -> bytes:
    archive_name = name.replace("\\", "/")
    payload = synthetic_xlsx(
        (
            "对象",
            [
                ["对象英文名称", "属性英文名"],
                ["DEMO_OBJECT", "OBJECT_ID"],
            ],
        )
    )
    output = BytesIO()
    with ZipFile(BytesIO(payload)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr(archive_name, data)
    content = output.getvalue()
    if archive_name == name:
        return content
    return content.replace(archive_name.encode(), name.encode())


def synthetic_xlsx_with_encrypted_member() -> bytes:
    payload = bytearray(synthetic_xlsx_with_member("encrypted.xml", b"secret"))
    central_directory = payload.rfind(b"PK\x01\x02")
    assert central_directory >= 0
    flags_offset = central_directory + 8
    flags = int.from_bytes(payload[flags_offset : flags_offset + 2], "little")
    payload[flags_offset : flags_offset + 2] = (flags | 0x1).to_bytes(2, "little")
    return bytes(payload)


def test_tsv_parser_groups_three_objects_atomically() -> None:
    parsed = parse_metadata_upload("objects.tsv", THREE_OBJECTS_TSV.encode("utf-8"), LIMITS)

    assert [item.physical_name for item in parsed.objects] == [
        "DEMO_ACCOUNT_M",
        "DEMO_CUSTOMER_M",
        "DEMO_ORDER_D",
    ]
    assert [item.id for item in parsed.objects] == [
        "object/demo_account_m",
        "object/demo_customer_m",
        "object/demo_order_d",
    ]
    assert sum(len(item.fields) for item in parsed.objects) == 8
    assert parsed.objects[0].fields[1].id == "field/demo_account_m/open_date"
    assert parsed.objects[0].fields[1].physical_name == "OPEN_DATE"
    assert parsed.objects[0].fields[1].description == "开户日期"
    assert not any(item.code == "multiple_objects" for item in parsed.diagnostics)


def test_tsv_parser_preserves_source_row_locations_in_diagnostics() -> None:
    payload = (
        "对象英文名称\t属性英文名\n" "DEMO_ACCOUNT_M\tBAD-NAME\n" "DEMO_CUSTOMER_M\tCUSTOMER_ID\n"
    ).encode()

    parsed = parse_metadata_upload("objects.tsv", payload, LIMITS)

    diagnostic = next(
        item for item in parsed.diagnostics if item.code == "invalid_field_identifier"
    )
    assert "objects.tsv 第 2 行，列“属性英文名”" in diagnostic.message
    assert diagnostic.related_ids == ("object/demo_account_m", "field/demo_account_m/bad-name")


def test_tsv_parser_keeps_missing_object_name_as_a_global_diagnostic() -> None:
    payload = (
        "对象英文名称\t属性英文名\n" "\tORPHAN_FIELD\n" "DEMO_ACCOUNT_M\tACCOUNT_ID\n"
    ).encode()

    parsed = parse_metadata_upload("objects.tsv", payload, LIMITS)

    diagnostic = next(item for item in parsed.diagnostics if item.code == "missing_table_name")
    assert "objects.tsv 第 2 行，列“对象英文名称”" in diagnostic.message
    assert diagnostic.related_ids == ()


def test_tsv_parser_rejects_invalid_utf8_and_oversized_content() -> None:
    with pytest.raises(UnsafeUploadError, match="UTF-8"):
        parse_metadata_upload("objects.tsv", b"\xff", LIMITS)
    with pytest.raises(UnsafeUploadError, match="为空或超过大小限制"):
        parse_metadata_upload("objects.tsv", b"x" * (LIMITS.max_upload_bytes + 1), LIMITS)


def test_xlsx_parser_groups_sheets_and_interleaved_objects_with_data_only_values() -> None:
    payload = synthetic_xlsx(
        (
            "账户与客户",
            [
                ["无关列", "对象英文名称", "属性英文名", "属性类型"],
                ["=1+1", "DEMO_ACCOUNT_M", "ACCOUNT_ID", "bigint"],
                ["=1+1", "DEMO_CUSTOMER_M", "CUSTOMER_ID", "bigint"],
                ["=1+1", "DEMO_ACCOUNT_M", "BALANCE", '=CONCAT("de", "cimal")'],
            ],
        ),
        (
            "订单",
            [
                ["对象英文名称", "属性英文名", "属性类型"],
                ["DEMO_ORDER_D", "ORDER_ID", "bigint"],
                ["DEMO_ACCOUNT_M", "ACCOUNT_STATUS", "string"],
                ["DEMO_ORDER_D", "ORDER_AMOUNT", "decimal"],
            ],
        ),
    )

    parsed = parse_metadata_upload("objects.xlsx", payload, LIMITS)

    assert [item.physical_name for item in parsed.objects] == [
        "DEMO_ACCOUNT_M",
        "DEMO_CUSTOMER_M",
        "DEMO_ORDER_D",
    ]
    assert [field.physical_name for field in parsed.objects[0].fields] == [
        "ACCOUNT_ID",
        "BALANCE",
        "ACCOUNT_STATUS",
    ]
    assert not any(item.code == "unknown_field_type" for item in parsed.diagnostics)


def test_xlsx_rejects_external_links_before_workbook_load(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = synthetic_xlsx_with_member("xl/externalLinks/externalLink1.xml", b"<externalLink/>")
    monkeypatch.setattr(
        parsers, "load_workbook", lambda *args, **kwargs: pytest.fail("已加载工作簿")
    )

    with pytest.raises(UnsafeUploadError, match="外部链接"):
        parse_metadata_upload("objects.xlsx", payload, LIMITS)


@pytest.mark.parametrize(
    ("member", "message"),
    [
        (r"..\evil.xml", "不安全"),
        (r"xl\externalLinks\externalLink1.xml", "外部链接"),
        (r"xl\vbaProject.bin", "宏"),
        (r"C:\evil.xml", "不安全"),
        ("/evil.xml", "不安全"),
        ("./evil.xml", "不安全"),
        ("nested/../evil.xml", "不安全"),
    ],
    ids=[
        "backslash-traversal",
        "backslash-external-link",
        "backslash-macro",
        "drive",
        "absolute",
        "dot",
        "nested-traversal",
    ],
)
def test_xlsx_rejects_unsafe_backslash_or_dot_member_before_workbook_load(
    monkeypatch: pytest.MonkeyPatch,
    member: str,
    message: str,
) -> None:
    if "\\" in member:
        monkeypatch.setattr(zipfile.os, "sep", "/")
    monkeypatch.setattr(
        parsers, "load_workbook", lambda *args, **kwargs: pytest.fail("已加载工作簿")
    )

    with pytest.raises(UnsafeUploadError, match=message):
        parse_metadata_upload("objects.xlsx", synthetic_xlsx_with_member(member, b"unsafe"), LIMITS)


@pytest.mark.parametrize(
    ("member", "data", "message"),
    [
        ("xl/vbaProject.bin", b"macro", "宏"),
        ("large.xml", b"x" * (LIMITS.max_xlsx_uncompressed_bytes + 1), "解压后"),
        ("compressed.xml", b"x" * 20_000, "压缩比"),
    ],
    ids=["macro", "expanded-size", "compression-ratio"],
)
def test_xlsx_rejects_hostile_archive_members(member: str, data: bytes, message: str) -> None:
    with pytest.raises(UnsafeUploadError, match=message):
        parse_metadata_upload("objects.xlsx", synthetic_xlsx_with_member(member, data), LIMITS)


def test_xlsx_rejects_encrypted_member_before_workbook_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        parsers, "load_workbook", lambda *args, **kwargs: pytest.fail("已加载工作簿")
    )

    with pytest.raises(UnsafeUploadError, match="加密"):
        parse_metadata_upload("objects.xlsx", synthetic_xlsx_with_encrypted_member(), LIMITS)


def test_xlsm_is_rejected_even_when_payload_is_a_valid_xlsx() -> None:
    payload = synthetic_xlsx(
        (
            "对象",
            [["对象英文名称", "属性英文名"], ["DEMO_OBJECT", "OBJECT_ID"]],
        )
    )

    with pytest.raises(UnsafeUploadError, match="仅支持"):
        parse_metadata_upload("objects.xlsm", payload, LIMITS)


def test_tsv_duplicate_fields_return_diagnostic_without_model_validation_error() -> None:
    payload = (
        "对象英文名称\t属性英文名\t属性描述\n"
        "DEMO_ACCOUNT_M\tACCOUNT_ID\t账户编码\n"
        "DEMO_ACCOUNT_M\taccount_id\t账户编码副本\n"
    ).encode()

    parsed = parse_metadata_upload("objects.tsv", payload, LIMITS)

    assert [field.physical_name for field in parsed.objects[0].fields] == ["ACCOUNT_ID"]
    diagnostic = next(item for item in parsed.diagnostics if item.code == "duplicate_field")
    assert "objects.tsv 第 3 行，列“属性英文名”" in diagnostic.message
    assert diagnostic.related_ids == ("object/demo_account_m", "field/demo_account_m/account_id")


def test_xlsx_duplicate_fields_return_diagnostic_without_model_validation_error() -> None:
    payload = synthetic_xlsx(
        (
            "对象",
            [
                ["对象英文名称", "属性英文名", "属性描述"],
                ["DEMO_ACCOUNT_M", "ACCOUNT_ID", "账户编码"],
                ["DEMO_ACCOUNT_M", "account_id", "账户编码副本"],
            ],
        )
    )

    parsed = parse_metadata_upload("objects.xlsx", payload, LIMITS)

    assert [field.physical_name for field in parsed.objects[0].fields] == ["ACCOUNT_ID"]
    diagnostic = next(item for item in parsed.diagnostics if item.code == "duplicate_field")
    assert "objects.xlsx:对象 第 3 行，列“属性英文名”" in diagnostic.message
