import threading
import time
import typing
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timezone

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from loguru import logger

if typing.TYPE_CHECKING:
    # type: ignore[import-not-found]: pyre on modal does't believe in mypy_boto3_s3
    from mypy_boto3_s3 import Client
else:
    Client = object

from pydantic import PrivateAttr

from imbue_core.pydantic_serialization import FrozenModel

EXTRAS_UPLOADED_FILES_KEY = "uploaded_files"

PRODUCTION_UPLOADS_BUCKET = "traceback-uploads-production"
STAGING_UPLOADS_BUCKET = "traceback-uploads-staging"

DEFAULT_REGION = "us-west-2"
MAXIMUM_QUEUED_S3_UPLOADS = 50  # rather arbitrary but better to err on the side of caution when going from the current unbounded


class _S3Uploader(FrozenModel):
    bucket: str
    region: str
    maximum_concurrency: int = MAXIMUM_QUEUED_S3_UPLOADS

    _s3_client: Client = PrivateAttr()  # type: ignore[valid-type]

    # protects access to the thread collections
    _thread_pool: ThreadPoolExecutor = PrivateAttr()
    _thread_limiter: threading.Semaphore = PrivateAttr()

    def model_post_init(self, context) -> None:
        # NOTE: we use an unsigned client to avoid the need to provide AWS credentials.
        self._s3_client = boto3.client(
            "s3", region_name=self.region, config=Config(signature_version=UNSIGNED)
        )
        self._thread_pool = ThreadPoolExecutor(
            max_workers=None, thread_name_prefix=f"s3_upload"
        )
        # Unfortunately, there's no safe access to the queue size of the thread pool so calculating that number precisely
        # using a semaphore. Each queued up uploads acquires a single value and returns it only after its thread is done
        # interacting with S3. The value of the semaphore at any given time is the number of available work slots, and
        # it cannot go negative. The semaphore is bounded purely to track that there are no more releases than acquisitions.
        self._thread_limiter = threading.BoundedSemaphore(self.maximum_concurrency)

    def _upload_thread(self, key: str, contents: bytes) -> None:
        try:
            logger.debug("Uploading to s3://{}/{}", self.bucket, key)
            # NOTE: we use put_object instead of upload_file because we don't want multipart uploads
            # multipart uploads are not allowed for unsigned clients
            self._s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=contents,
            )
            logger.debug(
                "Done uploading to s3://{}/{}", self.bucket, key
            )  # XXX remove before merge
        except Exception as e:
            logger.info("Failed to upload {} to S3: {}", key, e)
            # if re-raised, who would even catch this exception?
        finally:
            self._thread_limiter.release()

    def s3_uri_from_key(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def upload_if_possible(self, key: str, contents: bytes) -> str | None:
        """Returns the S3 URL of the upload or None if the upload is not possible"""
        if not self._thread_limiter.acquire(timeout=0):
            logger.debug(
                "Skipping upload to {key}, maximum concurrent uploads in progress already (limit={limit})",
                key=key,
                limit=self.maximum_concurrency,
            )
            return None

        try:
            self._thread_pool.submit(self._upload_thread, key, contents)
        except Exception as e:
            # we have to release the semaphore since the thread didn't start
            # this shouldn't ever happen but the docs for `.submit` don't promise
            # anything
            self._thread_limiter.release()
            logger.debug(
                "Failed to queue a thread for an upload to {key}: {e}", key=key, e=e
            )
            return None

        return self.s3_uri_from_key(key)

    def wait_for_all_uploads(
        self, timeout: float | None, is_shutting_down: bool
    ) -> bool:
        """Waits for all the uploads that may still be in progress or queued.

        When is_shutting_down is True, the function will block until all uploads are completed and will disable any
        future use of the uploader.

        The is_shutting_down parameter is meant to be overridden only in tests as a way to checkpoint before
        proceeding to schedule more work.
        """
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout

        # tracks the number of work slots from semaphore that this function already acquired
        # if all self.maximum_concurrency values are collected then we guarantee that no other
        # work is queue or in progress
        n = 0

        # a fast pass to collect available tickets before we start waiting and log messages to the user.
        while self._thread_limiter.acquire(timeout=0):
            n += 1

        while (
            deadline is None or time.monotonic() < deadline
        ) and n < self.maximum_concurrency:
            if is_shutting_down:
                logger.info(
                    "Please stand by: waiting for remaining uploads to finish! Still uploading: {} reports",
                    self.maximum_concurrency - n,
                )
            timeout = None if deadline is None else deadline - time.monotonic()
            if self._thread_limiter.acquire(timeout=timeout):
                n += 1

        all_done = n == self.maximum_concurrency
        if is_shutting_down:
            # block more work from getting scheduled in case we didn't gobble up all the slots
            # this may also make the semaphore out of sync, as cancelled queued features will not
            # release theirs
            self._thread_pool.shutdown(wait=False, cancel_futures=True)
            if not all_done:
                logger.info(
                    "Failed to upload the S3 reports after timeout reached (timeout={}), {} reports still uploading",
                    timeout,
                    self.maximum_concurrency - n,
                )
        elif n > 0:
            # allow further work
            logger.debug("Letting go of {n} slots", n=n)
            self._thread_limiter.release(n)

        return all_done


# FIXME: move the methods below to error-handling specific module and get rid of this global variable if possible
_S3_UPLOADER: _S3Uploader | None = None


def setup_s3_uploads(is_production: bool = False) -> None:
    """Set up S3 upload settings."""
    global _S3_UPLOADER
    if _S3_UPLOADER is not None:
        logger.debug("S3 upload settings already initialized, skipping setup")
        return
    if is_production:
        bucket_name = PRODUCTION_UPLOADS_BUCKET
    else:
        bucket_name = STAGING_UPLOADS_BUCKET
    _S3_UPLOADER = _S3Uploader(bucket=bucket_name, region=DEFAULT_REGION)


def get_s3_upload_key(key_prefix: str, key_suffix: str) -> str:
    """Get a URL for an S3 upload."""
    key = (
        "_".join(
            [
                key_prefix,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S"),
                uuid.uuid4().hex,
            ]
        )
        + key_suffix
    )
    return key


def get_s3_upload_url(key: str) -> str | None:
    """Get a URL for an S3 upload."""
    if _S3_UPLOADER is None:
        logger.info("S3 upload settings not initialized. Skipping upload.")
        return None
    return _S3_UPLOADER.s3_uri_from_key(key)


def upload_to_s3_with_key(key: str, contents: bytes) -> str | None:
    """Upload a file to S3 and return the S3 URL. Returns None if upload is not possible."""
    if _S3_UPLOADER is None:
        logger.info("S3 upload settings not initialized. Skipping upload.")
        return None
    return _S3_UPLOADER.upload_if_possible(key, contents)


def upload_to_s3(key_prefix: str, key_suffix: str, contents: bytes) -> str | None:
    """Upload a file to S3 in the background."""
    if _S3_UPLOADER is None:
        logger.info("S3 upload settings not initialized. Skipping upload.")
        return None

    key = get_s3_upload_key(key_prefix, key_suffix)
    return upload_to_s3_with_key(key, contents)


def wait_for_s3_uploads(timeout: float | None, is_shutting_down: bool) -> bool | None:
    logger.info("Checking whether S3 uploads are still in progress!")
    if _S3_UPLOADER is None:
        return None

    return _S3_UPLOADER.wait_for_all_uploads(
        timeout=timeout, is_shutting_down=is_shutting_down
    )
