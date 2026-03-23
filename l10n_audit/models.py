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
    source: str = ""
    target: str = ""
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
    issue_type = str(raw.get("issue_type") or raw.get("type") or "")
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
        source=str(raw.get("source") or ""),
        target=str(raw.get("target") or raw.get("current_translation") or ""),
        extra={k: v for k, v in raw.items() if k not in {
            "key", "code", "issue_type", "type", "severity", "locale",
            "message", "description", "file", "line", "suggestion",
            "source", "target", "current_translation",
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

VERSION = "1.2.7"


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
    batch_size: int = 20  # Number of keys per AI request / عدد المفاتيح في كل طلب للذكاء الاصطناعي
    short_label_threshold: int = 3  # Min words for context evaluation / الحد الأدنى للكلمات لتقييم السياق

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
class AuditOptions:
    """Unified configuration for a single l10n-audit run / الإعدادات الموحدة لعملية التدقيق"""

    stage: str = "full"  # Audit stage to run (full|fast|terminology|...) / مرحلة التدقيق المطلوب تشغيلها
    write_reports: bool = True  # Generate file output (JSON/CSV/XLSX) / إنشاء ملفات التقارير
    
    project_detection: ProjectDetection = field(default_factory=ProjectDetection)
    audit_rules: AuditRules = field(default_factory=AuditRules)
    ai_review: AIReview = field(default_factory=AIReview)
    output: OutputOptions = field(default_factory=OutputOptions)
    ar_locale_qc: ARLocaleQC = field(default_factory=ARLocaleQC)

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
            "project_root": self.project_root,
            "glossary_file": self.glossary_file,
            "languagetool_dir": self.languagetool_dir,
        }

    def default_config_json(self, profile_name: str | None = None) -> str:
        """Returns a hyper-detailed prettified JSON string of all defaults with vertical bilingual comments."""
        data = {
            "config_version": 2,
            "//_comment_stage_en": [
                "1. Control depth of the audit process.",
                "2. [full]: Comprehensive audit (Grammar, AI, Terminology, QC).",
                "3. [fast]: Performance-focused audit (Terminology & QC).",
                "4. [terminology]: Isolated glossary enforcement only.",
                "5. [grammar]: Pure linguistic and style verification."
            ],
            "//_comment_stage_ar": [
                "1. التحكم في عمق ومستوى عملية التدقيق.",
                "2. [full]: تدقيق شامل (لغويات، ذكاء اصطناعي، مصطلحات، جودة).",
                "3. [fast]: تدقيق سريع يركز على المصطلحات والجودة.",
                "4. [terminology]: فحص تطابق المصطلحات مع القاموس فقط.",
                "5. [grammar]: تدقيق لغوي وأسلوبي فقط."
            ],
            "stage": self.stage,

            "project_detection": {
                "//_comment_auto_detect_en": [
                    "1. Enable automatic framework discovery.",
                    "2. [true]: Scans project for .arb, .php, or i18n markers.",
                    "3. [false]: Ignores scanning; requires force_profile."
                ],
                "//_comment_auto_detect_ar": [
                    "1. تفعيل الاكتشاف التلقائي لإطار العمل.",
                    "2. [true]: يبحث في المشروع عن ملفات .arb أو .php أو علامات i18n.",
                    "3. [false]: يتجاهل الفحص؛ يتطلب تحديد force_profile يدوياً."
                ],
                "auto_detect": self.project_detection.auto_detect,

                "//_comment_force_profile_en": [
                    "1. Manual project profile override.",
                    "2. Supported: [flutter_arb, laravel_php, json_flat, react_i18n, vue_i18n, android_xml, ios_strings]."
                ],
                "//_comment_force_profile_ar": [
                    "1. تخصيص يدوي لنوع المشروع.",
                    "2. المدعوم: [flutter_arb, laravel_php, json_flat, react_i18n, vue_i18n, android_xml, ios_strings]."
                ],
                "force_profile": profile_name or self.project_detection.force_profile
            },

            "audit_rules": {
                "//_comment_role_identifiers_en": [
                    "1. Define domain-specific roles (e.g. 'captain', 'rider').",
                    "2. These terms are protected from mixed-script or semantic flags."
                ],
                "//_comment_role_identifiers_ar": [
                    "1. تعريف أدوار النظام الخاصة بك (مثل 'سائق' أو 'راكب').",
                    "2. هذه المصطلحات محمية من تحذيرات اللغة أو المعنى."
                ],
                "role_identifiers": self.audit_rules.role_identifiers,

                "//_comment_latin_whitelist_en": [
                    "1. Allow technical terms or brands in Arabic text.",
                    "2. Examples: ['DeepSeek', 'API', 'Betaxi']."
                ],
                "//_comment_latin_whitelist_ar": [
                    "1. السماح بمصطلحات تقنية أو علامات تجارية داخل النص العربي.",
                    "2. أمثلة: ['DeepSeek', 'API', 'Betaxi']."
                ],
                "latin_whitelist": self.audit_rules.latin_whitelist,

                "//_comment_entity_whitelist_en": [
                    "1. Global terms to protect from inappropriate translation.",
                    "2. Formatted as {'en': [], 'ar': []}."
                ],
                "//_comment_entity_whitelist_ar": [
                    "1. مصطلحات عامة تجب حمايتها من الترجمة غير المناسبة.",
                    "2. التنسيق: {'en': [], 'ar': []}."
                ],
                "entity_whitelist": self.audit_rules.entity_whitelist,

                "//_comment_apply_safe_fixes_en": [
                    "1. Standardize terminology automatically.",
                    "2. [true]: Replaces forbidden_terms directly in file.",
                    "3. [false]: Generates report only."
                ],
                "//_comment_apply_safe_fixes_ar": [
                    "1. توحيد المصطلحات آلياً.",
                    "2. [true]: يستبدل الكلمات المحظورة مباشرة في ملفاتك.",
                    "3. [false]: ينشئ تقريراً فقط."
                ],
                "apply_safe_fixes": self.audit_rules.apply_safe_fixes
            },

            "ai_review": {
                "//_comment_enabled_en": [
                    "1. Enable LLM-powered semantic review.",
                    "2. Requires a valid API key and internet connection."
                ],
                "//_comment_enabled_ar": [
                    "1. تفعيل المراجعة المعنوية بالذكاء الاصطناعي.",
                    "2. يتطلب مفتاح API صالح واتصالاً بالإنترنت."
                ],
                "enabled": self.ai_review.enabled,

                "//_comment_provider_en": [
                    "1. AI Service Provider selection.",
                    "2. Supported: [openai, deepseek, litellm].",
                    "3. litellm is recommended for universal model support."
                ],
                "//_comment_provider_ar": [
                    "1. اختيار مزود خدمة الذكاء الاصطناعي.",
                    "2. المدعوم: [openai, deepseek, litellm].",
                    "3. يفضل استخدام litellm لدعم شامل للنماذج."
                ],
                "provider": self.ai_review.provider,

                "//_comment_model_en": [
                    "1. Specific LLM identifier (e.g. gpt-4o-mini).",
                    "2. Recommendation: Use 'mini' models to optimize cost."
                ],
                "//_comment_model_ar": [
                    "1. معرف نموذج اللغة (مثال: gpt-4o-mini).",
                    "2. نصيحة: استخدم نماذج 'mini' لتقليل التكلفة."
                ],
                "model": self.ai_review.model or "gpt-4o-mini",

                "//_comment_api_key_env_en": [
                    "1. Environment variable name holding your API key.",
                    "2. Standard: OPENAI_API_KEY or DEEPSEEK_API_KEY."
                ],
                "//_comment_api_key_env_ar": [
                    "1. اسم متغير البيئة الذي يحتوي على مفتاح الـ API.",
                    "2. افتراضي: OPENAI_API_KEY أو DEEPSEEK_API_KEY."
                ],
                "api_key_env": self.ai_review.api_key_env or "OPENAI_API_KEY",

                "//_comment_batch_size_en": [
                    "1. Number of labels to process in a single AI request.",
                    "2. Recommended: 20-50 based on context length."
                ],
                "//_comment_batch_size_ar": [
                    "1. عدد النصوص التي يتم معالجتها في طلب ذكاء اصطناعي واحد.",
                    "2. ينصح بـ 20-50 بناءً على طول المحتوى."
                ],
                "batch_size": self.ai_review.batch_size,

                "//_comment_short_label_threshold_en": [
                    "1. Minimum word count to trigger AI semantic check.",
                    "2. Helps skip trivial labels like 'OK' or 'Save'."
                ],
                "//_comment_short_label_threshold_ar": [
                    "1. الحد الأدنى لعدد الكلمات لتفعيل فحص الذكاء الاصطناعي.",
                    "2. يساعد في تخطي الكلمات القصيرة مثل 'موافق' أو 'حفظ'."
                ],
                "short_label_threshold": self.ai_review.short_label_threshold
            },

            "output": {
                "//_comment_results_dir_en": [
                    "1. Target directory for logs and reports.",
                    "2. Default: 'Results'."
                ],
                "//_comment_results_dir_ar": [
                    "1. المجلد المستهدف لسجلات الفحص والتقارير.",
                    "2. الافتراضي: 'Results'."
                ],
                "results_dir": self.output.results_dir or "Results",

                "//_comment_retention_mode_en": [
                    "1. History management for previous audit results.",
                    "2. [overwrite]: Deletes the last Run directory.",
                    "3. [archive]: Moves results to timestamped _archives/."
                ],
                "//_comment_retention_mode_ar": [
                    "1. إدارة تاريخ نتائج الفحص السابقة.",
                    "2. [overwrite]: يحذف مجلد الفحص السابق.",
                    "3. [archive]: ينقل النتائج إلى مجلد _archives مؤرخ."
                ],
                "retention_mode": self.output.retention_mode,

                "//_comment_archive_name_prefix_en": [
                    "1. Prefix for archived result folders.",
                    "2. Format: {prefix}_YYYYMMDD_HHMMSS."
                ],
                "//_comment_archive_name_prefix_ar": [
                    "1. البادئة لمجلدات الفحص المؤرشفة.",
                    "2. التنسيق: {prefix}_YYYYMMDD_HHMMSS."
                ],
                "archive_name_prefix": self.output.archive_name_prefix or "audit"
            },

            "ar_locale_qc": {
                "//_comment_enable_exclamation_style_en": [
                    "1. Spacing check around Arabic punctuation ('!', '؟').",
                    "2. Recommendation: true."
                ],
                "//_comment_enable_exclamation_style_ar": [
                    "1. التحقق من المسافات حول علامات الترقيم ('!'، '؟').",
                    "2. ينصح بـ true."
                ],
                "enable_exclamation_style": self.ar_locale_qc.enable_exclamation_style,

                "//_comment_enable_long_ui_string_en": [
                    "1. Detection of overly long translations vs source.",
                    "2. Prevents UI overflow in mobile/compact views."
                ],
                "//_comment_enable_long_ui_string_ar": [
                    "1. اكتشاف الترجمات الطويلة جداً مقارنة بالمصدر.",
                    "2. يمنع تداخل النصوص في واجهات الهواتف."
                ],
                "enable_long_ui_string": self.ar_locale_qc.enable_long_ui_string,

                "//_comment_enable_similar_phrase_variation_en": [
                    "1. Inconsistency Detection.",
                    "2. Flags different translations for the same phrase."
                ],
                "//_comment_enable_similar_phrase_variation_ar": [
                    "1. اكتشاف عدم التناسق.",
                    "2. ينبه لوجود ترجمات مختلفة لنفس العبارة."
                ],
                "enable_similar_phrase_variation": self.ar_locale_qc.enable_similar_phrase_variation,

                "//_comment_enable_suspicious_literal_translation_en": [
                    "1. Catch literal translations that lose semantic value.",
                    "2. Highly recommended for creative UI content."
                ],
                "//_comment_enable_suspicious_literal_translation_ar": [
                    "1. اكتشاف الترجمات الحرفية التي تفقد المعنى.",
                    "2. ينصح به بشدة لمحتوى الواجهات الإبداعي."
                ],
                "enable_suspicious_literal_translation": self.ar_locale_qc.enable_suspicious_literal_translation
            },

            "//_comment_project_root_en": ["Relative or absolute path to the project root."],
            "//_comment_project_root_ar": ["المسار النسبي أو المطلق لجذر المشروع."],
            "project_root": self.project_root,

            "//_comment_glossary_file_en": ["Path to the terminology glossary file."],
            "//_comment_glossary_file_ar": ["مسار ملف القاموس الموحد."],
            "glossary_file": self.glossary_file,

            "//_comment_languagetool_dir_en": ["Local LanguageTool installation directory (optional)."],
            "//_comment_languagetool_dir_ar": ["مسار تثبيت LanguageTool المحلي (اختياري)."],
            "languagetool_dir": self.languagetool_dir
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
            "summary": self.summary.to_dict(),
            "issues": [i.to_dict() for i in self.issues],
            "reports": [r.to_dict() for r in self.reports],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
