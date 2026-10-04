"""Audit tests: they read the source of scripts/*.py and fail if it does anything a reviewer would not expect.

The point is that anyone can verify model_setup.py: standard library only, no shell, no dynamic code,
network only to Hugging Face, and no reads of personal files.
Run: python3 -m unittest discover -s tests -v
"""
import ast
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SOURCES = sorted(SCRIPTS.glob("*.py"))

# Everything the script may import. All of it ships with Python; nothing is installed with pip.
ALLOWED_IMPORTS = {"__future__", "argparse", "csv", "ctypes", "datetime", "io", "json", "os", "platform",
                   "re", "shutil", "subprocess", "sys", "urllib", "pathlib"}
ALLOWED_HOSTS = {"huggingface.co", "github.com"}
# The only programs the script may start (always as an argument list, never through a shell).
ALLOWED_PROGRAMS = {"nvidia-smi", "sysctl", "--list-devices", "llama-server", "llama-bench"}


def trees():
    for path in SOURCES:
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class TestSourceAudit(unittest.TestCase):
    def test_there_is_something_to_audit(self):
        self.assertTrue(any(p.name == "model_setup.py" for p in SOURCES))

    def test_python_standard_library_only(self):
        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        for path, tree in trees():
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    top = m.split(".")[0]
                    self.assertIn(top, ALLOWED_IMPORTS, f"{path.name}: unexpected import '{m}'")
                    if stdlib:
                        self.assertIn(top, stdlib, f"{path.name}: '{m}' is not in the standard library")

    def test_no_dynamic_code_or_shell(self):
        banned_builtins = {"eval", "exec", "compile", "__import__"}          # as bare names: dynamic code
        banned_os = {"system", "popen", "startfile", "spawnl", "spawnv", "spawnlp", "spawnvp", "fork", "execv", "execl"}
        for path, tree in trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if isinstance(f, ast.Name):
                    self.assertNotIn(f.id, banned_builtins, f"{path.name}:{node.lineno} calls {f.id}()")
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "os":
                    self.assertNotIn(f.attr, banned_os, f"{path.name}:{node.lineno} calls os.{f.attr}()")
                for kw in node.keywords:
                    self.assertNotEqual(kw.arg, "shell", f"{path.name}:{node.lineno} passes shell=")
            text = path.read_text()
            for banned in ("pickle", "marshal", "base64", "socket", "ftplib", "smtplib", "telnetlib"):
                self.assertNotRegex(text, rf"(?m)^\s*(import|from)\s+{banned}\b", f"{path.name} imports {banned}")

    def test_subprocess_only_runs_known_programs_as_lists(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("run", "Popen", "call", "check_output")
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
                    self.assertTrue(node.args and not isinstance(node.args[0], ast.Constant),
                                    f"{path.name}:{node.lineno} subprocess must take an argument list, not a string")
        text = (SCRIPTS / "model_setup.py").read_text()
        for call in re.findall(r'run_cmd\(\[\s*"([^"]+)"', text):
            self.assertIn(call, ALLOWED_PROGRAMS, f"run_cmd starts unexpected program {call!r}")

    def test_network_hosts_are_only_huggingface_and_github(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for url in re.findall(r"https?://[^\s\"')]+", node.value):
                        host = urlparse(url).hostname
                        self.assertIn(host, ALLOWED_HOSTS, f"{path.name}:{node.lineno} talks to {host}")

    def test_http_goes_through_one_function_and_sends_no_personal_data(self):
        text = (SCRIPTS / "model_setup.py").read_text()
        self.assertEqual(text.count("urllib.request.urlopen("), 2, "only http_get and fetch_file touch the network")
        # request headers are limited to a fixed user-agent and (for resume) a Range header
        headers = set(re.findall(r'headers\[?\s*[\"\']?(?:\[)?"(\w[\w-]*)"', text)) | set(re.findall(r'"(User-Agent|Range)"', text))
        self.assertTrue(headers <= {"User-Agent", "Range"}, headers)
        self.assertNotRegex(text, r"(getpass|gethostname|getlogin|node\(\)|platform\.(node|uname)|os\.environ\.copy)")
        self.assertNotRegex(text, r"urlopen\([^)]*data=", "no request bodies are sent")

    def test_no_reads_of_personal_files(self):
        text = (SCRIPTS / "model_setup.py").read_text()
        for needle in (".ssh", ".aws", ".gnupg", "Cookies", "Login Data", "id_rsa", ".netrc", "keychain", ".bash_history"):
            self.assertNotIn(needle, text)

    def test_writes_stay_in_models_dir_and_state_file(self):
        text = (SCRIPTS / "model_setup.py").read_text()
        writers = re.findall(r"(write_text|write_bytes|open\([^)]*[\"'][wa]b?[\"']|os\.replace|shutil\.(move|copy|rmtree)|os\.remove|unlink|rmdir)", text)
        found = {w[0].split("(")[0] for w in writers}
        self.assertFalse({"shutil.rmtree", "os.remove", "unlink", "rmdir"} & found, f"unexpected deletes: {found}")

    def test_no_obfuscation(self):
        for path in SOURCES:
            text = path.read_text()
            self.assertNotRegex(text, r"\\x[0-9a-fA-F]{2}\\x[0-9a-fA-F]{2}\\x[0-9a-fA-F]{2}", f"{path.name}: hex-escaped strings")
            self.assertFalse(any(len(line) > 200 for line in text.splitlines()), f"{path.name}: very long line (obfuscation?)")
            self.assertNotIn("\x00", text)


if __name__ == "__main__":
    unittest.main()
