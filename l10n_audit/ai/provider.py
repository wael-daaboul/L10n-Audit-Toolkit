import json
import logging
import litellm
import time

def request_ai_review(prompt, config, max_retries=3):
    """
    Connects to AI using litellm to get a review suggestion.
    """
    return request_ai_review_litellm(prompt, config, max_retries)

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
        {"role": "system", "content": "You are a localization expert. Return JSON ONLY."},
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

            return json.loads(content)

        except Exception as e:
            logging.warning(f"AI Review LiteLLM error (attempt {attempt + 1}): {e}")
            if "429" in str(e):
                time.sleep(2 * (attempt + 1))
                continue
            break
            
    return None
