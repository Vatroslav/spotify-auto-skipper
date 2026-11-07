"""Read what a shell command is about to commit, for check-version-bump.sh.

The guard has to know the repo, the files and the message before the command runs, from its
text alone. The index is not enough: `git commit -m x -- path` needs nothing staged.

stdin: the PreToolUse hook JSON.
stdout: nothing when the command makes no commit in this repo. Otherwise `root <path>`, one
`file <path>` per committed file (root-relative), then a `msg` line and the message.
`skip <reason>` instead: a commit whose target the text does not tell.
"""
import json
import os
import re
import subprocess
import sys

SEP = object()
MARK = "\x01"
MARKER = re.compile(MARK + r"(\d+)" + MARK)
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "time", "command", "nohup"}
DECLARE = {"export", "local", "declare", "readonly", "env"}
ASSIGN = re.compile(r"^([A-Za-z_]\w*)=(.*)$", re.S)
PS_ASSIGN = re.compile(r"^\$([A-Za-z_]\w*)=?(.*)$", re.S)
VAR = re.compile(r"\$(?:\{([^}]*)\}|env:(\w+)|(\w+))")
FREE_TYPES = {"docs", "chore", "style", "refactor", "test", "ci", "build", "revert"}
COMMIT_VALUE_OPTS = {"--author", "--date", "--fixup", "--squash", "--cleanup", "--trailer", "--template", "--reuse-message", "--reedit-message", "--pathspec-from-file"}
ADD_ALL_OPTS = {"-A", "--all", "-u", "--update"}


def take_bodies(text, powershell):
    """Swap here-doc bodies and PowerShell here-strings for markers: their quotes mean nothing to the shell."""
    bodies = []

    def mark(body):
        bodies.append(body)
        return f"{MARK}{len(bodies) - 1}{MARK}"

    if powershell:
        text = re.sub(r"""@(['"])\r?\n(.*?)\r?\n\1@""", lambda m: mark(m.group(2)), text, flags=re.S)
        return text, bodies
    pos = 0
    opener = re.compile(r"""(?<!<)<<-?\s*(['"]?)([A-Za-z_]\w*)\1""")
    while True:
        m = opener.search(text, pos)
        if not m:
            break
        eol = text.find("\n", m.end())
        end = re.compile(rf"^[ \t]*{m.group(2)}[ \t]*\r?$", re.M).search(text, eol + 1) if eol >= 0 else None
        if not end:
            pos = m.end()
            continue
        head = text[: m.start()] + mark(text[eol + 1 : end.start()].rstrip("\r\n"))
        text = head + text[m.end() : eol + 1] + text[end.end() :].lstrip("\r\n")
        pos = len(head)
    # -m "$(cat <<'EOF' ... EOF)" is the message itself.
    text = re.sub(r'"\$\(\s*cat\s+(' + MARK + r"\d+" + MARK + r')\s*\)"', r"\1", text)
    return text, bodies


def after_parens(text, i):
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        elif c in "'\"":
            j = text.find(c, i + 1)
            if j < 0:
                return len(text)
            i = j
        i += 1
    return len(text)


def read_double(text, i, powershell):
    """A double-quoted string from just after its opening quote: (content, index after the closing quote)."""
    out = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            if powershell and text[i + 1 : i + 2] == '"':
                out.append('"')
                i += 2
                continue
            return "".join(out), i + 1
        if powershell and c == "`" or not powershell and c == "\\" and text[i + 1 : i + 2] in ('"', "\\", "$", "`"):
            out.append(text[i + 1 : i + 2])
            i += 2
        elif c == "$" and text[i + 1 : i + 2] == "(":
            j = after_parens(text, i + 1)
            out.append(text[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out), n


def read_words(text, powershell):
    """Split like a shell. A word is a list of (text, kind); kind is plain, double, single or subst."""
    out = []
    word = None
    drop_next = False
    escape = "`" if powershell else "\\"
    i = 0
    n = len(text)

    def end_word():
        nonlocal word, drop_next
        if word is not None:
            if drop_next:
                drop_next = False
            else:
                out.append(word)
            word = None

    def add(piece, kind):
        nonlocal word
        if word and word[-1][1] == kind:
            word[-1] = (word[-1][0] + piece, kind)
        else:
            word = (word or []) + [(piece, kind)]

    while i < n:
        c = text[i]
        if c in " \t\r":
            end_word()
            i += 1
        elif c == "#" and word is None:
            while i < n and text[i] != "\n":
                i += 1
        elif c in "\n;|()" or (c == "&" and text[i + 1 : i + 2] != ">"):
            end_word()
            if out and out[-1] is not SEP:
                out.append(SEP)
            i += 1
        elif c in "<>&":  # a redirection and its target are not arguments
            if word and len(word) == 1 and word[0][0].isdigit():
                word = None
            else:
                end_word()
            while i < n and text[i] in "<>&":
                i += 1
            drop_next = True
        elif c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            add(text[i + 1 : j], "single")
            i = j + 1
        elif c == '"':
            piece, i = read_double(text, i + 1, powershell)
            add(piece, "double")
        elif c == escape:
            if text[i + 1 : i + 2] != "\n":
                add(text[i + 1 : i + 2], "single")
            i += 2
        elif c == "$" and text[i + 1 : i + 2] == "(":
            j = after_parens(text, i + 1)
            add(text[i:j], "subst")
            i = j
        elif c == "`":
            j = text.find("`", i + 1)
            j = n if j < 0 else j
            add(text[i : j + 1], "subst")
            i = j + 1
        else:
            add(c, "plain")
            i += 1
    end_word()
    return out


def lookup(name, names):
    if name in names:
        return names[name]
    return os.environ.get(name)


def expand(word, names):
    """The strings a word becomes. None stands for what the text alone cannot tell."""
    pieces = [""]
    unknown = False
    for piece, kind in word:
        if kind == "single":
            pieces[-1] += piece
            continue
        if kind == "subst" or "$(" in piece:
            unknown = True
            continue
        pos = 0
        for m in VAR.finditer(piece):
            pieces[-1] += piece[pos : m.start()]
            pos = m.end()
            value = lookup(m.group(1) or m.group(2) or m.group(3), names)
            if value is None:
                unknown = True
            elif kind == "plain":
                parts = value.split()
                if parts:
                    pieces[-1] += parts[0]
                    pieces += parts[1:]
            else:
                pieces[-1] += value
        pieces[-1] += piece[pos:]
    return [None] if unknown else pieces


def one(word, names):
    got = expand(word, names)
    return None if None in got else " ".join(got)


def native(path):
    """A path as Windows git expects it: Git Bash's /c/... and ~ are the shell's, not git's."""
    if path.startswith("~"):
        path = os.path.expanduser("~") + path[1:]
    m = re.match(r"^/([a-zA-Z])(/.*)?$", path)
    if m and os.name == "nt":
        path = m.group(1) + ":" + (m.group(2) or "/")
    return path


def join_dir(base, path):
    if base is None or path is None:
        return None
    return os.path.normpath(os.path.join(base, native(path)))


class Commit:
    def __init__(self, directory, args, adds):
        self.dir = directory
        self.args = args  # words
        self.adds = adds  # (directory, strings or None) from `git add` earlier in the command


def find_commits(text, powershell, cwd, names=None):
    text, bodies = take_bodies(text, powershell)
    words = read_words(text, powershell)
    names = {} if names is None else names
    commits = []
    adds = []
    here = cwd
    segment = []
    for item in words + [SEP]:
        if item is not SEP:
            segment.append(item)
            continue
        if segment:
            here = read_segment(segment, powershell, here, names, commits, adds, bodies)
        segment = []
    return commits, bodies


def read_segment(words, powershell, here, names, commits, adds, bodies):
    """One simple command. Returns the folder the next one runs in."""
    words = list(words)
    raw = lambda w: "".join(p for p, _ in w)

    while words and raw(words[0]) in KEYWORDS | DECLARE and all(k == "plain" for _, k in words[0]):
        words.pop(0)
    if words and raw(words[0]) in ("for", "foreach"):
        if len(words) > 1:
            names[raw(words[1]).lstrip("$")] = None
        return here

    # NAME=value in front of a command or alone; $Name = value in PowerShell.
    while words and words[0][0][1] == "plain":
        first = words[0][0][0]
        m = ASSIGN.match(first)
        if not powershell and m:
            rest = ([(m.group(2), "plain")] if m.group(2) else []) + words[0][1:]
            names[m.group(1)] = "" if not rest else one(rest, names)
            words.pop(0)
            continue
        m = PS_ASSIGN.match(first)
        if powershell and m and (m.group(2) or (len(words) > 1 and raw(words[1]) == "=")):
            if m.group(2) or raw(words[0]).endswith("="):
                rest = ([(m.group(2), "plain")] if m.group(2) else []) + words[0][1:] or (words[1] if len(words) > 1 else [])
            else:
                rest = words[2] if len(words) > 2 else []
            names[m.group(1)] = one(rest, names) if rest else ""
            return here
        break
    if not words:
        return here

    head = one(words[0], names) or ""
    tool = os.path.basename(head.replace("\\", "/")).lower()
    tool = tool[:-4] if tool.endswith(".exe") else tool

    if tool == "timeout" and len(words) > 2:
        return read_segment(words[2:], powershell, here, names, commits, adds, bodies)
    if tool == "eval" or (tool in ("bash", "sh", "pwsh", "powershell") and len(words) > 2 and raw(words[1]).lower() in ("-c", "-command")):
        inner = " ".join(raw(w) for w in words[1:]) if tool == "eval" else raw(words[2])
        inner_commits, inner_bodies = find_commits(inner, tool in ("pwsh", "powershell"), here, names)
        commits.extend(inner_commits)
        bodies.extend(inner_bodies)
        return here
    if tool in ("cd", "set-location", "sl", "pushd", "chdir"):
        args = [w for w in words[1:] if not raw(w).startswith("-")]
        if not args:
            return here if len(words) > 1 else native("~")
        return join_dir(here, one(args[0], names))
    if tool != "git":
        return here

    target = here
    i = 1
    while i < len(words):
        token = one(words[i], names)
        if token == "-C":
            target = join_dir(target, one(words[i + 1], names)) if i + 1 < len(words) else None
            i += 2
        elif token in ("-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        elif token and token.startswith("-"):
            i += 1
        else:
            break
    if i >= len(words):
        return here
    sub = one(words[i], names)
    if sub == "add":
        strings = []
        for w in words[i + 1 :]:
            strings += expand(w, names)
        adds.append((target, strings))
    elif sub == "commit":
        commits.append(Commit(target, words[i + 1 :], list(adds)))
    return here


def body_of(value, bodies):
    m = MARKER.fullmatch(value or "")
    if m:
        return bodies[int(m.group(1))]
    # A message made by a command cannot be read from the text.
    return "" if value and value.startswith(("$(", "`")) else value


class Args:
    def __init__(self):
        self.paths, self.messages, self.files = [], [], []
        self.all = self.include = self.amend = False
        self.stdin = None  # the here-doc on this command's stdin


def read_args(commit, names, bodies):
    a = Args()
    words = commit.args
    i = 0
    raw = lambda w: "".join(p for p, _ in w)
    text = lambda w: one(w, names) or raw(w)  # a message keeps what it cannot expand
    while i < len(words):
        token = text(words[i])
        i += 1
        if MARKER.fullmatch(token):
            a.stdin = body_of(token, bodies)
            continue
        if token == "--":
            for w in words[i:]:
                a.paths += expand(w, names)
            break
        if token.startswith("--"):
            name, eq, value = token.partition("=")
            if name == "--message":
                if not eq and i < len(words):
                    value = text(words[i])
                    i += 1
                a.messages.append(body_of(value, bodies))
            elif name == "--file":
                if not eq and i < len(words):
                    value = one(words[i], names)
                    i += 1
                a.files.append(value)
            elif name == "--all":
                a.all = True
            elif name == "--include":
                a.include = True
            elif name == "--amend":
                a.amend = True
            elif name in COMMIT_VALUE_OPTS and not eq:
                i += 1
            continue
        if token.startswith("-") and len(token) > 1:
            j = 1
            while j < len(token):
                c = token[j]
                j += 1
                if c in "mFCct":
                    value = token[j:]
                    if not value and i < len(words):
                        value = text(words[i]) if c == "m" else one(words[i], names)
                        i += 1
                    if c == "m":
                        a.messages.append(body_of(value, bodies))
                    elif c == "F":
                        a.files.append(value)
                    break
                if c == "a":
                    a.all = True
                elif c == "i":
                    a.include = True
                elif c in "uS":
                    break  # their value is attached
            continue
        a.paths += expand(words[i - 1], names)
    return a


def run_git(directory, *args):
    r = subprocess.run(["git", "-C", directory, *args], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def names_from(directory, *args):
    return [x for x in (run_git(directory, *args) or "").split("\0") if x]


def changed(directory, specs=None):
    """Files that differ from HEAD (or are new) under these pathspecs, root-relative."""
    tail = ["--", *specs] if specs else []
    files = names_from(directory, "diff", "HEAD", "--name-only", "--no-renames", "-z", *tail)
    if specs:
        files += names_from(directory, "ls-files", "--others", "--exclude-standard", "--full-name", "-z", *tail)
    return files


def added_files(directory, strings):
    known = [native(s) for s in strings if s is not None and not s.startswith("-")]
    if None in strings or set(strings) & ADD_ALL_OPTS:
        return changed(directory)
    return changed(directory, known) if known else []


def commit_files(commit, a):
    cached = names_from(commit.dir, "diff", "--cached", "--name-only", "--no-renames", "-z")
    if a.paths:
        known = [native(p) for p in a.paths if p is not None]
        files = changed(commit.dir, known) if known else []
        if None in a.paths:
            files += changed(commit.dir)
        return files + cached if a.include else files
    files = list(cached)
    if a.all:
        files += changed(commit.dir)
    for directory, strings in commit.adds:
        if directory is None:
            files += changed(commit.dir)
        elif same_repo(directory, commit.dir):
            files += added_files(directory, strings)
    return files


def common_dir(directory):
    out = run_git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return out.strip() if out else None


def same_repo(a, b):
    ca, cb = common_dir(a), common_dir(b)
    return bool(ca and cb) and os.path.samefile(ca, cb)


def read_message(a, directory, bodies):
    if a.messages:
        return "\n\n".join(m for m in a.messages if m is not None)
    for f in a.files:
        if f in ("-", "/dev/stdin"):
            # Its own here-doc, or one piped in from an earlier command.
            return a.stdin if a.stdin is not None else (bodies[-1] if bodies else "")
        if f:
            try:
                with open(os.path.join(directory, native(f)), encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                return ""
    if a.amend:
        return run_git(directory, "log", "-1", "--format=%B") or ""
    return ""


def strictest(messages):
    """Several commits in one command: judge by the one that asks most of the guard."""
    for m in messages:
        word = re.match(r"[A-Za-z]+", m)
        if not word or word.group(0).lower() not in FREE_TYPES:
            return m
    return messages[0] if messages else ""


def facts(command, powershell, cwd, hook_dir):
    if "commit" not in command:
        return []
    commits, bodies = find_commits(command, powershell, cwd)
    if not commits:
        return []
    names = {}  # the walk's variables are gone by now: what a commit's own words still need is unread
    mine, unread = [], False
    for c in commits:
        if c.dir is None:
            unread = True
        elif same_repo(c.dir, hook_dir):
            mine.append(c)
    if not mine:
        return ["skip commit target not readable from the command, guard skipped"] if unread else []
    root = run_git(mine[0].dir, "rev-parse", "--show-toplevel")
    if root is None:
        return []
    files, messages = [], []
    for c in mine:
        a = read_args(c, names, bodies)
        if not a.paths and run_git(c.dir, "rev-parse", "-q", "--verify", "MERGE_HEAD"):
            continue  # concluding a merge declares no intent of its own
        files += commit_files(c, a)
        messages.append(read_message(a, c.dir, bodies))
    if not messages:
        return []
    out = ["root " + root.strip()]
    out += ["file " + f for f in dict.fromkeys(files)]
    out += ["msg", strictest(messages).replace("\r\n", "\n").strip()]
    return out


def main():
    hook = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    command = (hook.get("tool_input") or {}).get("command") or ""
    cwd = hook.get("cwd") or ""
    cwd = cwd if os.path.isdir(cwd) else os.getcwd()
    powershell = hook.get("tool_name") == "PowerShell"
    try:
        lines = facts(command, powershell, cwd, os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        lines = [f"skip read-commit.py failed ({type(e).__name__}), guard skipped"]
    if lines:
        sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
