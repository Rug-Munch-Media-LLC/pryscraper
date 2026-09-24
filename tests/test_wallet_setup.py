# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.payments.wallet_setup — address validation, .env read/write,
masking, and the Click `wallets` command group. No live infra.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - pytest annotations remain runtime-safe

import pytest
from click.testing import CliRunner

from pry.payments import wallet_setup as ws


class TestValidateAddress:
    @pytest.mark.parametrize(
        "addr",
        [
            "0x" + "a" * 40,
            "0x52908400098527886E0F7030069857D2E4169EE7",  # checksummed
        ],
    )
    def test_evm_valid(self, addr: str) -> None:
        assert ws.validate_address("evm", addr) is True

    def test_evm_all_uppercase_body_rejected(self) -> None:
        # `0x` prefix is lowercase, so addr != addr.upper(); the mixed-case
        # body then fails checksum validation. Pins the real behavior.
        assert ws.validate_address("evm", "0x" + "A" * 40) is False

    @pytest.mark.parametrize(
        "addr",
        [
            "0x" + "a" * 39,  # too short
            "0x" + "a" * 41,  # too long
            "a" * 42,  # no 0x
            "0x" + "g" * 40,  # non-hex
            "",
        ],
    )
    def test_evm_invalid(self, addr: str) -> None:
        assert ws.validate_address("evm", addr) is False

    def test_evm_whitespace_stripped(self) -> None:
        assert ws.validate_address("evm", "  0x" + "a" * 40 + "  ") is True

    def test_solana_valid(self) -> None:
        assert ws.validate_address("solana", "1" * 32) is True
        assert ws.validate_address("solana", "A" * 44) is True

    @pytest.mark.parametrize("addr", ["1" * 31, "1" * 45, "0" * 32, "O" * 32, ""])
    def test_solana_invalid(self, addr: str) -> None:
        assert ws.validate_address("solana", addr) is False

    def test_tron_valid(self) -> None:
        assert ws.validate_address("tron", "T" + "1" * 33) is True

    @pytest.mark.parametrize("addr", ["T" + "1" * 32, "A" + "1" * 33, "T" + "0" * 33, ""])
    def test_tron_invalid(self, addr: str) -> None:
        assert ws.validate_address("tron", addr) is False

    def test_unknown_family_returns_false(self) -> None:
        assert ws.validate_address("dogecoin", "D" * 34) is False


class TestEnvHelpers:
    def test_read_env_missing_file(self, tmp_path: Path) -> None:
        assert ws._read_env(tmp_path / "nope.env") == {}

    def test_read_env_parses_and_strips_quotes(self, tmp_path: Path) -> None:
        p = tmp_path / ".env"
        p.write_text("# comment\nA=1\nB=\"two\"\nC='three'\n\nD=has=equals\nno_equals_line\n")
        assert ws._read_env(p) == {"A": "1", "B": "two", "C": "three", "D": "has=equals"}

    def test_read_env_last_value_wins(self, tmp_path: Path) -> None:
        p = tmp_path / ".env"
        p.write_text("A=1\nA=2\n")
        assert ws._read_env(p) == {"A": "2"}

    def test_write_env_replaces_in_place_preserving_comments(self, tmp_path: Path) -> None:
        p = tmp_path / ".env"
        p.write_text("# keep me\nA=old\nB=keep\n")
        ws._write_env(p, {"A": "new"})
        text = p.read_text()
        assert "# keep me" in text
        assert "A=new" in text
        assert "B=keep" in text
        assert "A=old" not in text

    def test_write_env_appends_new_keys(self, tmp_path: Path) -> None:
        p = tmp_path / ".env"
        p.write_text("A=1\n")
        ws._write_env(p, {"B": "2"})
        assert p.read_text() == "A=1\nB=2\n"

    def test_write_env_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "nested" / "dir" / ".env"
        ws._write_env(p, {"A": "1"})
        assert p.read_text() == "A=1\n"

    def test_write_env_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / ".env"
        ws._write_env(p, {"X": "y"})
        assert ws._read_env(p) == {"X": "y"}


class TestMask:
    @pytest.mark.parametrize(
        ("addr", "expected"),
        [
            ("", "(unset)"),
            ("   ", "(unset)"),
            ("short", "shor...rt"),
            ("0x1234567890abcdef", "0x1234...cdef"),
        ],
    )
    def test_mask(self, addr: str, expected: str) -> None:
        assert ws._mask(addr) == expected


class TestCurrentWallets:
    def test_reads_from_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        p.write_text("PRY_X402_WALLET_BASE=0x" + "a" * 40 + "\n")
        result = ws._current_wallets(p)
        assert result["PRY_X402_WALLET_BASE"] == "0x" + "a" * 40
        assert result["PRY_X402_WALLET_SOLANA"] == ""

    def test_process_env_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = tmp_path / ".env"
        p.write_text("PRY_X402_WALLET_BASE=fromfile\n")
        monkeypatch.setenv("PRY_X402_WALLET_BASE", "fromenv")
        assert ws._current_wallets(p)["PRY_X402_WALLET_BASE"] == "fromenv"


class TestWalletsCli:
    def test_show_masks_configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        p.write_text("PRY_X402_WALLET_BASE=0x" + "a" * 40 + "\n")
        result = CliRunner().invoke(ws.wallets, ["show", "--env-file", str(p)])
        assert result.exit_code == 0
        assert "0xaaaa...aaaa" in result.output
        assert "(unset)" in result.output

    def test_validate_all_valid_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        p.write_text("PRY_X402_WALLET_BASE=0x" + "a" * 40 + "\n")
        result = CliRunner().invoke(ws.wallets, ["validate", "--env-file", str(p)])
        assert result.exit_code == 0
        assert "All configured wallets are valid." in result.output

    def test_validate_invalid_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        p.write_text("PRY_X402_WALLET_BASE=not-an-address\n")
        result = CliRunner().invoke(ws.wallets, ["validate", "--env-file", str(p)])
        assert result.exit_code == 1
        assert "INVALID" in result.output

    def test_validate_unset_is_not_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        p.write_text("")
        result = CliRunner().invoke(ws.wallets, ["validate", "--env-file", str(p)])
        assert result.exit_code == 0
        assert "unset" in result.output

    def test_init_writes_valid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        # 7 prompts: one per chain. Provide a valid Base address, skip the rest.
        inputs = ["0x" + "a" * 40] + [""] * 6
        result = CliRunner().invoke(
            ws.wallets, ["init", "--env-file", str(p)], input="\n".join(inputs) + "\n"
        )
        assert result.exit_code == 0
        assert "Wrote 1 wallet(s)" in result.output
        assert ws._read_env(p) == {"PRY_X402_WALLET_BASE": "0x" + "a" * 40}

    def test_init_invalid_wallet_not_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        inputs = ["bad-address"] + [""] * 6
        result = CliRunner().invoke(
            ws.wallets, ["init", "--env-file", str(p)], input="\n".join(inputs) + "\n"
        )
        assert result.exit_code == 0
        assert "invalid" in result.output
        assert "No wallets configured. Nothing written." in result.output
        assert not p.exists()

    def test_init_all_skipped_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for chain in ws.CHAINS:
            monkeypatch.delenv(str(chain["env"]), raising=False)
        p = tmp_path / ".env"
        result = CliRunner().invoke(ws.wallets, ["init", "--env-file", str(p)], input="\n" * 7)
        assert result.exit_code == 0
        assert "No wallets configured. Nothing written." in result.output
        assert not p.exists()
