"""
app/llm/lfm_provider.py

LFMProvider — implements BaseLLMProvider using local transformers.
Uses LiquidAI/LFM2.5-1.2B-Thinking.
"""

from __future__ import annotations

import re
import traceback
from typing import Type, TypeVar
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from pydantic import BaseModel

from app.core.models import ExitSignal
from app.llm.ask_llm import BaseLLMProvider
from app.llm.response_safety import parse_llm_response
from app.utils.logger import logger
from config.llm_config import MAX_OUTPUT_TOKENS_ENTRY, MAX_OUTPUT_TOKENS_EXIT

T = TypeVar("T", bound=BaseModel)


class LFMProvider(BaseLLMProvider):
    """
    On-device LLM provider using LiquidAI LFM 2.5.
    """

    def __init__(self, model_id: str = "LiquidAI/LFM2.5-1.2B-Thinking") -> None:
        logger.info("Initializing Local LFM Model: {}...", model_id)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map="auto" if self.device == "cuda" else None,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                trust_remote_code=True
            )
            
            if self.device == "cpu":
                self.model = self.model.to("cpu")
                
            logger.info("LFM Model loaded on {}.", self.device)
        except Exception:
            logger.exception("FATAL: Failed to load LFM model")
            raise

    def ask(
        self, 
        prompt: str, 
        system_message: str, 
        response_model: Type[T]
    ) -> T:
        """
        Runs local inference and extracts JSON from the thinking model.
        """
        try:
            # Prepare Chat Template
            messages = [
                {"role": "system", "content": f"{system_message}\n\nCRITICAL INSTRUCTION: You must respond ONLY with a raw, valid JSON object matching this schema: {response_model.model_json_schema()}.\nDo not use markdown code blocks like ```json. Do not include <think> tags. Start your response immediately with the character {{ and end it with }}. Do not add any text before or after."},
                {"role": "user", "content": prompt}
            ]
            
            logger.debug("Raw Prompt : {}", messages)
            
            prompt_text = self.tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
            inputs = self.tokenizer(prompt_text, return_tensors="pt").to(self.model.device)
            prompt_length = inputs["input_ids"].shape[1]

            logger.debug("Generating local response for {} tokens...", prompt_length)
            
            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    do_sample=False,
                    repetition_penalty=1.05,
                    max_new_tokens=self._max_new_tokens(response_model),
                )

            # Decode only the NEW tokens
            raw_content = self.tokenizer.decode(output_ids[0][prompt_length:], skip_special_tokens=True)
            # logger.debug("LFM Raw Response: {}", raw_content)

            # Robust JSON extraction
            json_str = self._extract_json(raw_content)
            content_to_parse = json_str if json_str else raw_content
            return parse_llm_response(content_to_parse, response_model, prompt, "LFM")

        except Exception as exc:
            logger.error("LFM local inference failed: {}", exc)
            logger.debug(traceback.format_exc())
            raise

    def _max_new_tokens(self, response_model: Type[T]) -> int:
        return MAX_OUTPUT_TOKENS_EXIT if response_model is ExitSignal else MAX_OUTPUT_TOKENS_ENTRY

    def _extract_json(self, text: str) -> str | None:
        """Extracts the first valid JSON block from text, handling thinking model noise."""
        import json
        
        # 1. Try to find content between triple backticks
        code_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        for block in code_blocks:
            try:
                json.loads(block)
                return block
            except Exception:
                pass
        
        # 2. Brute-force search for balanced braces that parse as JSON
        # Thinking models often put '{' inside their <think> blocks, so we must validate.
        matches = re.finditer(r"\{", text)
        for match in matches:
            start_idx = match.start()
            open_braces = 0
            for i in range(start_idx, len(text)):
                if text[i] == '{': open_braces += 1
                elif text[i] == '}': open_braces -= 1
                
                if open_braces == 0:
                    candidate = text[start_idx:i+1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except Exception:
                        break  # Try the next starting brace
        return None
