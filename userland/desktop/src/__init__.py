# Ainos Desktop - AI Backend Management Interface
# Copyright (c) 2024 Ainos Team. All rights reserved.

__version__ = "0.1.0"
__author__ = "Ainos Team"
__email__ = "dev@ainos.ai"
__license__ = "MIT"
__description__ = "A cross-platform desktop GUI for the Ainos AI backend"

import sys
import os

# Ensure the src directory is on the path
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)