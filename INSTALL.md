# Installation Guide

## English

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
- Java
  - needed for local LanguageTool grammar analysis
- Local LanguageTool bundle
  - expected under `vendor/LanguageTool-6.6`

### Python Dependency Files
- `requirements.txt`
  - mandatory Python packages
- `requirements-optional.txt`
  - optional enhancement packages
- `requirements-dev.txt`
  - development and maintenance packages

### Current Dependency Model
- Core runtime and reporting work without third-party Python packages.
- Grammar gets deeper with Java plus local LanguageTool.
- Some optional Python packages are reserved for richer future audits and developer workflows.

### Create and Activate a Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Bootstrap alternative:
```bash
./bootstrap.sh
./bootstrap.sh --with-tests --validate-schemas
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
Check that this exists:
- `vendor/LanguageTool-6.6/languagetool-commandline.jar`

Quick verification:
```bash
ls vendor/LanguageTool-6.6/languagetool-commandline.jar
```

### If LanguageTool Is Missing
Place a compatible LanguageTool distribution under:
- `vendor/LanguageTool-6.6/`

Expected important files:
- `languagetool-commandline.jar`
- `languagetool.jar`
- `libs/`

If it is missing, grammar audit still runs with local fallback rules.

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
- `Results/per_tool/...`
- `Results/final/...`

For full validation:
```bash
./bin/run_all_audits.sh --stage full
```

For fix planning:
```bash
./bin/run_all_audits.sh --stage autofix
```

For schema validation from the repository root:
```bash
python3 -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
python3 -m core.schema_validation --input docs/terminology/betaxi_glossary_official.json --schema schemas/glossary.schema.json
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
  - `Results/per_tool/`
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
  - place the bundle in `vendor/LanguageTool-6.6`
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
  - grammar falls back to local rules
- No local LanguageTool:
  - grammar falls back to local rules
- No optional Python packages:
  - core audit, aggregation, and fix-planning still work
- No optional NLP corpora:
  - future NLP-heavy optional checks may be reduced, but the main toolkit still works
- No `pytest`:
  - the toolkit still runs, but the regression suite cannot be executed

---

## العربية

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
- Java
  - مطلوب فقط لتشغيل LanguageTool المحلي
- LanguageTool المحلي
  - متوقع داخل `vendor/LanguageTool-6.6`

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
تأكد من وجود:
- `vendor/LanguageTool-6.6/languagetool-commandline.jar`

### إذا كان LanguageTool مفقوداً
ضع نسخة متوافقة داخل:
- `vendor/LanguageTool-6.6/`

وعند غيابه، ستستمر طبقة القواعد بالعمل باستخدام قواعد محلية أخف.

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
python3 -m core.schema_validation --input docs/terminology/betaxi_glossary_official.json --schema schemas/glossary.schema.json
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
  - `Results/per_tool/`
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
  - ضعها داخل `vendor/LanguageTool-6.6`
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
  - تدقيق القواعد يرجع إلى القواعد المحلية
- غياب LanguageTool المحلي:
  - تدقيق القواعد يرجع إلى القواعد المحلية
- غياب الحزم الاختيارية:
  - تبقى الطبقات الأساسية والتجميع وخطة الإصلاح عاملة
- غياب `pytest`:
  - تبقى الحزمة عاملة، لكن لن تتمكن من تشغيل مجموعة الاختبارات
