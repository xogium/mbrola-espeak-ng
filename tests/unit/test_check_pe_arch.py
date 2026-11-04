import struct

import pytest

import check_pe_arch


def make_pe(machine: int, pe_offset: int = 0x80) -> bytes:
	data = bytearray(pe_offset + 24)
	data[0:2] = b"MZ"
	struct.pack_into("<I", data, 0x3C, pe_offset)
	data[pe_offset : pe_offset + 4] = b"PE\0\0"
	struct.pack_into("<H", data, pe_offset + 4, machine)
	return bytes(data)


def test_reads_machine_field():
	assert check_pe_arch.pe_machine(make_pe(0x8664)) == 0x8664
	assert check_pe_arch.pe_machine(make_pe(0x014C, pe_offset=0x100)) == 0x014C


@pytest.mark.parametrize("data", [b"", b"ELF" + b"\0" * 100, b"MZ" + b"\0" * 0x3E])
def test_rejects_non_pe(data):
	with pytest.raises(check_pe_arch.NotPeFileError):
		check_pe_arch.pe_machine(data)


def test_check_accepts_x64_and_rejects_x86(tmp_path):
	good = tmp_path / "good.dll"
	bad = tmp_path / "bad.dll"
	good.write_bytes(make_pe(0x8664))
	bad.write_bytes(make_pe(0x014C))
	errors = check_pe_arch.check([good, bad])
	assert len(errors) == 1
	assert "bad.dll" in errors[0] and "32-bit" in errors[0]


def test_main_exit_codes(tmp_path):
	good = tmp_path / "good.dll"
	good.write_bytes(make_pe(0x8664))
	missing = tmp_path / "missing.dll"
	assert check_pe_arch.main([str(good)]) == 0
	assert check_pe_arch.main([str(good), str(missing)]) == 1
	assert check_pe_arch.main([]) == 2
