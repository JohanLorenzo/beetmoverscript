import logging
import os
import zipfile

from scriptworker.exceptions import TaskVerificationError


log = logging.getLogger(__name__)

MAX_COMPRESSION_RATIO = 10

def check_and_extract_zip_archives(artifacts_per_task_id, zip_extract_max_file_size_in_mb):
    for task_id, task_params in artifacts_per_task_id:
        if task_params['must_extract'] is False:
            continue

        for path in task_params['paths']:
            log.info('Processing archive "{}" which marked as `zipExtract`able'.format(path))
            _check_extract_and_delete_zip_archive(zip_path, zip_extract_max_file_size_in_mb)


def _check_extract_and_delete_zip_archive(zip_path, zip_extract_max_file_size_in_mb):
    _check_archive_itself(zip_path, zip_extract_max_file_size_in_mb)

    with zipfile.ZipFile(zip_path) as zip_file:
        zip_metadata = _fetch_zip_metadata(zip_file)

        # we don't close the file descriptor here to avoid the tested file to be swapped by a rogue one
        _ensure_files_in_archive_have_decent_sizes(zip_path, zip_metadata, zip_extract_max_file_size_in_mb):
        _ensure_all_files_are_present(zip_path, zip_metadata)
        log.info('Content of archive "{}" is sane'.format(zip_path))

        _extract_files(zip_file)

    # We remove the zip archive because it's not used anymore. We just need the deflated files
    os.remove(zip_path)
    log.info('Deleted archive "{}"'.format(zip_path, extract_to))


def _check_archive_itself(zip_path, zip_extract_max_file_size_in_mb):
    zip_size = os.path.getsize(zip_path)
    zip_size_in_mb = zip_size // (1024 * 1024)

    if zip_size_in_mb > zip_extract_max_file_size_in_mb:
        raise TaskVerificationError(
            'Archive "{}" is too big. Max accepted size (in MB): {}. File size (in MB): {}'.format(
                zip_path, zip_size_in_mb, zip_extract_max_file_size_in_mb
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


def _ensure_files_in_archive_have_decent_sizes(zip_path, zip_metadata, zip_extract_max_file_size_in_mb):
    # XXX Rule of thumb roughly made for Geckoview. Please increase if you have different data.
    max_size_of_extracted_file = MAX_COMPRESSION_RATIO * zip_extract_max_file_size_in_mb

    for file_name, file_metadata in zip_metadata:
        if file_metadata['compress_size'] > zip_extract_max_file_size_in_mb:
            raise TaskVerificationError(
                'In archive "{}", compressed file "{}" is too big. Max accepted size (in MB): {}. File size (in MB): {}'.format(
                    zip_path, file_name, file_metadata['compress_size'], zip_extract_max_file_size_in_mb
                )
            )

        if file_metadata['file_size'] > max_size_of_extracted_file:
            raise TaskVerificationError(
                'In archive "{}", uncompressed file "{}" is too big. Max accepted size (in MB): {}. File size (in MB): {}'.format(
                    zip_path, file_name, file_metadata['file_size'], max_size_of_extracted_file
                )
            )


def _ensure_all_files_are_present(zip_path, zip_metadata):
    # TODO ensure no full path nor .. are in there. This should be already done by ZipFile.extractall()
    pass


def _extract_files(zip_path, zip_file):
    extract_to = os.path.dirname(zip_path)
    log.info('Extracting archive "{}" to "{}"...'.format(zip_path, extract_to))
    zip_file.extractall(extract_to)
    log.info('Extracted archive "{}"'.format(zip_path, extract_to))
