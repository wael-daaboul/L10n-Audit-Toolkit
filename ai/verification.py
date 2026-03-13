import re
import logging

def check_placeholders(source, suggestion):
    """
    Checks if all placeholders in the source are present in the suggestion.
    Supports: {name}, %s, %(count)d, etc.
    """
    # Simple brackets: {name}
    source_placeholders = set(re.findall(r"\\{[^}]+\\}", source))
    suggest_placeholders = set(re.findall(r"\\{[^}]+\\}", suggestion))
    
    if not source_placeholders.issubset(suggest_placeholders):
        missing = source_placeholders - suggest_placeholders
        return False, f"Missing placeholders: {', '.join(missing)}"
    
    # Classic printf style: %s, %d, %(count)s
    printf_regex = r"%(\\([^)]+\\))?[-#0 +]*[\\d\\.]*[hlL]*[diouxXeEfFgGcrs%]"
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
    source_newlines = source.count("\\n") + source.count("\\n")
    suggest_newlines = suggestion.count("\\n") + suggestion.count("\\n")
    
    if suggest_newlines < source_newlines:
        return False, f"Missing newlines: expected at least {source_newlines}, got {suggest_newlines}"
    
    return True, ""

def check_html(source, suggestion):
    """
    Checks if HTML tags are intact.
    """
    source_tags = set(re.findall(r"<[^>]+>", source))
    suggest_tags = set(re.findall(r"<[^>]+>", suggestion))
    
    if not source_tags.issubset(suggest_tags):
        missing = source_tags - suggest_tags
        return False, f"Missing HTML tags: {', '.join(missing)}"
    
    return True, ""

def verify_batch_fixes(original_batch, ai_fixes):
    """
    Verifies a batch of AI suggestions.
    Checks placeholders, newlines, and HTML tags.
    If a suggestion fails verification, it is safely discarded.
    """
    verified_fixes = []
    source_by_key = {item["key"]: item["source"] for item in original_batch}
    target_by_key = {item["key"]: item["current_translation"] for item in original_batch}
    
    for fix in ai_fixes:
        key = fix.get("key")
        suggestion = fix.get("suggestion")
        
        if not key or not suggestion or key not in source_by_key:
            continue
            
        source = source_by_key[key]
        target = target_by_key[key]
        
        # If suggestion is identical, skip
        if suggestion.strip() == target.strip():
            continue
            
        # Verification
        v_tasks = [
            check_placeholders(source, suggestion),
            check_newlines(source, suggestion),
            check_html(source, suggestion)
        ]
        
        failed = [msg for ok, msg in v_tasks if not ok]
        
        if not failed:
            verified_fixes.append({
                "key": key,
                "issue_type": "ai_suggestion",
                "severity": "info",
                "message": f"AI Suggestion: {fix.get('reason', '')}",
                "source": source,
                "target": target,
                "suggestion": suggestion
            })
        else:
            logging.debug(f"AI Suggestion for {key} rejected by verification: {failed}")
            
    return verified_fixes
