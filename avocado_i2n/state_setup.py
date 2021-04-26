# Copyright 2013-2020 Intranet AG and contributors
#
# avocado-i2n is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# avocado-i2n is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with avocado-i2n.  If not, see <http://www.gnu.org/licenses/>.

from .states.setup import *
from .states.qcow2 import *
from .states.lvm import *
from .states.ramfile import *

import logging
logging.getLogger().warn("The `state_setup` module is deprecated, please use "
                         "the `states` subpackage.")

check_state = check_states
get_state = get_states
set_state = set_states
unset_state = unset_states
push_state = push_states
pop_state = pop_states
