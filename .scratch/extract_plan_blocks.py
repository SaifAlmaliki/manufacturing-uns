from pathlib import Path
import re

plan_path = Path(r"c:\Dev\unifiednamespace\docs\superpowers\plans\2026-08-31-simulator-plant-model.md")
raw = plan_path.read_bytes()
print("size", len(raw), "crlf", raw.count(b"\r\n"), "lf-only estimate", raw.count(b"\n"))
text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
fence = "`" * 3
print("fence count", text.count(fence))
print("python fences", text.count(fence + "python"))
idx = text.find("## Task 13:")
print("task13 idx", idx)
snippet = text[idx : idx + 1200]
i = snippet.find(fence)
print("fence idx in snippet", i)
print(repr(snippet[i : i + 50]) if i >= 0 else "NO FENCE")

lines = text.splitlines(keepends=True)
task_starts = []
for i, line in enumerate(lines):
    m = re.match(r"^## Task (\d+):", line)
    if m:
        task_starts.append((int(m.group(1)), i))

out_dir = Path(r"c:\Dev\unifiednamespace\.scratch\plan-extract-13-19")
out_dir.mkdir(parents=True, exist_ok=True)
pattern = re.compile(rf"^{fence}(\w+)\n(.*?){fence}", re.MULTILINE | re.DOTALL)

for idx, (num, start) in enumerate(task_starts):
    if num < 13 or num > 19:
        continue
    end = task_starts[idx + 1][1] if idx + 1 < len(task_starts) else len(lines)
    body = "".join(lines[start:end])
    (out_dir / f"task-{num:02d}-full.md").write_text(body, encoding="utf-8", newline="\n")
    blocks = list(pattern.finditer(body))
    print(f"Task {num}: {len(blocks)} blocks")
    for j, m in enumerate(blocks, 1):
        lang, code = m.group(1), m.group(2)
        ext = {
            "python": "py",
            "yaml": "yaml",
            "toml": "toml",
            "dockerfile": "dockerfile",
            "markdown": "md",
            "bash": "sh",
        }.get(lang, lang)
        (out_dir / f"task-{num:02d}-block-{j:02d}.{ext}").write_text(code, encoding="utf-8", newline="\n")
        first = code.strip().splitlines()[0][:90] if code.strip() else "(empty)"
        print(f"  {j:02d} {lang:10s} {len(code.splitlines()):4d}L  {first}")
