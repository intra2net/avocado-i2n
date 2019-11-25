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

from avocado.utils import process
from avocado.core.settings import settings

from avocado_i2n import state_setup


def sleep(self, n=10):
    """
    Sleep for `n` seconds.

    :param int n: seconds to sleep
    """
    time.sleep(n)
