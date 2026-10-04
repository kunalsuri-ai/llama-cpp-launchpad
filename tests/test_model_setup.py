"""Tests for scripts/model_setup.py. Standard library only: python3 -m unittest discover -s tests -v

No network, GPU or llama.cpp needed: Hugging Face, nvidia-smi, llama-bench and downloads are faked
with fixtures (tests/fixtures). One test starts a throw-away local HTTP server to check resume.
"""
import contextlib
import datetime as dt
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import model_setup as ms  # noqa: E402

FIX = HERE / "fixtures"
GB = 1073741824


def fixture(name):
    return (FIX / name).read_text()


class Base(unittest.TestCase):
    """Fresh temp dirs, fixed date, and a fake Hugging Face."""

    hyped = "hf_model_gated.json"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = {"STATE_FILE": str(self.tmp / "state"), "MODELS_DIR": str(self.tmp / "models"),
               "LP_TODAY": "2026-10-05", "LP_GPU_USABLE": "0"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for var in ("INCLUDE_ALL", "MIN_DL", "LP_RAM_MB", "LP_VRAM_MB", "LLAMA_SERVER", "CHECK_DAYS",
                    "LP_ASSUME_TTY"):
            os.environ.pop(var, None)
        self.urls = []
        patcher = mock.patch.object(ms, "http_get", self.fake_http_get)
        patcher.start()
        self.addCleanup(patcher.stop)
        ms.Ctx.assume_yes = False
        ms.init_style(io.StringIO())          # no colours

    def fake_http_get(self, url, timeout=25):
        self.urls.append(url)
        if getattr(self, "offline", False):
            raise urllib.error.URLError("offline")
        if "/models?limit=1" in url:
            return "[]"
        if "/models?author=ggml-org" in url or "sort=trendingScore" in url:
            return getattr(self, "list_json", None) or fixture("hf_list.json")
        if "/models?author=" in url:
            return "[]"
        if "/models/ggml-org/NewModel-3B" in url:
            return fixture("hf_model_good.json")
        if "/models/random/Hyped-7B" in url:
            return fixture(self.hyped)
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    def hw(self, ram=16384, vram=0, kind="none", usable=False, cores=4):
        return ms.Hw(ram_mb=ram, cores=cores, gpu_kind=kind, gpu_name="Test", vram_mb=vram, gpu_usable=usable)

    def run_main(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("sys.stdin", io.StringIO(stdin)):
            rc = ms.main(argv)
        return rc, out.getvalue(), err.getvalue()


class TestDatesAndState(Base):
    def test_dates(self):
        with mock.patch.dict(os.environ, {"LP_TODAY": "2026-10-12"}):
            self.assertEqual(ms.days_since("2026-10-05"), 7)
        self.assertEqual(ms.days_since("2026-10-05"), 0)
        self.assertEqual(ms.add_days("2026-10-05", 7), "2026-10-12")
        self.assertEqual(ms.add_days("2026-10-26", 7), "2026-11-02")
        self.assertEqual(ms.add_days("2026-10-05", -30), "2026-09-05")

    def test_state_roundtrip(self):
        self.assertEqual(ms.state_get("nothing"), "")
        ms.state_set("a", 1)
        ms.state_set("b", "two words")
        ms.state_set("a", 3)
        self.assertEqual(ms.state_get("a"), "3")
        self.assertEqual(ms.state_get("b"), "two words")
        self.assertEqual(Path(os.environ["STATE_FILE"]).read_text().count("a="), 1)

    def test_state_is_data_never_executed(self):
        marker = self.tmp / "pwned"
        ms.state_set("evil", f"$(touch {marker}); `touch {marker}`")
        self.assertIn("touch", ms.state_get("evil"))
        self.assertFalse(marker.exists())

    def test_state_strips_newlines_and_tolerates_junk(self):
        ms.state_set("multi", "x\ny")
        self.assertEqual(ms.state_get("multi"), "xy")
        Path(os.environ["STATE_FILE"]).write_text("garbage line\n=\nk=v\n")
        self.assertEqual(ms.state_get("k"), "v")
        self.assertEqual(ms.state_int("k"), 0)         # not a number: 0, no crash


class TestFit(Base):
    def test_cpu_budget(self):
        h = self.hw(16384)
        self.assertEqual(ms.fit(5 * GB // 2, h), "cpu")
        self.assertEqual(ms.fit(7 * GB, h), "cpu")
        self.assertEqual(ms.fit(8 * GB, h), "tight")
        self.assertEqual(ms.fit(10 * GB, h), "tight")
        self.assertEqual(ms.fit(15 * GB, h), "no")
        self.assertEqual(ms.fit(7 * GB, self.hw(8192)), "no")
        self.assertEqual(ms.fit(3 * GB, self.hw(8192)), "cpu")

    def test_usable_gpu(self):
        h = self.hw(16384, 12288, "nvidia", True, 8)
        self.assertEqual(ms.fit(7 * GB, h), "gpu")
        self.assertEqual(ms.fit(9 * GB, h), "tight")

    def test_unusable_gpu_is_ignored(self):
        self.assertEqual(ms.fit(1 * GB, self.hw(16384, 2048, "nvidia", False, 2)), "cpu")

    def test_apple_unified_memory(self):
        h = self.hw(16384, 0, "apple", True, 8)
        self.assertEqual(ms.fit(8 * GB, h), "gpu")
        self.assertEqual(ms.fit(10 * GB, h), "tight")

    def test_speed_estimates(self):
        h = self.hw()
        self.assertEqual(ms.est_tps(5 * GB // 2, "cpu", h), 5)
        self.assertEqual(ms.est_tps(2489757856, "cpu", h), 6)        # real gemma-3-4b file
        self.assertEqual(ms.est_tps(799525120, "cpu", h), 20)        # close to a real 2-core laptop (18)
        self.assertGreater(ms.est_tps(GB, "gpu", h), ms.est_tps(GB, "cpu", h))

    def test_measured_speed_replaces_default(self):
        ms.state_set("eff_bw", 14800)
        ms.state_set("eff_mode", "cpu")
        self.assertEqual(ms.est_tps(799525120, "cpu", self.hw()), 19)
        self.assertEqual(ms.est_tps(2900 * 1048576, "cpu", self.hw()), 5)

    def test_verdicts(self):
        self.assertEqual([ms.verdict(t) for t in (15, 14, 5, 4)], ["smooth", "usable", "usable", "slow"])

    def test_upgrade_labels(self):
        self.assertEqual(ms.upgrade_label(1000, 2500), "lighter, faster")
        self.assertEqual(ms.upgrade_label(3000, 2500), "bigger, more capable")
        self.assertEqual(ms.upgrade_label(2500, 2500), "similar size, newer")
        self.assertEqual(ms.upgrade_label(2500, 0), "new")


class TestRecommend(Base):
    def names(self, use, hw):
        return [m["name"] for m in ms.recommend(use, hw)]

    def test_chat_on_16gb_cpu(self):
        rows = ms.recommend("chat", self.hw())
        self.assertLessEqual(len(rows), 5)
        self.assertIn("4B", rows[0]["name"])                          # biggest model that still runs usably
        names = [r["name"] for r in rows]
        self.assertFalse(any("12b" in n.lower() or "14B" in n for n in names), "too slow on CPU")
        self.assertFalse(any("coder" in n.lower() for n in names), "chat excludes coding-only models")

    def test_use_filters(self):
        self.assertTrue(any("Coder-7B" in n for n in self.names("coding", self.hw(32768))))
        self.assertFalse(any("gemma" in n for n in self.names("coding", self.hw())))

    def test_fast_sorts_by_speed(self):
        self.assertIn("1b", ms.recommend("fast", self.hw())[0]["name"].lower())

    def test_small_machines(self):
        self.assertFalse(any("4b" in n.lower() for n in self.names("chat", self.hw(4096))))
        two_gb = ms.recommend("chat", self.hw(2048))
        self.assertTrue(two_gb and all(r["verdict"] == "tight" for r in two_gb), "tight fits never look usable")
        self.assertEqual(ms.recommend("chat", self.hw(1024)), [])

    def test_row_shape(self):
        row = ms.recommend("chat", self.hw())[0]
        for key in ("name", "repo", "file", "size", "mode", "tps", "verdict", "note"):
            self.assertIn(key, row)

    def test_catalog_is_well_formed(self):
        rows = ms.load_catalog()
        self.assertGreater(len(rows), 8)
        for m in rows:
            self.assertTrue(m["file"].endswith(".gguf"), m)
            self.assertGreater(m["size"], MIN := 300_000_000, m)
            self.assertTrue(set(m["tags"]) <= {"chat", "translation", "coding", "fast"}, m)
            self.assertRegex(m["repo"], r"^[\w.-]+/[\w.-]+$")
        self.assertEqual(len({m["name"] for m in rows}), len(rows), "duplicate names")


class TestHardware(Base):
    @unittest.skipUnless(sys.platform.startswith("linux"), "uses /proc/meminfo format")
    def test_linux_detection_and_gpu(self):
        with mock.patch.dict(os.environ, {"MEMINFO_FILE": str(FIX / "meminfo_16g")}):
            with mock.patch.object(ms, "run_cmd", return_value=""):
                h = ms.detect_hw()
                self.assertEqual((h.ram_mb, h.gpu_kind), (15625, "none"))
            smi = "NVIDIA GeForce RTX 3060, 12288\n"
            with mock.patch.object(ms, "run_cmd", return_value=smi), \
                    mock.patch.dict(os.environ, {"LP_GPU_USABLE": "1"}):
                h = ms.detect_hw()
                self.assertEqual((h.gpu_kind, h.gpu_name, h.vram_mb, h.gpu_usable),
                                 ("nvidia", "NVIDIA GeForce RTX 3060", 12288, True))
            with mock.patch.object(ms, "run_cmd", return_value=smi):       # CPU-only llama.cpp build
                self.assertFalse(ms.detect_hw().gpu_usable)
            with mock.patch.object(ms, "run_cmd", return_value="garbage"):
                self.assertEqual(ms.detect_hw().gpu_kind, "none")

    def test_overrides(self):
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "8192", "LP_VRAM_MB": "6144"}), \
                mock.patch.object(ms, "run_cmd", return_value=""):
            h = ms.detect_hw()
        self.assertEqual((h.ram_mb, h.vram_mb, h.gpu_kind), (8192, 6144, "gpu"))

    def test_signature_changes_with_hardware(self):
        self.assertNotEqual(self.hw(16384).sig(), self.hw(32768).sig())

    def test_description_has_only_hardware_facts(self):
        text = ms.describe_hw(self.hw(16384, 2048, "nvidia", False, 2))
        for needle in ("16 GB RAM", "not used by your llama.cpp build", "CPU mode"):
            self.assertIn(needle, text)
        self.assertNotIn(str(Path.home()), text)

    def test_gpu_usable_needs_a_gpu_backend(self):
        with mock.patch.object(ms, "find_llama_server", return_value="/x/llama-server"):
            with mock.patch.object(ms, "run_cmd", return_value="Available devices:\n  CUDA0: GeForce"):
                self.assertTrue(ms.gpu_usable())
            with mock.patch.object(ms, "run_cmd", return_value="Available devices:\n"):
                self.assertFalse(ms.gpu_usable())
        with mock.patch.object(ms, "find_llama_server", return_value=""):
            self.assertFalse(ms.gpu_usable())


class TestParsers(Base):
    def test_parse_models(self):
        rows = ms.parse_models(json.loads(fixture("hf_list.json")), "2026-09-01")
        ids = [r[0] for r in rows]
        self.assertIn("ggml-org/NewModel-3B-GGUF", ids)
        self.assertNotIn("ggml-org/OldModel-3B-GGUF", ids)            # too old
        self.assertNotIn("someone/Private-GGUF", ids)                 # private
        self.assertEqual(rows[0], ("ggml-org/NewModel-3B-GGUF", 900, 4, "2026-10-01"))
        self.assertEqual(ms.parse_models(None, "2026-01-01"), [])
        self.assertEqual(ms.parse_models([{"no": "id"}, {"id": "a/b"}], "2026-01-01"), [])

    def test_model_files(self):
        files = dict(ms.model_files(json.loads(fixture("hf_model_good.json"))))
        self.assertEqual(files["NewModel-3B-Q4_K_M.gguf"], 2000000000)
        self.assertIn("NewModel-3B-Q8_0.gguf", files)
        self.assertEqual(len(files), 2, "no mmproj, split, subfolder or non-gguf files")
        self.assertEqual(ms.model_files(json.loads(fixture("hf_model_gated.json"))), [])
        self.assertEqual(ms.model_files(None), [])
        self.assertEqual(ms.model_files({"siblings": None}), [])

    def test_choose_quant(self):
        files = [("m-Q8_0.gguf", 3_400_000_000), ("m-Q4_K_M.gguf", 2_000_000_000)]
        self.assertEqual(ms.choose_quant(files, self.hw())[0], "m-Q4_K_M.gguf")      # prefers Q4_K_M
        self.assertIsNone(ms.choose_quant(files, self.hw(3072)))                       # nothing fits
        self.assertIsNone(ms.choose_quant([("adapter-Q4_K_M.gguf", 200_000_000)], self.hw()))  # too small
        self.assertIsNone(ms.choose_quant([("big-Q4_K_M.gguf", 4_500_000_000)], self.hw()))    # too slow (3 t/s)
        self.assertEqual(ms.choose_quant([("q-q4_k_m.GGUF", 2_000_000_000)], self.hw())[0], "q-q4_k_m.GGUF")

    def test_trust(self):
        self.assertTrue(ms.is_trusted("bartowski/Foo-GGUF"))
        self.assertTrue(ms.is_trusted("openbmb/MiniCPM5-2B-GGUF"))
        self.assertFalse(ms.is_trusted("someone/Foo-GGUF"))
        self.assertFalse(ms.is_trusted("bartowski-fake/Foo-GGUF"))

    def test_bench_csv_real_output(self):
        self.assertEqual(ms.parse_bench_csv(fixture("bench.csv")), 19)
        self.assertIsNone(ms.parse_bench_csv("not,csv\n1,2"))
        self.assertIsNone(ms.parse_bench_csv(""))


class TestPrompt(Base):
    def setUp(self):
        super().setUp()
        os.environ["LP_ASSUME_TTY"] = "1"

    def test_rules(self):
        self.assertFalse(ms.should_prompt(), "no profile yet: the wizard handles it")
        ms.state_set("hw_sig", "x")
        self.assertTrue(ms.should_prompt(), "never checked")
        for last, want in (("2026-09-20", True), ("2026-09-28", True), ("2026-09-29", False)):
            ms.state_set("last_checked", last)
            self.assertEqual(ms.should_prompt(), want, last)
        ms.state_set("last_checked", "2026-09-01")
        for snooze, want in (("2026-10-10", False), ("2026-10-05", True), ("2026-10-01", True)):
            ms.state_set("next_prompt", snooze)
            self.assertEqual(ms.should_prompt(), want, snooze)
        ms.state_set("check_updates", "off")
        self.assertFalse(ms.should_prompt())
        ms.state_set("check_updates", "on")
        with mock.patch.dict(os.environ, {"CHECK_DAYS": "0"}):
            self.assertFalse(ms.should_prompt())
        with mock.patch.dict(os.environ, {"CHECK_DAYS": "14"}):
            ms.state_set("last_checked", "2026-09-25")
            ms.state_set("next_prompt", "")
            self.assertFalse(ms.should_prompt(), "10 days < 14")

    def test_never_blocks_when_not_interactive(self):
        ms.state_set("hw_sig", "x")
        os.environ.pop("LP_ASSUME_TTY")
        self.assertFalse(ms.should_prompt(interactive=False))
        rc, out, err = self.run_main(["--weekly-prompt"])        # stdin is not a tty here
        self.assertEqual((rc, out), (0, ""))

    def test_answers(self):
        ms.state_set("hw_sig", "x")
        ms.state_set("last_checked", "2026-09-01")
        rc, out, _ = self.run_main(["--weekly-prompt"], "n\n")
        self.assertIn("34 days since", out)
        self.assertEqual(ms.state_get("next_prompt"), "2026-10-12")
        self.assertEqual(ms.state_get("last_checked"), "2026-09-01", "n is not a check")
        ms.state_set("next_prompt", "")
        for ans in ("later\n", "\n", ""):
            self.run_main(["--weekly-prompt"], ans)
            self.assertEqual(ms.state_get("next_prompt"), "", repr(ans))
        self.run_main(["--weekly-prompt"], "never\n")
        self.assertEqual(ms.state_get("check_updates"), "off")
        self.assertFalse(ms.should_prompt())

    def test_yes_runs_the_check(self):
        ms.state_set("hw_sig", "x")
        ms.state_set("last_checked", "2026-09-01")
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"}), mock.patch.object(ms, "run_cmd", return_value=""):
            rc, out, _ = self.run_main(["--weekly-prompt"], "y\n")
        self.assertIn("Checking Hugging Face", out)
        self.assertEqual(ms.state_get("last_checked"), "2026-10-05")
        self.assertFalse(ms.should_prompt(), "right after a check, no prompt")


class TestUpdates(Base):
    def setUp(self):
        super().setUp()
        ms.state_set("installed_size_mb", 2374)
        ms.state_set("installed_repo", "ggml-org/gemma-3-4b-it-GGUF")
        ms.state_set("installed", "gemma-3-4b-it-Q4_K_M")
        ms.state_set("last_checked", "2026-09-01")

    def upgrades(self, hw=None):
        return ms.find_upgrades("2026-09-01", hw or self.hw())

    def test_finds_new_trusted_model(self):
        rows = self.upgrades()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["repo"], r["file"], r["size"], r["tps"], r["label"], r["downloads"], r["created"]),
                         ("ggml-org/NewModel-3B-GGUF", "NewModel-3B-Q4_K_M.gguf", 2000000000, 8,
                          "similar size, newer", 900, "2026-10-01"))

    def test_unknown_authors_skipped_by_default(self):
        repos = [r["repo"] for r in self.upgrades()]
        self.assertFalse(any("Hyped" in r or "Nobody" in r or "Private" in r or "Old" in r for r in repos))

    def test_include_all_still_filters_gated_unpopular_and_slow(self):
        with mock.patch.dict(os.environ, {"INCLUDE_ALL": "1", "MIN_DL": "1000"}):
            self.assertFalse(any("Hyped" in r["repo"] for r in self.upgrades()), "gated")
            self.assertFalse(any("Nobody" in r["repo"] for r in self.upgrades()), "download floor")
            self.hyped = "hf_model_big.json"
            self.assertFalse(any("Hyped" in r["repo"] for r in self.upgrades()), "3 t/s on this CPU")
            rows = self.upgrades(self.hw(16384, 8192, "nvidia", True, 8))
            hyped = [r for r in rows if "Hyped" in r["repo"]]
            self.assertEqual(len(hyped), 1)
            self.assertEqual(hyped[0]["label"], "bigger, more capable")

    def test_excluded_names_even_when_trusted(self):
        data = json.loads(fixture("hf_list.json"))
        data[0]["id"] = "bartowski/Foo-abliterated-GGUF"
        self.list_json = json.dumps(data)
        self.assertFalse(any("abliterated" in r["repo"] for r in self.upgrades()))

    def test_never_suggests_what_is_installed(self):
        ms.state_set("installed_repo", "ggml-org/NewModel-3B-GGUF")
        self.assertEqual(self.upgrades(), [])

    def test_queries_trusted_authors_and_trending(self):
        self.upgrades()
        joined = "\n".join(self.urls)
        for needle in ("author=ggml-org", "author=bartowski", "sort=trendingScore"):
            self.assertIn(needle, joined)
        for url in self.urls:
            self.assertTrue(url.startswith("https://huggingface.co/"), url)

    def test_check_updates_flow(self):
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"}), mock.patch.object(ms, "run_cmd", return_value=""):
            rc, out, _ = self.run_main(["--check-updates", "--yes"])
        self.assertEqual(rc, 0)
        for needle in ("released since 2026-09-01", "NewModel-3B-GGUF", "a hint, not a quality score"):
            self.assertIn(needle, out)
        self.assertEqual(ms.state_get("last_checked"), "2026-10-05")
        self.assertEqual(ms.state_get("next_prompt"), "2026-10-12")
        self.assertFalse((self.tmp / "models").exists(), "default answer (n) downloads nothing")

    def test_offline_does_not_advance_last_checked(self):
        self.offline = True
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"}), mock.patch.object(ms, "run_cmd", return_value=""):
            rc, out, _ = self.run_main(["--check-updates"])
        self.assertEqual(rc, 1)
        self.assertIn("Could not reach Hugging Face", out)
        self.assertEqual(ms.state_get("last_checked"), "2026-09-01")

    def test_nothing_new(self):
        self.list_json = "[]"
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"}), mock.patch.object(ms, "run_cmd", return_value=""):
            rc, out, _ = self.run_main(["--check-updates"])
        self.assertIn("Nothing new fits", out)

    def test_hardware_change_is_noticed(self):
        ms.state_set("hw_sig", "1-0-none-0-4")
        ms.state_set("eff_bw", 9999)
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"}), mock.patch.object(ms, "run_cmd", return_value=""):
            rc, out, _ = self.run_main(["--check-updates"])
        self.assertIn("hardware changed", out)
        self.assertEqual(ms.state_get("eff_bw"), "")

    def test_picking_a_candidate_downloads_and_tests_it(self):
        def fake_fetch(url, part, size):
            part.parent.mkdir(parents=True, exist_ok=True)
            with open(part, "wb") as f:
                f.truncate(size)
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"}), mock.patch.object(ms, "run_cmd", return_value=""), \
                mock.patch.object(ms, "fetch_file", fake_fetch), mock.patch.object(ms, "run_bench", return_value=12):
            rc, out, err = self.run_main(["--check-updates"], "1\n")
        self.assertIn("Generation speed: 12 t/s", out)
        self.assertTrue((self.tmp / "models" / "NewModel-3B-Q4_K_M.gguf").is_file())
        self.assertEqual(ms.state_get("installed"), "NewModel-3B-Q4_K_M")
        self.assertEqual(ms.state_get("installed_size_mb"), "1907")


class TestDownload(Base):
    def test_success_path_and_url(self):
        calls = []

        def fake(url, part, size):
            calls.append(url)
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(b"x" * size)
        with mock.patch.object(ms, "fetch_file", fake), contextlib.redirect_stderr(io.StringIO()):
            path = ms.download("org/repo-GGUF", "m-Q4_K_M.gguf", 1000)
        self.assertEqual(path, self.tmp / "models" / "m-Q4_K_M.gguf")
        self.assertEqual(calls, ["https://huggingface.co/org/repo-GGUF/resolve/main/m-Q4_K_M.gguf"])
        self.assertFalse(Path(str(path) + ".part").exists())

    def test_size_mismatch_keeps_part_for_resume(self):
        def fake(url, part, size):
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(b"x" * 900)
        buf = io.StringIO()
        with mock.patch.object(ms, "fetch_file", fake), contextlib.redirect_stderr(buf):
            self.assertIsNone(ms.download("o/r", "m.gguf", 1000))
        self.assertIn("does not match", buf.getvalue())
        self.assertFalse((self.tmp / "models" / "m.gguf").exists())
        self.assertTrue((self.tmp / "models" / "m.gguf.part").exists())

    def test_low_disk_space_stops_before_downloading(self):
        called = []
        buf = io.StringIO()
        with mock.patch.object(ms, "fetch_file", lambda *a: called.append(a)), \
                mock.patch.object(ms.shutil, "disk_usage", return_value=mock.Mock(free=100)), \
                contextlib.redirect_stderr(buf):
            self.assertIsNone(ms.download("o/r", "big.gguf", 5_000_000_000))
        self.assertIn("Not enough free disk space", buf.getvalue())
        self.assertEqual(called, [])

    def test_network_failure(self):
        buf = io.StringIO()
        with mock.patch.object(ms, "fetch_file", side_effect=urllib.error.URLError("down")), \
                contextlib.redirect_stderr(buf):
            self.assertIsNone(ms.download("o/r", "m.gguf", 10))
        self.assertIn("Download failed", buf.getvalue())

    def test_path_traversal_stays_in_models_dir(self):
        def fake(url, part, size):
            part.write_bytes(b"x" * size)
        with mock.patch.object(ms, "fetch_file", fake), contextlib.redirect_stderr(io.StringIO()):
            path = ms.download("o/r", "../../evil.gguf", 10)
        self.assertEqual(path.parent, self.tmp / "models")
        self.assertFalse((self.tmp / "evil.gguf").exists())


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """Minimal static server that honours Range (or ignores it when ignore_range is set)."""
    payload = b""
    ignore_range = False

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng and not self.ignore_range:
            start = int(rng.split("=")[1].rstrip("-"))
            body = self.payload[start:]
            self.send_response(206)
        else:
            body = self.payload
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class TestRealFetch(Base):
    """fetch_file against a local HTTP server: fresh download, resume, and a server that ignores Range."""

    def serve(self, payload, ignore_range=False):
        handler = type("H", (RangeHandler,), {"payload": payload, "ignore_range": ignore_range})
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}/f.gguf"

    def test_fresh_resume_and_range_ignored(self):
        data = bytes(range(256)) * 5000                    # 1.28 MB, spans two read chunks
        url = self.serve(data)
        part = self.tmp / "f.part"
        ms.fetch_file(url, part, len(data))
        self.assertEqual(part.read_bytes(), data)
        part.write_bytes(data[:300_000])                   # interrupted download
        ms.fetch_file(url, part, len(data))
        self.assertEqual(part.read_bytes(), data, "resumed from the partial file")
        url2 = self.serve(data, ignore_range=True)
        part.write_bytes(data[:300_000])
        ms.fetch_file(url2, part, len(data))
        self.assertEqual(part.read_bytes(), data, "server ignored Range: restarted cleanly, no corruption")


class TestBench(Base):
    def test_run_bench_without_llama_bench(self):
        with mock.patch.object(ms, "find_bench", return_value=""), self.assertRaises(FileNotFoundError):
            ms.run_bench(Path("x.gguf"))

    def test_model_speed_reporting(self):
        h = self.hw()
        size = 2489757856
        for tps, word in ((40, "smooth"), (12, "usable"), (3, "slow")):
            buf = io.StringIO()
            with mock.patch.object(ms, "run_bench", return_value=tps), contextlib.redirect_stdout(buf):
                self.assertEqual(ms.check_model_speed(Path("m.gguf"), size, h), 0)
            self.assertIn(word, buf.getvalue())
        self.assertEqual(ms.state_get("measured_tps"), "3")
        self.assertEqual(ms.state_get("eff_bw"), str(3 * 2374))
        buf = io.StringIO()
        with mock.patch.object(ms, "run_bench", return_value=None), contextlib.redirect_stdout(buf):
            self.assertEqual(ms.check_model_speed(Path("m.gguf"), size, h), 1)
        self.assertIn("did not load", buf.getvalue())
        with mock.patch.object(ms, "run_bench", side_effect=FileNotFoundError), contextlib.redirect_stdout(buf):
            self.assertEqual(ms.check_model_speed(Path("m.gguf"), size, h), 2)


class TestCli(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"LP_RAM_MB": "16384"})
        p.start()
        self.addCleanup(p.stop)
        for target, kw in (("run_cmd", {"return_value": ""}), ("run_bench", {"return_value": 12}),
                           ("find_llama_server", {"return_value": ""})):
            q = mock.patch.object(ms, target, **kw)
            q.start()
            self.addCleanup(q.stop)
        self.fetches = []

        def fake_fetch(url, part, size):
            self.fetches.append(url)
            part.parent.mkdir(parents=True, exist_ok=True)
            with open(part, "wb") as f:
                f.truncate(size)
        q = mock.patch.object(ms, "fetch_file", fake_fetch)
        q.start()
        self.addCleanup(q.stop)

    def test_list_only(self):
        rc, out, _ = self.run_main(["--list", "--use", "chat"])
        self.assertEqual(rc, 0)
        self.assertIn("Recommended for you", out)
        self.assertEqual(self.fetches, [])
        self.assertTrue(Path(os.environ["STATE_FILE"]).exists(), "hardware profile saved")

    def test_full_wizard_then_rerun(self):
        rc, out, err = self.run_main(["--yes", "--use", "chat"])
        self.assertEqual(rc, 0)
        for needle in ("Your system: 16 GB RAM", "Qwen3-4B-Q4_K_M", "Generation speed: 12 t/s", "serve.sh"):
            self.assertIn(needle, out)
        self.assertIn("Downloading Qwen3-4B-Q4_K_M.gguf", err)
        self.assertTrue((self.tmp / "models" / "Qwen3-4B-Q4_K_M.gguf").is_file())
        state = Path(os.environ["STATE_FILE"]).read_text()
        for needle in ("installed=Qwen3-4B-Q4_K_M", "measured_tps=12", "last_checked=2026-10-05", "use=chat"):
            self.assertIn(needle, state)
        self.assertNotIn(str(Path.home()), state)
        self.assertEqual(len(self.fetches), 1)
        rc, out, _ = self.run_main(["--yes", "--use", "chat"])
        self.assertIn("already in", out)
        self.assertEqual(len(self.fetches), 1, "second run does not download again")

    def test_wizard_interactive_choices(self):
        rc, out, err = self.run_main([], "3\n1\n")          # use = coding, first pick
        self.assertEqual(rc, 0)
        self.assertEqual(ms.state_get("use"), "coding")
        # Qwen3-4B carries the coding tag and runs usably here, so it outranks the slow 7B coder
        self.assertEqual(ms.state_get("installed"), "Qwen3-4B-Q4_K_M")

    def test_invalid_choice_and_skip(self):
        rc, out, _ = self.run_main(["--use", "chat"], "99\n")
        self.assertEqual(rc, 1)
        rc, out, _ = self.run_main(["--use", "chat"], "n\n")
        self.assertIn("Skipped", out)
        self.assertEqual(self.fetches, [])

    def test_test_command(self):
        model = self.tmp / "models" / "Qwen3-4B-Q4_K_M.gguf"
        model.parent.mkdir()
        model.write_bytes(b"x" * 1000)
        ms.state_set("installed", "Qwen3-4B-Q4_K_M")
        rc, out, _ = self.run_main(["--test"])
        self.assertEqual(rc, 0)
        self.assertIn("Testing Qwen3-4B-Q4_K_M.gguf", out)
        with mock.patch.object(ms, "run_bench", return_value=None):
            self.assertEqual(self.run_main(["--test", str(model)])[0], 1)
        model.unlink()
        rc, out, _ = self.run_main(["--test"])
        self.assertEqual(rc, 1)
        self.assertIn("No model to test", out)

    def test_tiny_machine_and_unreadable_ram(self):
        with mock.patch.dict(os.environ, {"LP_RAM_MB": "1024"}):
            rc, out, _ = self.run_main(["--yes", "--use", "chat"])
        self.assertEqual(rc, 1)
        self.assertIn("No catalog model fits", out)
        with mock.patch.dict(os.environ, {"LP_RAM_MB": ""}), mock.patch.object(ms, "read_ram_mb", return_value=0):
            rc, out, _ = self.run_main(["--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("Could not read your RAM", out)

    def test_unknown_option_and_help(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            ms.main(["--bogus"])
        self.assertEqual(cm.exception.code, 2)
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as cm:
            ms.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--check-updates", out.getvalue())


if __name__ == "__main__":
    unittest.main()
