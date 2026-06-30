import base64
import logging
import io
import tiktoken
from PIL import Image

logger = logging.getLogger(__name__)

# Model Context limits
MODEL_CONTEXT_LIMITS = {
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "gpt-3.5-turbo": 16385,
    "llama3:8b": 8000,
    "llama3": 8000,
}
DEFAULT_CONTEXT_LIMIT = 8000

def estimate_text_tokens(text: str, model_name: str = "gpt-4o-mini") -> int:
    """
    Estimates token count for input text using tiktoken encoding.
    """
    try:
        # Resolve standard OpenAI model names to encoding
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

def estimate_image_tokens(base64_image: str, detail: str = "low") -> int:
    """
    Estimates token count for images using OpenAI visual token formula.
    """
    if detail == "low":
        return 85
        
    try:
        # Remove data URI headers if present (e.g. data:image/png;base64,...)
        if "," in base64_image:
            base64_image = base64_image.split(",")[1]
            
        img_data = base64.b64decode(base64_image)
        img = Image.open(io.BytesIO(img_data))
        width, height = img.size
        
        # 1. Scale image to fit within 2048 x 2048 square
        if width > 2048 or height > 2048:
            aspect_ratio = width / height
            if width > height:
                width = 2048
                height = int(2048 / aspect_ratio)
            else:
                height = 2048
                width = int(2048 * aspect_ratio)
                
        # 2. Scale shortest side to 768px
        if width < height:
            aspect_ratio = height / width
            width = 768
            height = int(768 * aspect_ratio)
        else:
            aspect_ratio = width / height
            height = 768
            width = int(768 * aspect_ratio)
            
        # 3. Calculate 512x512 tiles
        tiles_w = (width + 511) // 512
        tiles_h = (height + 511) // 512
        total_tiles = tiles_w * tiles_h
        
        return total_tiles * 170 + 85
    except Exception as e:
        logger.warning("Could not calculate high-detail image tokens, falling back to standard page limit: %s", e)
        # Default fallback for A4 page high detail is 1105 tokens (6 tiles)
        return 1105

def estimate_prompt_tokens(ocr_text: str, images: list[str], model_name: str = "gpt-4o-mini") -> int:
    """
    Aggregates text and image token counts for prompt estimation.
    """
    text_tokens = estimate_text_tokens(ocr_text, model_name)
    image_tokens = sum(estimate_image_tokens(img) for img in images)
    return text_tokens + image_tokens

def check_token_guardrails(
    ocr_text: str, 
    images: list[str], 
    tenant_id: str, 
    model_name: str = "gpt-4o-mini", 
    estimated_output: int = 4096
) -> tuple[bool, int, int]:
    """
    Pre-flight check: validates if the prompt + output tokens fit within the model context limit.
    Logs usage stats tagged with tenant_id for attribution.
    """
    # Clean up model name from full path or prefix
    clean_model_name = model_name.lower().split("/")[-1]
    
    input_tokens = estimate_prompt_tokens(ocr_text, images, clean_model_name)
    limit = MODEL_CONTEXT_LIMITS.get(clean_model_name, DEFAULT_CONTEXT_LIMIT)
    
    total_tokens = input_tokens + estimated_output
    is_safe = total_tokens <= limit
    
    # Log usage stats with tenant_id for monitoring and cost-attribution
    logger.info(
        "[Token Usage Log] tenant_id=%s model=%s input_tokens=%d estimated_output=%d limit=%d total_tokens=%d status=%s",
        tenant_id, model_name, input_tokens, estimated_output, limit, total_tokens, "PASS" if is_safe else "BLOCKED"
    )
    
    return is_safe, input_tokens, limit
