"""
Strip comments, docstrings, and collapse excess blank lines from
standalone_full.py to produce a smaller standalone.py for upload, WITHOUT
changing formatting, renaming anything, folding constants, joining
statements onto one line, or altering any string/numeric literal.

This works line-by-line on the ORIGINAL SOURCE TEXT guided by the
tokenizer (rather than reconstructing via tokenize.untokenize, which
proved unreliable for exact-formatting preservation) -- for each line,
comment tokens are trimmed from the end, and lines that are entirely a
docstring statement are dropped, but everything else is left as
byte-identical original text.
"""
import tokenize
import io

SRC = "standalone_full.py"
OUT = "standalone.py"

source = open(SRC).read()
original_lines = source.split("\n")

tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))

# Lines (1-indexed, matching tokenize) that are entirely consumed by a
# docstring statement -- to be dropped completely.
docstring_lines = set()
# (line, col) spans of COMMENT tokens -- to be trimmed from their line.
comment_spans = []  # list of (lineno, start_col)

for i, tok in enumerate(tokens):
    ttype, tstring, start, end, line = tok

    if ttype == tokenize.COMMENT:
        comment_spans.append((start[0], start[1]))
        continue

    if ttype != tokenize.STRING:
        continue

    # Is this STRING token a standalone docstring statement? Look forward
    # past NL to find NEWLINE; look backward past NL/COMMENT to find
    # NEWLINE, INDENT, or ':' (module/class/function docstring position).
    j = i + 1
    while j < len(tokens) and tokens[j].type == tokenize.NL:
        j += 1
    is_stmt = j < len(tokens) and tokens[j].type == tokenize.NEWLINE
    if not is_stmt:
        continue

    k = i - 1
    while k >= 0 and tokens[k].type in (tokenize.NL, tokenize.COMMENT):
        k -= 1
    is_docstring_position = (
        k < 0
        or tokens[k].type in (tokenize.NEWLINE, tokenize.INDENT)
        or (tokens[k].type == tokenize.OP and tokens[k].string == ":")
    )
    if not is_docstring_position:
        continue

    for lineno in range(start[0], end[0] + 1):
        docstring_lines.add(lineno)

out_lines = []
for lineno, text in enumerate(original_lines, start=1):
    if lineno in docstring_lines:
        continue
    trimmed = text
    for cl, cc in comment_spans:
        if cl == lineno:
            trimmed = text[:cc].rstrip()
            break
    out_lines.append(trimmed)

collapsed = []
blank_run = 0
for l in out_lines:
    if l.strip() == "":
        blank_run += 1
        if blank_run <= 1:
            collapsed.append("")
    else:
        blank_run = 0
        collapsed.append(l)

result = "\n".join(collapsed)

# --- Tab conversion: replace each leading group of 4 spaces with one tab ---
# Only safe if no multiline string literals remain (their internal leading
# whitespace would be corrupted). All multiline strings in this codebase are
# docstrings, which were just removed -- but verify rather than assume.
import ast as _ast
_tree = _ast.parse(result)
_multiline = [n.lineno for n in _ast.walk(_tree)
              if isinstance(n, _ast.Constant) and isinstance(n.value, str)
              and "\n" in n.value]
if _multiline:
    print(f"WARNING: multiline strings at lines {_multiline}; skipping tab conversion")
else:
    import re as _re
    def _tabify(line):
        m = _re.match(r"^( +)", line)
        if not m:
            return line
        spaces = len(m.group(1))
        return "\t" * (spaces // 4) + " " * (spaces % 4) + line[spaces:]
    result = "\n".join(_tabify(l) for l in result.split("\n"))

# Sanity: the transformed file must parse to the same AST as before tabify.
assert _ast.dump(_ast.parse(result)) == _ast.dump(_tree), "tabify changed the AST!"

open(OUT, "w").write(result)

print(f"Original: {len(source)} bytes, {len(original_lines)} lines")
print(f"Stripped: {len(result)} bytes, {len(collapsed)} lines")
