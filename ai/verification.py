import re

def check_placeholders(source, suggestion):
    """
    Checks if all placeholders in the source are present in the suggestion.
    Supports: {name}, %s, %(count)d, etc.
    """
    # Simple brackets: {name}
    source_placeholders = set(re.findall(r"\{[^}]+\}", source))
    suggest_placeholders = set(re.findall(r"\{[^}]+\}", suggestion))
    
    if not source_placeholders.issubset(suggest_placeholders):
        missing = source_placeholders - suggest_placeholders
        return False, f"Missing placeholders: {', '.join(missing)}"
    
    # Classic printf style: %s, %d, %(count)s
    # We want to match the WHOLE string to be strict: %[mapping][flags][width][.precision][length]type
    printf_regex = r"%(\([^)]+\))?[-#0 +]*[\d\.]*[hlL]*[diouxXeEfFgGcrs%]"
    source_printf = set(re.findall(printf_regex, source))
    # For source_printf findall returns the group if present. We need the full match.
    source_printf = set(m.group(0) for m in re.finditer(printf_regex, source))
    suggest_printf = set(m.group(0) for m in re.finditer(printf_regex, suggestion))
    
    if not source_printf.issubset(suggest_printf):
        missing = source_printf - suggest_printf
        return False, f"Printf-style placeholders mismatch: missing {', '.join(missing)}"
    
    return True, ""

def check_newlines(source, suggestion):
    """
    Checks if basic newline occurrences are drastically different.
    We don't want the AI to merge lines if layout depends on them.
    """
    source_newlines = source.count("\\n") + source.count("\n")
    suggest_newlines = suggestion.count("\\n") + suggestion.count("\n")
    
    if suggest_newlines < source_newlines:
        return False, f"Missing newlines: expected at least {source_newlines}, got {suggest_newlines}"
    
    return True, ""

def check_html(source, suggestion):
    """
    Checks if HTML tags are intact.
    """
    source_tags = set(re.findall(r"<[^>]+>", source))
    suggest_tags = set(re.findall(r"<[^>]+>", suggestion))
    
    # Verify all source tags exist in the suggestion
    if not source_tags.issubset(suggest_tags):
        missing = source_tags - suggest_tags
        return False, f"Missing HTML tags: {', '.join(missing)}"
    
    return True, ""
