from transformers import AutoModel, AutoTokenizer, AutoConfig
import torch
import re
import os
from huggingface_hub.inference._text_generation import TextGenerationStreamResponse, Token
from collections.abc import Iterable
from typing import Any, Protocol

from conversation import Conversation, Role


TOOL_PROMPT = 'Answer the following questions as best as you can. You have access to the following tools:'
OBS_PROMPT = "You have used tools and got the related information. Using the following tool results answering the previous questions: "

def stream_chat(model, tokenizer, query: str, history: list[tuple[str, str]] = None, role: str = "user",
                    past_key_values=None,max_length: int = 8192, do_sample=True, top_p=0.8, temperature=0.8,
                    logits_processor=None, return_past_key_values=False, **kwargs):
        
    from transformers.generation.logits_process import LogitsProcessor
    from transformers.generation.utils import LogitsProcessorList

    class InvalidScoreLogitsProcessor(LogitsProcessor):
        def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> torch.FloatTensor:
            if torch.isnan(scores).any() or torch.isinf(scores).any():
                scores.zero_()
                scores[..., 5] = 5e4
            return scores

    if history is None:
        history = []
    if logits_processor is None:
        logits_processor = LogitsProcessorList()
    logits_processor.append(InvalidScoreLogitsProcessor())
    eos_token_id = [tokenizer.eos_token_id, tokenizer.get_command("<|user|>"),
                    tokenizer.get_command("<|observation|>")]
    gen_kwargs = {"max_length": max_length, "do_sample": do_sample, "top_p": top_p,
                    "temperature": temperature, "logits_processor": logits_processor, **kwargs}
    if past_key_values is None:
        inputs = tokenizer.build_chat_input(query, history=history, role=role)
    else:
        inputs = tokenizer.build_chat_input(query, role=role)
    inputs = inputs.to(model.device)
    if past_key_values is not None:
        past_length = past_key_values[0][0].shape[0]
        if model.transformer.pre_seq_len is not None:
            past_length -= model.transformer.pre_seq_len
        inputs.position_ids += past_length
        attention_mask = inputs.attention_mask
        attention_mask = torch.cat((attention_mask.new_ones(1, past_length), attention_mask), dim=1)
        inputs['attention_mask'] = attention_mask
    history.append({"role": role, "content": query})
    for outputs in model.stream_generate(**inputs, past_key_values=past_key_values,
                                        eos_token_id=eos_token_id, return_past_key_values=return_past_key_values,
                                        **gen_kwargs):
        if return_past_key_values:
            outputs, past_key_values = outputs
        outputs = outputs.tolist()[0][len(inputs["input_ids"][0]):]
        response = tokenizer.decode(outputs)
        if response and response[-1] != "�":
            new_history = history
            if return_past_key_values:
                yield response, new_history, past_key_values
            else:
                yield response, new_history

# class Client(Protocol):         # 协议类只用于代码静态检查
#     def generate_stream(self,
#         system: str | None,
#         tools: list[dict] | None,
#         history: list[Conversation],
#         **parameters: Any
#     ) -> Iterable[TextGenerationStreamResponse]:
#         ...


class HFClient:
    def __init__(self, model_path: str, tokenizer_path: str, pt_checkpoint: str | None = None, gpu: str = 0, ):
        self.model_path = model_path
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

        if pt_checkpoint is not None:
            config = AutoConfig.from_pretrained(model_path, trust_remote_code=True, pre_seq_len=128)
            self.model = AutoModel.from_pretrained(model_path, trust_remote_code=True, config=config)
            prefix_state_dict = torch.load(os.path.join(pt_checkpoint, "pytorch_model.bin"))
            new_prefix_state_dict = {}
            for k, v in prefix_state_dict.items():
                if k.startswith("transformer.prefix_encoder."):
                    new_prefix_state_dict[k[len("transformer.prefix_encoder."):]] = v
            print("Loaded from pt checkpoints", new_prefix_state_dict.keys())
            self.model.transformer.prefix_encoder.load_state_dict(new_prefix_state_dict)
        else:
            self.model = AutoModel.from_pretrained(model_path, trust_remote_code=True)

        self.model = self.model.to(
            f'cuda:{gpu}' if torch.cuda.is_available() else
            'mps' if torch.backends.mps.is_available() else
            'cpu'
        ).eval()



    def generate_stream(self,
        system: str | None,
        tools: list[dict] | None,
        history: list[Conversation],
        **parameters: Any
    ) -> Iterable[TextGenerationStreamResponse]:

        chat_history = []

        for conversation in history[:-1]:
            chat_history.append({
                'role': str(conversation.role).removeprefix('<|').removesuffix('|>'),
                'content': conversation.content,
            })
        
        chat_history.append({
            'role': 'system',
            'content': OBS_PROMPT if history[-1].role==Role.OBSERVATION else TOOL_PROMPT,
        })

        if tools:
            chat_history[-1]['tools'] = tools

        # chat_history.append({
        #         'role': str(history[-1].role).removeprefix('<|').removesuffix('|>'),
        #         'content': history[-1].content,
        #     })


        query = history[-1].content
        role = str(history[-1].role).removeprefix('<|').removesuffix('|>')

        text = ''
        
        for new_text, _ in stream_chat(self.model,
            self.tokenizer,
            query,
            chat_history,
            role,
            **parameters,
        ):
            word = new_text.removeprefix(text)
            word_stripped = word.strip()
            text = new_text
            yield TextGenerationStreamResponse(
                generated_text=text,
                token=Token(
                    id=0,
                    logprob=0,
                    text=word,
                    special=word_stripped.startswith('<|') and word_stripped.endswith('|>'),
                )
            )

## utils


def append_conversation(
    conversation: Conversation,
    history: list[Conversation],
    placeholder=None, 
    # placeholder: DeltaGenerator | None=None,
) -> None:
    history.append(conversation)
    # conversation.show(placeholder)

def extract_code(text: str) -> str:
    pattern = r'```([^\n]*)\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[-1][1]

def tool_call(*args, **kwargs) -> dict:
    print("=== Tool call:")
    print(args)
    print(kwargs)
    return kwargs

def postprocess_text(text: str) -> str:
    text = text.replace("\(", "$")
    text = text.replace("\)", "$")
    text = text.replace("\[", "$$")
    text = text.replace("\]", "$$")
    text = text.replace("<|assistant|>", "")
    text = text.replace("<|observation|>", "")
    text = text.replace("<|system|>", "")
    text = text.replace("<|user|>", "")
    text_split = text.strip('\n ').split('\n')
    if len(text_split)==2 and text_split[1].strip().startswith(text_split[0].strip()):
        text = text_split[1]
        
    return "\n"+text.strip()