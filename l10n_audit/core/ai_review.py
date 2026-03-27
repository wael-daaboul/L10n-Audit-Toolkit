import logging
import json
from pathlib import Path
from l10n_audit.core.results_manager import save_to_staged
from l10n_audit.core.glossary_engine import validate_item

class AISiftingReviewer:
    """
    Advanced AI Review Engine that sifts through results, 
    persisting valid items immediately and retrying only failed ones.
    """
    def __init__(self, ai_client, config, glossary, project_root: Path):
        self.ai_client = ai_client
        self.config = config
        self.glossary = glossary
        self.project_root = project_root
        self.logger = logging.getLogger("l10n_audit.ai_sifter")

    def process_batch_with_sifting(self, batch_items, retry_count=0):
        """
        يقوم بمعالجة الدفعة، يقبل الجمل الصحيحة فوراً، ويعيد المحاولة للفاشلة فقط.
        """
        max_retries = self.config.get("max_retries", 5)
        
        if retry_count > max_retries:
            self.logger.error(f"❌ Failed to fix {len(batch_items)} items after {max_retries} retries. Skipping.")
            return []

        # إعداد البرومبت المدمج (العام والصارم)
        system_prompt = (
            "You are a Professional Localization & QA Engine. Your mission is to translate or review software strings with 100% technical and linguistic accuracy.\\n"
            "STRICT RULES:\\n"
            "1. Glossary Compliance: You MUST strictly follow the provided 'Approved Terms'. Using forbidden terms results in immediate rejection.\\n"
            "2. Technical Integrity: Preserve all placeholders (e.g., {name}, :value, %s) exactly as they are. Do NOT modify them.\\n"
            "3. Context Awareness: If the key is in snake_case or camelCase, translate the value only.\\n"
            "4. Format: Output must be a valid JSON object. No conversational text.\\n"
            "5. Failure to comply will trigger a re-processing of your output."
        )

        # طلب المراجعة من AI
        # We assume ai_client has a request method that takes prompt and batch
        # If it returns a dict, we wrap it or handle it.
        try:
            response = self.ai_client.request(system_prompt, batch_items)
        except Exception as e:
            self.logger.error(f"AI Client request failed: {e}")
            return []
        
        passed_items = []
        failed_items = []

        # Handle different response formats (object with .fixes or dict with ['fixes'])
        fixes = []
        if hasattr(response, 'fixes'):
            fixes = response.fixes
        elif isinstance(response, dict):
            fixes = response.get('fixes', [])
        else:
            self.logger.warning(f"Unexpected AI response format: {type(response)}")

        for item in fixes:
            # فحص الجملة بشكل فردي مقابل القاموس
            is_valid, errors = validate_item(item, self.glossary)
            
            if is_valid:
                # ✅ نجحت: احفظها فوراً في staged لتوفير الذاكرة والـ Tokens
                save_to_staged(self.project_root, item)
                passed_items.append(item)
            else:
                # ❌ فشلت: أضفها لقائمة الإعادة مع سبب الفشل
                item['error_hint'] = "; ".join(errors)
                failed_items.append(item)

        # إذا وجد فشل، أعد المحاولة للجمل الفاشلة فقط
        if failed_items:
            self.logger.warning(f"⚠️ Sifting: {len(failed_items)} items failed. Retrying only failed items (Attempt {retry_count + 1}/{max_retries})")
            # تقليل الـ batch_size تلقائياً في الإعادة لتجنب القطع (JSON Truncation)
            passed_items.extend(self.process_batch_with_sifting(failed_items, retry_count + 1))

        return passed_items
