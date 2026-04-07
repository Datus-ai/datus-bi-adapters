# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.


class DatusBiException(Exception):
    def __init__(self, message: str, platform: str = ""):
        self.message = message
        self.platform = platform
        super().__init__(f"[{platform}] {message}" if platform else message)
