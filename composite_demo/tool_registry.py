from copy import deepcopy
import inspect
from pprint import pformat
import traceback
from types import GenericAlias
from typing import get_origin, Annotated, Literal

_TOOL_HOOKS = {}
_TOOL_DESCRIPTIONS = {}

def register_tool(func: callable):
    tool_name = func.__name__
    tool_description = inspect.getdoc(func).strip()
    python_params = inspect.signature(func).parameters
    tool_params = []
    for name, param in python_params.items():
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            raise TypeError(f"Parameter `{name}` missing type annotation")
        if get_origin(annotation) != Annotated:
            raise TypeError(f"Annotation type for `{name}` must be typing.Annotated")
        
        typ, (description, required) = annotation.__origin__, annotation.__metadata__
        typ: str = str(typ) if isinstance(typ, GenericAlias) else typ.__name__
        if not isinstance(description, str):
            raise TypeError(f"Description for `{name}` must be a string")
        if not isinstance(required, bool):
            raise TypeError(f"Required for `{name}` must be a bool")

        tool_params.append({
            "name": name,
            "description": description,
            "type": typ,
            "required": required
        })
    tool_def = {
        "name": tool_name,
        "description": tool_description,
        "params": tool_params
    }

    print("[registered tool] " + pformat(tool_def))
    _TOOL_HOOKS[tool_name] = func
    _TOOL_DESCRIPTIONS[tool_name] = tool_def

    return func

def dispatch_tool(tool_name: str, tool_params: dict) -> str:
    if tool_name not in _TOOL_HOOKS:
        return f"Tool `{tool_name}` not found. Please use a provided tool."
    tool_call = _TOOL_HOOKS[tool_name]
    try:
        ret = tool_call(**tool_params)  
    except:
        ret = traceback.format_exc()
    return str(ret)

def get_tools() -> dict:
    return deepcopy(_TOOL_DESCRIPTIONS)

# Tool Definitions

@register_tool
def random_number_generator(
    seed: Annotated[int, '随机数生成器使用的种子', True], 
    range: Annotated[tuple[int, int], '生成随机数的范围', True],
) -> int:
    """
    随机生成一个数x, 使得 `range[0]` <= x < `range[1]`， 随机数生成的种子使用 `seed`
    """
    if not isinstance(seed, int):
        raise TypeError("Seed must be an integer")
    if not isinstance(range, tuple):
        raise TypeError("Range must be a tuple")
    if not isinstance(range[0], int) or not isinstance(range[1], int):
        raise TypeError("Range must be a tuple of integers")

    import random
    return f"生成的随机数为{random.Random(seed).randint(*range)}"

@register_tool
def get_sentence_length(
    input_text: Annotated[str, '输入的句子', True],
) -> int:
    """
    获取句子 `input_text` 的长度
    """
    return f"这句话{input_text}的长度为{len(input_text)}"

@register_tool
def exponentiation_calculation(
    base: Annotated[int, '底数', True], 
    power: Annotated[int, '指数', True],
) -> int:
    """
    返回指数计算的结果，底数 `base` 的指数 `power` 次方
    """
    return f"{base}的{power}次方的计算结果为{base**power}"

@register_tool
def web_search(
    keyword: Annotated[str, '搜索使用的关键字', True],
    # search_engine: Annotated[Literal['ddgs', 'baidu'], '使用的搜索引擎', False] = 'ddgs', 
) -> str:
    """
    从网络上获得 `keyword` 的习惯内容信息。
    在你要回答你现有知识无法回答的问题时，你应该使用这个工具（尤其是当你需要获得最新的实时信息，或者你缺少相关信息时，在这种情况下请更倾向于使用这个工具）。
    """
    # Get related contents from internet. 
    # You should use this function especially when you meet something beyond your knowledge. 


    # import os
    # # os.environ["OPENAI_API_KEY"] = "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"
    # # os.environ["SERPAPI_API_KEY"] = "1acc98c79ed21041c727e5ecca30eba3380d5d290ce9e56d4434264fdfa34f54"
    # os.environ["HTTP_PROXY"]='http://10.10.20.100:1089'
    # os.environ["HTTPS_PROXY"]='http://10.10.20.100:1089'
    search_engine = 'baidu'
    if search_engine == 'ddgs':
        from duckduckgo_search import DDGS
        content = DDGS().text(keyword, region="cn-zh", max_results=1).__next__()
        return content['body'].replace('\\n', '')
    elif search_engine == 'baidu':
    # print("+"*15, "ddgs搜索结果", "+"*15)
    # print(content['title'])
    # print("+"*40)
        from baidusearch.baidusearch import search
        content = search(keyword, 1)[0]
        return content['abstract'].replace('\\n', '')
    else:
        print(f"错误的搜索引擎{search_engine}，将使用百度")
        from baidusearch.baidusearch import search
        content = search(keyword, 1)[0]
        return content['abstract'].replace('\\n', '')

@register_tool
def get_weather(
    city_name: Annotated[str, 'The name of the city to be queried', True],
) -> str:
    """
    Get the current weather for `city_name`
    """

    if not isinstance(city_name, str):
        raise TypeError("City name must be a string")

    key_selection = {
        "current_condition": ["temp_C", "FeelsLikeC", "humidity", "weatherDesc",  "observation_time"],
    }
    import requests
    try:
        resp = requests.get(f"https://wttr.in/{city_name}?format=j1")
        resp.raise_for_status()
        resp = resp.json()
        ret = {k: {_v: resp[k][0][_v] for _v in v} for k, v in key_selection.items()}
    except:
        import traceback
        ret = "Error encountered while fetching weather data!\n" + traceback.format_exc() 

    return str(ret)

if __name__ == "__main__":
    print(dispatch_tool("get_weather", {"city_name": "beijing"}))
    print(get_tools())
