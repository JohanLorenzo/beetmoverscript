import pytest

from beetmoverscript.maven import get_maven_expected_files_per_archive_per_task_id


@pytest.mark.parametrize('upstream_artifacts, mapping_manifest, expected, raises', ((
    [{
        'paths': ['public/build/target.maven.zip'],
        'taskId': 'someTaskId',
        'taskType': 'build',
    }],
    {
        'mapping': {
            'en-US': {
                'geckoview-beta-x86-62.0b3.aar': {},
                'geckoview-beta-x86-62.0b3.aar.md5': {},
                'geckoview-beta-x86-62.0b3.aar.sha1': {},
                'geckoview-beta-x86-62.0b3.pom': {},
                'geckoview-beta-x86-62.0b3.pom.md5': {},
                'geckoview-beta-x86-62.0b3.pom.sha1': {},
                'geckoview-beta-x86-62.0b3-javadoc.jar': {},
                'geckoview-beta-x86-62.0b3-javadoc.jar.md5': {},
                'geckoview-beta-x86-62.0b3-javadoc.jar.sha1': {},
                'geckoview-beta-x86-62.0b3-sources.jar': {},
                'geckoview-beta-x86-62.0b3-sources.jar.md5': {},
                'geckoview-beta-x86-62.0b3-sources.jar.sha1': {},
            }
        },
        's3_bucket_path': 'maven2/org/mozilla/geckoview-beta-x86/62.0b3/',
    },
    {
        'someTaskId': {
            'target.maven.zip': [
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3.aar',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3.aar.md5',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3.aar.sha1',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3.pom',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3.pom.md5',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3.pom.sha1',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3-javadoc.jar',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3-javadoc.jar.md5',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3-javadoc.jar.sha1',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3-sources.jar',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3-sources.jar.md5',
                'org/mozilla/geckoview-beta-x86/62.0b3/geckoview-beta-x86-62.0b3-sources.jar.sha1',
            ],
        },
    },
    False,
), (
    [{
        'paths': ['public/build/target.jsshell.zip'],
        'taskId': 'someTaskId',
        'taskType': 'build',
    }],
    {
        'mapping': {
            'en-US': {
                'geckoview-beta-x86-62.0b3.aar': {},
                'geckoview-beta-x86-62.0b3.aar.md5': {},
                'geckoview-beta-x86-62.0b3.aar.sha1': {},
                'geckoview-beta-x86-62.0b3-sources.jar.sha1': {},
            }
        },
        's3_bucket_path': 'maven2/org/mozilla/geckoview-beta-x86/62.0b3/',
    },
    {},
    True,
), (
    [{
        'paths': ['public/build/target.maven.zip'],
        'taskId': 'someTaskId',
        'taskType': 'build',
    }, {
        'paths': ['public/build/target.maven.zip'],
        'taskId': 'someOtherTaskId',
        'taskType': 'build',
    }],
    {
        'mapping': {
            'en-US': {
                'geckoview-beta-x86-62.0b3.aar': {},
                'geckoview-beta-x86-62.0b3.aar.md5': {},
                'geckoview-beta-x86-62.0b3.aar.sha1': {},
                'geckoview-beta-x86-62.0b3-sources.jar.sha1': {},
            }
        },
        's3_bucket_path': 'maven2/org/mozilla/geckoview-beta-x86/62.0b3/',
    },
    {},
    True,
)))
def test_get_maven_expected_files_per_archive_per_task_id(upstream_artifacts, mapping_manifest, expected, raises):
    if raises:
        with pytest.raises(ValueError):
            get_maven_expected_files_per_archive_per_task_id(upstream_artifacts, mapping_manifest)
    else:
        assert get_maven_expected_files_per_archive_per_task_id(
            upstream_artifacts, mapping_manifest
        ) == expected
