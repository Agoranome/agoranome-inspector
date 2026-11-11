"""Model uses: the month's hard cap, failure that never reaches the caller, the weekly note's number check, the
run doctor's issue and the sealed red-team report."""

import functools
import json
from types import SimpleNamespace

import pytest

from agoranome_inspector import assist, measure, models
from agoranome_inspector.cli import main
from agoranome_inspector.keys import Signer

from fakes import standard_market


class FakeClient:
    """Stands in for anthropic.Anthropic: counts tokens, answers, and records what it was asked."""

    def __init__(self, text="An answer.", *, input_tokens=1000, output_tokens=500, stop="end_turn",
                 served="claude-opus-5-5", fail=None):
        self.calls = []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=input_tokens))
        reply = SimpleNamespace(model=served, stop_reason=stop, content=[
            SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0))

        def create(**kw):
            self.calls.append(kw)
            if fail:
                raise fail
            return reply

        class Stream:
            def __init__(self, **kw):
                create(**kw)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return reply

        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create, stream=Stream))


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "spend.jsonl"
    path.touch()
    return models.Ledger(str(path))


def test_a_call_reserves_its_worst_case_then_settles_at_its_usage(ledger):
    client = FakeClient("Hello.")
    assert models.ask("t", "sys", "user", max_tokens=8000, client=client, ledger=ledger) == "Hello."
    lines = [json.loads(x) for x in ledger.path.read_text().splitlines()]
    assert [x["state"] for x in lines] == ["reserved", "settled"]
    assert lines[0]["usd"] == pytest.approx(models.worst_case(1000, 8000))
    assert lines[1]["usd"] == pytest.approx((1000 * 4 + 500 * 20) / 1e6)
    assert ledger.spent() == pytest.approx(lines[1]["usd"])
    call = client.calls[0]
    assert call["fallbacks"] == "default" and call["betas"] == [models.FALLBACK_BETA]
    assert call["output_config"] == {"effort": "medium"} and "thinking" not in call


def test_the_cap_is_never_passed(ledger, monkeypatch):
    month = models._now().strftime("%Y-%m")
    ledger.add({"call": "old", "month": month, "use": "t", "state": "settled", "usd": 19.5})
    client = FakeClient()
    assert models.ask("t", "s", "u", max_tokens=64000, client=client, ledger=ledger) is None
    assert client.calls == []                                         # no call was made
    assert models.ask("t", "s", "u", max_tokens=1000, client=client, ledger=ledger) == "An answer."
    monkeypatch.setenv("INSPECTOR_MODEL_CAP_USD", "500")                # the cap cannot be raised
    assert models.cap() == models.CAP_USD
    monkeypatch.setenv("INSPECTOR_MODEL_CAP_USD", "5")
    assert models.ask("t", "s", "u", max_tokens=1000, client=client, ledger=ledger) is None


def test_last_months_spend_does_not_count(ledger):
    ledger.add({"call": "a", "month": "2000-01", "use": "t", "state": "settled", "usd": 19.99})
    assert ledger.spent() == 0


def test_a_failed_call_stays_reserved_and_nothing_raises(ledger):
    assert models.ask("t", "s", "u", max_tokens=8000, client=FakeClient(fail=RuntimeError("boom")),
                      ledger=ledger) is None
    assert ledger.spent() == pytest.approx(models.worst_case(1000, 8000))


def test_refusals_cut_answers_and_unknown_models(ledger):
    assert models.ask("t", "s", "u", max_tokens=100, client=FakeClient(stop="refusal"), ledger=ledger) is None
    assert models.ask("t", "s", "u", max_tokens=100, client=FakeClient(stop="max_tokens"), ledger=ledger) is None
    models.ask("t", "s", "u", max_tokens=100, client=FakeClient(served="claude-future-9"), ledger=ledger)
    last = json.loads(ledger.path.read_text().splitlines()[-1])
    assert last["usd"] == pytest.approx((1000 * models.WORST_IN + 500 * models.WORST_OUT) / 1e6)


def test_no_ledger_no_key_or_a_damaged_ledger_means_no_call(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.delenv("INSPECTOR_SPEND_LEDGER", raising=False)
    assert models.ask("t", "s", "u", max_tokens=10, client=client) is None
    missing = models.Ledger(str(tmp_path / "never-read.jsonl"))
    assert models.ask("t", "s", "u", max_tokens=10, client=client, ledger=missing) is None
    damaged = tmp_path / "damaged.jsonl"
    damaged.write_text('{"call": "a", "month"\n')
    assert models.ask("t", "s", "u", max_tokens=10, client=client, ledger=models.Ledger(str(damaged))) is None
    monkeypatch.setenv("INSPECTOR_SPEND_LEDGER", str(tmp_path / "s.jsonl"))
    (tmp_path / "s.jsonl").touch()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert models.ask("t", "s", "u", max_tokens=10) is None
    assert client.calls == []


# --- The weekly note -----------------------------------------------------------------------------------------------

@pytest.fixture
def site(tmp_path, monkeypatch):
    market = standard_market()
    monkeypatch.setattr(measure, "IndexReader", lambda: market.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: market.fetcher())
    monkeypatch.setattr(measure, "Settings", functools.partial(measure.Settings, retry_pause=0, confirm_pause=0,
                                                               host_pause=0))
    key = tmp_path / "key.pem"
    assert main(["keygen", "--out", str(key)]) == 0
    site = tmp_path / "site"
    for day in ("2026-11-16", "2026-11-23"):
        assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key),
                     "--id", f"x402-{day}", "--concurrency", "2"]) == 0
    return site


def test_the_note_sees_counts_only(site):
    found = assist.facts(str(site))
    text = json.dumps(found)
    assert found["markets"]["x402"]["sheet"] == "x402-2026-11-23"
    assert found["markets"]["x402"]["changes_since"] == "x402-2026-11-16"
    assert "://" not in text and ".example" not in text and "0x" not in text   # no row, host or address


def test_a_note_with_a_number_not_in_the_counts_is_dropped(site):
    found = assist.facts(str(site))
    rows = found["markets"]["x402"]["rows"]
    good = f"This week the x402 sheet holds {rows:,} listings, as of 2026-11-23."
    assert assist.unchecked_numbers(good, found) == []
    assert assist.unchecked_numbers(f"About {rows + 977} listings, up 12.5%.", found) == [str(rows + 977), "12.5%"]
    asked = []

    def model(use, system, user, **kw):
        asked.append(user)
        return f"The sheet holds {rows + 977} listings."

    assert assist.weekly_note(str(site), ask=model) is None
    assert not (site / "notes").exists()
    assert ".example" not in asked[0]


def test_a_checked_note_is_written_once_outside_the_book(site):
    rows = assist.facts(str(site))["markets"]["x402"]["rows"]
    book_before = (site / "book.jsonl").read_bytes()
    path = assist.weekly_note(str(site), ask=lambda *a, **k: f"The x402 sheet holds {rows} listings this week.")
    assert path == site / "notes" / "x402-2026-11-23.md"
    text = path.read_text()
    assert "Written by a model" in text and "not part of the signed book" in text
    assert (site / "book.jsonl").read_bytes() == book_before
    assert assist.weekly_note(str(site), ask=lambda *a, **k: pytest.fail("asked twice")) is None
    assert main(["verify", str(site), "--all"]) == 0


def test_no_model_no_note(site):
    assert assist.weekly_note(str(site), ask=lambda *a, **k: None) is None


# --- The run doctor -------------------------------------------------------------------------------------------------

HELD_LOG = '\n'.join([
    "some output",
    json.dumps({"held": ["41% of the endpoints asked gave no answer at all (bound 25%)"], "sheet": "x402-2026-11-23"}),
    "HELD, not published: ...",
    "::error::Held by the check before signing, not published: x402.",
])


def test_the_doctor_opens_an_issue_with_the_facts_even_without_a_model():
    issue = assist.doctor_issue(HELD_LOG, "https://github.com/o/r/actions/runs/1", ask=lambda *a, **k: None,
                                day="2026-11-23")
    assert issue["title"] == "Weekly run held on 2026-11-23"
    assert "41% of the endpoints" in issue["body"] and "publish anyway" in issue["body"]
    assert "No model reading" in issue["body"]
    failed = assist.doctor_issue("Traceback ...\nRuntimeError: x", None, ask=lambda *a, **k: "Look at the index.")
    assert failed["title"].startswith("Weekly run failed") and "A model's reading" in failed["body"]


def test_open_issue_posts_with_the_job_token():
    seen = {}

    def post(url, json=None, **kw):
        seen.update(url=url, json=json, auth=kw["headers"]["Authorization"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"html_url": "https://x/1"})

    url = assist.open_issue({"title": "t", "body": "b"}, repo="o/r", token="tok", post=post)
    assert url == "https://x/1" and seen["url"] == "https://api.github.com/repos/o/r/issues"
    assert seen["auth"] == "Bearer tok"


# --- The monthly red-team -------------------------------------------------------------------------------------------

FINDINGS = [{"severity": "low", "title": "Loose header", "file": "fetch.py", "what_goes_wrong": "w", "fix": "x"},
            {"severity": "high", "title": "Forged root", "file": "verify.py", "what_goes_wrong": "v", "fix": "y"}]


def test_the_red_team_reads_this_code_and_its_findings_are_sealed(tmp_path, capsys):
    sent = {}

    def model(use, system, user, **kw):
        sent.update(user=user, kw=kw)
        return json.dumps({"findings": FINDINGS})

    findings = assist.red_team(".", ask=model)
    assert findings == FINDINGS
    assert 'path="src/agoranome_inspector/rule.py"' in sent["user"] and sent["kw"]["stream"]
    assert sent["kw"]["output_format"]["type"] == "json_schema"
    signer = Signer.generate()
    issue = assist.red_team_issue(findings, signer, day="2026-12-02")
    assert issue["title"] == "Monthly red-team, 2026-12-02: 1 high, 0 medium, 1 low"
    assert "Forged root" not in issue["body"] and "verify.py" not in issue["body"]
    report = assist.unseal(issue["body"], signer)
    assert report.index("[high] Forged root") < report.index("[low] Loose header")
    with pytest.raises(Exception):
        assist.unseal(issue["body"], Signer.generate())                 # another key cannot read it
    key = tmp_path / "key.pem"
    key.write_text(signer.pem())
    body = tmp_path / "issue.txt"
    body.write_text(issue["body"])
    assert main(["reveal", str(body), "--key-file", str(key)]) == 0
    assert "[high] Forged root (verify.py)" in capsys.readouterr().out


def test_an_unusable_red_team_answer_is_none():
    assert assist.red_team(".", ask=lambda *a, **k: None) is None
    assert assist.red_team(".", ask=lambda *a, **k: "not json") is None
