import pytest
from pathlib import Path
from l10n_audit.core.workspace import prepare_audit_workspace
from l10n_audit.fixes.apply_safe_fixes import preprocess_source_text

def test_preprocess_source_text_basic():
    # Test common contractions
    assert preprocess_source_text("dont do that") == "don't do that"
    assert preprocess_source_text("cant believe it") == "can't believe it"
    assert preprocess_source_text("wont happen") == "won't happen"
    assert preprocess_source_text("it isnt true") == "it isn't true"

def test_preprocess_source_text_sorting():
    # This is a bit internal, but we want to ensure "you're" doesn't get messed up if "you" was a replacement
    # Our current dict doesn't have "you", but let's test the logic by adding a temporary rule if we could
    # Since we can't easily modify the dict in the module for the test without monkeypatching:
    
    from l10n_audit.fixes.apply_safe_fixes import SAFE_REPLACEMENTS
    original = SAFE_REPLACEMENTS.copy()
    try:
        SAFE_REPLACEMENTS["apple"] = "fruit"
        SAFE_REPLACEMENTS["applesauce"] = "sauce"
        # If sorted correctly (sauce first), "applesauce" -> "sauce"
        # If sorted incorrectly (apple first), "applesauce" -> "fruitsauce"
        assert preprocess_source_text("applesauce") == "sauce"
    finally:
        # Restore
        SAFE_REPLACEMENTS.clear()
        SAFE_REPLACEMENTS.update(original)

def test_workspace_isolation_flow(tmp_path):
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    
    # Create some locale files
    locales_dir = project_root / "locales"
    locales_dir.mkdir()
    en_file = locales_dir / "en.json"
    ar_file = locales_dir / "ar.json"
    en_file.write_text('{"key": "value"}')
    ar_file.write_text('{"key": "قيمة"}')
    
    # Mock runtime
    class MockRuntime:
        def __init__(self):
            self.project_root = project_root
            self.locales_dir = locales_dir
            self.en_file = en_file
            self.ar_file = ar_file
            self.locale_format = "json"
            self.target_locales = ("ar",)
            self.results_dir = project_root / "Results"
            self.original_en_file = None
            self.original_ar_file = None
            
    runtime = MockRuntime()
    
    # Prepare workspace
    prepare_audit_workspace(runtime)
    
    workspace_dir = project_root / ".l10n-audit" / "workspace"
    assert workspace_dir.exists()
    assert (workspace_dir / "en.json").exists()
    assert (workspace_dir / "ar.json").exists()
    
    # Verify runtime has original paths (captured before redirect)
    assert runtime.original_en_file == en_file
    assert runtime.original_ar_file == ar_file
    
    # Verify runtime now points to workspace copies
    assert runtime.en_file == workspace_dir / "en.json"
    assert runtime.ar_file == workspace_dir / "ar.json"

def test_workspace_isolation_laravel(tmp_path):
    project_root = tmp_path / "laravel"
    project_root.mkdir()
    
    lang_dir = project_root / "resources" / "lang"
    lang_dir.mkdir(parents=True)
    en_dir = lang_dir / "en"
    ar_dir = lang_dir / "ar"
    en_dir.mkdir()
    ar_dir.mkdir()
    (en_dir / "auth.php").write_text("<?php return [];")
    (ar_dir / "auth.php").write_text("<?php return [];")
    
    class MockRuntime:
        def __init__(self):
            self.project_root = project_root
            self.locales_dir = lang_dir
            self.en_file = en_dir
            self.ar_file = ar_dir
            self.locale_format = "laravel_php"
            self.target_locales = ("ar",)
            self.results_dir = project_root / "Results"
            self.original_en_file = None
            self.original_ar_file = None
            
    runtime = MockRuntime()
    prepare_audit_workspace(runtime)
    
    workspace_dir = project_root / ".l10n-audit" / "workspace"
    assert workspace_dir.exists()
    assert (workspace_dir / "en" / "auth.php").exists()
    assert (workspace_dir / "ar" / "auth.php").exists()
    
    # Test directory to directory mapping
    assert runtime.en_file == workspace_dir / "en"
    assert runtime.ar_file == workspace_dir / "ar"
    assert runtime.original_en_file == en_dir
    assert runtime.original_ar_file == ar_dir
