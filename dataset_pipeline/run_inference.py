import argparse
import json
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from dataset_pipeline.prompts import build_messages, extract_sql_from_response

try:
    from peft import PeftModel
except ImportError:
    PeftModel = None

def load_model_and_tokenizer(base_model_id: str, adapter_dir: Path | None = None):
    tokenizer = AutoTokenizer.from_pretrained(base_model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        base_model_id,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    if adapter_dir is not None:
        if PeftModel is None:
            raise RuntimeError("peft is required to load an adapter.")
        model = PeftModel.from_pretrained(model, str(adapter_dir))
    model.eval()
    return model, tokenizer

@torch.inference_mode()
def generate_predictions(
    eval_path: Path,
    output_path: Path,
    base_model_id: str,
    adapter_dir: Path | None = None,
    max_new_tokens: int = 256,
) -> None:
    """
    Runs deterministic inference and saves raw + extracted SQL predictions to JSONL
    so `eval_metrics.py` can score/rescore offline without re-running the GPU.
    """
    model, tokenizer = load_model_and_tokenizer(base_model_id, adapter_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with eval_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            item = json.loads(line)
            messages = build_messages(item["schema_prompt"], item["question"])
            prompt_text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
            generated_ids = output_ids[0][inputs["input_ids"].shape[1] :]
            pred_raw = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            pred_sql = extract_sql_from_response(pred_raw)
            record = {
                **item,
                "pred_raw": pred_raw,
                "pred_sql": pred_sql,
            }
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-path", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--base-model", type=str, required=True)
    parser.add_argument("--adapter-dir", type=Path, default=None)
    args = parser.parse_args()
    generate_predictions(args.eval_path, args.output_path, args.base_model, args.adapter_dir)