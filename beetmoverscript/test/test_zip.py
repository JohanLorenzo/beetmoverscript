import contextlib
import os
import pytest
import tempfile
import zipfile

from pathlib import Path
from scriptworker.exceptions import TaskVerificationError

from beetmoverscript.zip import (
    _fetch_zip_metadata,
    _ensure_files_in_archive_have_decent_sizes,
    _ensure_all_expected_files_are_present_in_archive,
    _extract_and_check_output_files,
    _ensure_all_expected_files_are_deflated_on_disk,
    _ensure_no_file_got_overwritten,
)


def test_fetch_zip_metadata():
    with tempfile.NamedTemporaryFile(mode='w+b') as f:
        with zipfile.ZipFile(f.name, mode='w', compression=zipfile.ZIP_BZIP2) as zip_file:
            with tempfile.NamedTemporaryFile(mode='w') as f1:
                f1.write('some content that is 32-byte-big')
                f1.seek(0)
                zip_file.write(f1.name, arcname='some_file')

            with tempfile.NamedTemporaryFile(mode='w') as f2:
                f2.write('some other content that is 38-byte-big')
                f2.seek(0)
                zip_file.write(f2.name, arcname='some/subdir/some_other_file')

        with zipfile.ZipFile(f.name, mode='r') as zip_file:
            assert _fetch_zip_metadata(zip_file) == {
                'some_file': {
                    'compress_size': 67,
                    'file_size': 32,
                },
                'some/subdir/some_other_file': {
                    'compress_size': 72,
                    'file_size': 38,
                }
            }


@pytest.mark.parametrize('zip_metadata, zip_extract_max_file_size_in_mb, raises', ((
    {
        'file1': {
            'compress_size': 1000,
            'file_size': 1000,
        },
        'file2': {
            'compress_size': 1000,
            'file_size': 2000,
        },
    },
    100,
    False,
), (
    {
        'file1': {
            'compress_size': 101 * 1024 * 1024,
            'file_size': 101 * 1024 * 1024,
        },
    },
    100,
    True,
), (
    {
        'file1': {
            'compress_size': 2 * 1024 * 1024,
            'file_size': 2 * 1024 * 1024,
        },
    },
    1,
    True,
), (
    {
        'file1': {
            'compress_size': 100,
            'file_size': 1 * 1024 * 1024,
        },
    },
    100,
    True,
), (
    {
        'file1': {
            'compress_size': 50,
            'file_size': 10,    # Can happen with small files
        },
    },
    100,
    False,
)))
def test_ensure_files_in_archive_have_decent_sizes(zip_metadata, zip_extract_max_file_size_in_mb, raises):
    if raises:
        with pytest.raises(TaskVerificationError):
            _ensure_files_in_archive_have_decent_sizes('/some/archive.zip', zip_metadata, zip_extract_max_file_size_in_mb)
    else:
        _ensure_files_in_archive_have_decent_sizes('/some/archive.zip', zip_metadata, zip_extract_max_file_size_in_mb)


@pytest.mark.parametrize('files_in_archive, expected_files, raises', ((
    ['some_file', 'some/other/file'],
    ['some_file', 'some/other/file'],
    False,
), (
    ['/some/absolute/path'],
    ['/some/absolute/file'],
    True,
), (
    ['some/.///redundant/path'],
    ['some/.///redundant/path'],
    True,
), (
    ['some/../../../etc/passwd'],
    ['some/../../../etc/passwd'],
    True,
), (
    ['some_file', 'some_wrong_file'],
    ['some_file', 'some_other_file'],
    True,
), (
    ['some_file'],
    ['some_file', 'some_missing_file'],
    True,
), (
    ['some_file', 'some_unexpected_file'],
    ['some_file'],
    True,
)))
def test_ensure_all_expected_files_are_present_in_archive(files_in_archive, expected_files, raises):
    if raises:
        with pytest.raises(TaskVerificationError):
            _ensure_all_expected_files_are_present_in_archive('/some/archive.zip', files_in_archive, expected_files)
    else:
        _ensure_all_expected_files_are_present_in_archive('/some/archive.zip', files_in_archive, expected_files)


def test_extract_and_check_output_files():
    with tempfile.TemporaryDirectory() as d:
        zip_path = os.path.join(d, 'some.zip')

        file1 = os.path.join(d, 'some_file')
        with open(file1, mode='w') as f:
            f.write('some content')

        file2 = os.path.join(d, 'some_other_file')
        with open(file2, mode='w') as f:
            f.write('some other content')

        with zipfile.ZipFile(zip_path, mode='w') as zip_file:
            zip_file.write(file1, arcname='some_file')
            zip_file.write(file2, arcname='some/subfolder/file')

        os.remove(file1)
        os.remove(file2)

        extracted_file1 = os.path.join(d, 'some.zip.out', 'some_file')
        extracted_file2 = os.path.join(d, 'some.zip.out', 'some', 'subfolder', 'file')
        expected_extracted_files = [extracted_file1, extracted_file2]

        with zipfile.ZipFile(zip_path, mode='r') as zip_file:
            assert _extract_and_check_output_files(
                zip_file, ['some_file', 'some/subfolder/file']
            ) == expected_extracted_files

        with open(extracted_file1) as f:
            assert f.read() == 'some content'

        with open(extracted_file2) as f:
            assert f.read() == 'some other content'


@contextlib.contextmanager
def cwd(new_cwd):
    current_dir = os.getcwd()
    try:
        os.chdir(new_cwd)
        yield
    finally:
        os.chdir(current_dir)


def test_fail_extract_and_check_output_files():
    zip_path = 'relative/path/to/some.zip'

    with tempfile.TemporaryDirectory() as d:
        with cwd(d):
            os.makedirs(os.path.join(d, 'relative/path/to'))
            with zipfile.ZipFile(zip_path, mode='w') as zip_file:
                pass

            with zipfile.ZipFile(zip_path, mode='r') as zip_file:
                with pytest.raises(TaskVerificationError):
                    _extract_and_check_output_files(zip_file, ['some_file', 'some/subfolder/file'])


def test_ensure_all_expected_files_are_deflated_on_disk():
    with tempfile.TemporaryDirectory() as d:
        folder = os.path.join(d, 'some/folder')
        os.makedirs(folder)
        file1 = os.path.join(folder, 'some_file')
        file2 = os.path.join(folder, 'some_other_file')
        Path(file1).touch()
        Path(file2).touch()

        _ensure_all_expected_files_are_deflated_on_disk('/path/to/zip', [file1, file2])


def test_fail_ensure_all_expected_files_are_deflated_on_disk():
    with tempfile.TemporaryDirectory() as d:
        folder = os.path.join(d, 'some/folder')
        os.makedirs(folder)
        non_existing_path = os.path.join(folder, 'non_existing_path')

        with pytest.raises(TaskVerificationError):
            _ensure_all_expected_files_are_deflated_on_disk('/path/to/zip', [non_existing_path])

        with pytest.raises(TaskVerificationError):
            _ensure_all_expected_files_are_deflated_on_disk('/path/to/zip', [folder])


@pytest.mark.parametrize('files, raises', (
    (['/some/file'], False),
    (['/some/file', '/some/other_file'], False),
    (['/some/file', '/some/other_file', '/some/file'], True),
))
def test_ensure_no_file_got_overwritten(files, raises):
    if raises:
        with pytest.raises(TaskVerificationError):
            _ensure_no_file_got_overwritten('someTaskId', files)
    else:
        _ensure_no_file_got_overwritten('someTaskId', files)
