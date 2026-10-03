"""``python -m gtnh_shadow_convert``, the same as the ``gtnh-shadow-convert`` command."""

import sys

from .cli import main

sys.exit(main())
