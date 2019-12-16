"""

SUMMARY
------------------------------------------------------
Utility with functionality shared among some tests.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging
import time


def sleep(n=10):
    """
    Sleep for `n` seconds.

    :param int n: seconds to sleep
    """
    logging.info("Sleeping for %s seconds", n)
    time.sleep(n)
