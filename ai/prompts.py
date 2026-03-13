import json

REVIEW_PROMPT = """
You are an expert localization quality assurance (L10n QA) engine and Auto-Fixer.
Your task is to fix translations based on identified issues and project rules.

RULES:
1. You will receive a JSON array of translation issues.
2. You must return a JSON object containing a "fixes" array with the exact same length. Each object in the array should contain the 'key', the fixed 'suggestion', and a short 'reason' for your change.
3. YOU MUST MAINTAIN ALL PLACEHOLDERS (e.g., {{name}}, %s, %(count)d).
4. YOU MUST MAINTAIN HTML TAGS.
5. YOU MUST MAINTAIN NEWLINE CHARACTERS (\\n).
6. Respect the provided GLOSSARY. If a term is in the glossary, use it.
7. Return valid JSON only. Your response must be parseable as a JSON object.

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
    glossary_str = "{}"
    if glossary_terms:
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
