"""Deterministic SQL evaluation primitives."""

from evaluation.comparison import compare_sql_structures, summarize_candidate_results
from evaluation.contracts import ImportedCase, JoinSignature, PredicateSignature, SqlStructure
from evaluation.importer import build_evaluation_template, import_evaluation_workbook
from evaluation.sql_structure import extract_sql_structure

__all__ = [
    "ImportedCase",
    "JoinSignature",
    "PredicateSignature",
    "SqlStructure",
    "build_evaluation_template",
    "compare_sql_structures",
    "extract_sql_structure",
    "import_evaluation_workbook",
    "summarize_candidate_results",
]
