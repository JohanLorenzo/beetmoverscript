import boto3
import logging
import mimetypes
import mock
import os
import pytest
from yarl import URL

import beetmoverscript.script
from beetmoverscript.script import (setup_mimetypes, put,
                                    move_beets, move_beet, async_main,
                                    main, enrich_balrog_manifest,
                                    list_bucket_objects,
                                    push_to_releases, copy_beets)
from beetmoverscript.task import get_upstream_artifacts
from beetmoverscript.test import (
    context, get_fake_valid_config, get_fake_valid_task, get_fake_balrog_props,
    noop_async
)
from beetmoverscript.utils import generate_beetmover_manifest, is_promotion_action
from scriptworker.context import Context
from scriptworker.exceptions import (ScriptWorkerRetryException,
                                     ScriptWorkerTaskException)
from scriptworker.test import event_loop, fake_session, fake_session_500

assert event_loop, context  # silence flake8
assert fake_session, fake_session_500  # silence flake8
assert noop_async  # silence flake8


# push_to_releases {{{1
@pytest.mark.parametrize("candidates_keys,releases_keys,exception_type", ((
    {"foo.zip": "x", "foo.exe": "y"}, {}, None,
), (
    {"foo.zip": "x", "foo.exe": "y"}, {"asdf": 1}, None,
), (
    {}, {"asdf": 1}, ScriptWorkerTaskException,
)))
@pytest.mark.asyncio
async def test_push_to_releases(context, mocker, candidates_keys,
                                releases_keys, exception_type):
    context.task = {
        "payload": {
            "product": "fennec",
            "build_number": 33,
            "version": "99.0b44"
        }
    }

    objects = [candidates_keys, releases_keys]

    def check(_, _2, r):
        assert r == releases_keys

    def fake_list(*args):
        return objects.pop(0)

    mocker.patch.object(boto3, "resource")
    mocker.patch.object(beetmoverscript.script, "list_bucket_objects", new=fake_list)
    mocker.patch.object(beetmoverscript.script, "copy_beets", new=check)

    if exception_type is not None:
        with pytest.raises(exception_type):
            await push_to_releases(context)
    else:
        await push_to_releases(context)


# copy_beets {{{1
@pytest.mark.parametrize("releases_keys,raises", ((
    {}, False
), (
    {"to2": "from2_md5"}, False
), (
    {"to1": "to1_md5"}, True
)))
def test_copy_beets(context, mocker, releases_keys, raises):
    called_with = []

    def fake_copy_object(**kwargs):
        called_with.append(kwargs)

    boto_client = mock.MagicMock()
    boto_client.copy_object = fake_copy_object
    mocker.patch.object(boto3, "client", return_value=boto_client)
    context.artifacts_to_beetmove = {
        "from1": "to1",
        "from2": "to2",
    }
    candidates_keys = {
        "from1": "from1_md5",
        "from2": "from2_md5",
    }
    context.bucket_name = "this-is-a-fake-bucket"
    if raises:
        with pytest.raises(ScriptWorkerTaskException):
            copy_beets(context, candidates_keys, releases_keys)
    else:
        copy_beets(context, candidates_keys, releases_keys)
        a = {
            'Bucket': context.bucket_name,
            'CopySource': {'Bucket': context.bucket_name, 'Key': 'from1'},
            'Key': 'to1',
        }
        b = {
            'Bucket': context.bucket_name,
            'CopySource': {'Bucket': context.bucket_name, 'Key': 'from2'},
            'Key': 'to2',
        }
        if releases_keys:
            expected = [[a]]
        else:
            # Allow for different sorting
            expected = [[a, b], [b, a]]
        assert called_with in expected


# list_bucket_objects {{{1
def test_list_bucket_objects():
    bucket = mock.MagicMock()
    s3_resource = mock.MagicMock()

    def fake_bucket(_):
        return bucket

    def fake_filter(**kwargs):
        one = mock.MagicMock()
        two = mock.MagicMock()
        one.key = "one"
        one.e_tag = "asdf-x"
        two.key = "two"
        two.e_tag = "foo-bar"
        return [one, two]

    s3_resource.Bucket = fake_bucket
    bucket.objects.filter = fake_filter

    assert list_bucket_objects(mock.MagicMock(), s3_resource, None) == {"one": "asdf", "two": "foo"}


# setup_mimetypes {{{1
def test_setup_mimetypes():
    non_default_types = [
        'https://foo.com/fake_artifact.bundle', 'http://www.bar.com/fake_checksum.beet'
    ]

    # before we add custom mimetypes
    assert ([mimetypes.guess_type(url)[0] for url in non_default_types] == [None, None])

    setup_mimetypes()

    # after we add custom mimetypes
    assert (sorted([mimetypes.guess_type(url)[0] for url in non_default_types]) ==
            ['application/octet-stream', 'text/plain'])


# put {{{1
def test_put_success(event_loop, fake_session):
    context = Context()
    context.config = get_fake_valid_config()
    context.session = fake_session
    response = event_loop.run_until_complete(
        put(context, url=URL('https://foo.com/packages/fake.package'), headers={},
            abs_filename='beetmoverscript/test/fake_artifact.json', session=fake_session)
    )
    assert response.status == 200
    assert response.resp == [b'asdf', b'asdf']


def test_put_failure(event_loop, fake_session_500):
    context = Context()
    context.config = get_fake_valid_config()
    context.session = fake_session_500
    with pytest.raises(ScriptWorkerRetryException):
        event_loop.run_until_complete(
            put(context, url=URL('https://foo.com/packages/fake.package'), headers={},
                abs_filename='beetmoverscript/test/fake_artifact.json', session=fake_session_500)
        )


# enrich_balrog_manifest {{{1
@pytest.mark.parametrize("branch,action", ((
    "mozilla-central", "push-to-nightly",
), (
    "try", "push-to-nightly",
), (
    "mozilla-beta", "push-to-releases",
)))
def test_enrich_balrog_manifest(context, branch, action):
    context.release_props = get_fake_balrog_props()["properties"]
    context.release_props['platform'] = context.release_props['stage_platform']
    context.release_props['branch'] = branch
    context.task['payload']['build_number'] = 33
    context.task['payload']['version'] = '99.0b44'
    context.action = action

    expected_data = {
        'appName': context.release_props['appName'],
        'appVersion': context.release_props['appVersion'],
        'branch': context.release_props['branch'],
        'buildid': context.release_props['buildid'],
        'extVersion': context.release_props['appVersion'],
        'hashType': context.release_props['hashType'],
        'locale': 'sample-locale',
        'platform': context.release_props['stage_platform'],
        'url_replacements': [],
    }
    if branch != 'try':
        expected_data['url_replacements'] = [[
            'http://archive.mozilla.org/pub',
            'http://download.cdn.mozilla.net/pub'
        ]]
    if action != "push-to-nightly":
        expected_data['tc_release'] = True
        expected_data['build_number'] = 33
        expected_data['version'] = '99.0b44'
    else:
        expected_data['tc_nightly'] = True

    data = enrich_balrog_manifest(context, 'sample-locale')
    assert data == expected_data


# retry_upload {{{1
@pytest.mark.asyncio
async def test_retry_upload(context, mocker):
    mocker.patch.object(beetmoverscript.script, 'upload_to_s3', new=noop_async)
    await beetmoverscript.script.retry_upload(context, ['a', 'b'], 'c')


# upload_to_s3 {{{1
@pytest.mark.asyncio
async def test_upload_to_s3(context, mocker):
    context.release_props['appName'] = 'fake'
    mocker.patch.object(beetmoverscript.script, 'retry_async', new=noop_async)
    mocker.patch.object(beetmoverscript.script, 'boto3')
    await beetmoverscript.script.upload_to_s3(context, 'foo', 'bar')


# move_beets {{{1
@pytest.mark.parametrize("partials", (False, True))
def test_move_beets(event_loop, partials):
    context = Context()
    context.config = get_fake_valid_config()
    context.task = get_fake_valid_task()
    context.release_props = get_fake_balrog_props()["properties"]
    context.release_props['platform'] = context.release_props['stage_platform']
    context.bucket = 'nightly'
    context.action = 'push-to-nightly'
    context.raw_balrog_manifest = dict()
    context.balrog_manifest = list()
    context.artifacts_to_beetmove = get_upstream_artifacts(context)
    manifest = generate_beetmover_manifest(context)

    expected_sources = [
        os.path.abspath(
            'beetmoverscript/test/test_work_dir/cot/eSzfNqMZT_mSiQQXu8hyqg/public/build/target.mozinfo.json'
        ),
        os.path.abspath(
            'beetmoverscript/test/test_work_dir/cot/eSzfNqMZT_mSiQQXu8hyqg/public/build/target.txt',
        ),
        os.path.abspath(
            'beetmoverscript/test/test_work_dir/cot/eSzfNqMZT_mSiQQXu8hyqg/public/build/target_info.txt'
        ),
        os.path.abspath(
            'beetmoverscript/test/test_work_dir/cot/eSzfNqMZT_mSiQQXu8hyqg/public/build/target.test_packages.json'
        ),
    ]
    expected_destinations = [
        ['pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target_info.txt',
         'pub/mobile/nightly/latest-mozilla-central-fake/en-US/fake-99.0a1.en-US.target_info.txt'],
        ['pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.mozinfo.json',
         'pub/mobile/nightly/latest-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.mozinfo.json'],
        ['pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt',
         'pub/mobile/nightly/latest-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt'],
        ['pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.test_packages.json',
         'pub/mobile/nightly/latest-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.test_packages.json'],
    ]

    expected_balrog_manifest = [
        {
            'tc_nightly': True,
            'appName': 'Fake',
            'appVersion': '99.0a1',
            'branch': 'mozilla-central',
            'buildid': '20990205110000',
            'extVersion': '99.0a1',
            'hashType': 'sha512',
            'locale': 'en-US',
            'platform': 'android-api-15',
            'url_replacements': [['http://archive.mozilla.org/pub', 'http://download.cdn.mozilla.net/pub']],
            'completeInfo': [
                {
                    'hash': 'dummyhash',
                    'size': 123456,
                    'url': 'pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.mozinfo.json'
                },
                {
                    'hash': 'dummyhash',
                    'size': 123456,
                    'url': 'pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target_info.txt'
                }
            ],
        }
    ]
    if partials:
        expected_balrog_manifest[0]['partialInfo'] = [
            {
                'from_buildid': 19991231235959,
                'hash': 'dummyhash',
                'size': 123456,
                'url': 'pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt'
            }
        ]

    actual_sources = []
    actual_destinations = []

    def sort_completeInfo(manifest):
        completeInfo = manifest[0]['completeInfo']
        manifest[0]['completeInfo'] = sorted(completeInfo, key=lambda ci: ci['url'])

    async def fake_move_beet(context, source, destinations, locale,
                             update_balrog_manifest, artifact_pretty_name, from_buildid):
        actual_sources.append(source)
        actual_destinations.append(destinations)
        if update_balrog_manifest:

            data = {
                "hash": 'dummyhash',
                "size": 123456,
                "url": destinations[0]
            }
            if from_buildid:
                if partials:
                    data["from_buildid"] = from_buildid
                    component = 'partialInfo'
                else:
                    return
            else:
                component = 'completeInfo'
            context.raw_balrog_manifest.setdefault(locale, {})
            context.raw_balrog_manifest[locale].setdefault(component, [])
            context.raw_balrog_manifest[locale][component].append(data)

    with mock.patch('beetmoverscript.script.move_beet', fake_move_beet):
        event_loop.run_until_complete(
            move_beets(context, context.artifacts_to_beetmove, manifest)
        )

    assert sorted(expected_sources) == sorted(actual_sources)
    assert sorted(expected_destinations) == sorted(actual_destinations)

    # Deal with different-sorted completeInfo
    sort_completeInfo(context.balrog_manifest)
    sort_completeInfo(expected_balrog_manifest)
    assert context.balrog_manifest == expected_balrog_manifest


# move_beet {{{1
@pytest.mark.parametrize('update_manifest,action', [
     (True, 'push-to-candidates'),
     (True, 'push-to-nightly'),
     (False, 'push-to-nightly'),
     (False, 'push-to-candidates')
])
def test_move_beet(event_loop, update_manifest, action):
    context = Context()
    context.config = get_fake_valid_config()
    context.task = get_fake_valid_task()
    context.task['extra'] = dict()
    context.task['extra']['partials'] = [
        {
            "artifact_name": "target-98.0b96.partial.mar",
            "platform": "linux",
            "locale": "de",
            "buildid": "19991231235959",
            "previousVersion": "98.0b96",
            "previousBuildNumber": "1"
        },
        {
            "artifact_name": "target-97.0b96.partial.mar",
            "platform": "linux",
            "locale": "de",
            "buildid": "22423423402984",
            "previousVersion": "97.0b96",
            "previousBuildNumber": "1"
        }
    ]
    context.action = action
    context.checksums = dict()
    context.balrog_manifest = list()
    context.raw_balrog_manifest = dict()
    context.release_props = get_fake_balrog_props()["properties"]
    context.release_props['platform'] = context.release_props['stage_platform']
    locale = "sample-locale"

    target_source = 'beetmoverscript/test/test_work_dir/cot/eSzfNqMZT_mSiQQXu8hyqg/public/build/target.txt'
    pretty_name = 'fake-99.0a1.en-US.target.txt'
    target_destinations = (
        'pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt',
        'pub/mobile/nightly/latest-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt'
    )
    expected_upload_args = [
        ('pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt',
         'pub/mobile/nightly/latest-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt'),
        'beetmoverscript/test/test_work_dir/cot/eSzfNqMZT_mSiQQXu8hyqg/public/build/target.txt'
    ]
    expected_balrog_manifest = {
        'hash': '73b91c3625d70e9ba1992f119bdfd3fba85041e6f804a985a18efe06ebb1d4147fb044ac06b28773130b4887dd8b5b3bc63958e1bd74003077d8bc2a3909416b',
        'size': 18,
        'url': 'https://archive.mozilla.org/pub/mobile/nightly/2016/09/2016-09-01-16-26-14-mozilla-central-fake/en-US/fake-99.0a1.en-US.target.txt',
    }
    actual_upload_args = []

    async def fake_retry_upload(context, destinations, path):
        actual_upload_args.extend([destinations, path])

    with mock.patch('beetmoverscript.script.retry_upload', fake_retry_upload):
        event_loop.run_until_complete(
            move_beet(context, target_source, target_destinations, locale,
                      update_balrog_manifest=update_manifest,
                      artifact_pretty_name=pretty_name, from_buildid=None)
        )
    assert expected_upload_args == actual_upload_args
    if update_manifest:
        for k in expected_balrog_manifest.keys():
            assert (context.raw_balrog_manifest[locale]['completeInfo'][0][k] ==
                    expected_balrog_manifest[k])

    expected_balrog_manifest['from_buildid'] = '19991231235959'
    with mock.patch('beetmoverscript.script.retry_upload', fake_retry_upload):
        event_loop.run_until_complete(
            move_beet(context, target_source, target_destinations, locale,
                      update_balrog_manifest=update_manifest,
                      artifact_pretty_name=pretty_name,
                      from_buildid='19991231235959')
        )
    if update_manifest:
        if is_promotion_action(context.action):
            expected_balrog_manifest['previousBuildNumber'] = '1'
            expected_balrog_manifest['previousVersion'] = '98.0b96'
        for k in expected_balrog_manifest.keys():
            assert (context.raw_balrog_manifest[locale]['partialInfo'][0][k] ==
                    expected_balrog_manifest[k])


# async_main {{{1
@pytest.mark.parametrize('action,raises', ((
    'push-to-nightly', False
), (
    'push-to-unknown', True
)))
@pytest.mark.asyncio
async def test_async_main(context, mocker, action, raises):
    context.action = action

    def fake_action(*args):
        return action

    mocker.patch('beetmoverscript.script.move_beets', new=noop_async)
    mocker.patch.object(beetmoverscript.script, 'get_task_action', new=fake_action)
    if raises:
        with pytest.raises(SystemExit):
            await async_main(context)
    else:
        await async_main(context)

    for module in ("botocore", "boto3", "chardet"):
        assert logging.getLogger(module).level == logging.INFO


# main {{{1
def test_main(event_loop, fake_session):
    context = Context()
    context.config = get_fake_valid_config()

    async def fake_async_main(context):
        pass

    async def fake_async_main_with_exception(context):
        raise ScriptWorkerTaskException("This is wrong, the answer is 42")

    with mock.patch('beetmoverscript.script.async_main', new=fake_async_main):
        main(config_path='beetmoverscript/test/fake_config.json')

    with mock.patch('beetmoverscript.script.async_main', new=fake_async_main_with_exception):
        try:
            main(config_path='beetmoverscript/test/fake_config.json')
        except SystemExit as exc:
            assert exc.code == 1
