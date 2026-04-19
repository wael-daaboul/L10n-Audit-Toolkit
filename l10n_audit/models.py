"""
Typed data models for the l10n_audit Python API.

These models define the stable JSON contract returned by :func:`run_audit`.
All models are dataclasses and serialise to / from plain ``dict`` / JSON
so that a downstream web API can pass results directly to a frontend.

Issue Codes
-----------
Each :class:`AuditIssue` carries a machine-readable ``code`` field:

+-------------------------------+--------------------------------------------+
| Code                          | Meaning                                    |
+===============================+============================================+
| MISSING_KEY                   | Key used in code but absent in locale file |
| UNUSED_KEY                    | Key in locale file not found in code       |
| EMPTY_TRANSLATION             | Translation value is empty / whitespace    |
| PLACEHOLDER_MISMATCH          | Placeholder count/names differ             |
| TERMINOLOGY_VIOLATION         | Forbidden term used in translation         |
| ICU_SYNTAX_ERROR              | Invalid ICU message format                 |
| GRAMMAR_ERROR                 | Grammar / spelling issue                   |
| AR_QC                         | Arabic locale quality-control issue        |
| AR_SEMANTIC                   | Arabic semantic / meaning issue            |
| AI_SUGGESTION                 | AI-generated suggested improvement         |
| NEEDS_MANUAL_REVIEW           | Ambiguous item needing human review        |
| DYNAMIC_INFERRED_USAGE        | Key likely used via dynamic expression     |
| MISSING_KEY_AR                | Key present in EN but absent in AR         |
| MISSING_KEY_EN                | Key present in AR but absent in EN         |
| UNKNOWN                       | Unclassified issue                         |
+-------------------------------+--------------------------------------------+
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

VALID_STAGES = frozenset(
    {
        "fast",
        "full",
        "grammar",
        "terminology",
        "placeholders",
        "ar-qc",
        "ar-semantic",
        "icu",
        "reports",
        "autofix",
        "ai-review",
    }
)

# Producers: Stages that generate new audit data 
PRODUCER_STAGES = frozenset({"full", "fast", "grammar", "terminology", "placeholders", "ar-qc", "ar-semantic", "icu"})

# Consumers: Stages that process/transform existing results
CONSUMER_STAGES = frozenset({"ai-review", "reports", "autofix"})

IssueCode = Literal[
    "MISSING_KEY",
    "MISSING_KEY_AR",
    "MISSING_KEY_EN",
    "UNUSED_KEY",
    "EMPTY_TRANSLATION",
    "PLACEHOLDER_MISMATCH",
    "TERMINOLOGY_VIOLATION",
    "ICU_SYNTAX_ERROR",
    "GRAMMAR_ERROR",
    "AR_QC",
    "AR_SEMANTIC",
    "AI_SUGGESTION",
    "NEEDS_MANUAL_REVIEW",
    "DYNAMIC_INFERRED_USAGE",
    "ENGINE_ERROR",
    "UNKNOWN",
]

Severity = Literal["error", "warning", "info"]


@dataclass
class AuditIssue:
    """A single localisation issue found during an audit run.

    Parameters
    ----------
    key:
        The translation key this issue relates to.
    code:
        Machine-readable issue code (see module docstring table).
    issue_type:
        Legacy string from the existing audit modules — kept for backward
        compatibility with existing JSON consumers.
    severity:
        ``"error"`` | ``"warning"`` | ``"info"``
    locale:
        Locale identifier (e.g. ``"ar"``, ``"en"``, ``"en/ar"``).
    message:
        Human-readable description.
    file:
        Source file path where the issue was detected (if applicable).
    line:
        Line number in *file* (if applicable).
    suggestion:
        Suggested correction (populated by AI review stage).
    source:
        Original source-language string (populated by AI review stage).
    target:
        Current translation string (populated by AI review stage).
    extra:
        Arbitrary additional data from the underlying audit module.
    """

    key: str = ""
    code: IssueCode = "UNKNOWN"
    issue_type: str = ""
    severity: Severity = "warning"
    locale: str = ""
    message: str = ""
    file: str = ""
    line: int | None = None
    suggestion: str = ""
    suggested_fix: str = ""
    approved_new: str = ""
    source: str = ""
    target: str = ""
    needs_review: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Remove None values for cleaner JSON
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Mapping from legacy issue_type strings → IssueCode
# ---------------------------------------------------------------------------

_ISSUE_TYPE_TO_CODE: dict[str, IssueCode] = {
    "missing_in_both": "MISSING_KEY",
    "missing_ar": "MISSING_KEY_AR",
    "missing_in_ar": "MISSING_KEY_AR",
    "in_en_not_ar": "MISSING_KEY_AR",
    "missing_en": "MISSING_KEY_EN",
    "missing_in_en": "MISSING_KEY_EN",
    "in_ar_not_en": "MISSING_KEY_EN",
    "unused_ar": "UNUSED_KEY",
    "unused_en": "UNUSED_KEY",
    "confirmed_unused_key": "UNUSED_KEY",
    "empty_ar": "EMPTY_TRANSLATION",
    "empty_en": "EMPTY_TRANSLATION",
    "placeholder_mismatch": "PLACEHOLDER_MISMATCH",
    "placeholder": "PLACEHOLDER_MISMATCH",
    "terminology": "TERMINOLOGY_VIOLATION",
    "terminology_violation": "TERMINOLOGY_VIOLATION",
    "icu_error": "ICU_SYNTAX_ERROR",
    "icu_syntax_error": "ICU_SYNTAX_ERROR",
    "grammar_error": "GRAMMAR_ERROR",
    "grammar": "GRAMMAR_ERROR",
    "ar_qc": "AR_QC",
    "ar_locale_qc": "AR_QC",
    "ar_semantic": "AR_SEMANTIC",
    "ar_semantic_qc": "AR_SEMANTIC",
    "ai_suggestion": "AI_SUGGESTION",
    "needs_manual_review": "NEEDS_MANUAL_REVIEW",
    "suspicious_usage": "NEEDS_MANUAL_REVIEW",
    "dynamic_inferred_usage": "DYNAMIC_INFERRED_USAGE",
    "dynamic_inferred_ar": "DYNAMIC_INFERRED_USAGE",
    "dynamic_inferred_en": "DYNAMIC_INFERRED_USAGE",
}


def issue_code_from_type(issue_type: str) -> IssueCode:
    """Convert a legacy *issue_type* string to an :data:`IssueCode`."""
    return _ISSUE_TYPE_TO_CODE.get(issue_type.lower(), "UNKNOWN")


def issue_from_dict(raw: dict[str, Any]) -> AuditIssue:
    """Create an :class:`AuditIssue` from a raw dict (from any audit module)."""
    issue_type = str(raw.get("issue_type") or raw.get("type") or "").strip() or "unknown"
    code: IssueCode = raw.get("code") or issue_code_from_type(issue_type)  # type: ignore[assignment]
    file_val = raw.get("file") or ""
    if isinstance(file_val, Path):
        file_val = str(file_val)
    return AuditIssue(
        key=str(raw.get("key") or ""),
        code=code,
        issue_type=issue_type,
        severity=raw.get("severity", "warning"),
        locale=str(raw.get("locale") or ""),
        message=str(raw.get("message") or raw.get("description") or ""),
        file=str(file_val),
        line=raw.get("line"),
        suggestion=str(raw.get("suggestion") or ""),
        suggested_fix=str(raw.get("suggested_fix") or raw.get("suggestion") or ""),
        approved_new=str(raw.get("approved_new") or ""),  # Boundary: Apply-layer field — must NOT fall back from 'suggestion' (bypasses safety gate)
        source=str(raw.get("source") or ""),
        target=str(raw.get("target") or raw.get("current_translation") or ""),
        needs_review=bool(raw.get("needs_review", False)),
        extra={k: v for k, v in raw.items() if k not in {
            "key", "code", "issue_type", "type", "severity", "locale",
            "message", "description", "file", "line", "suggestion",
            "suggested_fix", "approved_new",
            "source", "target", "current_translation", "needs_review",
        }},
    )


# ---------------------------------------------------------------------------
# AuditSummary
# ---------------------------------------------------------------------------

@dataclass
class AuditSummary:
    """Aggregate counts from all audit stages in a single run."""

    total_keys_en: int = 0
    total_keys_ar: int = 0
    missing_keys: int = 0
    unused_keys: int = 0
    empty_translations: int = 0
    placeholder_errors: int = 0
    terminology_errors: int = 0
    icu_errors: int = 0
    grammar_errors: int = 0
    ar_qc_issues: int = 0
    ar_semantic_issues: int = 0
    ai_suggestions: int = 0
    needs_manual_review: int = 0
    total_issues: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_issues(cls, issues: list[AuditIssue]) -> "AuditSummary":
        """Build a summary by counting issues list."""
        s = cls()
        s.total_issues = len(issues)
        for issue in issues:
            code = issue.code
            if code in ("MISSING_KEY", "MISSING_KEY_AR", "MISSING_KEY_EN"):
                s.missing_keys += 1
            elif code == "UNUSED_KEY":
                s.unused_keys += 1
            elif code == "EMPTY_TRANSLATION":
                s.empty_translations += 1
            elif code == "PLACEHOLDER_MISMATCH":
                s.placeholder_errors += 1
            elif code == "TERMINOLOGY_VIOLATION":
                s.terminology_errors += 1
            elif code == "ICU_SYNTAX_ERROR":
                s.icu_errors += 1
            elif code == "GRAMMAR_ERROR":
                s.grammar_errors += 1
            elif code == "AR_QC":
                s.ar_qc_issues += 1
            elif code == "AR_SEMANTIC":
                s.ar_semantic_issues += 1
            elif code == "AI_SUGGESTION":
                s.ai_suggestions += 1
            elif code == "NEEDS_MANUAL_REVIEW":
                s.needs_manual_review += 1
        return s


# ---------------------------------------------------------------------------
# ReportArtifact
# ---------------------------------------------------------------------------

@dataclass
class ReportArtifact:
    """Metadata about a report file written to disk."""

    name: str
    """Human-readable report name, e.g. ``"localization_audit_pro_en"``."""

    path: str
    """Absolute path to the written file."""

    format: Literal["json", "md", "xlsx", "csv", "markdown"]
    """File format."""

    category: Literal["summary", "tool", "review", "logs"] = "tool"
    """Report category."""

    size_bytes: int = 0
    """File size in bytes after writing."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ResultsRetention
# ---------------------------------------------------------------------------

@dataclass
class ResultsRetention:
    """Configures how historical audit results are handled in the Results/ directory."""

    mode: Literal["archive", "overwrite"] = "overwrite"
    """Whether to move old results to an archive folder or just overwrite them."""

    archive_name_prefix: str = "audit"
    """Prefix for archive directories, e.g. "audit_v1"."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# AuditOptions
# ---------------------------------------------------------------------------

VERSION = "1.7.0"


@dataclass
class ProjectDetection:
    """Settings controlling how the project profile is discovered / إعدادات اكتشاف نوع المشروع"""
    auto_detect: bool = True  # Enable automatic project discovery / تفعيل اكتشاف المشروع تلقائياً
    force_profile: str | None = None  # Force a specific profile (e.g. 'flutter') / فرض ملف تعريف محدد للمشروع

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditRules:
    """Terminology and semantic rules for the audit engine / قواعد المصطلحات والمعاني لمحرك التدقيق"""
    role_identifiers: list[str] = field(default_factory=list)  # Domain-specific roles (e.g. 'admin') / أدوار النظام (مثل 'المسؤول')
    latin_whitelist: list[str] = field(default_factory=list)  # Latin terms allowed in Arabic text / كلمات لاتينية مسموح بها في النص العربي
    entity_whitelist: dict[str, list[str]] = field(default_factory=lambda: {"en": [], "ar": []})  # Protected entities / الكيانات المحمية
    apply_safe_fixes: bool = False  # Automatically apply glossary replacements / تطبيق تصحيحات القاموس تلقائياً

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AIReview:
    """Configuration for LLM-powered review stages / إعدادات مرحلة المراجعة بالذكاء الاصطناعي"""
    enabled: bool = False  # Enable/disable AI review / تفعيل أو تعطيل مراجعة الذكاء الاصطناعي
    provider: str = "litellm"  # AI provider name (openai, deepseek, etc) / مزود خدمة الذكاء الاصطناعي
    model: str | None = None  # Model identifier (e.g. 'gpt-4o-mini') / اسم نموذج الذكاء الاصطناعي
    api_key_env: str | None = None  # Env var for API key / اسم متغير البيئة لمفتاح API
    batch_size: int = 10  # Number of keys per AI request / عدد المفاتيح في كل طلب للذكاء الاصطناعي
    max_retries: int = 5  # Maximum retry attempts for glossary compliance / أقصى عدد لمحاولات إعادة المحاولة
    request_timeout_seconds: int = 60  # Per-request provider timeout in seconds / مهلة الطلب لمزود الذكاء الاصطناعي بالثواني
    max_consecutive_failures: int = 3  # Circuit-breaker threshold for provider failures / حد إيقاف المحاولات بعد فشل متتالي
    short_label_threshold: int = 3  # Min words for context evaluation / الحد الأدنى للكلمات لتقييم السياق
    translate_missing: bool = False  # Auto-translate missing keys / الترجمة الآلية للمفاتيح المفقودة

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutputOptions:
    """Settings for results storage and report generation / إعدادات تخزين النتائج وإنشاء التقارير"""
    results_dir: str | Path | None = None  # Custom results directory / مجلد مخصص للنتائج
    retention_mode: Literal["archive", "overwrite"] = "overwrite"  # Action for old results / ماذا نفعل للنتائج القديمة
    archive_name_prefix: str = "audit"  # Prefix for archive files / بادئة أسماء ملفات الأرشيف

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("results_dir") is not None:
            d["results_dir"] = str(d["results_dir"])
        return d


@dataclass
class ARLocaleQC:
    """Settings for Arabic-specific quality control / إعدادات ضبط الجودة الخاصة باللغة العربية"""
    enable_exclamation_style: bool = True  # Check for spacing before '!' and '؟'
    enable_long_ui_string: bool = True  # Flag unusually long translations
    enable_similar_phrase_variation: bool = True  # Detect inconsistent translations for same term
    enable_suspicious_literal_translation: bool = True  # Catch literal translations that lose meaning

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutputSuppression:
    """Phase D/F — Feature flags that suppress optional artifact writes.

    Phase D introduced these flags (all defaulting to True).
    Phase F changes the defaults for artifacts classified as ``optional_legacy``
    in the Phase E deprecation registry.  The four flags below now default to
    ``False`` because:

    - No active production code reads their outputs via ``run_stage()``.
    - No ``run_stage()`` test depends on their presence.
    - CLI ``main()`` paths pass explicit ``--out-*`` args and bypass these flags.
    - Evidence: Phase E consumer audit, grep across tests/ confirmed zero
      ``run_stage`` dependencies.

    Phase F defaults applied:
    - CSV/XLSX disabled by default
    - multilingual markdown removed (Phase G2)

    To restore full outputs (e.g. for debugging or extended CI artifacts)::

        AuditOptions(suppression=OutputSuppression(
            include_per_tool_csv=True,
            include_per_tool_xlsx=True,
            include_fix_plan_xlsx=True,
        ))

    Critical outputs (audit_master.json, review_queue.xlsx/json,
    final_audit_report.json, final_audit_report.md) are NEVER controlled
    by these flags and are always written.
    """

    # Per-tool CSV files (.cache/raw_tools/*/*.csv)
    # Phase F default: False — no run_stage consumer; CLI main() is unaffected.
    include_per_tool_csv: bool = False

    # Per-tool XLSX files (.cache/raw_tools/*/*.xlsx)
    # Phase F default: False — no run_stage consumer; CLI main() is unaffected.
    include_per_tool_xlsx: bool = False

    # fix_plan.xlsx (.cache/apply/fix_plan.xlsx)
    # fix_plan.json is always written; XLSX is human-convenience only.
    # Phase F default: False — test_safe_fixes.py exercises main() path only.
    include_fix_plan_xlsx: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditOptions:
    """Unified configuration for a single l10n-audit run / الإعدادات الموحدة لعملية التدقيق"""

    stage: str = "full"  # Audit stage to run (full|fast|terminology|...) / مرحلة التدقيق المطلوب تشغيلها
    write_reports: bool = True  # Generate file output (JSON/CSV/XLSX) / إنشاء ملفات التقارير

    project_detection: ProjectDetection = field(default_factory=ProjectDetection)
    audit_rules: AuditRules = field(default_factory=AuditRules)
    ai_review: AIReview = field(default_factory=AIReview)
    output: OutputOptions = field(default_factory=OutputOptions)
    ar_locale_qc: ARLocaleQC = field(default_factory=ARLocaleQC)

    # Phase D — output suppression flags (all default True = no change)
    suppression: OutputSuppression = field(default_factory=OutputSuppression)

    # Environment paths (often overridden by runtime)
    project_root: str = ".."
    # Power-user Overrides
    glossary_file: str | Path | None = "glossary.json"
    out_xlsx: str | Path | None = None
    config_schema: str | Path | None = None
    languagetool_dir: str = "vendor"

    # Internal injection for testing / Feedback
    ai_provider_override: Any | None = None
    verbose: bool = False

    # Phase G1 - Governs how strictly we enforce deprecations
    strict_deprecations: bool = False

    # v1.3.1 - Hydration / Cache Loading
    input_report: str | Path | None = None

    def effective_output_dir(self, runtime_results_dir: Path) -> Path:
        """Determines the final results directory by checking output options."""
        if self.output.results_dir:
            return Path(self.output.results_dir)
        return runtime_results_dir

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "project_detection": self.project_detection.to_dict(),
            "audit_rules": self.audit_rules.to_dict(),
            "ai_review": self.ai_review.to_dict(),
            "output": self.output.to_dict(),
            "ar_locale_qc": self.ar_locale_qc.to_dict(),
            "suppression": self.suppression.to_dict(),
            "project_root": self.project_root,
            "glossary_file": self.glossary_file,
            "languagetool_dir": self.languagetool_dir,
        }

    def default_config_json(self, profile_name: str | None = None) -> str:
        """Returns a hyper-detailed prettified JSON string of all defaults with vertical bilingual comments."""
        data = {
            "config_version": 2,

            "//_stage": {
                "title": "Audit Depth | عمق التدقيق",
                "choices": [
                    "full        = AI + Grammar + QC (Recommended for production)",
                    "fast        = Terminology + QC (High performance)",
                    "terminology = Isolated Glossary enforcement",
                    "grammar     = Pure linguistic and style verification"
                ]
            },
            "stage": self.stage,

            "project_detection": {
                "//_auto_detect": "Automatic framework discovery | الاكتشاف التلقائي لإطار العمل",
                "auto_detect": self.project_detection.auto_detect,

                "//_force_profile": {
                    "title": "Manual Profile Override | فرض ملف تعريف يدوي",
                    "choices": [
                        "flutter_arb, laravel_php, json_flat, react_i18n, vue_i18n",
                        "android_xml, ios_strings"
                    ]
                },
                "force_profile": profile_name or self.project_detection.force_profile
            },

            "audit_rules": {
                "//_role_identifiers": "Domain-specific roles (e.g. captain) | أدوار النظام الخاصة (مثل سائق)",
                "role_identifiers": self.audit_rules.role_identifiers,

                "//_latin_whitelist": "Allowed brands in Arabic text | العلامات التجارية المسموحة في النص العربي",
                "latin_whitelist": self.audit_rules.latin_whitelist,

                "//_entity_whitelist": "Protected terms | الكيانات المحمية",
                "entity_whitelist": self.audit_rules.entity_whitelist,

                "//_apply_safe_fixes": "Auto-apply glossary fixes | تطبيق تصحيحات القاموس آلياً",
                "apply_safe_fixes": self.audit_rules.apply_safe_fixes
            },

            "ai_review": {
                "//_enabled": "Enable LLM semantic review | تفعيل المراجعة بالذكاء الاصطناعي",
                "enabled": self.ai_review.enabled,

                "//_provider": "AI Provider (openai/deepseek/litellm) | مزود خدمة الذكاء الاصطناعي",
                "provider": self.ai_review.provider,

                "//_model": "LLM Identifier (e.g. gpt-4o-mini) | معرف نموذج اللغة",
                "model": self.ai_review.model or "gpt-4o-mini",

                "//_api_key_env": "Env var for API key | اسم متغير البيئة لمفتاح API",
                "api_key_env": self.ai_review.api_key_env or "OPENAI_API_KEY",

                "//_batch_size": "Number of labels per AI request | عدد النصوص في كل طلب",
                "batch_size": self.ai_review.batch_size,

                "//_request_timeout_seconds": "Provider timeout per request (seconds) | مهلة المزود لكل طلب (بالثواني)",
                "request_timeout_seconds": self.ai_review.request_timeout_seconds,

                "//_max_consecutive_failures": "Stop AI stage after repeated provider failures | إيقاف مرحلة الذكاء بعد فشل المزود المتكرر",
                "max_consecutive_failures": self.ai_review.max_consecutive_failures,
            },

            "output": {
                "//_results_dir": "Target directory for reports | مجلد مخرجات التقارير",
                "results_dir": self.output.results_dir or "Results",

                "//_retention_mode": {
                    "title": "History Management | إدارة تاريخ الفحص",
                    "choices": [
                        "overwrite = Delete last run (Default)",
                        "archive   = Move to timestamped archives"
                    ]
                },
                "retention_mode": self.output.retention_mode
            },

            "//_project_root": "Project root directory path | مسار جذر المشروع",
            "project_root": self.project_root,

            "//_glossary_file": "Terminology glossary JSON path | مسار ملف القاموس الموحد",
            "glossary_file": self.glossary_file
        }
        return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# AuditResult
# ---------------------------------------------------------------------------

@dataclass
class AuditResult:
    """The top-level result of a :func:`run_audit` call.

    All fields serialise deterministically via :meth:`to_dict` / :meth:`to_json`
    so that downstream HTTP APIs can pass them directly to a frontend.

    Run Metadata
    ------------
    job_id:
        A UUID string uniquely identifying this run.
    started_at:
        ISO-8601 UTC timestamp of when the run started.
    finished_at:
        ISO-8601 UTC timestamp of when the run finished.
    duration_ms:
        Wall-clock duration in milliseconds.
    """

    # Identifiers
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str = ""
    profile: str = ""
    stage: str = ""

    # Run metadata
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0

    # Results
    summary: AuditSummary = field(default_factory=AuditSummary)
    issues: list[AuditIssue] = field(default_factory=list)
    reports: list[ReportArtifact] = field(default_factory=list)

    # Status
    success: bool = True
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def mark_started(self) -> None:
        self.started_at = self._now_iso()
        self._start_ts = datetime.now(timezone.utc).timestamp()

    def mark_finished(self) -> None:
        self.finished_at = self._now_iso()
        if hasattr(self, "_start_ts"):
            self.duration_ms = int(
                (datetime.now(timezone.utc).timestamp() - self._start_ts) * 1000
            )

    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_path": self.project_path,
            "profile": self.profile,
            "stage": self.stage,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.metadata,
            "summary": self.summary.to_dict(),
            "issues": [i.to_dict() for i in self.issues],
            "reports": [r.to_dict() for r in self.reports],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
