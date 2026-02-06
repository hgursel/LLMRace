from app.runs.tools import calculator, execute_tool, extract_code_blocks, json_validate, parse_fallback_tool_command


def test_calculator_and_execute_tool() -> None:
    assert calculator('2+2*3') == 8
    out = execute_tool('calculator', {'expression': '10/2'})
    assert out['result'] == 5


def test_json_validate() -> None:
    assert json_validate('{"a":1}') == {'valid': True}
    invalid = json_validate('{"a":1,}')
    assert invalid['valid'] is False
    assert 'error' in invalid


def test_extract_code_blocks() -> None:
    blocks = extract_code_blocks('x ```python\nprint(1)\n``` y ```js\nconsole.log(2)\n```')
    assert blocks == ['print(1)', 'console.log(2)']


def test_parse_fallback_tool_command() -> None:
    cmd = parse_fallback_tool_command('{"tool":"calculator","args":{"expression":"3*3"}}')
    assert cmd == {'name': 'calculator', 'arguments': {'expression': '3*3'}}
