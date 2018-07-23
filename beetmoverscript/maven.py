import os

from scriptworker.utils import get_single_item_from_sequence


def get_maven_expected_files_per_archive_per_task_id(upstream_artifacts, mapping_manifest):
    maven_zip_name = 'target.maven.zip'
    return {
        _get_single_task_id_which_contains_maven_zip(upstream_artifacts, maven_zip_name): {
            maven_zip_name: _get_maven_expected_files_in_archive(mapping_manifest)
        }
    }


def _get_single_task_id_which_contains_maven_zip(upstream_artifacts, maven_zip_name):
    upstream_definition = get_single_item_from_sequence(
        upstream_artifacts,
        condition=lambda upstream_definition: any(path.endswith(maven_zip_name) for path in upstream_definition['paths'])
    )
    return upstream_definition['taskId']


def _get_maven_expected_files_in_archive(mapping_manifest):
    files = mapping_manifest['mapping']['en-US'].keys()
    return [
        os.path.join(
            _remove_first_directory_from_bucket(mapping_manifest['s3_bucket_path']),
            file
        ) for file in files
    ]


def _remove_first_directory_from_bucket(s3_bucket_path):
    # remove 'maven2' because it's not in the archive, but it exists on the maven server
    return '/'.join(s3_bucket_path.split('/')[1:])
