"""Custom tool text_counts — created through the agent tool pipeline (tool_create), not hand-written.

Count words, characters, and lines of a given text.
"""

def text_counts(text):
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    return {'words': len(text.split()), 'chars': len(text), 'lines': len(text.splitlines())}
