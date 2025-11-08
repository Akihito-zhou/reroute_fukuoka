from pathlib import Path
path = Path('apps/api/services/planner.py')
text = path.read_text(encoding='utf-8')

def replace_block(header: str, new_block: str) -> str:
    start = text.index(header)
    end = text.index('\n\n', start)
    return text[:start] + new_block + text[end+2:]
