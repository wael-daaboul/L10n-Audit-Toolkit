#!/usr/bin/env python3
import os
import shutil
import logging

def check_java_available() -> bool:
    """
    Return True if Java runtime is available in PATH.
    Respects L10N_SKIP_JAVA_CHECK environment variable.
    """
    if os.environ.get("L10N_SKIP_JAVA_CHECK") == "true":
        return True
        
    return shutil.which("java") is not None

def get_java_missing_warning(language: str = "Arabic") -> str:
    """Returns a formatted warning message for missing Java."""
    return (
        f"⚠️ Java is not installed on your system. The {language} grammar check requires Java to run LanguageTool locally.\n"
        f"💡 Please install Java and rerun this audit for best results. Installation instructions:\n"
        f"   • macOS: brew install openjdk\n"
        f"   • Ubuntu/Debian: sudo apt install default-jre\n"
        f"   • Windows: download from https://adoptium.net/\n"
        f"🔁 Continuing without {language} grammar checks. Other audits will still run."
    )
