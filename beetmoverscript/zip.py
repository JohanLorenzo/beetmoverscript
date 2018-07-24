import logging
import os
import zipfile

from scriptworker.exceptions import TaskVerificationError

from beetmoverscript.constants import ZIP_MAX_COMPRESSION_RATIO

log = logging.getLogger(__name__)


def check_and_extract_zip_archives(artifacts_per_task_id, expected_files_per_archive_per_task_id, zip_max_size_in_mb):
    deflated_artifacts = []

    for task_id, task_artifacts_params in artifacts_per_task_id.items():
        for artifacts_param in task_artifacts_params:
            paths_for_task = artifacts_param['paths']

            if artifacts_param['zip_extract'] is False:
                log.debug('Skipping artifacts marked as not `zipExtract`able: {}'.format(paths_for_task))
                deflated_artifacts.extend(paths_for_task)
                continue

            expected_files_per_archive = expected_files_per_archive_per_task_id[task_id]
            deflated_artifacts.extend(_check_and_extract_zip_archives_for_given_task(
                task_id, expected_files_per_archive, zip_max_size_in_mb
            ))

    return deflated_artifacts


def _check_and_extract_zip_archives_for_given_task(task_id, expected_files_per_archive, zip_max_size_in_mb):
    extracted_files = []

    for archive_path, expected_files in expected_files_per_archive.items():
        log.info('Processing archive "{}" which marked as `zipExtract`able'.format(archive_path))
        extracted_files.extend(
            _check_extract_and_delete_zip_archive(archive_path, expected_files, zip_max_size_in_mb)
        )

    # We make this check at this stage (and not when all files from all tasks got extracted)
    # because files from different tasks are stored in different folders by scriptworker. Moreover
    # we tested no relative paths like ".." are not used within the archive.
    _ensure_no_file_got_overwritten(task_id, extracted_files)

    return extracted_files


def _check_extract_and_delete_zip_archive(zip_path, expected_files, zip_max_size_in_mb):
    _check_archive_itself(zip_path, zip_max_size_in_mb)

    with zipfile.ZipFile(zip_path) as zip_file:
        zip_metadata = _fetch_zip_metadata(zip_file)

        # we don't close the file descriptor here to avoid the tested file to be swapped by a rogue one
        _ensure_files_in_archive_have_decent_sizes(zip_path, zip_metadata, zip_max_size_in_mb)
        _ensure_all_expected_files_are_present_in_archive(zip_path, zip_metadata, expected_files)
        log.info('Content of archive "{}" is sane'.format(zip_path))

        extracted_files = _extract_and_check_output_files(zip_file, zip_metadata.keys())

    # We remove the zip archive because it's not used anymore. We just need the deflated files
    os.remove(zip_path)
    log.debug('Deleted archive "{}"'.format(zip_path))

    return extracted_files


def _check_archive_itself(zip_path, zip_max_size_in_mb):
    zip_size = os.path.getsize(zip_path)
    zip_size_in_mb = zip_size // (1024 * 1024)

    if zip_size_in_mb > zip_max_size_in_mb:
        raise TaskVerificationError(
            'Archive "{}" is too big. Max accepted size (in MB): {}. File size (in MB): {}'.format(
                zip_path, zip_max_size_in_mb, zip_size_in_mb
            )
        )

    if not zipfile.is_zipfile(zip_path):
        raise TaskVerificationError(
            'Archive "{}" is not a valid zip file.'
        )

    log.info('Structure of archive "{}" is sane'.format(zip_path))


def _fetch_zip_metadata(zip_file):
    return {
        info.filename: {
            'compress_size': info.compress_size,
            'file_size': info.file_size,
        }
        for info in zip_file.infolist()
    }


def _ensure_files_in_archive_have_decent_sizes(zip_path, zip_metadata, zip_max_size_in_mb):
    for file_name, file_metadata in zip_metadata.items():
        compressed_size = file_metadata['compress_size']
        real_size = file_metadata['file_size']
        compressed_size_size_in_mb = compressed_size // (1024 * 1024)

        if compressed_size_size_in_mb > zip_max_size_in_mb:
            raise TaskVerificationError(
                'In archive "{}", compressed file "{}" is too big. Max accepted size (in MB): {}. File size (in MB): {}'.format(
                    zip_path, file_name, zip_max_size_in_mb, compressed_size_size_in_mb
                )
            )

        compression_ratio = real_size / compressed_size
        if compression_ratio > ZIP_MAX_COMPRESSION_RATIO:
            raise TaskVerificationError(
                'In archive "{}", file "{}" has a suspicious compression ratio. Max accepted: {}. Found: {}'.format(
                    zip_path, file_name, ZIP_MAX_COMPRESSION_RATIO, compression_ratio
                )
            )

    log.info('Archive "{}" contains files with legitimate sizes.'.format(zip_path))


def _ensure_all_expected_files_are_present_in_archive(zip_path, files_in_archive, expected_files):
    files_in_archive = set(files_in_archive)

    unique_expected_files = set(expected_files)
    if len(expected_files) != len(unique_expected_files):
        duplicated_files = [file for file in unique_expected_files if expected_files.count(file) > 1]
        raise TaskVerificationError(
            'Found duplicated expected files in archive "{}": {}'.format(zip_path, duplicated_files)
        )

    for file in files_in_archive:
        if os.path.isabs(file):
            raise TaskVerificationError(
                'File "{}" in archive "{}" cannot be an absolute one.'.format(file, zip_path)
            )
        if os.path.normpath(file) != file:
            raise TaskVerificationError(
                'File "{}" in archive "{}" cannot contain up-level reference nor redundant separators'.format(
                    file, zip_path
                )
            )
        if file not in unique_expected_files:
            raise TaskVerificationError(
                'File "{}" present in archive "{}" is not expected.'.format(
                    file, zip_path
                )
            )

    if len(files_in_archive) != len(unique_expected_files):
        missing_expected_files = [file for file in unique_expected_files if file not in files_in_archive]
        raise TaskVerificationError(
            'Expected files are missing in archive "{}": {}'.format(zip_path, missing_expected_files)
        )

    log.info('Archive "{}" contains all expected files: {}'.format(zip_path, unique_expected_files))


def _extract_and_check_output_files(zip_file, expected_files_in_archive):
    zip_path = zip_file.filename

    if not os.path.isabs(zip_path):
        raise TaskVerificationError(
            'Archive "{}" is not absolute path. Cannot know where to extract content'.format(zip_path)
        )

    extract_to = '{}.out'.format(zip_path)
    expected_full_paths = [
        os.path.join(extract_to, path_in_archive) for path_in_archive in expected_files_in_archive
    ]
    log.info('Extracting archive "{}" to "{}"...'.format(zip_path, extract_to))
    zip_file.extractall(extract_to)
    log.info('Extracted archive "{}". Verfiying extracted data...'.format(zip_path, extract_to))

    _ensure_all_expected_files_are_deflated_on_disk(zip_path, expected_full_paths)

    return expected_full_paths


def _ensure_all_expected_files_are_deflated_on_disk(zip_path, expected_full_paths):
    for full_path in expected_full_paths:
        if not os.path.exists(full_path):
            raise TaskVerificationError(
                'After extracting "{}", expected file "{}" does not exist'.format(zip_path, full_path)
            )
        if not os.path.isfile(full_path):
            raise TaskVerificationError(
                'After extracting "{}", "{}" is not a file'.format(zip_path, full_path)
            )

    log.info('All files declared in archive "{}" exist and are regular files: {}'.format(
        zip_path, expected_full_paths
    ))


def _ensure_no_file_got_overwritten(task_id, extracted_files):
    unique_paths = set(extracted_files)

    if len(unique_paths) != len(extracted_files):
        duplicated_paths = [path for path in unique_paths if extracted_files.count(path) > 1]
        raise TaskVerificationError(
            'Archives from task "{}" overwrote files: {}'.format(task_id, duplicated_paths)
        )

    log.info('All archives from task "{}" outputed different files.')
