"""Touch a filepath when remote framebuffer updates arrive."""

import logging

_LOGGER = logging.getLogger(__name__)


def touch_activity_stamp_file(activity_stamp_filepath: str) -> None:
    """Create or update mtime on the activity stamp file."""

    try:
        with open(activity_stamp_filepath, "a"):
            pass

    except OSError as error:
        _LOGGER.warning(
            "activity stamp touch failed filepath={activity_stamp_filepath} error={error}".format(
                activity_stamp_filepath=activity_stamp_filepath,
                error=error))
