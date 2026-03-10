import json

REVIEW_PROMPT = """
You are an expert localization quality assurance (L10n QA) engine.
Your task is to review a translation and suggest a better version if applicable.

RULES:
1. Only suggest a change if it significantly improves quality, naturalness, or accuracy.
2. YOU MUST MAINTAIN ALL PLACEHOLDERS (e.g., {{name}}, %s, %(count)d).
3. YOU MUST MAINTAIN HTML TAGS.
4. YOU MUST MAINTAIN NEWLINE CHARACTERS (\\n).
5. DO NOT change the meaning unless it is clearly wrong.
6. Provide your response strictly in the following JSON format:
{{
    "suggestion": "The improved translation or original if no change needed",
    "reason": "Short reason for the change in English, or empty string if no change"
}}

CONTEXT:
Source Language: {source_lang}
Target Language: {target_lang}
Source Text: "{source_text}"
Current Translation: "{target_text}"
"""

def get_review_prompt(source_text, target_text, source_lang="en", target_lang="ar"):
    return REVIEW_PROMPT.format(
        source_text=source_text,
        target_text=target_text,
        source_lang=source_lang,
        target_lang=target_lang
    )
