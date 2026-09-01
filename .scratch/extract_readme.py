from pathlib import Path

text = Path(
    r"c:\Dev\unifiednamespace\docs\superpowers\plans\2026-08-31-simulator-plant-model.md"
).read_text(encoding="utf-8").replace("\r\n", "\n")
fence4 = "`" * 4
start = text.find(fence4 + "markdown\n")
end = text.find("\n" + fence4, start + 1)
assert start >= 0 and end > start
code = text[start + len(fence4 + "markdown\n") : end]
out = Path(r"c:\Dev\unifiednamespace\.scratch\plan-extract-13-19\task-19-readme-section.md")
out.write_text(code, encoding="utf-8", newline="\n")
print("README section lines", len(code.splitlines()))
print(code[:120])
