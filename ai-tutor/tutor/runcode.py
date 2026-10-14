import shutil
import subprocess
import tempfile
from pathlib import Path

TIMEOUT_S = 10

LANGS = {
    "python": ("main.py", lambda f: ["python3", f]),
    "ruby": ("main.rb", lambda f: ["ruby", f]),
    "javascript": ("main.js", lambda f: ["node", f]),
    "java": ("Main.java", lambda f: ["java", f]),  # single-file source launch, needs a JDK
}


def run_code(language: str, code: str, stdin: str = "") -> str:
    language = language.lower()
    if language not in LANGS:
        return f"ERROR: language must be one of {', '.join(LANGS)}"
    filename, cmd = LANGS[language]
    if not shutil.which(cmd("x")[0]):
        return f"ERROR: '{cmd('x')[0]}' is not installed"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_text(code)
        try:
            proc = subprocess.run(
                cmd(str(path)), input=stdin, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=tmp
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: timed out after {TIMEOUT_S}s (infinite loop?)"
    out = f"exit code {proc.returncode}\nstdout:\n{proc.stdout[-4000:]}"
    if proc.stderr:
        out += f"\nstderr:\n{proc.stderr[-2000:]}"
    if language == "java" and "jdk.compiler" in proc.stderr:
        out += "\nNOTE: only a Java runtime is installed; run `sudo apt install openjdk-21-jdk` to run Java."
    return out
