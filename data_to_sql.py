from transformers import AutoTokenizer, AutoModelForCausalLM
from torch.utils.data import DataLoader
from peft import LoraConfig, get_peft_model, PeftModel, PeftConfig
import torch
import torch.nn as nn


def getLoraModel(model):
    lora_config = LoraConfig(
        r=16,
        target_modules="all-linear",
        lora_dropout = 0.05,
        task_type = "CAUSAL_LM"
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    return model

model_name = "llama3"
model = AutoModelForCausalLM.from_pretrained(model_name)
model = getLoraModel(model)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
