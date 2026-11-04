"""Adjust email links without running scripts or changing stored email HTML."""
from html import escape
from html.parser import HTMLParser


class EmailLinks(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        for line in content.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.changes = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag not in ('a', 'area'):
            return
        attrs = [(key, value) for key, value in attrs if key not in ('target', 'rel')]
        attrs.extend([('target', '_blank'), ('rel', 'noopener noreferrer')])
        replacement = '<' + tag + ''.join(
            ' ' + key + (f'="{escape(value, quote=True)}"' if value is not None else '')
            for key, value in attrs
        ) + '>'
        line, column = self.getpos()
        start = self.offsets[line - 1] + column
        self.changes.append((start, start + len(self.get_starttag_text()), replacement))

    handle_startendtag = handle_starttag


def links_in_new_tabs(content):
    parser = EmailLinks(content)
    for start, end, replacement in reversed(parser.changes):
        content = content[:start] + replacement + content[end:]
    return content
