"""
LLM客户端模块（严格对齐参考项目实现）
"""
import requests
from typing import List, Optional


def _normalize_base(base: str) -> str:
    return (base or "").rstrip("/")


def _build_headers(apikey: str) -> dict:
    k = apikey or ""
    return {
        "Authorization": f"Bearer {k}",
        "x-api-key": k,
        "Content-Type": "application/json",
    }


def _candidate_model_urls(base: str):
    b = _normalize_base(base)
    candidates = []

    if b.endswith(("/v1", "/v2", "/v3", "/coding")):
        candidates.append(f"{b}/models")
    else:
        candidates.append(f"{b}/models")
        candidates.append(f"{b}/v1/models")

    if "volces.com" in b or "ark.cn-beijing.volces.com" in b:
        root = b.split("/api")[0] if "/api" in b else b
        candidates.append(f"{root}/api/v3/models")
        candidates.append(f"{root}/api/coding/v1/models")

    if "/api/coding" in b:
        root = b.split("/api/coding")[0]
        candidates.append(f"{root}/api/v3/models")
        candidates.append(f"{root}/api/v1/models")

    seen = set()
    deduped = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        deduped.append(c)
    return deduped


def _extract_models(data):
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return sorted([m.get("id", m.get("name", "unknown")) for m in data["data"] if isinstance(m, dict)])
    if isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
        return sorted([m.get("name", m.get("id", "unknown")) for m in data["models"] if isinstance(m, dict)])
    if isinstance(data, list):
        return sorted([m.get("id", m.get("name", "unknown")) for m in data if isinstance(m, dict)])
    return []


def _get_chat_endpoint(url: str) -> str:
    u = _normalize_base(url)
    if "/api/coding" in u:
        return f"{u}/v1/chat/completions"

    if "volces.com" in u:
        return f"{u}/chat/completions" if "/api" in u and not u.endswith("/chat/completions") else u

    if u.endswith("/chat/completions"):
        return u
    if u.endswith(("/v1", "/v2", "/v3", "/coding")):
        return f"{u}/chat/completions"
    if "/api" in u and not u.endswith("/api"):
        return f"{u}/chat/completions"
    return f"{u}/v1/chat/completions"


def _resolve_model_for_endpoint(endpoint: str, model: str) -> str:
    m = model or ""
    e = endpoint or ""
    if "volces.com" in e or "ark.cn-beijing.volces.com" in e:
        if m == "doubao-seed-2-0-pro":
            return "doubao-seed-2-0-pro-260215"
    return m


def fetch_model_list(url: str, apikey: str, timeout=10) -> List[str]:
    """
    获取模型列表（对齐参考项目接口）
    :param url: API基础地址
    :param apikey: API密钥
    :param timeout: 超时时间
    :return: 模型名称列表
    """
    headers = _build_headers(apikey)
    last_error = None

    for endpoint in _candidate_model_urls(url):
        try:
            response = requests.get(endpoint, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            models = _extract_models(data)
            if models:
                return models
            last_error = f"No models found in response from {endpoint}"
        except Exception as e:
            last_error = f"{endpoint} -> {e}"
            continue

    raise RuntimeError(last_error or "Unable to fetch models from any candidate endpoint")


def test_model_connection(url: str, apikey: str, model: str, timeout=20) -> str:
    """
    测试模型连接（对齐参考项目接口）
    :param url: API基础地址
    :param apikey: API密钥
    :param model: 模型名称
    :param timeout: 超时时间
    :return: 测试返回内容
    """
    endpoint = _get_chat_endpoint(url)
    headers = _build_headers(apikey)
    resolved_model = _resolve_model_for_endpoint(endpoint, model)
    payload = {"model": resolved_model, "messages": [{"role": "user", "content": "Hello, please reply with exactly: 'OK'"}], "max_tokens": 10}
    response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if response.status_code != 200:
        err_msg = response.text
        try:
            err_json = response.json()
            if "error" in err_json and "message" in err_json["error"]:
                err_msg = err_json["error"]["message"]
        except Exception:
            pass
        raise Exception(f"HTTP {response.status_code} ({endpoint}): {err_msg}")
    return response.json().get("choices", [{}])[0].get("message", {}).get("content", "无返回值")


def post_chat_completion(url: str, apikey: str, model: str, messages: list, is_stream: bool = False):
    """
    发送聊天完成请求（对齐参考项目接口）
    :param url: API基础地址
    :param apikey: API密钥
    :param model: 模型名称
    :param messages: 消息列表
    :param is_stream: 是否流式返回
    :return: 请求响应对象
    """
    endpoint = _get_chat_endpoint(url)
    headers = _build_headers(apikey)
    resolved_model = _resolve_model_for_endpoint(endpoint, model)
    payload = {"model": resolved_model, "messages": messages, "stream": is_stream}
    return requests.post(endpoint, headers=headers, json=payload, timeout=60, stream=is_stream)
