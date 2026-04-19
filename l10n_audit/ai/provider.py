import json
import logging
import litellm
import time
from dataclasses import dataclass
from typing import Any
from l10n_audit.ai.verification import validate_glossary_compliance
from l10n_audit.core.ai_trace import is_ai_debug_mode

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

DEFAULT_REQUEST_TIMEOUT_SECONDS = 60


def _suppress_provider_noise_in_normal_mode() -> None:
    if is_ai_debug_mode():
        return
    for logger_name in ("litellm", "LiteLLM", "httpx", "openai"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)


@dataclass
class AIProviderError(RuntimeError):
    category: str
    message: str
    details: dict[str, Any] | None = None
    cause: Exception | None = None

    def __str__(self) -> str:
        return self.message


def classify_provider_exception(exc: Exception) -> str:
    """Map provider/network failures to deterministic reason codes."""
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

    timeout_markers = ("timeout", "timed out", "readtimeout", "apitimeouterror", "timeoutexception")
    connection_markers = ("connection", "connecterror", "apiconnectionerror", "ssl", "dns", "network")
    rate_limit_markers = ("rate limit", "too many requests", "quota")

    if isinstance(exc, TimeoutError) or any(m in text or m in name for m in timeout_markers):
        return "provider_timeout"
    if status_code == 429 or any(m in text for m in rate_limit_markers):
        return "provider_rate_limited"
    if any(m in text or m in name for m in connection_markers):
        return "provider_connection_error"
    if isinstance(status_code, int) and status_code >= 400:
        return "provider_api_error"
    return "provider_api_error"

def clean_json_response(raw_content):
    """
    Ensures the response is a valid JSON string even if truncated or wrapped in markdown.
    """
    import re
    # 0. strip markdown code blocks
    content = raw_content.strip()
    if content.startswith("```"):
        # Remove ```json or just ```
        content = re.sub(r"^```(?:json)?", "", content)
        # Remove trailing ```
        content = re.sub(r"```$", "", content).strip()

    # Look for the outermost JSON object or array if still not clean
    json_match = re.search(r'(\{.*\}|\[.*\])', content, re.DOTALL)
    if json_match:
        content = json_match.group(1)
        # Repair truncated JSON by closing open braces
        if content.count('{') > content.count('}'):
            content += '}' * (content.count('{') - content.count('}'))
        if content.count('[') > content.count(']'):
            content += ']' * (content.count('[') - content.count(']'))
        return content
    return content

def request_ai_review(prompt, config, original_batch=None, glossary=None, max_retries=None, raise_on_provider_error=False):
    """
    Connects to AI using litellm to get a review suggestion.
    Implements a SOFT enforcement mechanism for glossary compliance.
    """
    current_prompt = prompt
    negative_feedback = ""
    last_errors = []
    
    if max_retries is None:
        max_retries = config.get("max_retries", 5)

    for attempt in range(max_retries):
        full_prompt = current_prompt
        if negative_feedback:
            # Inject negative prompt to force correction
            full_prompt += f"\n\n### IMPORTANT FIX NEEDED (Attempt {attempt + 1})\n{negative_feedback}\nPLEASE RE-EVALUATE AND ENSURE GLOSSARY COMPLIANCE."

        try:
            response = request_ai_review_litellm(full_prompt, config)
        except AIProviderError:
            if raise_on_provider_error:
                raise
            return None
        
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
                    ok, reason = validate_glossary_compliance(suggestion, source_by_key[key], glossary, key=key)
                    if not ok:
                        compliance_errors.append(f"Key '{key}': {reason}")
                        # Soft Enforcement: Mark for review instead of strictly rejecting the batch
                        fix["needs_review"] = True
                        fix["compliance_warning"] = reason
            
            if compliance_errors and attempt < max_retries - 1:
                last_errors = compliance_errors
                logging.warning(f"AI Response has glossary compliance warnings (attempt {attempt + 1}): {compliance_errors}")
                negative_feedback = "The previous response violated terminology rules:\n- " + "\n- ".join(compliance_errors[:5])
                continue # Retry to get a better version, but won't hard-crash if last attempt
            
            # On last attempt or if successful, return what we have with flags
            return response

        return response
    
    if last_errors:
        err_msg = f"Glossary enforcement warnings after {max_retries} attempts for sample keys."
        audit_logger.warning(err_msg)
        print(f"\n⚠️ [GLOSSARY WARNING]: {err_msg} Check the report for flagged items.")
            
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
    timeout_seconds = config.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)
    try:
        timeout_seconds = float(timeout_seconds)
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_REQUEST_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        timeout_seconds = DEFAULT_REQUEST_TIMEOUT_SECONDS
    _suppress_provider_noise_in_normal_mode()
    
    if not api_key:
        logging.warning("AI Review skipped: No API Key provided.")
        return None

    messages = [
        {"role": "system", "content": "You are a localization expert. You MUST return a valid JSON object EXCLUSIVELY. No conversational text, no backticks, no notes before or after the JSON. Follow the glossary strictly."},
        {"role": "user", "content": prompt}
    ]
    
    # Provider hints
    # Some providers need different handling for JSON mode
    response_format = None
    if "openai" in (api_base or "").lower() or "gpt" in model.lower() or "deepseek" in (api_base or "").lower():
        response_format = {"type": "json_object"}

    last_provider_error: AIProviderError | None = None
    for attempt in range(max_retries):
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_key=api_key,
                base_url=api_base,
                temperature=0.0,
                response_format=response_format,
                timeout=timeout_seconds,
                num_retries=1 # handle retries manually for better logging
            )
            
            content = response.choices[0].message.content
            content = clean_json_response(content)
 
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                category = "provider_invalid_response"
                last_provider_error = AIProviderError(
                    category=category,
                    message="AI provider returned invalid JSON response.",
                    details={"attempt": attempt + 1, "max_attempts": max_retries, "content_preview": content[:160]},
                )
                if is_ai_debug_mode():
                    logging.exception(
                        "AI Review LiteLLM invalid response (attempt %d/%d): %s",
                        attempt + 1,
                        max_retries,
                        content[:300],
                    )
                else:
                    logging.debug(
                        "AI Review provider error [%s] on attempt %d/%d",
                        category,
                        attempt + 1,
                        max_retries,
                    )
                continue

        except Exception as e:
            category = classify_provider_exception(e)
            last_provider_error = AIProviderError(
                category=category,
                message=f"AI provider request failed ({category}).",
                details={"attempt": attempt + 1, "max_attempts": max_retries, "error_type": type(e).__name__, "error": str(e)},
                cause=e,
            )
            if is_ai_debug_mode():
                logging.exception(
                    "AI Review LiteLLM request failure [%s] (attempt %d/%d)",
                    category,
                    attempt + 1,
                    max_retries,
                )
            else:
                logging.debug(
                    "AI Review provider error [%s] on attempt %d/%d",
                    category,
                    attempt + 1,
                    max_retries,
                )
            if category == "provider_rate_limited" and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
            if attempt < max_retries - 1:
                continue
            raise last_provider_error from e

    if last_provider_error is not None:
        raise last_provider_error from last_provider_error.cause
    raise AIProviderError(
        category="provider_invalid_response",
        message="AI provider returned no usable response.",
    )
