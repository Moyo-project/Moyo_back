from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import json

model_name = "naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B"

# 모델 로드
tokenizer = AutoTokenizer.from_pretrained(
    model_name,
    trust_remote_code=True
)

model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto",
    trust_remote_code=True
)

# System Prompt
system_prompt = """
너는 챗봇이다.
"""

# 실제 입력 메시지
user_prompt = """
안녕하세요.
"""

messages = [
    {
        "role": "system",
        "content": system_prompt
    },
    {
        "role": "user",
        "content": user_prompt
    }
]

inputs = tokenizer.apply_chat_template(
    messages,
    tokenize=True,
    add_generation_prompt=True,
    return_tensors="pt",
    return_dict=True
).to(model.device)

print("=== 실제 모델 입력 ===")
print(tokenizer.decode(inputs["input_ids"][0], skip_special_tokens=False))

outputs = model.generate(
    **inputs,
    max_new_tokens=100,
    do_sample=False
)

result = outputs[0][inputs["input_ids"].shape[-1]:]

print("\n=== 출력 ===")
print(tokenizer.decode(result, skip_special_tokens=True))