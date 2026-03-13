import json
import logging
import urllib.request
import urllib.error
import time

def request_ai_review(prompt, config, max_retries=3):
    """
    Connects to an OpenAI-compatible API to get a review suggestion using urllib.
    Handles batch requests and implements exponential backoff.
    
    Returns:
        dict: The response JSON {'fixes': [...]} or None.
    """
    api_key = config.get('api_key')
    api_base = config.get('api_base', 'https://api.openai.com/v1')
    model = config.get('model', 'gpt-4o-mini')
    
    if not api_key:
        logging.warning("AI Review skipped: No API Key provided.")
        return None

    url = f"{api_base.rstrip('/')}/chat/completions"
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a localization expert. Return JSON ONLY."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0
    }
    
    if "openai" in api_base.lower() or "deepseek" in api_base.lower():
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload).encode("utf-8")
    
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {api_key}")

    retry_delay = 2
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                content = resp_data['choices'][0]['message']['content']
                
                content = content.strip()
                if content.startswith("```"):
                    lines = content.split('\\n')
                    if lines[0].startswith("```json"):
                        content = '\\n'.join(lines[1:-1])
                    elif lines[0].startswith("```"):
                        content = '\\n'.join(lines[1:-1])
                    if content.endswith("```"):
                        content = content.rsplit("```", 1)[0]

                return json.loads(content)

        except urllib.error.HTTPError as e:
            if e.code == 429:
                logging.warning(f"AI Review network error 429 Too Many Requests. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                logging.warning(f"AI Review HTTP error: {e}")
                break
        except urllib.error.URLError as e:
            logging.warning(f"AI Review network error: {e}")
            break
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logging.warning(f"AI Review JSON parsing failure: {e}")
            break
        except Exception as e:
            logging.warning(f"AI Review unexpected error: {e}")
            break
            
    return None
