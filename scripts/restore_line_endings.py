"""还原被编辑器规范化的行尾分布，使 git diff 只保留真实改动。

本仓库 HEAD 中多数文件是 CRLF/LF 混合行尾且 core.autocrlf=false，
编辑工具保存时会把整个文件统一为 CRLF，导致 git diff 显示全文件重写。

做法：以"去掉行尾后的内容"为基准做 diff，
  - equal 块      → 直接取 HEAD 原始行（保留其原有行尾）
  - replace/insert → 取工作区内容，行尾沿用上下文 HEAD 行的行尾
  - delete 块     → 丢弃

用法: python scripts/restore_line_endings.py <file> [<file> ...]
"""
import subprocess
import sys
from difflib import SequenceMatcher


def split_keep_ends(data):
    return data.decode('utf-8').splitlines(keepends=True)


def strip_end(line):
    return line.rstrip('\r\n')


def line_end(line):
    if line.endswith('\r\n'):
        return '\r\n'
    if line.endswith('\n'):
        return '\n'
    return ''


def restore(path):
    head_bytes = subprocess.check_output(['git', 'show', f'HEAD:{path}'])
    head_lines = split_keep_ends(head_bytes)
    with open(path, 'rb') as f:
        work_lines = split_keep_ends(f.read())

    head_body = [strip_end(l) for l in head_lines]
    work_body = [strip_end(l) for l in work_lines]

    # 该文件 HEAD 中的主流行尾，用作新增行的默认值
    ends = [line_end(l) for l in head_lines if line_end(l)]
    default_end = max(set(ends), key=ends.count) if ends else '\n'

    out = []
    matcher = SequenceMatcher(None, head_body, work_body, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            out.extend(head_lines[i1:i2])
        elif tag == 'delete':
            continue
        else:  # replace / insert
            # 新增行的行尾沿用被替换处/前一行的 HEAD 行尾
            ctx = head_lines[i1] if i1 < len(head_lines) else (
                head_lines[i1 - 1] if i1 > 0 else '')
            end = line_end(ctx) or default_end
            for line in work_body[j1:j2]:
                out.append(line + end)

    # 保持原文件末行是否有换行的状态
    if work_lines and not line_end(work_lines[-1]) and out and line_end(out[-1]):
        out[-1] = strip_end(out[-1])

    result = ''.join(out).encode('utf-8')
    with open(path, 'wb') as f:
        f.write(result)

    # 内容必须逐字节等于工作区（仅行尾可不同）
    assert [strip_end(l) for l in split_keep_ends(result)] == work_body, \
        f'{path}: 还原后正文内容发生变化，已中止'
    crlf = sum(1 for l in split_keep_ends(result) if l.endswith('\r\n'))
    lf = sum(1 for l in split_keep_ends(result) if line_end(l) == '\n')
    print(f'{path}: CRLF={crlf}, LF={lf}')


if __name__ == '__main__':
    for target in sys.argv[1:]:
        restore(target)
