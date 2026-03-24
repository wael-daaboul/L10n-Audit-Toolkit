import json
import logging
import litellm
import time
from l10n_audit.ai.verification import verify_batch_fixes, validate_glossary_compliance, GlossaryViolationError

def setup_audit_logger():
    """Configure a file logger for critical audit errors."""
    from pathlib import Path
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "audit_errors.log"
    
    logger = logging.getLogger("l10n_audit.audit_errors")
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
    return logger

audit_logger = setup_audit_logger()

def request_ai_review(prompt, config, original_batch=None, glossary=None, max_retries=3):
    """
    Connects to AI using litellm to get a review suggestion.
    Implements a 3-retry mechanism for glossary compliance.
    """
    current_prompt = prompt
    negative_feedback = ""
    last_errors = []

    for attempt in range(max_retries):
        full_prompt = current_prompt
        if negative_feedback:
            # Inject negative prompt to force correction
            full_prompt += f"\n\n### IMPORTANT FIX NEEDED (Attempt {attempt + 1})\n{negative_feedback}\nPLEASE RE-EVALUATE AND ENSURE GLOSSARY COMPLIANCE."

        response = request_ai_review_litellm(full_prompt, config)
        
        if not response or "fixes" not in response:
            continue

        # If we have original_batch and glossary, we perform an immediate compliance check
        if original_batch and glossary:
            compliance_errors = []
            source_by_key = {item["key"]: item.get("source_text", item.get("source", "")) for item in original_batch}
            
            for fix in response["fixes"]:
                key = fix.get("key")
                suggestion = fix.get("suggestion")
                if key in source_by_key and suggestion:
                    ok, reason = validate_glossary_compliance(suggestion, source_by_key[key], glossary)
                    if not ok:
                        compliance_errors.append(f"Key '{key}': {reason}")
            
            if compliance_errors:
                last_errors = compliance_errors
                logging.warning(f"AI Response failed glossary compliance (attempt {attempt + 1}): {compliance_errors}")
                negative_feedback = "The previous response violated terminology rules:\n- " + "\n- ".join(compliance_errors[:5])
                continue # Retry with negative feedback

        return response
    
    if last_errors:
        err_msg = f"Glossary enforcement failed after {max_retries} attempts: {'; '.join(last_errors[:3])}"
        audit_logger.error(err_msg) # Log to logs/audit_errors.log
        print(f"\n❌ [CRITICAL ERROR]: {err_msg}") # Log to Terminal
        raise GlossaryViolationError(err_msg)
            
    return None


def request_ai_review_litellm(prompt, config, max_retries=3):
    """
    Uses litellm.completion() to handle multi-provider AI calls.
    
    Returns:
        dict: The response JSON {'fixes': [...]} or None.
    """
    api_key = config.get('api_key')
    api_base = config.get('api_base')
    model = config.get('model', 'gpt-4o-mini')
    
    if not api_key:
        logging.warning("AI Review skipped: No API Key provided.")
        return None

    messages = [
        {"role": "system", "content": "You are a localization expert. Return JSON ONLY. Follow the glossary strictly."},
        {"role": "user", "content": prompt}
    ]
    
    # Provider hints
    # Some providers need different handling for JSON mode
    response_format = None
    if "openai" in (api_base or "").lower() or "gpt" in model.lower() or "deepseek" in (api_base or "").lower():
        response_format = {"type": "json_object"}

    for attempt in range(max_retries):
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_key=api_key,
                base_url=api_base,
                temperature=0.0,
                response_format=response_format,
                num_retries=1 # handle retries manually for better logging
            )
            
            content = response.choices[0].message.content
            content = content.strip()
            
            # Clean markdown if present
            if content.startswith("```"):
                if content.startswith("```json"):
                    content = content[len("```json"):]
                elif content.startswith("```"):
                    content = content[len("```"):]
                if content.endswith("```"):
                    content = content.rsplit("```", 1)[0]
                content = content.strip()
 
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logging.warning(f"AI Review LiteLLM: Failed to parse JSON content: {content[:100]}...")
                continue

        except Exception as e:
            logging.warning(f"AI Review LiteLLM error (attempt {attempt + 1}): {e}")
            if "429" in str(e):
                time.sleep(2 * (attempt + 1))
                continue
            break
            
    return None
