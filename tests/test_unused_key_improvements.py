import pytest
from pathlib import Path
from core.usage_scanner import scan_code_usage

def test_wrapper_usage_detection(tmp_path):
    # 1. Create a dummy code file with wrapper usage
    code_dir = tmp_path / "lib"
    code_dir.mkdir()
    code_file = code_dir / "main.dart"
    code_file.write_text("""
        var x = t("ride_started");
        var y = translate('1_of_3');
        var z = i18n("unknown_key");
    """)

    # 2. Run scan
    results = scan_code_usage(
        code_dirs=[code_dir],
        patterns=[],
        allowed_extensions=[".dart"],
        wrappers=["t", "translate", "i18n"]
    )

    static_occurrences = results["static_occurrences"]
    
    # 3. Assertions
    assert "ride_started" in static_occurrences
    assert "1_of_3" in static_occurrences
    assert "unknown_key" in static_occurrences
    
    # Verify snippet and line number
    occ = static_occurrences["ride_started"][0]
    assert occ["line"] == 2 # line 2
    assert 't("ride_started")' in occ["text"]

def test_accessor_usage_detection(tmp_path):
    # 1. Create a dummy code file with accessor usage
    code_dir = tmp_path / "lib"
    code_dir.mkdir(exist_ok=True)
    code_file = code_dir / "generated.dart"
    code_file.write_text("""
        print(LocaleKeys.ride_started.tr);
        print(AppStrings.homeTitle);
        print(S.of(context).login_button);
        print(context.l10n.signupButton);
    """)

    # 2. Run scan with locale_keys for camelCase mapping
    locale_keys = {"ride_started", "home_title", "login_button", "signup_button"}
    results = scan_code_usage(
        code_dirs=[code_dir],
        patterns=[],
        allowed_extensions=[".dart"],
        accessors=["LocaleKeys", "AppStrings"],
        locale_keys=locale_keys
    )

    static_occurrences = results["static_occurrences"]
    
    # 3. Assertions
    assert "ride_started" in static_occurrences
    assert "home_title" in static_occurrences # camelCase mapped to snake_case
    assert "login_button" in static_occurrences # S.of(context)
    assert "signup_button" in static_occurrences # context.l10n + camelCase
    
    # Verify mapping
    assert "homeTitle" in results["static_raw_keys"]["home_title"]

def test_config_usage_detection(tmp_path):
    # 1. Create a dummy code file with config usage
    code_dir = tmp_path / "lib"
    code_dir.mkdir(exist_ok=True)
    
    # Test JSON-style and Dart-style map references
    code_file = code_dir / "config.dart"
    code_file.write_text("""
        const uiSchema = {
            "titleKey": "ride_started",
            'labelKey': 'login_button',
            translation_key: "signup_button",
            custom_key: "home_title"
        };
    """)

    # 2. Run scan with custom config_fields
    results = scan_code_usage(
        code_dirs=[code_dir],
        patterns=[],
        allowed_extensions=[".dart"],
        config_fields=["titleKey", "label_key", "translation_key", "custom_key"]
    )

    static_occurrences = results["static_occurrences"]
    
    # 3. Assertions
    assert "ride_started" in static_occurrences
    assert "signup_button" in static_occurrences
    assert "home_title" in static_occurrences
    # Note: labelKey in code vs label_key in patterns is literal match, 
    # but the regex covers labelKey if we add it exactly.
    
    # Test with labelKey specifically
    results2 = scan_code_usage(
        code_dirs=[code_dir],
        patterns=[],
        allowed_extensions=[".dart"],
        config_fields=["labelKey"]
    )
    assert "login_button" in results2["static_occurrences"]

def test_dynamic_inference_patterns(tmp_path):
    # 1. Create a dummy code file with dynamic patterns
    code_dir = tmp_path / "lib"
    code_dir.mkdir(exist_ok=True)
    code_file = code_dir / "dynamic.dart"
    code_file.write_text("""
        var s = "${step}_of_3".tr;
        var p = "status_" + currentStatus;
        var b = "step_" + index + "_label".tr;
    """)

    # 2. Run scan
    results = scan_code_usage(
        code_dirs=[code_dir],
        patterns=[],
        allowed_extensions=[".dart"]
    )
    
    # 3. Assertions
    exprs = [d["expression"] for d in results["dynamic_examples"]]
    
    # Check if we caught the patterns
    # The scanner normalizes "status_" + var to "status_ + var"
    assert "${step}_of_3" in exprs
    assert "status_ + var" in exprs
    assert "step_ + var + _label" in exprs

if __name__ == "__main__":
    pytest.main([__file__])
