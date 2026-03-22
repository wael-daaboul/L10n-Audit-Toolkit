import json

REVIEW_PROMPT = """
You are a Localization (L10n) Expert for Mobile UIs and an Auto-Fixer.
Your task is to fix translations based on identified issues and project rules.

STRICT RULES:
1. Return JSON ONLY. Your response must be a parseable JSON object.
2. Protect Placeholders: Never translate or modify `{{variables}}`, `{{name}}`, `%s`, or formatting tags (e.g., `<b></b>`, `\\n`). 
3. Strict Brevity: Mobile screens are small. If a short Arabic noun (e.g., 'العنوان') conveys the meaning of an English verb phrase (e.g., 'Add Address'), accept it as CORRECT. Do not demand imperative verbs for UI Labels.
4. Smart Suggestions: Non-Arabic speaking developers rely on you. If a translation is semantically wrong, provide a highly accurate, context-aware Arabic `suggestion`. Do not use literal robotic translations.
5. Respect the provided GLOSSARY. If a term is in the glossary, use it.

Return format:
{{
  "fixes": [
    {{
      "key": "example_key",
      "suggestion": "The improved translation",
      "reason": "Short reason for the change"
    }}
  ]
}}

GLOSSARY:
{glossary}

ISSUES BATCH:
{issues_json}
"""

def get_review_prompt(batch_issues, glossary_terms=None):
    # Backward compatibility: if batch_issues is a string, treat as single source
    if isinstance(batch_issues, str):
        target_text = glossary_terms if isinstance(glossary_terms, str) else ""
        batch_issues = [{
            "key": "manual_review",
            "source": batch_issues,
            "current_translation": target_text,
            "identified_issue": "General Quality Review"
        }]
        # If glossary_terms was target_text, reset it to None for the logic below
        glossary_terms = None

    glossary_str = "{}"
    if isinstance(glossary_terms, dict):
        glossary_items = []
        for term, details in glossary_terms.items():
            translation = details.get("translation", "")
            notes = details.get("notes", "")
            glossary_items.append(f"- {term} -> {translation} ({notes})")
        if glossary_items:
            glossary_str = "\\n".join(glossary_items)
            
    issues_json = json.dumps(batch_issues, ensure_ascii=False, indent=2)
    
    return REVIEW_PROMPT.format(
        glossary=glossary_str,
        issues_json=issues_json
    )
