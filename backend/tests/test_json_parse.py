from app.infra.llm_client import parse_json_object


def test_fence():
    assert parse_json_object('```json\n{"a": 1}\n```')["a"] == 1


def test_think_tags():
    assert parse_json_object('<think>xxx</think>{"b": 2}')["b"] == 2


def test_noise_around():
    assert parse_json_object('好的如下 {"c": 3} 完毕')["c"] == 3
