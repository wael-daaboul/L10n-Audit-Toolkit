# Installation Guide

This guide covers environment setup, dependency installation, test setup, and first-run validation for L10n Audit Toolkit. For the shortest onboarding path, see [docs/quickstart.md](docs/quickstart.md).

## English

Current version: **1.4.0** (The Master Architecture Edition)

### Purpose
This guide covers system setup, optional dependencies, local LanguageTool, virtual environments, and first-run validation for the localization QA toolkit.

Current compatibility scope:
- JSON locale files
- Laravel PHP translation files with safe static parseable return structures such as `return [...]` and `return array(...)`
- Flutter / GetX
- Laravel JSON translations
- Laravel PHP translations
- React / Next.js JSON i18n
- Vue / Nuxt JSON i18n

### Required System Dependencies
- Python 3.10 or newer
- A supported localization project
  - choose the closest built-in `project_profile`
  - or set `project_profile` to `auto`
  - or configure `locale_paths`, `locale_root`, and `code_dirs` explicitly

### Optional System Dependencies
- Java (JRE/JDK 11+)
  - **Critical**: Required for local LanguageTool grammar analysis and Arabic linguistic QC (`ar_locale_qc`). Without Java, the toolkit will gracefully skip these stages with a warning.
- AI API Keys
  - Required for `ai-review` stage. Configure them in `~/.l10n-audit/config.env` (created automatically on first run).
- Local LanguageTool bundle
  - optional, discovered dynamically under `tools/vendor/LanguageTool-*` or `vendor/LanguageTool-*`

### Python Dependency Files
- `requirements.txt`
  - mandatory Python packages
- `requirements-optional.txt`
  - optional enhancement packages
- `requirements-dev.txt`
  - development and maintenance packages

### Current Dependency Model
- Core runtime and reporting work without third-party Python packages.
- Grammar first tries a local LanguageTool installation and then falls back to `language-tool-python`.
- Some optional Python packages are reserved for richer future audits and developer workflows.

## Installation Guide

### For Users (Recommended)
Install the global CLI tool directly from PyPI using `pipx` to keep it isolated from your system Python:

```bash
pipx install l10n-audit-toolkit
```

**Verify your installation:**
```bash
l10n-audit doctor
```

### For Developers (Source Code)
If you want to contribute or use raw scripts, clone the repository and run the bootstrap script:

```bash
git clone https://github.com/wael-daaboul/L10n-Audit-Toolkit.git
cd L10n-Audit-Toolkit
./bootstrap.sh --with-tests
```
*(Optional flags: `--skip-optional`, `--validate-schemas`, `--run-tests`)*

When working from source, you can use the legacy bash wrapper if needed:
```bash
./bin/run_all_audits.sh --stage fast
```
*(We highly recommend using `l10n-audit` CLI instead).*

### Updating
To update the global CLI:
```bash
pipx upgrade l10n-audit-toolkit
```

### Install Mandatory Packages
```bash
pip install -r requirements.txt
```

### Install Optional Packages
```bash
pip install -r requirements-optional.txt
```

### Install Development Packages
```bash
pip install -r requirements-dev.txt
```

Development packages are recommended for:
- running the pytest regression suite
- validating toolkit JSON contracts during maintenance

### Verify Python
```bash
python3 --version
```

### Verify Java
```bash
java -version
```

If Java is missing:
- macOS with Homebrew:
  - `brew install openjdk`
- then ensure Java is on `PATH`

### Verify Local LanguageTool
The toolkit first looks for a local LanguageTool installation in the project.

It does not rely on a fixed version like `LanguageTool-6.6`. Instead it accepts any local directory named `LanguageTool-*`.

Preferred discovery locations:
- `tools/vendor/LanguageTool-*`
- `vendor/LanguageTool-*`

If you want to pin a specific path, set:

```json
{
  "languagetool_dir": "tools/vendor/LanguageTool-7.0"
}
```

Quick verification:
```bash
find tools/vendor vendor -maxdepth 1 -type d -name 'LanguageTool-*'
```

### If LanguageTool Is Missing
If no local LanguageTool installation is found, the toolkit falls back to `language-tool-python`. That fallback may download LanguageTool once and cache it automatically.

This means:
- local bundled LanguageTool is used immediately when present
- no hardcoded version directory is required
- the GitHub repository can stay smaller because `vendor/LanguageTool-*` does not need to be committed

### Optional NLP Data
If future optional checks use TextBlob or NLTK corpora, initialize them only when needed.

Typical commands:
```bash
python3 -m textblob.download_corpora
python3 - <<'PY'
import nltk
nltk.download('punkt')
nltk.download('wordnet')
PY
```

These are optional and not required for the current core flow.

### First Successful Validation
From project root:
```bash
./bin/run_all_audits.sh --stage fast
```

If you are onboarding a non-Flutter project, either set `project_profile` manually or use `project_profile = "auto"` to enable autodetection.
For Laravel PHP translations, use `project_profile = "laravel_php"` and configure `locale_root` if your project does not use the default `resources/lang`.

Expected canonical outputs:
- `.cache/raw_tools/...`
- `Results/final/...`

For full validation:
```bash
l10n-audit init
l10n-audit run --stage full
```

For fix planning:
```bash
l10n-audit run --stage autofix
```

To inspect or refresh an existing workspace:

```bash
l10n-audit doctor
l10n-audit update --check
l10n-audit update
```

To sync workspace templates from GitHub:

```bash
l10n-audit init --from-github --channel stable --repo https://github.com/your-org/l10n-audit-toolkit
l10n-audit update --from-github --channel main --repo https://github.com/your-org/l10n-audit-toolkit
```

For schema validation from the repository root:
```bash
python3 -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
python3 -m core.schema_validation --input docs/terminology/<your-glossary-file>.json --schema schemas/glossary.schema.json

Any glossary filename is supported. For new projects, `docs/terminology/glossary.json` is the recommended neutral name.

The bundled `docs/terminology/glossary.json` file is only a small neutral example. Replace it with your own approved terminology data.
```

After generating audit outputs, you can validate the full built-in contract set:
```bash
python3 -m core.schema_validation --preset core
```

For fixture-based regression tests:
```bash
python3 -m pytest tests
```

### Canonical Output Locations
- Per-tool raw outputs:
  - `.cache/raw_tools/`
- Normalized outputs:
  - `Results/normalized/`
- Final aggregated outputs:
  - `Results/final/`
- Safe-fix outputs:
  - `Results/fixes/`

### Typical Installation Problems
- `python3` not found
  - install Python 3 and retry
- `java` not found
  - install Java or accept grammar fallback mode
- LanguageTool jar missing
  - place a `LanguageTool-*` directory under `tools/vendor/` or `vendor/`, or use the cached fallback
- Permission denied on shell scripts
  - run:
    - `chmod +x bin/run_all_audits.sh`
- Aggregator says reports are missing
  - run the relevant audit stage before `--stage reports`
- Toolkit cannot detect the project layout
  - set `project_profile` in `config/config.json`
  - if needed, override `locale_paths` and `code_dirs` explicitly

### macOS Notes
- Homebrew is the simplest path for Java:
  - `brew install openjdk`
- If Java installs but is not detected, update shell startup files so `java` is available in non-interactive shells as well.

### Graceful Degradation Summary
- No Java:
  - grammar cannot use LanguageTool, so the audit falls back to deterministic local grammar rules
- No local LanguageTool:
  - grammar falls back to `language-tool-python`, which may download and cache LanguageTool
- No optional Python packages:
  - core audit, aggregation, and fix-planning still work
- No optional NLP corpora:
  - future NLP-heavy optional checks may be reduced, but the main toolkit still works
- No `pytest`:
  - the toolkit still runs, but the regression suite cannot be executed

---

## العربية

الإصدار الحالي: **1.4.0** (The Master Architecture Edition)

### الغرض من هذا الدليل
يوضح هذا الدليل كيفية تثبيت الحزمة وتجهيز البيئة وتشغيل أول تحقق ناجح، مع توضيح التبعيات المطلوبة والاختيارية وكيفية التراجع الآمن عند غياب بعضها.

نطاق التوافق الحالي:
- ملفات ترجمة JSON
- ملفات Laravel PHP ذات البنى الثابتة القابلة للتحليل مثل `return [...]` و `return array(...)`
- Flutter / GetX
- Laravel JSON
- Laravel PHP
- React / Next.js JSON
- Vue / Nuxt JSON

### التبعيات النظامية المطلوبة
- Python 3.10 أو أحدث
- مشروع يستخدم ملفات ترجمة مدعومة
  - JSON أو Laravel PHP arrays
  - مع اختيار `project_profile` مناسب
  - أو تعريف `locale_paths` أو `locale_root` و `code_dirs` بشكل صريح عند الحاجة

### التبعيات النظامية الاختيارية
- Java (JRE/JDK 11+)
  - **هام جداً**: مطلوب لتشغيل LanguageTool المحلي وفحوصات الجودة اللغوية العربية (`ar_locale_qc`). في حال غيابه، ستعرض الأداة تنبيهاً وتتجاوز هذه المراحل بسلام.
- مفاتيح الذكاء الاصطناعي (AI Keys)
  - مطلوبة لمرحلة `ai-review`. يجب ضبطها في الملف العالمي `~/.l10n-audit/config.env`.
- LanguageTool المحلي
  - اختياري، ويتم اكتشافه ديناميكياً داخل `tools/vendor/LanguageTool-*` أو `vendor/LanguageTool-*`

### ملفات التبعيات في Python
- `requirements.txt`
  - الحزم الأساسية المطلوبة
- `requirements-optional.txt`
  - الحزم الاختيارية
- `requirements-dev.txt`
  - حزم التطوير والصيانة

### إنشاء البيئة الافتراضية وتفعيلها
```bash
cd tools
python3 -m venv .venv
source .venv/bin/activate
```

### الخطوة الأولى الموصى بها

#### للمستخدمين (طريقة التثبيت الموصى بها)
ثبّت الأداة كأمر نظام عالمي (Global CLI) مباشرة من PyPI باستخدام `pipx` لضمان عزلها عن بيئة بايثون الأساسية:

```bash
pipx install l10n-audit-toolkit
```

**للتحقق من التثبيت:**
```bash
l10n-audit doctor
```

#### للمطورين (من الكود المصدري)
إذا كنت ترغب في المساهمة في المشروع أو استخدام السكريبتات الخام، قم بسحب المستودع وتشغيل سكريبت الـ bootstrap:

```bash
git clone https://github.com/wael-daaboul/L10n-Audit-Toolkit.git
cd L10n-Audit-Toolkit
./bootstrap.sh --with-tests
```
*(خيارات إضافية: `--skip-optional`, `--validate-schemas`, `--run-tests`)*

عند العمل من الكود المصدري، يمكنك استخدام سكريبت الـ bash القديم إذا لزم الأمر:
```bash
./bin/run_all_audits.sh --stage fast
```
*(نوصي بشدة باستخدام أمر `l10n-audit` بدلاً منه).*

#### التحديث
لتحديث الأداة العالمية لأحدث إصدار، استخدم الأمر التالي:
```bash
pipx upgrade l10n-audit-toolkit
```

### تثبيت الحزم الأساسية
```bash
pip install -r requirements.txt
```

### تثبيت الحزم الاختيارية
```bash
pip install -r requirements-optional.txt
```

### تثبيت حزم التطوير
```bash
pip install -r requirements-dev.txt
```

حزم التطوير مفيدة لتشغيل:
- اختبارات pytest
- التحقق من مخططات JSON الخاصة بالحزمة

### التحقق من Python
```bash
python3 --version
```

### التحقق من Java
```bash
java -version
```

إذا لم تكن Java موجودة:
- في macOS مع Homebrew:
  - `brew install openjdk`

### التحقق من LanguageTool المحلي
تحاول الأداة أولاً العثور على نسخة محلية من LanguageTool داخل المشروع.

ولا تعتمد الأداة على رقم إصدار ثابت مثل `LanguageTool-6.6`، بل تقبل أي مجلد محلي باسم مشابه لـ `LanguageTool-*`.

أماكن البحث المفضلة:
- `tools/vendor/LanguageTool-*`
- `vendor/LanguageTool-*`

وإذا أردت تحديد المسار صراحةً في الإعدادات:

```json
{
  "languagetool_dir": "tools/vendor/LanguageTool-7.0"
}
```

### إذا كان LanguageTool مفقوداً
إذا لم تجد الأداة نسخة محلية من LanguageTool، فإنها تنتقل إلى السلوك الاحتياطي عبر `language-tool-python`، والذي قد يقوم بتحميل LanguageTool مرة واحدة ثم تخزينه مؤقتاً.

وهذا يعني:
- إذا وجدت الأداة نسخة محلية فإنها تستخدمها فوراً
- لا حاجة للاعتماد على مجلد بإصدار ثابت
- يمكن إبقاء مستودع GitHub أخف لأن `vendor/LanguageTool-*` ليس إلزامياً

### بيانات NLP الاختيارية
إذا احتاجت بعض الفحوص المستقبلية إلى TextBlob أو NLTK، يمكن تنزيل البيانات عند الحاجة فقط:
```bash
python3 -m textblob.download_corpora
python3 - <<'PY'
import nltk
nltk.download('punkt')
nltk.download('wordnet')
PY
```

### أول تشغيل ناجح
من جذر المشروع:
```bash
./bin/run_all_audits.sh --stage fast
```

إذا كان المشروع غير Flutter، اضبط `project_profile` أولاً داخل `config/config.json`.

ثم للتحقق الكامل:
```bash
./bin/run_all_audits.sh --stage full
```

ولخطة الإصلاح:
```bash
./bin/run_all_audits.sh --stage autofix
```

وللتحقق من المخططات من جذر المستودع:
```bash
python3 -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
python3 -m core.schema_validation --input docs/terminology/<your-glossary-file>.json --schema schemas/glossary.schema.json
```

وبعد توليد مخرجات التدقيق يمكن التحقق من جميع العقود المضمنة عبر:
```bash
python3 -m core.schema_validation --preset core
```

ولتشغيل اختبارات الـ fixtures:
```bash
python3 -m pytest tests
```

### أماكن المخرجات المعتمدة
- المخرجات الخام لكل أداة:
  - `.cache/raw_tools/`
- المخرجات الموحدة:
  - `Results/normalized/`
- التقارير النهائية:
  - `Results/final/`
- مخرجات الإصلاح:
  - `Results/fixes/`

### أكثر مشاكل التثبيت شيوعاً
- عدم وجود `python3`
  - ثبّت Python 3
- عدم وجود `java`
  - ثبّت Java أو اقبل وضع التراجع في طبقة القواعد
- غياب ملفات LanguageTool
  - ضع مجلد `LanguageTool-*` داخل `tools/vendor/` أو `vendor/` أو استخدم السلوك الاحتياطي عبر التخزين المؤقت
- مشكلة صلاحيات التنفيذ
  - نفّذ:
    - `chmod +x bin/run_all_audits.sh`
- نقص بعض التقارير
  - شغّل المرحلة المناسبة قبل `reports`
- فشل اكتشاف بنية المشروع
  - حدّد `project_profile` في `config/config.json`
  - وإذا لزم الأمر عرّف `locale_paths` و `code_dirs` بشكل صريح

### ملاحظات خاصة بـ macOS
- أسهل طريقة لتثبيت Java هي Homebrew
- إذا تم تثبيت Java ولم تتعرف عليها الأوامر، حدّث إعدادات الـ shell بحيث تكون Java متاحة في الأوامر غير التفاعلية أيضاً

### ملخص التراجع الآمن
- غياب Java:
  - لا يمكن استخدام LanguageTool، لذلك يرجع تدقيق القواعد إلى القواعد المحلية الحتمية
- غياب LanguageTool المحلي:
  - ينتقل تدقيق القواعد إلى `language-tool-python` والذي قد يقوم بالتحميل والتخزين المؤقت
- غياب الحزم الاختيارية:
  - تبقى الطبقات الأساسية والتجميع وخطة الإصلاح عاملة
- غياب `pytest`:
  - تبقى الحزمة عاملة، لكن لن تتمكن من تشغيل مجموعة الاختبارات
